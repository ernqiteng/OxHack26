"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ACTION, fmtDay, fmtTime, gbp, useApi } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import { useWidth } from "@/lib/useWidth";

const H = 640;
const PAD = { top: 112, right: 28, bottom: 56, left: 64 };
const MIN_SPAN_MS = 6 * 3600e3; // zoom in to a 6-hour window at most

const LONDON_DATE = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", day: "2-digit" });

/** UTC instants of London midnights inside [t0, t1], found where the London date changes. */
function localMidnights(t0, t1) {
  const out = [];
  const step = 30 * 60e3;
  let prev = LONDON_DATE.format(Math.floor(t0 / step) * step);
  for (let t = Math.floor(t0 / step) * step + step; t <= t1; t += step) {
    const day = LONDON_DATE.format(t);
    if (day !== prev && t >= t0) out.push(t);
    prev = day;
  }
  return out;
}

export default function DecisionMap() {
  const { data, error, loading } = useApi("/decisions");
  const { data: live } = useApi("/live", { refreshMs: 60_000 });
  const { selected, setSelected } = useSelection();
  const [ref, width] = useWidth();
  const [hovered, setHovered] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [view, setView] = useState(null); // [t0, t1] in ms; null = last four days + plan; "all" = everything
  const drag = useRef(null);
  const svgRef = useRef(null);
  const onWheel = useRef(null);

  // React's onWheel is passive, so the page would scroll while zooming; listen natively instead.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const handler = (e) => {
      e.preventDefault();
      onWheel.current?.(e);
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  });

  const model = useMemo(() => {
    if (!data) return null;
    const past = data.prices.map((p) => ({ t: Date.parse(p.bucket), v: p.price }));
    const plan = (live?.plan || []).map((p) => ({
      t: Date.parse(p.target_time), v: p.p50, lo: p.p10, hi: p.p90, action: p.action, mw: p.mw,
    }));
    const markers = data.decisions.map((d) => ({ ...d, t: Date.parse(d.target_time) }));
    const all = [...past, ...plan];
    if (!all.length) return null;
    const t0 = Math.min(...all.map((p) => p.t));
    const t1 = Math.max(...all.map((p) => p.t));
    const vals = [...past.map((p) => p.v), ...plan.flatMap((p) => [p.lo ?? p.v, p.hi ?? p.v])];
    const vmin = Math.min(0, ...vals);
    const vmax = Math.max(...vals);
    const now = live ? Date.parse(live.now) : past.length ? past[past.length - 1].t : t1;
    return { past, plan, markers, t0, t1, vmin, vmax: vmax + (vmax - vmin) * 0.08, now };
  }, [data, live]);

  if (loading && !data) return <MapFrame><p className="text-sky-100 text-lg">Loading map…</p></MapFrame>;
  if (error) return <MapFrame><p className="text-rose-200 text-lg">Error loading map data: {error.message}. Is <code>make api</code> running?</p></MapFrame>;
  if (!model) return <MapFrame><p className="text-sky-100 text-lg">No prices or decisions yet.</p></MapFrame>;

  const defaultView = clampSpan(model, [Math.max(model.t0, model.now - 4 * 864e5), model.t1]);
  const [v0, v1] = view === "all" ? [model.t0, model.t1] : view || defaultView;
  const iw = width - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const x = (t) => PAD.left + ((t - v0) / (v1 - v0)) * iw;
  const y = (v) => PAD.top + ih - ((v - model.vmin) / (model.vmax - model.vmin)) * ih;
  const tAt = (px) => v0 + ((px - PAD.left) / iw) * (v1 - v0);

  const clampView = (a, b) => {
    const full = model.t1 - model.t0;
    let span = Math.min(full, Math.max(MIN_SPAN_MS, b - a));
    let s = Math.max(model.t0, Math.min(model.t1 - span, a));
    return span >= full ? "all" : [s, s + span];
  };
  const zoom = (factor, centre = (v0 + v1) / 2) => {
    const span = (v1 - v0) * factor;
    const frac = (centre - v0) / (v1 - v0);
    setView(clampView(centre - frac * span, centre - frac * span + span));
  };

  onWheel.current = (e) => zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, tAt(e.offsetX));

  const area = (pts) =>
    pts.length ? `M${x(pts[0].t)},${y(model.vmin)} ` + pts.map((p) => `L${x(p.t)},${y(p.v)}`).join(" ") + ` L${x(pts[pts.length - 1].t)},${y(model.vmin)} Z` : "";
  const line = (pts, key = "v") => pts.map((p, i) => `${i ? "L" : "M"}${x(p.t)},${y(p[key])}`).join(" ");
  const band = model.plan.length
    ? line(model.plan, "hi") + " " + [...model.plan].reverse().map((p) => `L${x(p.t)},${y(p.lo)}`).join(" ") + " Z"
    : "";
  const ticks = niceTicks(model.vmin, model.vmax, 5);
  const days = localMidnights(v0, v1);
  const inView = (t) => t >= v0 && t <= v1;
  const hoverPoint = cursor != null ? nearest([...model.past, ...model.plan], tAt(cursor)) : null;

  return (
    <div className="w-full" style={{ background: "var(--map-sea)" }}>
      <section ref={ref} className="relative h-[40rem] overflow-hidden select-none">
        <div className="absolute left-6 top-5 z-10 pointer-events-none max-w-[calc(100%-11rem)]">
          <h1 className="text-3xl font-bold text-white">Decision Map</h1>
          <p className="text-sky-100/80">Settled GB prices, the decisions Tempo made on them, and today&apos;s plan. Click a pin to audit its timing.</p>
        </div>
        <div className="absolute right-6 top-6 z-10 flex gap-2">
          <MapButton onClick={() => zoom(0.6)} label="Zoom in">+</MapButton>
          <MapButton onClick={() => zoom(1 / 0.6)} label="Zoom out">−</MapButton>
          <MapButton onClick={() => setView("all")} label="Show everything">⤢</MapButton>
        </div>

        <svg
          width={width}
          height={H}
          className={v1 - v0 < model.t1 - model.t0 ? "cursor-grab active:cursor-grabbing" : ""}
          ref={svgRef}
          onMouseDown={(e) => (drag.current = { px: e.clientX, v0, v1 })}
          onMouseMove={(e) => {
            const px = e.nativeEvent.offsetX;
            setCursor(px >= PAD.left && px <= width - PAD.right ? px : null);
            if (!drag.current) return;
            const dt = ((e.clientX - drag.current.px) / iw) * (drag.current.v1 - drag.current.v0);
            setView(clampView(drag.current.v0 - dt, drag.current.v1 - dt));
          }}
          onMouseUp={() => (drag.current = null)}
          onMouseLeave={() => {
            drag.current = null;
            setCursor(null);
          }}
          role="img"
          aria-label="Half-hourly GB electricity prices with Tempo's decisions"
        >
          <defs>
            <clipPath id="plot"><rect x={PAD.left} y={0} width={iw} height={H} /></clipPath>
          </defs>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(v)} y2={y(v)} stroke="white" strokeOpacity={0.08} />
              <text x={PAD.left - 10} y={y(v) + 4} textAnchor="end" className="fill-sky-100/60 text-[11px] font-mono">£{v}</text>
            </g>
          ))}
          <text x={PAD.left - 10} y={PAD.top - 24} textAnchor="end" className="fill-sky-100/60 text-[11px]">£/MWh</text>
          <g clipPath="url(#plot)">
            {days.map((t) => (
              <g key={t}>
                <line x1={x(t)} x2={x(t)} y1={PAD.top} y2={H - PAD.bottom} stroke="white" strokeOpacity={0.12} strokeDasharray="2 4" />
                {x(t) < width - PAD.right - 80 && (
                  <text x={x(t) + 6} y={H - PAD.bottom + 22} className="fill-sky-100/70 text-[12px]">{fmtDay(t)}</text>
                )}
              </g>
            ))}
            <path d={area(model.past)} fill="var(--map-fill)" stroke="var(--map-stroke)" strokeWidth={1.5} />
            {band && <path d={band} fill="#fde68a" fillOpacity={0.14} />}
            {model.plan.length > 0 && <path d={line(model.plan)} fill="none" stroke="#fcd34d" strokeWidth={2} strokeDasharray="6 4" />}
            {inView(model.now) && (
              <g>
                <line x1={x(model.now)} x2={x(model.now)} y1={PAD.top - 8} y2={H - PAD.bottom} stroke="white" strokeWidth={1.5} strokeDasharray="4 3" />
                <text x={x(model.now)} y={PAD.top - 14} textAnchor="middle" className="fill-white text-[12px] font-semibold">now</text>
              </g>
            )}
            {model.plan.filter((p) => p.action && p.action !== "hold" && inView(p.t)).map((p) => (
              <circle key={`plan-${p.t}`} cx={x(p.t)} cy={y(p.v)} r={5} fill="var(--map-sea)" stroke={ACTION[p.action].color} strokeWidth={2.5} />
            ))}
            {hoverPoint && (
              <line x1={x(hoverPoint.t)} x2={x(hoverPoint.t)} y1={PAD.top} y2={H - PAD.bottom} stroke="white" strokeOpacity={0.35} />
            )}
            {model.markers.filter((m) => inView(m.t)).map((m) => {
              const price = nearest(model.past, m.t);
              const cy = price && Math.abs(price.t - m.t) < 3600e3 ? y(price.v) : y(model.vmin) - 12;
              const a = ACTION[m.action] || ACTION.hold;
              const isSel = selected?.decision_id === m.decision_id;
              return (
                <g
                  key={m.decision_id}
                  transform={`translate(${x(m.t)},${cy})`}
                  className="cursor-pointer"
                  onMouseEnter={() => setHovered(m.decision_id)}
                  onMouseLeave={() => setHovered(null)}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => setSelected(m)}
                >
                  <circle r={16} fill="transparent" />
                  {isSel && <circle r={13} fill="none" stroke="white" strokeWidth={2} strokeDasharray="3 2" />}
                  <circle r={8} fill={a.color} stroke="#fff" strokeWidth={2} />
                  <text textAnchor="middle" y={3.5} className="fill-white text-[9px] pointer-events-none">{a.glyph}</text>
                  <g className={`transition-opacity duration-300 pointer-events-none ${hovered === m.decision_id ? "opacity-100" : "opacity-0"}`}>
                    <rect x={-74} y={-44} width={148} height={24} rx={6} fill="#f5f5f4" />
                    <text textAnchor="middle" y={-28} className="fill-black text-[12px] font-semibold">
                      {a.label} {Math.abs(m.mw ?? 0)} MW · {fmtTime(m.target_time)}
                    </text>
                  </g>
                </g>
              );
            })}
          </g>
        </svg>

        {hoverPoint && hovered == null && (
          <div
            className="absolute z-10 pointer-events-none rounded-md bg-white/95 px-3 py-2 text-sm shadow-lg"
            style={{ left: Math.min(x(hoverPoint.t) + 12, width - 190), top: PAD.top + 8 }}
          >
            <div className="font-semibold">{gbp(hoverPoint.v)}/MWh {hoverPoint.lo != null && <span className="text-slate-500 font-normal">forecast</span>}</div>
            <div className="text-slate-600">{fmtDay(hoverPoint.t)} · {fmtTime(hoverPoint.t)}</div>
          </div>
        )}

        <div className="absolute left-6 bottom-3 z-10 flex flex-wrap gap-x-5 gap-y-1 text-sm text-sky-50">
          <Legend swatch={<span className="inline-block w-4 h-3 rounded-sm" style={{ background: "var(--map-fill)" }} />}>Settled price</Legend>
          <Legend swatch={<span className="inline-block w-5 border-t-2 border-dashed border-amber-300" />}>Forecast p50, p10–p90 band</Legend>
          <Legend swatch={<Dot color="var(--charge)">▲</Dot>}>Charge</Legend>
          <Legend swatch={<Dot color="var(--sell)">▼</Dot>}>Sell</Legend>
          <Legend swatch={<span className="inline-block w-3 h-3 rounded-full border-2 border-slate-200" />}>Planned (hollow)</Legend>
        </div>
      </section>
    </div>
  );
}

function MapFrame({ children }) {
  return (
    <div className="w-full h-[40rem] flex items-center justify-center" style={{ background: "var(--map-sea)" }}>
      {children}
    </div>
  );
}

function MapButton({ children, onClick, label }) {
  return (
    <button onClick={onClick} aria-label={label} title={label}
      className="w-9 h-9 rounded-md bg-white/10 text-white text-lg hover:bg-white/20 cursor-pointer transition-colors">
      {children}
    </button>
  );
}

const Legend = ({ swatch, children }) => <span className="flex items-center gap-2">{swatch}{children}</span>;
const Dot = ({ color, children }) => (
  <span className="inline-flex w-4 h-4 rounded-full items-center justify-center text-[8px] text-white border-2 border-white" style={{ background: color }}>{children}</span>
);

function clampSpan(model, [a, b]) {
  return [Math.max(model.t0, a), Math.min(model.t1, b)];
}

function nearest(points, t) {
  let best = null;
  for (const p of points) if (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
  return best;
}

function niceTicks(lo, hi, n) {
  const step0 = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(Math.round(v));
  return out;
}
