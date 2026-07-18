# Media Saver

Self-hosted media downloader (YouTube, Instagram, and general links) with a
server-side extraction flow that never buffers files to disk.

## Architecture

```
┌─────────────┐   POST /api/v1/extract   ┌──────────────┐   extract_info(download=False)   ┌─────────┐
│  Next.js UI │ ───────────────────────▶ │  FastAPI     │ ────────────────────────────────▶ │ yt-dlp  │
│  (frontend) │ ◀─────────────────────── │  (backend)   │ ◀──────────────────────────────── │/instagrapi│
└─────────────┘   formats + extraction_id└──────────────┘                                   └─────────┘
       │
       │ POST /api/v1/download {url, format_id, extraction_id}
       ▼
┌──────────────┐   re-resolve fresh CDN url   ┌─────────────┐   httpx streaming GET   ┌───────────┐
│  FastAPI     │ ────────────────────────────▶│ yt-dlp      │────────────────────────▶│ Platform  │
│  StreamingResponse, chunked, no disk writes  │             │                         │ CDN       │
└──────────────┘◀──────────────────────────── └─────────────┘◀────────────────────────└───────────┘
```

Key design decisions:

- **Two-phase flow.** `/extract` only resolves metadata (title, thumbnail,
  available formats) via `yt_dlp.extract_info(download=False)` — no bytes
  touch the server. `/download` is a separate call that streams the actual
  media.
- **Fresh URL re-resolution.** CDN URLs returned by `/extract` are often
  signed and short-lived. `/download` re-resolves the direct URL right
  before streaming rather than trusting a URL cached client-side, which
  also closes off an open-proxy/SSRF vector (see `extraction_cache.py` and
  `utils/validators.py`).
- **True streaming, not buffering.** `services/streamer.py` uses `httpx`'s
  async streaming client plus FastAPI's `StreamingResponse` to forward
  bytes chunk-by-chunk from the origin CDN to the browser. Disk usage stays
  flat regardless of file size.
- **Rate limiting.** `slowapi` guards both endpoints per-IP
  (`RATE_LIMIT_EXTRACT`, `RATE_LIMIT_DOWNLOAD` in `.env`).
- **Instagram.** The generic `yt-dlp` extractor handles most public
  posts/reels. `services/instagram.py` provides an optional, session-cached
  `instagrapi` fallback (logs in once, persists cookies to
  `sessions/ig_session.json`) for when anonymous scraping gets throttled —
  configure `IG_USERNAME`/`IG_PASSWORD` to enable it.

## Directory Structure

```
media-saver/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory, CORS, rate limiter, error handlers
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings (env-driven)
│   │   │   ├── limiter.py           # shared slowapi Limiter
│   │   │   └── logging.py
│   │   ├── api/v1/
│   │   │   ├── router.py
│   │   │   └── endpoints/
│   │   │       ├── extract.py       # POST /api/v1/extract
│   │   │       └── download.py      # POST /api/v1/download
│   │   ├── services/
│   │   │   ├── extractor.py         # yt-dlp async wrapper + format ranking
│   │   │   ├── instagram.py         # instagrapi session-cached fallback
│   │   │   ├── streamer.py          # httpx chunked CDN piping
│   │   │   └── extraction_cache.py  # binds extract_id -> source url (TTL)
│   │   ├── models/schemas.py        # ExtractRequest/Response, DownloadRequest, FormatOption
│   │   └── utils/validators.py      # SSRF / unsafe-URL guard
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── app/
│   │   ├── page.tsx                 # landing page
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── UrlInputForm.tsx
│   │   ├── FormatGrid.tsx           # tabbed video/audio/image grid
│   │   └── FormatCard.tsx           # per-format download button + progress
│   ├── hooks/useExtract.ts
│   ├── lib/api.ts                   # typed fetch client, streams download to a Blob
│   ├── package.json
│   └── Dockerfile
└── docker-compose.yml
```

## Running locally

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Visit `http://localhost:3000`.

### Docker Compose

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

## Notes on production hardening

- Swap `ExtractionCache`'s in-memory dict for Redis if you run multiple
  backend replicas (the TTL/key logic already isolates this behind
  `extraction_cache.py`).
- `MAX_ALLOWED_FILESIZE_BYTES` and `MAX_EXTRACT_CONCURRENCY` in `.env`
  bound worst-case memory/thread usage per instance — tune to your host.
- Put the backend behind a reverse proxy (nginx/Caddy) with request
  timeouts tuned for large file downloads, and consider a CDN/pull cache
  in front of `/download` if the same media is requested often.
