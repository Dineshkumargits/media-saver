"""Short-lived, in-memory cache binding an /extract call to the /download
calls that follow it.

Why this exists: yt-dlp's direct CDN URLs are often signed and expire
within minutes, and we don't want the client dictating an arbitrary CDN
url directly (that would turn /download into an open proxy / SSRF
vector). Instead the client echoes back the `extraction_id` +
`format_id` we handed it, and we re-resolve the real, fresh CDN url
server-side at download time.

A single-process dict is fine for a self-hosted deployment. Swap for
Redis if you scale to multiple workers/replicas.
"""
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock

_TTL_SECONDS = 15 * 60


@dataclass
class CachedExtraction:
    source_url: str
    created_at: float = field(default_factory=time.time)


class ExtractionCache:
    def __init__(self) -> None:
        self._store: dict[str, CachedExtraction] = {}
        self._lock = Lock()

    def put(self, source_url: str) -> str:
        self._gc()
        extraction_id = uuid.uuid4().hex
        with self._lock:
            self._store[extraction_id] = CachedExtraction(source_url=source_url)
        return extraction_id

    def get(self, extraction_id: str) -> CachedExtraction | None:
        with self._lock:
            entry = self._store.get(extraction_id)
        if entry is None:
            return None
        if time.time() - entry.created_at > _TTL_SECONDS:
            with self._lock:
                self._store.pop(extraction_id, None)
            return None
        return entry

    def _gc(self) -> None:
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._store.items() if now - v.created_at > _TTL_SECONDS]
            for k in expired:
                self._store.pop(k, None)


extraction_cache = ExtractionCache()
