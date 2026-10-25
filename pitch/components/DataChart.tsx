"use client";

import { AnimatePresence, motion } from "motion/react";
import { useRef, useState } from "react";
import data from "@/data/data.json";
import { useSteps } from "@/lib/useSteps";

// Chapter 01: the pipeline lights up stage by stage, then the "no peeking" timeline with a draggable
// decision line (SPEC.md, 01).
const STEPS = 7;
const CAPTIONS = [
  "",
  "Official data · Elexon BMRS, the GB settlement feed",
  "Into Tiger, stamped with when it became available",
  "Rolled up automatically: half-hour → day → week",
  `${data.pipeline.features} features, built only from what was already published`,
  "LightGBM forecasts the next 48 half-hours, with a band",
  "Cost-gated: trade, or hold",
  "Drag the decision. Anything published later disappears.",
];

const p = data.pipeline;
const n = (v: number) => v.toLocaleString("en-GB");
const label = "font-mono uppercase tracking-[0.12em]";
const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.5 } };

export function DataChart() {
  const [step, next] = useSteps(STEPS);

  return (
    <div
      onClick={step < STEPS ? next : undefined}
      className={`card-grid flex h-full select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)] ${step < STEPS ? "cursor-pointer" : ""}`}
    >
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">01 · Data</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <div className="relative mt-4 min-h-0 flex-1">
        <AnimatePresence mode="wait">
          {step < STEPS ? (
            <motion.div key="pipeline" className="absolute inset-0" {...fade}>
              <Pipeline step={step} />
            </motion.div>
          ) : (
            <motion.div key="timeline" className="absolute inset-0" {...fade}>
              <Timeline />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <p className="mt-2 text-right font-mono text-[11px] uppercase tracking-[0.2em] text-faint">
        {step} / {STEPS} {step < STEPS ? "· press →" : "· drag the line"}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ pipeline */

const PW = 1200;
const PH = 520;
const SRC = { x: 30, w: 210, h: 66 };
// The three that feed the model, then the other three Tiger stores (generation mix FUELHH, demand outturn INDO,
// system price DISEBSP): used on screen (e.g. the wind share in 00), not by the forecaster.
const sources = [
  { y: 105, title: "Prices", lines: ["APX index · every 30 min"] },
  { y: 190, title: "Wind forecast", lines: ["WINDFOR · 3 days ahead"] },
  { y: 275, title: "Demand forecast", lines: ["NDF · national demand"] },
  { y: 380, title: "+3 more", lines: ["mix · demand · system price", "stored, not in the model"], muted: true },
];
const RING = { x: 370, y: 230, r: 66 };
const CHAIN = { y: 230, w: 158, h: 96, gap: 24, x0: 486 };
const chainX = (k: number) => CHAIN.x0 + k * (CHAIN.w + CHAIN.gap);
const OUT = { x: chainX(3), w: 158, h: 70 };

function Pipeline({ step }: { step: number }) {
  const on = (s: number) => step >= s;
  const op = (s: number) => (on(s) ? 1 : 0.18);

  return (
    <svg viewBox={`0 0 ${PW} ${PH}`} className="h-full w-full" role="img" aria-label="Tempo's data pipeline">
      <text x={SRC.x} y={44} className={`fill-faint text-[13px] ${label}`}>
        Elexon BMRS
      </text>
      <text x={chainX(3)} y={44} className={`fill-faint text-[13px] ${label}`}>
        Decision
      </text>

      {/* Connectors */}
      {sources.map((s) => (
        <Connector
          key={s.title}
          d={`M${SRC.x + SRC.w},${s.y} C${SRC.x + SRC.w + 70},${s.y} ${RING.x - RING.r - 60},${RING.y} ${RING.x - RING.r - 4},${RING.y}`}
          active={on(2)}
          muted={s.muted}
        />
      ))}
      <Connector d={`M${RING.x + RING.r + 4},${CHAIN.y} L${chainX(0) - 4},${CHAIN.y}`} active={on(4)} />
      <Connector d={`M${chainX(0) + CHAIN.w},${CHAIN.y} L${chainX(1) - 4},${CHAIN.y}`} active={on(5)} />
      <Connector d={`M${chainX(1) + CHAIN.w},${CHAIN.y} L${chainX(2) - 4},${CHAIN.y}`} active={on(6)} />
      <Connector
        d={`M${chainX(2) + CHAIN.w},${CHAIN.y} C${OUT.x - 14},${CHAIN.y} ${OUT.x - 24},${150} ${OUT.x - 4},${150}`}
        active={on(6)}
        tone="charge"
      />
      <Connector
        d={`M${chainX(2) + CHAIN.w},${CHAIN.y} C${OUT.x - 14},${CHAIN.y} ${OUT.x - 24},${310} ${OUT.x - 4},${310}`}
        active={on(6)}
      />
      

      {/* Step 1: sources */}
      {sources.map((s, k) => (
        <motion.g key={s.title} initial={{ opacity: 0, x: -12 }} animate={{ opacity: op(1), x: 0 }} transition={{ delay: on(1) ? k * 0.12 : 0, duration: 0.5 }}>
          <Node x={SRC.x} y={s.y - (s.muted ? 41 : SRC.h / 2)} w={SRC.w} h={s.muted ? 82 : SRC.h} title={s.title} lines={s.lines} muted={s.muted} />
        </motion.g>
      ))}
      <motion.text x={SRC.x} y={66} animate={{ opacity: op(1) }} className="fill-body font-sans text-[14px]">
        {p.datasets} datasets since {new Date(p.history_from).toLocaleDateString("en-GB", { month: "short", year: "numeric" })} · 3 feed the model
      </motion.text>

      {/* Step 2: Tiger */}
      <motion.g animate={{ opacity: op(2) }} transition={{ duration: 0.5 }}>
        <circle cx={RING.x} cy={RING.y} r={RING.r + 34} className="fill-glow" opacity={on(2) ? 0.7 : 0} />
        <circle cx={RING.x} cy={RING.y} r={RING.r} className="fill-card stroke-ring" strokeWidth={2.5} />
        <circle cx={RING.x} cy={RING.y} r={RING.r - 9} className="fill-none stroke-node-line" strokeWidth={1} />
        <text x={RING.x} y={RING.y - 4} textAnchor="middle" className={`fill-ring text-[18px] font-semibold ${label}`}>
          Tiger
        </text>
        <text x={RING.x} y={RING.y + 18} textAnchor="middle" className="fill-ring font-sans text-[13px]">
          hypertables
        </text>
        <text x={RING.x} y={RING.y + RING.r + 30} textAnchor="middle" className="fill-label font-sans text-[15px]">
          {n(p.rows)} rows · {Math.round(p.pct_compressed)}% compressed
        </text>
      </motion.g>
      <AnimatePresence>
        {step === 2 && (
          <motion.g key="stamp" {...fade}>
            <rect x={RING.x - 20} y={RING.y + RING.r + 44} width={350} height={34} rx={8} className="fill-brand" />
            <text x={RING.x + 155} y={RING.y + RING.r + 66} textAnchor="middle" className={`fill-paper text-[13px] ${label}`}>
              every row stamped available_at
            </text>
          </motion.g>
        )}
      </AnimatePresence>

      {/* Step 3: aggregates */}
      <motion.g animate={{ opacity: op(3) }} transition={{ duration: 0.5 }}>
        {[
          [n(p.hh), "half-hours"],
          [n(p.daily), "days"],
          [n(p.weekly), "weeks"],
        ].map(([v, unit], k) => (
          <motion.g key={unit} initial={false} animate={{ y: on(3) ? 0 : -10 }} transition={{ delay: k * 0.15 }}>
            <rect x={RING.x - 100 + k * 120} y={404} width={110} height={52} rx={8} className="fill-node stroke-node-line" />
            <text x={RING.x - 45 + k * 120} y={427} textAnchor="middle" className="fill-ink font-sans text-[16px] font-semibold">
              {v}
            </text>
            <text x={RING.x - 45 + k * 120} y={446} textAnchor="middle" className={`fill-body text-[11px] ${label}`}>
              {unit}
            </text>
            {k < 2 && (
              <text x={RING.x + 15 + k * 120} y={435} textAnchor="middle" className="fill-faint font-sans text-[14px]">
                →
              </text>
            )}
          </motion.g>
        ))}
        <text x={RING.x + 75} y={484} textAnchor="middle" className={`fill-faint text-[11px] ${label}`}>
          continuous aggregates · update themselves
        </text>
      </motion.g>

      {/* Steps 4-5: features, model */}
      <motion.g animate={{ opacity: op(4) }} transition={{ duration: 0.5 }}>
        <Node x={chainX(0)} y={CHAIN.y - CHAIN.h / 2} w={CHAIN.w} h={CHAIN.h} title={`${p.features} features`} lines={["point-in-time", "nothing from later"]} />
      </motion.g>
      <motion.g animate={{ opacity: op(5) }} transition={{ duration: 0.5 }}>
        <Node x={chainX(1)} y={CHAIN.y - CHAIN.h / 2} w={CHAIN.w} h={CHAIN.h} title="LightGBM" lines={["p10 · p50 · p90", `trains in ${Math.round(p.train_seconds)} s`]} strong />
      </motion.g>

      {/* Step 6: optimiser and its two outcomes */}
      <motion.g animate={{ opacity: op(6) }} transition={{ duration: 0.5 }}>
        <Node x={chainX(2)} y={CHAIN.y - CHAIN.h / 2} w={CHAIN.w} h={CHAIN.h} title="Optimiser" lines={["battery limits", "losses + wear"]} />
        <Status x={OUT.x} y={150 - OUT.h / 2} w={OUT.w} h={OUT.h} title="Trade" sub={`${n(p.decisions - p.holds)} charge / sell`} tone="charge" />
        <Status x={OUT.x} y={310 - OUT.h / 2} w={OUT.w} h={OUT.h} title="Hold" sub={`${n(p.holds)} on purpose`} tone="hold" />
        <text x={OUT.x} y={400} className="fill-body font-sans text-[15px]">
          {n(p.decisions)} live decisions
        </text>
      </motion.g>
    </svg>
  );
}

function Connector({ d, active, tone, muted }: { d: string; active: boolean; tone?: "charge"; muted?: boolean }) {
  return (
    <path
      d={d}
      fill="none"
      strokeWidth={muted ? 1.2 : 1.6}
      className={`${active ? "flow" : ""} ${active ? (tone === "charge" ? "stroke-charge" : "stroke-faint") : "stroke-rule"} transition-colors duration-500`}
      opacity={active ? (muted ? 0.6 : 1) : 0.5}
    />
  );
}

function Node({ x, y, w, h, title, lines, strong, muted }: { x: number; y: number; w: number; h: number; title: string; lines: string[]; strong?: boolean; muted?: boolean }) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        className={strong ? "fill-card stroke-ring" : muted ? "fill-card stroke-rule" : "fill-node stroke-node-line"}
        strokeWidth={strong ? 2 : 1}
        strokeDasharray={muted ? "4 4" : undefined}
      />
      <text x={x + w / 2} y={y + (lines.length > 1 ? 32 : 28)} textAnchor="middle" className={`text-[14px] font-semibold ${label} ${muted ? "fill-faint" : "fill-label"}`}>
        {title}
      </text>
      {lines.map((l, k) => (
        <text key={l} x={x + w / 2} y={y + (lines.length > 1 ? 56 : 50) + k * 20} textAnchor="middle" className="fill-body font-sans text-[14px]">
          {l}
        </text>
      ))}
    </g>
  );
}

function Status({ x, y, w, h, title, sub, tone }: { x: number; y: number; w: number; h: number; title: string; sub: string; tone: "charge" | "hold" }) {
  const charge = tone === "charge";
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={10} className={charge ? "fill-charge-bg stroke-charge-line" : "fill-node stroke-node-line"} />
      <circle cx={x + 18} cy={y + 22} r={5} className={charge ? "fill-charge" : "fill-hold"} />
      <text x={x + w / 2} y={y + 28} textAnchor="middle" className={`text-[14px] font-semibold ${label} ${charge ? "fill-charge-ink" : "fill-label"}`}>
        {title}
      </text>
      <text x={x + w / 2} y={y + 50} textAnchor="middle" className={`font-sans text-[14px] ${charge ? "fill-charge-ink" : "fill-body"}`}>
        {sub}
      </text>
    </g>
  );
}

/* ------------------------------------------------------------------ timeline */

const t = data.timeline;
const mins = (hm: string) => {
  const [h, m] = hm.split(":").map(Number);
  return h * 60 + m;
};
const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.round(m % 60)).padStart(2, "0")}`;
const T0 = mins(t.from);
const T1 = mins(t.to);
const TW = 900;
const TH = 420;
const TL = 150;
const TR = 20;
const TT = 70;
const LANE = 100;
const tx = (m: number) => TL + ((m - T0) / (T1 - T0)) * (TW - TL - TR);
const lanes = [
  { key: "price", title: "Price", sub: `published ${30 + t.mid_delay_min} min after each half-hour`, items: t.price.map((d) => ({ at: mins(d.pub), value: d.value })) },
  { key: "wind", title: "Wind forecast", sub: `for ${t.target} tonight`, items: t.wind.map((d) => ({ at: mins(d.pub), value: d.value })) },
  { key: "demand", title: "Demand forecast", sub: `for ${t.target} tonight`, items: t.demand.map((d) => ({ at: mins(d.pub), value: d.value })) },
];
const targetAt = mins(t.target);
const targetPrice = t.price.find((d) => d.period === t.target);

function latest<T extends { pub: string; value: number | null }>(list: T[], at: number): T | undefined {
  return [...list].reverse().find((d) => mins(d.pub) <= at && d.value != null);
}

function Timeline() {
  const [at, setAt] = useState(mins(t.decision));
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);

  const move = (e: React.PointerEvent) => {
    if (!dragging.current || !svg.current) return;
    const ctm = svg.current.getScreenCTM();
    if (!ctm) return;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    const m = T0 + ((pt.x - TL) / (TW - TL - TR)) * (T1 - T0);
    setAt(Math.round(Math.min(T1 - 1, Math.max(T0, m))));
  };

  const price = latest(t.price, at);
  const wind = latest(t.wind, at);
  const demand = latest(t.demand, at);
  const hidden = lanes.reduce((s, l) => s + l.items.filter((d) => d.at > at && d.at >= T0).length, 0);
  const newerWind = t.wind.filter((d) => mins(d.pub) > at && mins(d.pub) >= T0).length;
  const x = tx(at);

  return (
    <div className="grid h-full grid-cols-[1fr_300px] gap-8">
      <svg
        ref={svg}
        viewBox={`0 0 ${TW} ${TH}`}
        className="h-full w-full touch-none"
        onPointerDown={(e) => {
          dragging.current = true;
          (e.target as Element).setPointerCapture?.(e.pointerId);
          move(e);
        }}
        onPointerMove={move}
        onPointerUp={() => (dragging.current = false)}
        role="img"
        aria-label="Publication times of the data a decision can use"
      >
        {/* Hours */}
        {Array.from({ length: (T1 - T0) / 180 + 1 }, (_, k) => T0 + k * 180).map((m) => (
          <g key={m}>
            <line x1={tx(m)} x2={tx(m)} y1={TT - 20} y2={TT + LANE * 3 - 10} className="stroke-grid" />
            <text x={tx(m)} y={TH - 12} textAnchor={m === T1 ? "end" : "middle"} className="fill-faint font-mono text-[13px]">
              {hm(m)}
            </text>
          </g>
        ))}

        {/* "Not published yet" */}
        <rect x={x} y={TT - 20} width={tx(T1) - x} height={LANE * 3 + 10} className="fill-paper" opacity={0.8} />

        {/* Target half-hour */}
        <line x1={tx(targetAt)} x2={tx(targetAt)} y1={TT - 20} y2={TT + LANE * 3 - 10} className="stroke-sell" strokeDasharray="4 4" />
        <text x={tx(targetAt) + 6} y={TT - 26} className={`fill-sell-ink text-[12px] ${label}`}>
          {t.target} · evening peak
        </text>

        {/* Lanes */}
        {lanes.map((l, k) => {
          const cy = TT + k * LANE + 30;
          return (
            <g key={l.key}>
              <text x={0} y={cy - 4} className={`fill-label text-[13px] font-semibold ${label}`}>
                {l.title}
              </text>
              <text x={0} y={cy + 15} className="fill-body font-sans text-[12px]">
                {l.sub}
              </text>
              <line x1={TL} x2={TW - TR} y1={cy} y2={cy} className="stroke-node-line" />
              {l.items
                .filter((d) => d.at >= T0)
                .map((d, j) => {
                  const seen = d.at <= at;
                  const big = l.key === "wind";
                  return (
                    <g key={j}>
                      <circle
                        cx={tx(d.at)}
                        cy={cy}
                        r={big ? 8 : 4.5}
                        className={seen ? (big ? "fill-brand" : "fill-ring") : "fill-card stroke-rule"}
                        strokeWidth={1.5}
                        style={{ transition: "fill 200ms" }}
                      />
                      {big && d.value != null && (
                        <text x={tx(d.at)} y={cy - 16} textAnchor="middle" className={`font-mono text-[12px] ${seen ? "fill-ink" : "fill-rule"}`}>
                          {(d.value / 1000).toFixed(1)} GW
                        </text>
                      )}
                    </g>
                  );
                })}
            </g>
          );
        })}

        {/* Decision line */}
        <g className="cursor-ew-resize">
          <line x1={x} x2={x} y1={TT - 40} y2={TT + LANE * 3 - 10} className="stroke-brand" strokeWidth={2.5} />
          <rect x={x - 105} y={TT - 66} width={210} height={30} rx={6} className="fill-brand" />
          <text x={x} y={TT - 46} textAnchor="middle" className={`fill-paper text-[13px] ${label}`}>
            ⟷ Decision · {hm(at)}
          </text>
          <rect x={x - 14} y={TT - 40} width={28} height={LANE * 3 + 30} fill="transparent" />
        </g>
      </svg>

      {/* What the decision can see */}
      <div className="flex flex-col justify-center gap-4 border-l border-rule pl-8">
        <p className={`text-xs text-body ${label}`}>What the decision sees at {hm(at)}</p>
        <Seen title="Latest price" value={price ? gbp(price.value) : "—"} note={price ? `half-hour from ${price.period} · published ${price.pub}` : ""} />
        <Seen
          title={`Wind forecast for ${t.target}`}
          value={wind ? `${n(wind.value)} MW` : "—"}
          note={wind ? `published ${wind.pub}${newerWind ? ` · ${newerWind} newer ${newerWind > 1 ? "ones" : "one"} hidden` : ""}` : ""}
        />
        <Seen title={`Demand forecast for ${t.target}`} value={demand && demand.value != null ? `${n(demand.value)} MW` : "—"} note={demand ? `published ${demand.pub}` : ""} />
        <Seen
          title={`Actual price at ${t.target}`}
          value={targetPrice && mins(targetPrice.pub) <= at ? gbp(targetPrice.value) : "unknown"}
          note={targetPrice ? `${mins(targetPrice.pub) <= at ? "published" : "arrives"} ${targetPrice.pub}` : ""}
          tone={targetPrice && mins(targetPrice.pub) <= at ? "sell" : undefined}
        />
        <p className="border-t border-rule pt-4 font-sans text-sm text-body">
          <span className="font-semibold text-ink">{hidden}</span> publications after {hm(at)} don’t exist for it yet.
        </p>
      </div>
    </div>
  );
}

const gbp = (v: number) => `${v < 0 ? "−" : ""}£${Math.abs(v).toFixed(2)}`;

function Seen({ title, value, note, tone }: { title: string; value: string; note: string; tone?: "sell" }) {
  return (
    <div>
      <p className={`text-[11px] text-faint ${label}`}>{title}</p>
      <p className={`font-serif text-2xl font-bold ${tone === "sell" ? "text-sell-ink" : "text-ink"}`}>{value}</p>
      <p className="font-sans text-xs text-body">{note}</p>
    </div>
  );
}
