"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import proof from "@/data/proof.json";
import { useSteps } from "@/lib/useSteps";

// Chapter 04: the walk-forward backtest over 100 unseen weeks. The strategy ladder, every week as a dot,
// then a windy week replayed (SPEC.md, 04).
const STEPS = 3;
const CAPTIONS = [
  "",
  `Walk-forward backtest · ${proof.ladder[0].weeks} weeks the model never saw`,
  "Every one of those weeks",
  "Replay one: the median windy week",
];

const label = "font-mono uppercase tracking-[0.12em]";
const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.45 } };
const gbp0 = (v: number) => `£${Math.round(v).toLocaleString("en-GB")}`;
const money = (v: number) => `${v < 0 ? "\u2212" : ""}£${Math.abs(v)}`;

export function ProofChart() {
  const [step, next] = useSteps(STEPS);

  return (
    <div
      onClick={next}
      className="card-grid flex h-full cursor-pointer select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
    >
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">04 · Proof</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <div className="relative mt-4 min-h-0 flex-1">
        <AnimatePresence mode="wait">
          {step <= 1 && (
            <motion.div key="ladder" className="absolute inset-0" {...fade}>
              <Ladder />
            </motion.div>
          )}
          {step === 2 && (
            <motion.div key="weeks" className="absolute inset-0" {...fade}>
              <Weeks />
            </motion.div>
          )}
          {step === 3 && (
            <motion.div key="replay" className="absolute inset-0" {...fade}>
              <Replay />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <p className="mt-2 text-right font-mono text-[11px] uppercase tracking-[0.2em] text-faint">
        {step} / {STEPS} {step < STEPS ? "· press →" : ""}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ step 1: ladder */

function Ladder() {
  const l = proof.ladder;
  const notes: Record<string, string> = {
    simple_rule: `lost money in ${l[0].losing} weeks`,
    persistence_greedy: `+${(l[1].pct - l[0].pct).toFixed(1)} pts · forecasting beats a fixed schedule`,
    tempo: `+${(l[2].pct - l[1].pct).toFixed(1)} pts · same optimiser: that's the model`,
    tempo_lp: `+${(l[3].pct - l[2].pct).toFixed(1)} pts · a smarter optimiser`,
    perfect: "the ceiling · nobody beats this",
  };
  return (
    <div className="flex h-full flex-col justify-center gap-5">
      <p className={`text-[12px] text-faint ${label}`}>Share of the best possible profit · {l[0].weeks} unseen weeks · run {proof.run_id}</p>
      {l.map((s, k) => {
        const tempo = s.key === "tempo";
        const perfect = s.key === "perfect";
        return (
          <div key={s.key} className="grid grid-cols-[260px_1fr_190px] items-center gap-6">
            <div>
              <p className={`font-sans text-lg ${tempo ? "font-semibold text-ink" : "text-label"}`}>{s.name}</p>
              <p className="font-sans text-sm text-body">{s.sub}</p>
            </div>
            <div className="relative h-11 rounded-md bg-node">
              <motion.div
                className={`absolute inset-y-0 left-0 rounded-md ${tempo ? "bg-brand" : perfect ? "border-2 border-dashed border-ring bg-glow" : s.key === "tempo_lp" ? "bg-ring/60" : "bg-rule"}`}
                initial={{ width: 0 }}
                animate={{ width: `${s.pct}%` }}
                transition={{ delay: 0.3 + k * 0.45, duration: 0.7, ease: "easeOut" }}
              />
              <motion.span
                className={`absolute top-1/2 -translate-y-1/2 whitespace-nowrap font-mono text-xs uppercase tracking-[0.1em] ${
                  s.pct >= 60 ? `pr-4 text-right ${tempo ? "text-paper" : "text-ink"}` : `pl-3 ${s.key === "simple_rule" ? "text-sell-ink" : "text-body"}`
                }`}
                style={s.pct >= 60 ? { right: `${100 - s.pct}%` } : { left: `${s.pct}%` }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.9 + k * 0.45 }}
              >
                {perfect ? "" : notes[s.key]}
              </motion.span>
              {perfect && (
                <motion.span
                  className="absolute inset-y-0 left-4 flex items-center font-mono text-xs uppercase tracking-[0.1em] text-ring"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.9 + k * 0.45 }}
                >
                  {notes.perfect}
                </motion.span>
              )}
            </div>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 + k * 0.45 }} className="text-right">
              <p className={`font-serif font-bold ${tempo ? "text-4xl text-ink" : "text-2xl text-label"}`}>{s.pct.toFixed(1)}%</p>
              <p className="font-mono text-xs text-body">{gbp0(s.pnl)}</p>
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ step 2: every week */

function Weeks() {
  const W = 1200;
  const H = 440;
  const L = 40;
  const R = 40;
  const BASE = 330;
  const BIN = 2.5; // % of perfect per column
  const DOT = 15;
  const x = (pct: number) => L + (pct / 100) * (W - L - R);
  const tempo = proof.ladder.find((s) => s.key === "tempo")!;
  const persistence = proof.ladder.find((s) => s.key === "persistence_greedy")!;
  // Stack dots in bins (a simple beeswarm), calm first so the colours group.
  const stacks: Record<number, number> = {};
  const dots = [...proof.weeks]
    .sort((a, b) => (a.regime === b.regime ? a.pct - b.pct : a.regime === "calm" ? -1 : 1))
    .map((w) => {
      const bin = Math.floor(w.pct / BIN);
      const k = (stacks[bin] = (stacks[bin] ?? 0) + 1) - 1;
      return { ...w, cx: x((bin + 0.5) * BIN), cy: BASE - DOT / 2 - k * DOT };
    });
  const worst = proof.weeks.reduce((a, b) => (b.pct < a.pct ? b : a));
  const best = proof.weeks.reduce((a, b) => (b.pct > a.pct ? b : a));
  const at = (w: typeof worst) => dots.find((d) => d.week === w.week)!;
  const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label="Tempo's share of perfect foresight in each of 100 unseen weeks">
      {/* Axis */}
      <line x1={L} x2={W - R} y1={BASE} y2={BASE} className="stroke-rule" />
      {[0, 25, 50, 75, 100].map((v) => (
        <text key={v} x={x(v)} y={BASE + 28} textAnchor="middle" className="fill-faint font-mono text-[14px]">
          {v}%
        </text>
      ))}
      <text x={x(50)} y={BASE + 56} textAnchor="middle" className={`fill-faint text-[12px] ${label}`}>
        Share of the best possible profit, each week
      </text>
      <text x={x(0) + 8} y={78} className={`fill-body text-[12px] ${label}`}>
        Losing weeks: {tempo.losing}
      </text>

      {/* References */}
      {[
        { v: persistence.pct, t: `Same as yesterday ${persistence.pct}%`, cls: "stroke-faint", tcls: "fill-body", ty: 62, anchor: "end" as const },
        { v: tempo.pct, t: `Tempo overall ${tempo.pct}%`, cls: "stroke-brand", tcls: "fill-brand", ty: 86, anchor: "start" as const },
      ].map((r) => (
        <g key={r.t}>
          <line x1={x(r.v)} x2={x(r.v)} y1={r.ty + 6} y2={BASE} className={r.cls} strokeDasharray="5 5" strokeWidth={1.5} />
          <text x={x(r.v) + (r.anchor === "end" ? 6 : -6)} y={r.ty} textAnchor={r.anchor} className={`text-[12px] ${label} ${r.tcls}`}>
            {r.t}
          </text>
        </g>
      ))}

      {/* Dots */}
      {dots.map((d, k) => (
        <motion.circle
          key={d.week}
          cx={d.cx}
          r={DOT / 2 - 1}
          initial={{ cy: BASE - 300, opacity: 0 }}
          animate={{ cy: d.cy, opacity: 1 }}
          transition={{ delay: 0.2 + k * 0.012, duration: 0.5, ease: "easeOut" }}
          className={d.regime === "windy" ? "fill-brand" : "fill-hold"}
        />
      ))}

      {/* Worst and best */}
      {[
        { w: worst, t: `Worst · ${worst.pct}%`, sub: day(worst.week), anchor: "start" as const, dx: -6 },
        { w: best, t: `Best · ${best.pct}%`, sub: day(best.week), anchor: "end" as const, dx: 6 },
      ].map(({ w, t, sub, anchor, dx }) => {
        const d = at(w);
        return (
          <motion.g key={t} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.8 }}>
            <circle cx={d.cx} cy={d.cy} r={DOT / 2 + 3} className="fill-none stroke-ink" strokeWidth={1.5} />
            <line x1={d.cx} x2={d.cx + dx} y1={d.cy - 12} y2={d.cy - 40} className="stroke-faint" />
            <text x={d.cx + dx} y={d.cy - 60} textAnchor={anchor} className={`fill-ink text-[13px] font-medium ${label}`}>
              {t}
            </text>
            <text x={d.cx + dx} y={d.cy - 44} textAnchor={anchor} className="fill-body font-sans text-[13px]">
              {sub}
            </text>
          </motion.g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${W - R - 220},${BASE + 70})`}>
        <circle cx={6} cy={-4} r={6} className="fill-hold" />
        <text x={18} y={0} className="fill-label font-sans text-[14px]">
          calm week
        </text>
        <circle cx={116} cy={-4} r={6} className="fill-brand" />
        <text x={128} y={0} className="fill-label font-sans text-[14px]">
          windy week
        </text>
      </g>
    </svg>
  );
}

/* ------------------------------------------------------------------ step 3: replay */

const rp = proof.replay;
const RN = rp.periods.length;
const BASE_SECONDS = 22; // one week at 1×

function Replay() {
  const [pos, setPos] = useState(0); // fractional period index
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 4>(1);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (!playing) {
      last.current = null;
      return;
    }
    let raf = 0;
    const tick = (now: number) => {
      const dt = last.current == null ? 0 : (now - last.current) / 1000;
      last.current = now;
      setPos((p) => {
        const n = Math.min(RN - 1, p + (dt * speed * RN) / BASE_SECONDS);
        if (n >= RN - 1) setPlaying(false);
        return n;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed]);

  const i = Math.floor(pos);
  const now = rp.periods[i];
  const W = 900;
  const H = 520;
  const L = 64;
  const R = 12;
  const x = (k: number) => L + (k / (RN - 1)) * (W - L - R);
  const prices = rp.periods.map((p) => p.actual);
  const pLo = Math.floor(Math.min(...prices) / 25) * 25;
  const pHi = Math.ceil(Math.max(...prices) / 25) * 25;
  const py = (v: number) => 20 + ((pHi - v) / (pHi - pLo)) * 230;
  const sy = (v: number) => 340 - (v / 2) * 56;
  const cy = (v: number) => 490 - (v / rp.perfect_gbp) * 100;
  const upto = (f: (k: number) => string) => rp.periods.slice(0, i + 1).map((_, k) => `${k ? "L" : "M"}${f(k)}`).join("");
  const days = rp.periods.map((p, k) => ({ k, t: p.t })).filter(({ t }) => t.endsWith("01:00"));

  return (
    <div className="grid h-full grid-cols-[1fr_320px] gap-10">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label="A windy week replayed: price, battery and profit">
        {days.map(({ k, t }) => (
          <g key={k}>
            <line x1={x(k)} x2={x(k)} y1={20} y2={490} className="stroke-grid" />
            <text x={x(k) + 6} y={14} className={`fill-faint text-[12px] ${label}`}>
              {t.slice(0, 3)}
            </text>
          </g>
        ))}
        <text x={L - 10} y={py(pHi) + 5} textAnchor="end" className="fill-faint font-mono text-[12px]">
          {money(pHi)}
        </text>
        <text x={L - 10} y={py(pLo) + 5} textAnchor="end" className="fill-faint font-mono text-[12px]">
          {money(pLo)}
        </text>
        <text x={L - 10} y={300} textAnchor="end" className={`fill-faint text-[11px] ${label}`}>
          Battery
        </text>
        <text x={L - 10} y={440} textAnchor="end" className={`fill-faint text-[11px] ${label}`}>
          Profit
        </text>

        {/* Price (what actually happened) with trades marked */}
        <path d={rp.periods.map((p, k) => `${k ? "L" : "M"}${x(k)},${py(p.actual)}`).join("")} fill="none" className="stroke-rule" strokeWidth={1.5} />
        <path d={upto((k) => `${x(k)},${py(rp.periods[k].actual)}`)} fill="none" className="stroke-actual" strokeWidth={2} />
        {rp.periods.slice(0, i + 1).map((p, k) =>
          p.mw !== 0 ? <circle key={k} cx={x(k)} cy={py(p.actual)} r={3.5} className={p.mw > 0 ? "fill-charge" : "fill-sell"} /> : null,
        )}

        {/* Battery */}
        <rect x={L} y={284} width={W - L - R} height={56} rx={4} className="fill-node" />
        <path d={`${upto((k) => `${x(k)},${sy(rp.periods[k].soc)}`)}L${x(i)},340L${x(0)},340Z`} className="fill-charge/40 stroke-charge-ink" strokeWidth={1.25} />

        {/* Profit: Tempo against perfect foresight */}
        <line x1={L} x2={W - R} y1={cy(0)} y2={cy(0)} className="stroke-rule" />
        <path d={upto((k) => `${x(k)},${cy(rp.periods[k].perfect)}`)} fill="none" className="stroke-ring" strokeDasharray="5 4" strokeWidth={1.5} />
        <path d={upto((k) => `${x(k)},${cy(rp.periods[k].cum)}`)} fill="none" className="stroke-brand" strokeWidth={2.5} />

        {/* Playhead */}
        <line x1={x(pos)} x2={x(pos)} y1={20} y2={490} className="stroke-ink" strokeWidth={1} opacity={0.4} />
      </svg>

      <div className="flex flex-col justify-center gap-6 border-l border-rule pl-8" onClick={(e) => e.stopPropagation()}>
        <div>
          <p className={`text-[11px] text-faint ${label}`}>
            Week of {new Date(rp.week_start).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · {rp.regime}
          </p>
          <p className="mt-1 font-mono text-sm text-body">{now.t}</p>
        </div>
        <div>
          <p className="font-serif text-5xl font-bold text-ink">£{now.cum.toFixed(2)}</p>
          <p className={`mt-1 text-[11px] text-brand ${label}`}>Tempo, on prices it couldn&apos;t see</p>
        </div>
        <div>
          <p className="font-serif text-2xl font-bold text-ring">£{now.perfect.toFixed(2)}</p>
          <p className={`mt-1 text-[11px] text-body ${label}`}>Perfect foresight · £{rp.perfect_gbp.toFixed(2)} for the week</p>
        </div>
        <div className="space-y-2 font-sans text-sm text-label">
          <p className="flex items-center gap-3"><span className="h-[2px] w-6 bg-actual" /> Price that actually happened</p>
          <p className="flex items-center gap-3"><span className="h-2.5 w-2.5 rounded-full bg-charge" /> charge <span className="ml-2 h-2.5 w-2.5 rounded-full bg-sell" /> sell</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              if (pos >= RN - 1) setPos(0);
              setPlaying((p) => !p);
            }}
            className="rounded-md bg-brand px-5 py-3 font-mono text-sm font-medium uppercase tracking-[0.15em] text-paper"
          >
            {playing ? "❚❚ Pause" : pos >= RN - 1 ? "↺ Replay" : "▶ Play"}
          </button>
          <div className="flex rounded-md border border-rule bg-node p-1">
            {([1, 4] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                className={`rounded px-3 py-2 font-mono text-xs ${speed === s ? "bg-ink text-paper" : "text-body"}`}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
        {pos >= RN - 1 && (
          <motion.p {...fade} className="font-sans text-sm text-body">
            {rp.pct_of_perfect}% of perfect · the {rp.chosen_as}.
          </motion.p>
        )}
      </div>
    </div>
  );
}
