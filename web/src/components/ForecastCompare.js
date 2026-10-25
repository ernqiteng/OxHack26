"use client";

import { useMemo, useRef, useState } from "react";
import { gbp, useApi } from "@/lib/api";
import { ramp, RAMP_CSS } from "@/lib/ramp";
import { toWeekGrid } from "@/lib/week";

const LABEL_W = 64;

export default function ForecastCompare() {
  const { data, error, loading } = useApi("/replay");
  const [split, setSplit] = useState(50);
  const [hover, setHover] = useState(null);
  const box = useRef(null);

  const grid = useMemo(() => (data ? toWeekGrid(data.rows) : []), [data]);
  const [lo, hi] = useMemo(() => {
    const v = (data?.rows || []).flatMap((r) => [r.actual, r.p50]).filter((x) => x != null);
    return v.length ? [Math.min(...v), Math.max(...v)] : [0, 1];
  }, [data]);

  if (loading) return <p className="text-slate-600">Loading replay week…</p>;
  if (error) return <p className="text-red-600">Could not load the replay week: {error.message}</p>;
  if (!grid.length) return <p className="text-slate-600">No replay week stored yet.</p>;

  const startDrag = (e) => {
    e.preventDefault();
    const rect = box.current.getBoundingClientRect();
    const move = (ev) => {
      const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - rect.left - LABEL_W;
      setSplit(Math.max(0, Math.min(100, (px / (rect.width - LABEL_W)) * 100)));
    };
    const up = () => {
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchmove", move);
      window.removeEventListener("touchend", up);
    };
    document.body.style.cursor = "ew-resize";
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    window.addEventListener("touchmove", move);
    window.addEventListener("touchend", up);
  };

  const layer = (key) => (
    <div className="grid gap-[2px]" style={{ gridTemplateRows: `repeat(${grid.length}, 1fr)` }}>
      {grid.map((day) => (
        <div key={day.label} className="grid gap-[2px]" style={{ gridTemplateColumns: "repeat(48, 1fr)" }}>
          {Array.from({ length: 48 }, (_, s) => {
            const c = day.cells.find((c) => c.slot === s);
            return (
              <div
                key={s}
                className="h-9 rounded-[2px]"
                style={{ background: c && c[key] != null ? ramp((c[key] - lo) / (hi - lo)) : "#e2e8f0" }}
                onMouseEnter={() => c && setHover({ ...c, day: day.label })}
              />
            );
          })}
        </div>
      ))}
    </div>
  );

  return (
    <div className="bg-white rounded-lg shadow p-4 text-left">
      <div ref={box} className="relative select-none" onMouseLeave={() => setHover(null)}>
        <div className="flex">
          <div className="grid gap-[2px] shrink-0" style={{ width: LABEL_W, gridTemplateRows: `repeat(${grid.length}, 1fr)` }}>
            {grid.map((d) => <div key={d.label} className="h-9 flex items-center text-xs text-slate-600">{d.label}</div>)}
          </div>
          <div className="relative flex-1 min-w-0">
            {layer("actual")}
            <div className="absolute inset-0 overflow-hidden pointer-events-none" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>
              {layer("p50")}
            </div>
            <div className="absolute inset-0 pointer-events-none">
              <span className="absolute left-1 -top-6 text-xs font-semibold text-slate-700">◀ Forecast p50</span>
              <span className="absolute right-1 -top-6 text-xs font-semibold text-slate-700">Settled price ▶</span>
            </div>
            <div
              role="slider"
              aria-label="Compare forecast and settled price"
              aria-valuenow={Math.round(split)}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft") setSplit((s) => Math.max(0, s - 5));
                if (e.key === "ArrowRight") setSplit((s) => Math.min(100, s + 5));
              }}
              onMouseDown={startDrag}
              onTouchStart={startDrag}
              className="absolute top-[-4px] bottom-[-4px] w-1 bg-white cursor-ew-resize z-10 focus:outline-2 focus:outline-blue-500"
              style={{ left: `${split}%`, transform: "translateX(-2px)", boxShadow: "0 0 10px rgba(0,0,0,0.35)" }}
            >
              <span className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 left-1/2 w-6 h-6 rounded-full bg-white shadow flex items-center justify-center text-[10px] text-slate-600">⇔</span>
            </div>
          </div>
        </div>
        <div className="flex mt-1 text-[11px] text-slate-500" style={{ paddingLeft: LABEL_W }}>
          {["00:00", "06:00", "12:00", "18:00", "24:00"].map((t, i) => (
            <span key={t} className="flex-1" style={{ textAlign: i === 0 ? "left" : i === 4 ? "right" : "center" }}>{t}</span>
          ))}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <span>{gbp(lo, 0)}</span>
        <span className="h-3 w-40 rounded-sm" style={{ background: RAMP_CSS }} />
        <span>{gbp(hi, 0)} per MWh</span>
        <span className="ml-auto min-h-5 text-slate-800">
          {hover ? (
            <>
              <b>{hover.day} {hover.time}</b>: forecast {gbp(hover.p50)}, settled {gbp(hover.actual)}
              {hover.actual != null && hover.p50 != null && <> (off by {gbp(Math.abs(hover.actual - hover.p50))})</>}
            </>
          ) : "Hover a cell for its numbers"}
        </span>
      </div>
    </div>
  );
}
