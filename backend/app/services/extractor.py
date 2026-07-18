"""Production-safe async wrapper around yt-dlp.

yt-dlp itself is fully synchronous and does blocking network I/O, so we
never call it on the event loop directly -- every call is pushed into a
bounded thread pool via asyncio.to_thread, gated by a semaphore so a
burst of requests can't spawn unbounded OS threads / outbound
connections.

This module never downloads media to disk: `extract_info(..., download=False)`
only resolves metadata + direct CDN URLs.

Muxing note: platforms like YouTube serve resolutions above ~360p as
separate video-only and audio-only DASH streams -- there is no single
progressive URL for e.g. 1080p. To still hand the user one clickable,
audio-included download, extract_metadata() pairs each video-only tier
with its best matching audio-only stream and encodes the pair as a
synthetic format_id "<video_id>+<audio_id>". resolve_download_target()
recognizes that shape and resolves both streams' direct URLs; the actual
byte-level remux happens in services/streamer.py via an ffmpeg pipe, with
no intermediate file ever touching disk.
"""
import asyncio
import logging
from typing import Any

import yt_dlp

from app.core.config import get_settings
from app.models.schemas import ExtractResponse, FormatOption, MediaKind
from app.utils.validators import UnsafeURLError, assert_public_http_url

logger = logging.getLogger(__name__)
settings = get_settings()

# Bounds how many concurrent yt-dlp extractions can run at once, protecting
# the host from thread/CPU exhaustion under load.
_extract_semaphore = asyncio.Semaphore(settings.MAX_EXTRACT_CONCURRENCY)

_CODEC_COMPAT_PRIORITY = {"avc1": 0, "h264": 0, "vp9": 1, "av01": 2}


class ExtractionError(Exception):
    """Raised for any user-facing extraction failure (bad url, unsupported
    site, private/age-restricted content, upstream throttling, etc)."""


def _base_ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": settings.YTDLP_SOCKET_TIMEOUT,
        "nocheckcertificate": False,
        "geo_bypass": True,
        # Never let yt-dlp write anything to disk (thumbnails, .info.json, etc)
        "writeinfojson": False,
        "writethumbnail": False,
        "cachedir": False,
        "logger": logging.getLogger("yt_dlp"),
    }
    if settings.YTDLP_COOKIES_FILE:
        opts["cookiefile"] = settings.YTDLP_COOKIES_FILE
    return opts


def _classify_format(fmt: dict[str, Any]) -> FormatOption | None:
    vcodec = fmt.get("vcodec")
    acodec = fmt.get("acodec")
    has_video = bool(vcodec and vcodec != "none")
    has_audio = bool(acodec and acodec != "none")

    if not has_video and not has_audio:
        return None  # e.g. storyboards/mhtml, not downloadable media

    if has_video:
        kind = MediaKind.VIDEO
        height = fmt.get("height")
        quality_label = f"{height}p" if height else fmt.get("format_note")
    else:
        kind = MediaKind.AUDIO
        abr = fmt.get("abr")
        quality_label = f"{int(abr)}kbps" if abr else fmt.get("format_note")

    resolution = None
    if fmt.get("width") and fmt.get("height"):
        resolution = f"{fmt['width']}x{fmt['height']}"

    return FormatOption(
        format_id=str(fmt["format_id"]),
        kind=kind,
        ext=fmt.get("ext", "bin"),
        resolution=resolution,
        quality_label=quality_label,
        vcodec=vcodec if has_video else None,
        acodec=acodec if has_audio else None,
        filesize_bytes=fmt.get("filesize") or fmt.get("filesize_approx"),
        fps=fmt.get("fps"),
        has_audio=has_audio,
        has_video=has_video,
        is_progressive=has_audio and has_video,
        abr=fmt.get("abr"),
    )


def _pick_container(video_ext: str, audio_ext: str) -> str:
    """Chooses an output container that ffmpeg can populate with `-c copy`
    (no re-encoding) for the given video/audio codec pairing."""
    if video_ext == "mp4" and audio_ext in ("m4a", "mp4", "aac"):
        return "mp4"
    if video_ext == "webm" and audio_ext in ("webm", "opus"):
        return "webm"
    # Matroska accepts virtually any codec combination via stream copy,
    # so it's a safe fallback when video/audio come from different families.
    return "mkv"


