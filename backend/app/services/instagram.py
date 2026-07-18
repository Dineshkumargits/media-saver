"""Instagram-specific fallback extraction using instagrapi.

yt-dlp handles most public Instagram posts/reels out of the box, but
Instagram aggressively rate-limits/IP-bans anonymous scraping. This
module provides an authenticated, session-cached instagrapi client as a
fallback path for when yt-dlp's generic extractor gets throttled.

Design notes:
  - The session (auth cookies) is persisted to disk (IG_SESSION_PATH) and
    reused across requests, so we log in once, not per-request -- repeated
    logins are exactly what gets accounts flagged.
  - The client is a lazily-initialized singleton guarded by an asyncio lock
    so concurrent requests don't race to log in simultaneously.
  - All instagrapi calls are synchronous, so they're pushed to a thread,
    matching the pattern used in extractor.py.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client_lock = asyncio.Lock()
_client: Any | None = None


class InstagramUnavailableError(Exception):
    """Raised when instagrapi isn't configured or login fails."""


def _build_client_sync() -> Any:
    try:
        from instagrapi import Client
    except ImportError as exc:  # optional dependency
        raise InstagramUnavailableError(
            "instagrapi is not installed; add it to requirements.txt to enable "
            "the authenticated Instagram fallback."
        ) from exc

    if not settings.IG_USERNAME or not settings.IG_PASSWORD:
        raise InstagramUnavailableError(
            "IG_USERNAME/IG_PASSWORD are not configured; authenticated "
            "Instagram fallback is disabled."
        )

    client = Client()
    session_path = Path(settings.IG_SESSION_PATH)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    if session_path.exists():
        try:
            client.load_settings(session_path)
            client.login(settings.IG_USERNAME, settings.IG_PASSWORD)
            client.get_timeline_feed()  # cheap call to validate the session is still alive
            logger.info("Instagram session restored from cache")
            return client
        except Exception:  # noqa: BLE001 - any failure -> fall through to fresh login
            logger.warning("Cached Instagram session invalid, re-authenticating")

    client.login(settings.IG_USERNAME, settings.IG_PASSWORD)
    client.dump_settings(session_path)
    logger.info("Instagram session established and cached to %s", session_path)
    return client


async def _get_client() -> Any:
    global _client
    async with _client_lock:
        if _client is None:
            _client = await asyncio.to_thread(_build_client_sync)
    return _client


async def extract_instagram_media(url: str) -> dict[str, Any]:
    """Returns a yt-dlp-shaped info dict for a single Instagram post/reel URL,
    so callers can pass it through the same FormatOption mapping used
    elsewhere. Only used as a fallback when the generic extractor fails.
    """
    client = await _get_client()

    def _fetch() -> dict[str, Any]:
        media_pk = client.media_pk_from_url(url)
        media = client.media_info(media_pk)
        resources = media.resources or [media]

        formats: list[dict[str, Any]] = []
        for idx, res in enumerate(resources):
            if res.video_url:
                formats.append(
                    {
                        "format_id": f"ig-video-{idx}",
                        "url": str(res.video_url),
                        "ext": "mp4",
                        "vcodec": "h264",
                        "acodec": "aac",
                        "width": res.video_width or None,
                        "height": res.video_height or None,
                    }
                )
            elif res.thumbnail_url:
                formats.append(
                    {
                        "format_id": f"ig-image-{idx}",
                        "url": str(res.thumbnail_url),
                        "ext": "jpg",
                        "vcodec": "none",
                        "acodec": "none",
                        "width": res.thumbnail_width or None,
                        "height": res.thumbnail_height or None,
                    }
                )

        return {
            "extractor_key": "Instagram",
            "title": media.caption_text[:120] if media.caption_text else "Instagram media",
            "thumbnail": str(media.thumbnail_url) if media.thumbnail_url else None,
            "duration": getattr(media, "video_duration", None),
            "uploader": media.user.username if media.user else None,
            "formats": formats,
        }

    return await asyncio.to_thread(_fetch)
