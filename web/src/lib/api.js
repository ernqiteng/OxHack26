"use client";

import { useCallback, useEffect, useState } from "react";

export async function api(path, options) {
  const res = await fetch(`/api${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

/** GET a JSON endpoint; refetches when `path` changes. `path` null skips the request. */
export function useApi(path, { refreshMs } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path });

  const load = useCallback(async () => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api(path);
      setState({ data, error: null, loading: false });
    } catch (error) {
      setState({ data: null, error, loading: false });
    }
  }, [path]);

  useEffect(() => {
    load();
    if (!refreshMs) return;
    const id = setInterval(load, refreshMs);
    return () => clearInterval(id);
  }, [load, refreshMs]);

  return { ...state, reload: load };
}

const LONDON = { timeZone: "Europe/London" };
export const fmtTime = (iso) =>
  new Date(iso).toLocaleTimeString("en-GB", { ...LONDON, hour: "2-digit", minute: "2-digit" });
export const fmtDay = (iso) =>
  new Date(iso).toLocaleDateString("en-GB", { ...LONDON, weekday: "short", day: "2-digit", month: "short" });
export const gbp = (v, digits = 2) =>
  v == null ? "—" : `${v < 0 ? "−" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

export const ACTION = {
  charge: { label: "Charge", glyph: "▲", color: "var(--charge)" },
  discharge: { label: "Sell", glyph: "▼", color: "var(--sell)" },
  hold: { label: "Hold", glyph: "—", color: "var(--hold)" },
};