def _best_audio_raw(raw_formats: list[dict[str, Any]], prefer_ext: str) -> dict[str, Any] | None:
    candidates = [
        f
        for f in raw_formats
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]
    if not candidates:
        return None
    preferred = [f for f in candidates if f.get("ext") == prefer_ext]
    pool = preferred or candidates
    return max(pool, key=lambda f: f.get("abr") or 0)


def _dedupe_video_only(video_only: list[FormatOption]) -> list[FormatOption]:
    """One entry per resolution, preferring the most broadly-compatible codec
    (avc1/h264) over vp9/av01 when a tier has multiple codec variants."""

    def codec_rank(f: FormatOption) -> int:
        base = (f.vcodec or "").split(".")[0]
        return _CODEC_COMPAT_PRIORITY.get(base, 3)

    best_by_res: dict[str, FormatOption] = {}
    for f in sorted(video_only, key=codec_rank):
        key = f.resolution or f.quality_label or f.format_id
        if key not in best_by_res:
            best_by_res[key] = f
    return list(best_by_res.values())


def _build_video_formats(
    classified: list[FormatOption], raw_formats: list[dict[str, Any]]
) -> list[FormatOption]:
    """Progressive (already-muxed) formats pass through untouched. Video-only
    tiers get paired with the best matching audio-only stream into a
    synthetic "<video_id>+<audio_id>" format that /download will remux
    on the fly."""
    progressive = [f for f in classified if f.is_progressive]
    video_only = _dedupe_video_only([f for f in classified if f.has_video and not f.has_audio])

    covered_resolutions = {f.resolution for f in progressive if f.resolution}

    merged: list[FormatOption] = []
    for vf in video_only:
        if vf.resolution in covered_resolutions:
            continue  # a progressive stream already covers this tier
        prefer_ext = "m4a" if vf.ext == "mp4" else "webm"
        audio_raw = _best_audio_raw(raw_formats, prefer_ext=prefer_ext)
        if audio_raw is None:
            merged.append(vf)  # no audio available anywhere; expose as-is
            continue

        container = _pick_container(vf.ext, audio_raw.get("ext", "bin"))
        audio_size = audio_raw.get("filesize") or audio_raw.get("filesize_approx") or 0
        combined_size = (vf.filesize_bytes or 0) + audio_size

        merged.append(
            FormatOption(
                format_id=f"{vf.format_id}+{audio_raw['format_id']}",
                kind=MediaKind.VIDEO,
                ext=container,
                resolution=vf.resolution,
                quality_label=vf.quality_label,
                vcodec=vf.vcodec,
                acodec=audio_raw.get("acodec"),
                filesize_bytes=combined_size or None,
                fps=vf.fps,
                has_audio=True,
                has_video=True,
                is_progressive=True,
                abr=audio_raw.get("abr"),
            )
        )

    return progressive + merged


def _dedupe_and_rank(formats: list[FormatOption]) -> list[FormatOption]:
    video = [f for f in formats if f.kind == MediaKind.VIDEO]
    audio_only = [f for f in formats if f.kind == MediaKind.AUDIO]
    image = [f for f in formats if f.kind == MediaKind.IMAGE]

    def video_rank(f: FormatOption) -> int:
        try:
            return int((f.resolution or "0x0").split("x")[1])
        except (IndexError, ValueError):
            return 0

    video.sort(key=video_rank, reverse=True)
    audio_only.sort(key=lambda f: f.abr or 0, reverse=True)

    return video + audio_only + image


