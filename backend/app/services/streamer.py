"""Chunked byte piping from an upstream CDN to the client.

The plain passthrough path (stream_upstream) is fully disk-free: httpx
streams bytes straight through as they arrive. The muxed video+audio path
(mux_to_temp_and_stream) is the one exception -- see its docstring for why.
"""
import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class UpstreamError(Exception):
    pass


class MuxError(Exception):
    pass


async def stream_upstream(
    url: str,
    headers: dict[str, str] | None = None,
    range_header: str | None = None,
) -> tuple[httpx.Response, AsyncIterator[bytes]]:
    """Opens a streaming GET to the upstream CDN url and returns the response
    (for status/header inspection) plus an async byte iterator.

    Caller is responsible for closing the underlying client/response, which
    FastAPI's StreamingResponse background task handles for us (see
    download.py).
    """
    req_headers = dict(headers or {})
    if range_header:
        req_headers["Range"] = range_header

    client = httpx.AsyncClient(timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        request = client.build_request("GET", url, headers=req_headers)
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise UpstreamError(f"Failed to reach upstream media source: {exc}") from exc

    if response.status_code >= 400:
        await response.aclose()
        await client.aclose()
        raise UpstreamError(f"Upstream returned HTTP {response.status_code}")

    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_ALLOWED_FILESIZE_BYTES:
        await response.aclose()
        await client.aclose()
        raise UpstreamError("Requested file exceeds the maximum allowed download size.")

    async def _iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(chunk_size=settings.DOWNLOAD_CHUNK_SIZE):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return response, _iterator()


def _format_ffmpeg_headers(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    return "".join(f"{key}: {value}\r\n" for key, value in headers.items())


async def mux_to_temp_and_stream(
    video_url: str,
    video_headers: dict[str, str] | None,
    audio_url: str,
    audio_headers: dict[str, str] | None,
    container: str,
) -> tuple[int, AsyncIterator[bytes]]:
    """Remuxes a separately-hosted video-only + audio-only stream into a
    single container, `-c copy` throughout so nothing is re-encoded.

    Why a temp file instead of a live pipe: producing a standards-compliant
    "faststart" MP4 (moov atom populated and moved to the front, matching
    what strict consumers like WhatsApp/iOS Photos require) means ffmpeg
    must seek backward on its output once it knows the full frame layout.
    A live stdout pipe can't be seeked, so the only way to get that seek is
    to give ffmpeg a real file. The file is written to the container's local
    temp dir, streamed back to the client once complete, and deleted
    immediately after -- it never accumulates and isn't persisted, but it is
    a genuine (short-lived) disk write, unlike every other path in this app.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=f".{container}", dir=tempfile.gettempdir())
    os.close(fd)

    args = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin"]

    video_header_str = _format_ffmpeg_headers(video_headers)
    if video_header_str:
        args += ["-headers", video_header_str]
    args += ["-i", video_url]

    audio_header_str = _format_ffmpeg_headers(audio_headers)
    if audio_header_str:
        args += ["-headers", audio_header_str]
    args += ["-i", audio_url]

    args += ["-map", "0:v:0", "-map", "1:a:0", "-c", "copy"]

    if container == "mp4":
        args += ["-f", "mp4", "-movflags", "+faststart"]
    elif container == "webm":
        args += ["-f", "webm"]
    else:
        args += ["-f", "matroska"]

    args += [tmp_path]

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        os.remove(tmp_path)
        raise MuxError("ffmpeg is not installed on the server.") from exc

    _, stderr = await process.communicate()
    if process.returncode != 0:
        os.remove(tmp_path)
        raise MuxError(
            f"ffmpeg failed to merge video and audio: {stderr[-2000:].decode(errors='ignore')}"
        )

    filesize = os.path.getsize(tmp_path)
    if filesize > settings.MAX_ALLOWED_FILESIZE_BYTES:
        os.remove(tmp_path)
        raise MuxError("Merged file exceeds the maximum allowed download size.")

    async def _iterator() -> AsyncIterator[bytes]:
        try:
            with open(tmp_path, "rb") as f:
                while True:
                    chunk = await asyncio.to_thread(f.read, settings.DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return filesize, _iterator()
