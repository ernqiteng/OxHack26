"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fmtDay, fmtTime, gbp, useApi } from "@/lib/api";
import { toWeekGrid } from "@/lib/week";
import { useWidth } from "@/lib/useWidth";

// Cell states, in the spirit of ICHack26's EMPTY / TREE / BURNING / BURNT grid.
const COLORS = {
  upcoming: "#d3d3d3",
  hold: "#64748b",
  charge: "#15803d",
  sell: "#e11d48",
  playhead: "#facc15",
};
const ROW_H = 34;
const LEGEND = [
  ["upcoming", "Not played yet"],
  ["hold", "Held"],
  ["charge", "▲ Charged"],
  ["sell", "▼ Sold"],
];

export default function ReplaySimulation() {
  const { data, error, loading } = useApi("/replay");
  const rows = useMemo(() => data?.rows || [], [data]);
  const [wrap, width] = useWidth();
  const grid = useMemo(() => toWeekGrid(rows), [rows]);
  const [pos, setPos] = useState(-1);
  const [running, setRunning] = useState(false);
  const [speed, setSpeed] = useState(12); // periods per second
  const canvas = useRef(null);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      setPos((p) => {
        if (p >= rows.length - 1) {
          setRunning(false);
          return p;
        }
        return p + 1;
      });
    }, 1000 / speed);
    return () => clearInterval(id);
  }, [running, speed, rows.length]);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !grid.length) return;
    const dpr = window.devicePixelRatio || 1;
    const w = el.clientWidth;
    const cell = (w - 47 * 2) / 48;
    const h = grid.length * (ROW_H + 2) - 2;
    el.width = w * dpr;
    el.height = h * dpr;
    el.style.height = `${h}px`;
    const ctx = el.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    grid.forEach((day, d) =>
      day.cells.forEach((c) => {
        const state = c.i > pos ? "upcoming" : c.mw > 0 ? "charge" : c.mw < 0 ? "sell" : "hold";
        ctx.fillStyle = COLORS[state];
        const x = c.slot * (cell + 2);
        const y = d * (ROW_H + 2);
        ctx.beginPath();
        ctx.roundRect(x, y, cell, ROW_H, 2);
        ctx.fill();
        if (c.i === pos) {
          ctx.strokeStyle = COLORS.playhead;
          ctx.lineWidth = 3;
          ctx.strokeRect(x - 1, y - 1, cell + 2, ROW_H + 2);
        }
      }),
    );
  }, [grid, pos, width]);

  if (loading) return <p className="text-slate-600">Loading replay week…</p>;
  if (error) return <p className="text-red-600">Could not load the replay week: {error.message}</p>;
  if (!rows.length) return <p className="text-slate-600">No replay week stored yet.</p>;

  const cur = pos >= 0 ? rows[pos] : null;
  const done = pos >= rows.length - 1;

  return (
    <div className="bg-white rounded-lg shadow p-4 text-left">
      <div className="flex gap-2">
        <div className="flex flex-col gap-[2px] shrink-0 w-14 text-xs text-slate-600">
          {grid.map((d) => <span key={d.label} className="flex items-center" style={{ height: ROW_H }}>{d.label}</span>)}
        </div>
        <div ref={wrap} className="flex-1 min-w-0"><canvas ref={canvas} className="w-full block" aria-label="Replay week grid, one cell per half-hour" /></div>
      </div>

      <div className="mt-4 min-h-16 rounded-md bg-slate-100 p-3 text-center text-slate-700">
        {cur ? (
          <>
            <p className="font-semibold">{fmtDay(cur.ts)} {fmtTime(cur.ts)}: {cur.mw > 0 ? "▲ charging" : cur.mw < 0 ? "▼ selling" : "holding"} at {gbp(cur.actual)}/MWh</p>
            <p>State of charge {cur.soc_mwh?.toFixed(2)} MWh · running P&amp;L <b>{gbp(cur.cum_pnl_gbp)}</b></p>
          </>
        ) : (
          <p>Press Start to play the week back.</p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <SimButton color="bg-green-600 hover:bg-green-700" onClick={() => { if (done) setPos(-1); setRunning(true); }} disabled={running}>
          {pos < 0 ? "Start" : done ? "Replay" : "Resume"}
        </SimButton>
        <SimButton color="bg-orange-500 hover:bg-orange-600" onClick={() => setRunning(false)} disabled={!running}>Pause</SimButton>
        <SimButton color="bg-blue-600 hover:bg-blue-700" onClick={() => { setRunning(false); setPos(-1); }} disabled={pos < 0}>Reset</SimButton>
        <label className="flex items-center gap-2 text-sm text-slate-600 ml-auto">
          Speed
          <input type="range" min={2} max={48} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="accent-blue-600" />
          <span className="w-24">{speed} periods/s</span>
        </label>
      </div>

      <div className="mt-4 pt-3 border-t-2 border-slate-200 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-600">
        {LEGEND.map(([k, label]) => (
          <span key={k} className="flex items-center gap-2">
            <span className="w-7 h-5 rounded-[3px] border border-slate-700" style={{ background: COLORS[k] }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SimButton({ color, children, className = "", ...props }) {
  return (
    <button
      {...props}
      className={`px-5 py-3 text-sm font-semibold text-white rounded-md cursor-pointer transition-all hover:-translate-y-px hover:shadow disabled:bg-slate-300 disabled:cursor-not-allowed disabled:translate-y-0 disabled:shadow-none ${color} ${className}`}
    >
      {children}
    </button>
  );
}
