"use client";

import { useMemo, useState } from "react";
import { ExtractResponse, MediaKind } from "@/lib/api";
import { FormatCard } from "./FormatCard";

const TABS: { key: MediaKind; label: string }[] = [
  { key: "video", label: "Video" },
  { key: "audio", label: "Audio Only" },
  { key: "image", label: "Image" },
];

export function FormatGrid({ extraction }: { extraction: ExtractResponse }) {
  const availableTabs = useMemo(
    () => TABS.filter((t) => extraction.formats.some((f) => f.kind === t.key)),
    [extraction.formats]
  );
  const [activeTab, setActiveTab] = useState<MediaKind>(availableTabs[0]?.key ?? "video");

  const visibleFormats = extraction.formats.filter((f) => f.kind === activeTab);

  return (
    <div className="w-full max-w-4xl">
      <div className="mb-6 flex items-center gap-4">
        {extraction.thumbnail && (
          <img
            src={extraction.thumbnail}
            alt=""
            className="h-16 w-28 rounded-lg object-cover"
          />
        )}
        <div>
          <h2 className="line-clamp-2 font-semibold text-slate-100">{extraction.title}</h2>
          <p className="text-sm text-slate-500">
            {extraction.platform}
            {extraction.uploader ? ` · ${extraction.uploader}` : ""}
          </p>
        </div>
      </div>

      <div className="mb-4 flex gap-2 border-b border-slate-800">
        {availableTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium transition ${
              activeTab === tab.key
                ? "border-b-2 border-brand text-brand"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleFormats.map((format) => (
          <FormatCard key={format.format_id} format={format} extraction={extraction} />
        ))}
      </div>
    </div>
  );
}