def _run_extract_sync(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_base_ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ExtractionError("No media information could be extracted from this URL.")
    # Playlists: take the first entry only -- this endpoint is single-item by design
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise ExtractionError("This looks like an empty or private playlist.")
        info = entries[0]
    return info


async def extract_metadata(url: str) -> ExtractResponse:
    try:
        safe_url = assert_public_http_url(str(url))
    except UnsafeURLError as exc:
        raise ExtractionError(str(exc)) from exc

    async with _extract_semaphore:
        try:
            info = await asyncio.to_thread(_run_extract_sync, safe_url)
        except yt_dlp.utils.DownloadError as exc:
            logger.warning("yt-dlp extraction failed for %s: %s", safe_url, exc)
            raise ExtractionError(
                "Could not extract media from this link. It may be private, "
                "region-locked, or the platform isn't supported."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - convert all failures to a safe boundary error
            logger.exception("Unexpected extraction failure for %s", safe_url)
            raise ExtractionError("Unexpected error while processing this link.") from exc

    raw_formats = info.get("formats") or []
    classified = [f for f in (_classify_format(rf) for rf in raw_formats) if f is not None]

    video_formats = _build_video_formats(classified, raw_formats)
    audio_only = [f for f in classified if f.has_audio and not f.has_video]
    formats = video_formats + audio_only

    # Some extractors (e.g. direct image posts) have no "formats" list at all,
    # only a top-level url -- synthesize a single option in that case.
    if not formats and info.get("url"):
        formats = [
            FormatOption(
                format_id="direct",
                kind=MediaKind.IMAGE if info.get("ext") in {"jpg", "jpeg", "png", "webp"} else MediaKind.VIDEO,
                ext=info.get("ext", "bin"),
                has_audio=False,
                has_video=info.get("ext") not in {"jpg", "jpeg", "png", "webp"},
                is_progressive=False,
                filesize_bytes=info.get("filesize"),
            )
        ]

    if not formats:
        raise ExtractionError("No downloadable media formats were found for this link.")

    from app.services.extraction_cache import extraction_cache

    extraction_id = extraction_cache.put(source_url=safe_url)

    return ExtractResponse(
        source_url=safe_url,
        platform=info.get("extractor_key", "generic"),
        title=info.get("title", "Untitled"),
        thumbnail=info.get("thumbnail"),
        duration_seconds=info.get("duration"),
        uploader=info.get("uploader"),
        formats=_dedupe_and_rank(formats),
        extraction_id=extraction_id,
    )


def _run_extract_sync_with_format(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ExtractionError("No media information could be extracted from this URL.")
    return info


async def _resolve_single_format(source_url: str, format_id: str) -> dict[str, Any]:
    opts = _base_ydl_opts()
    opts["format"] = format_id

    async with _extract_semaphore:
        try:
            info = await asyncio.to_thread(_run_extract_sync_with_format, source_url, opts)
        except yt_dlp.utils.DownloadError as exc:
            raise ExtractionError("This link is no longer available for download.") from exc

    chosen = (info.get("requested_downloads") or [info])[0]
    direct_url = chosen.get("url")
    if not direct_url:
        raise ExtractionError("Could not resolve a direct media URL for the requested format.")

    return {
        "url": direct_url,
        "http_headers": chosen.get("http_headers") or info.get("http_headers") or {},
        "ext": chosen.get("ext", "bin"),
        "filesize": chosen.get("filesize") or chosen.get("filesize_approx"),
        "title": info.get("title", "download"),
    }


async def resolve_download_target(source_url: str, format_id: str) -> dict[str, Any]:
    """Re-resolve fresh, short-lived direct CDN url(s) + headers for the given
    format right before streaming, since URLs captured during /extract may
    have expired by the time the user picks a format.

    A format_id containing "+" is a synthesized video+audio pair (see
    _build_video_formats); both sides are resolved independently and the
    caller is expected to remux them via ffmpeg rather than stream either
    one directly.
    """
    if "+" in format_id:
        video_id, audio_id = format_id.split("+", 1)
        video_target = await _resolve_single_format(source_url, video_id)
        audio_target = await _resolve_single_format(source_url, audio_id)
        container = _pick_container(video_target["ext"], audio_target["ext"])
        return {
            "merge": True,
            "video": video_target,
            "audio": audio_target,
            "container": container,
            "title": video_target.get("title") or audio_target.get("title", "download"),
        }

    return await _resolve_single_format(source_url, format_id if format_id != "direct" else "best")
