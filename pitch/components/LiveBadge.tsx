"use client";

import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";

type Live = { period: number; latest_price: number | null };

// "● LIVE · period N · £X/MWh" from the API. Hidden unless the API is up and reading Tiger (not synthetic data).
export function LiveBadge() {
  const [live, setLive] = useState<Live | null>(null);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const status = await getJSON<{ source: string }>("/api/status");
        const next = status.source === "tiger" ? await getJSON<Live>("/api/live", 10000) : null;
        if (!stop) setLive(next);
      } catch {
        if (!stop) setLive(null);
      }
    };
    poll();
    const id = setInterval(poll, 60_000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, []);

  if (!live) return null;
  return (
    <span className="flex items-center gap-2 rounded-md bg-brand px-4 py-2.5 font-mono text-xs font-medium uppercase tracking-[0.12em] text-paper">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-charge opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-charge" />
      </span>
      Live · period {live.period}
      {live.latest_price != null && <> · {live.latest_price < 0 ? "−" : ""}£{Math.abs(live.latest_price).toFixed(2)}/MWh</>}
    </span>
  );
}
