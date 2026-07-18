const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type MediaKind = "video" | "audio" | "image";

export interface FormatOption {
  format_id: string;
  kind: MediaKind;
  ext: string;
  resolution: string | null;
  quality_label: string | null;
  vcodec: string | null;
  acodec: string | null;
  filesize_bytes: number | null;
  fps: number | null;
  has_audio: boolean;
  has_video: boolean;
  is_progressive: boolean;
  abr: number | null;
}

export interface ExtractResponse {
  source_url: string;
  platform: string;
  title: string;
  thumbnail: string | null;
  duration_seconds: number | null;
  uploader: string | null;
  formats: FormatOption[];
  extraction_id: string;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response): Promise<never> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (body?.detail) detail = body.detail;
  } catch {
    // response body wasn't JSON; fall back to statusText
  }
  throw new ApiError(res.status, detail);
}

export async function extractMedia(url: string): Promise<ExtractResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) return parseError(res);
  return res.json();
}

/**
 * Streams the chosen format from the backend and triggers a native browser
 * "Save As" download by piping the response body through a Blob URL.
 * onProgress receives bytes-received so callers can render a progress bar
 * (total may be null if the upstream didn't send Content-Length).
 */
export async function downloadMedia(
  params: { url: string; format_id: string; extraction_id: string; filename?: string },
  onProgress?: (loaded: number, total: number | null) => void
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok || !res.body) return parseError(res);

  const totalHeader = res.headers.get("Content-Length");
  const total = totalHeader ? Number(totalHeader) : null;

  const contentDisposition = res.headers.get("Content-Disposition") ?? "";
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch?.[1] ?? params.filename ?? "download";

  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.byteLength;
    onProgress?.(loaded, total);
  }

  const blob = new Blob(chunks as BlobPart[]);
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}
