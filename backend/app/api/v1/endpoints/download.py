import re
import shutil
import unicodedata

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.limiter import limiter
from app.services.extraction_cache import extraction_cache
from app.services.extractor import ExtractionError, resolve_download_target
from app.services.streamer import MuxError, UpstreamError, mux_to_temp_and_stream, stream_upstream
from app.models.schemas import DownloadRequest

router = APIRouter()
settings = get_settings()

_CONTENT_TYPES = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _safe_filename(name: str, ext: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^\w\-. ]", "", normalized).strip() or "download"
    cleaned = cleaned[:150]
    return f"{cleaned}.{ext}"


@router.post("/download")
@limiter.limit(settings.RATE_LIMIT_DOWNLOAD)
async def download(request: Request, payload: DownloadRequest) -> StreamingResponse:
    """Streams the chosen media format byte-by-byte from the origin CDN to
    the client. Single-stream formats never touch the server's disk; merged
    video+audio formats use a short-lived temp file (see
    mux_to_temp_and_stream) that's deleted immediately after streaming."""
    cached = extraction_cache.get(payload.extraction_id)
    if cached is None:
        raise HTTPException(
            status_code=410,
            detail="This extraction has expired. Please re-fetch formats for this URL.",
        )
    if cached.source_url != str(payload.url):
        raise HTTPException(status_code=400, detail="URL does not match the original extraction.")

    try:
        target = await resolve_download_target(cached.source_url, payload.format_id)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if target.get("merge"):
        if shutil.which("ffmpeg") is None:
            raise HTTPException(status_code=500, detail="Server is missing ffmpeg; cannot merge video and audio.")

        # Video-only + audio-only pair: remux via ffmpeg into a standard,
        # faststart-compatible container (required for strict consumers like
        # WhatsApp) and stream the finished file back. See
        # mux_to_temp_and_stream's docstring for why this needs a temp file.
        ext = target["container"]
        filename = _safe_filename(payload.filename or target.get("title", "download"), ext)
        media_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

        try:
            filesize, byte_iterator = await mux_to_temp_and_stream(
                video_url=target["video"]["url"],
                video_headers=target["video"].get("http_headers"),
                audio_url=target["audio"]["url"],
                audio_headers=target["audio"].get("http_headers"),
                container=ext,
            )
        except MuxError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return StreamingResponse(
            byte_iterator,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(filesize),
            },
        )

    try:
        response, byte_iterator = await stream_upstream(
            url=target["url"],
            headers=target.get("http_headers"),
            range_header=request.headers.get("range"),
        )
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ext = target.get("ext", "bin")
    filename = _safe_filename(payload.filename or target.get("title", "download"), ext)
    media_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

    response_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Accept-Ranges": "bytes",
    }
    upstream_content_length = response.headers.get("content-length")
    if upstream_content_length:
        response_headers["Content-Length"] = upstream_content_length
    upstream_content_range = response.headers.get("content-range")
    if upstream_content_range:
        response_headers["Content-Range"] = upstream_content_range

    status_code = 206 if upstream_content_range else 200

    return StreamingResponse(
        byte_iterator,
        status_code=status_code,
        media_type=media_type,
        headers=response_headers,
    )
