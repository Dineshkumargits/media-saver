"use client";

import { FormEvent, useState } from "react";

interface UrlInputFormProps {
  onSubmit: (url: string) => void;
  loading: boolean;
}

export function UrlInputForm({ onSubmit, loading }: UrlInputFormProps) {
  const [url, setUrl] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (trimmed) onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full max-w-2xl flex-col gap-3 sm:flex-row">
      <input
        type="url"
        required
        placeholder="Paste a YouTube, Instagram, or other link…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        className="flex-1 rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-base
                   placeholder:text-slate-500 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/40"
      />
      <button
        type="submit"
        disabled={loading}
        className="rounded-xl bg-brand px-6 py-3 font-semibold text-white transition
                   hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? "Fetching…" : "Get Formats"}
      </button>
    </form>
  );
}
