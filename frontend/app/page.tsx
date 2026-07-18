"use client";

import { FormatGrid } from "@/components/FormatGrid";
import { UrlInputForm } from "@/components/UrlInputForm";
import { useExtract } from "@/hooks/useExtract";

export default function HomePage() {
  const { data, loading, error, runExtract } = useExtract();

  return (
    <main className="flex min-h-screen flex-col items-center gap-10 px-4 py-20">
      <div className="flex flex-col items-center gap-3 text-center">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Media <span className="text-brand">Saver</span>
        </h1>
        <p className="max-w-lg text-slate-400">
          Download videos, reels, and audio from YouTube, Instagram, and most other platforms —
          straight to your device.
        </p>
      </div>

      <UrlInputForm onSubmit={runExtract} loading={loading} />

      {error && (
        <p className="max-w-2xl rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {error}
        </p>
      )}

      {data && <FormatGrid extraction={data} />}
    </main>
  );
}
