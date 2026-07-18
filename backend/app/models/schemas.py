from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class MediaKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"


class ExtractRequest(BaseModel):
    url: HttpUrl


class FormatOption(BaseModel):
    """One selectable download variant, mapped from a yt-dlp format dict."""

    format_id: str
    kind: MediaKind
    ext: str
    resolution: str | None = None          # e.g. "1920x1080"
    quality_label: str | None = None       # e.g. "1080p", "128kbps"
    vcodec: str | None = None
    acodec: str | None = None
    filesize_bytes: int | None = None
    fps: float | None = None
    has_audio: bool = False
    has_video: bool = False
    is_progressive: bool = False           # True when a/v are already muxed together
    abr: float | None = None               # audio bitrate, kbps


class ExtractResponse(BaseModel):
    source_url: str
    platform: str
    title: str
    thumbnail: str | None = None
    duration_seconds: float | None = None
    uploader: str | None = None
    formats: list[FormatOption]
    # opaque, short-lived token the frontend must echo back on /download
    # to prove the requested format came from a extraction we performed
    extraction_id: str


class DownloadRequest(BaseModel):
    url: HttpUrl = Field(..., description="Original source page URL (not the CDN url)")
    format_id: str
    extraction_id: str
    filename: str | None = None
