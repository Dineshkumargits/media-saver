"use client";

import { useCallback, useState } from "react";
import { ApiError, ExtractResponse, extractMedia } from "@/lib/api";

interface UseExtractState {
  data: ExtractResponse | null;
  loading: boolean;
  error: string | null;
}

export function useExtract() {
  const [state, setState] = useState<UseExtractState>({
    data: null,
    loading: false,
    error: null,
  });

  const runExtract = useCallback(async (url: string) => {
    setState({ data: null, loading: true, error: null });
    try {
      const result = await extractMedia(url);
      setState({ data: result, loading: false, error: null });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      setState({ data: null, loading: false, error: message });
    }
  }, []);

  const reset = useCallback(() => setState({ data: null, loading: false, error: null }), []);

  return { ...state, runExtract, reset };
}
