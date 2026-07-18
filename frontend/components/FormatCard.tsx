"use client";

import { useState } from "react";
import { downloadMedia, ExtractResponse, FormatOption } from "@/lib/api";

function formatBytes(bytes: number | null): string {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

interface FormatCardProps {
  format: FormatOption;
  extraction: ExtractResponse;
}

export function FormatCard({ format, extraction }: FormatCardProps) {
  const [progress, setProgress] = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label =
    format.quality_label ?? (format.kind === "audio" ? "Audio" : format.resolution ?? "Original");

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    setProgress(0);
    try {
      await downloadMedia(
        {
          url: extraction.source_url,
          format_id: format.format_id,
          extraction_id: extraction.extraction_id,
          filename: extraction.title,
        },
        (loaded, total) => {
          if (total) setProgress(Math.round((loaded / total) * 100));
        }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setDownloading(false);
      setProgress(null);
    }
  }

  return (
    <div className="flex flex-col justify-between rounded-xl border border-slate-800 bg-slate-900 p-4 shadow-sm">
      <div>
        <div className="flex items-center justify-between">
          <span className="text-lg font-semibold">{label}</span>
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs uppercase tracking-wide text-slate-400">
            {format.kind}
          </span>
        </div>
        <dl className="mt-2 space-y-1 text-sm text-slate-400">
          <div className="flex justify-between">
            <dt>Format</dt>
            <dd className="uppercase">{format.ext}</dd>
          </div>
          {format.filesize_bytes && (
            <div className="flex justify-between">
              <dt>Size</dt>
              <dd>{formatBytes(format.filesize_bytes)}</dd>
            </div>
          )}
          {format.is_progressive === false && format.has_video && (
            <div className="text-xs text-amber-400">Video-only (no audio track)</div>
          )}
        </dl>
      </div>

      <button
        onClick={handleDownload}
        disabled={downloading}
        className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white
                   transition hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {downloading ? (progress !== null ? `Downloading ${progress}%` : "Downloading…") : "Download"}
      </button>
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
    </div>
  );
}
