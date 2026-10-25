"use client";

import { animate, AnimatePresence, motion } from "motion/react";
import { useEffect, useRef } from "react";
import hook from "@/data/hook.json";
import { useSteps } from "@/lib/useSteps";

// Chapter 00: one real day of GB prices, revealed in five steps, full screen (SPEC.md, 00; script in docs/demox.md).
const STEPS = 5;
const CAPTIONS = [
  "",
  "25 March 2026 · 48 half-hours · GB wholesale price",
  `Same grid, same day. A £${Math.round(hook.high.price - hook.low.price)} swing.`,
  "A battery buys the bottom and sells the top.",
  "But at 02:00, you don’t know tonight’s price.",
  "Tempo makes that call every half hour.",
];

// Widescreen canvas, sized for a projector.
const W = 1200;
const H = 560;
const L = 80;
const R = 28;
const T = 36;
const B = 52;
const PW = W - L - R;
const PH = H - T - B;
const Y_MIN = -20;
const Y_MAX = 170;
const N = hook.periods.length;

const x = (i: number) => L + ((i + 0.5) * PW) / N; // centre of period i
const edge = (i: number) => L + (i * PW) / N; // left edge of period i
const y = (v: number) => T + ((Y_MAX - v) / (Y_MAX - Y_MIN)) * PH;
const gbp = (v: number) => `${v < 0 ? "−" : ""}£${Math.abs(v).toFixed(2)}`;
const line = (pts: { i: number; v: number }[]) => pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");

const prices = hook.periods.map((p, i) => ({ i, v: p.price }));
const nowIdx = hook.periods.findIndex((p) => p.t === hook.now);
const before = prices.slice(0, nowIdx + 1);
const after = prices.slice(nowIdx);
const tail = hook.periods.slice(nowIdx);
const band =
  tail.map((p, k) => `${k ? "L" : "M"}${x(nowIdx + k).toFixed(1)},${y(p.range_hi).toFixed(1)}`).join("") +
  tail
    .map((_, k) => {
      const j = tail.length - 1 - k;
      return `L${x(nowIdx + j).toFixed(1)},${y(tail[j].range_lo).toFixed(1)}`;
    })
    .join("") +
  "Z";

const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.5 } };
const label = "font-mono uppercase tracking-[0.12em]";

export function HookChart() {
  const [step, next] = useSteps(STEPS);
  const lowWind = hook.periods[hook.low.i].wind_share;
  const cx = (edge(hook.charge.from) + edge(hook.charge.to + 1)) / 2;
  const sx = (edge(hook.sell.from) + edge(hook.sell.to + 1)) / 2;
  const bandMid = 26;

  return (
    <div
      onClick={next}
      className="card-grid flex h-full cursor-pointer select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
    >
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">00 · Why this is hard</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="mt-4 min-h-0 w-full flex-1" role="img" aria-label="GB electricity price on 25 March 2026">
        {/* Axes */}
        {[0, 50, 100, 150].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === 0 ? "stroke-faint" : "stroke-grid"} strokeDasharray={v === 0 ? "4 5" : undefined} />
            <text x={L - 14} y={y(v) + 5} textAnchor="end" className="fill-faint font-mono text-[15px]">
              £{v}
            </text>
          </g>
        ))}
        {[0, 12, 24, 36, 48].map((i) => (
          <text key={i} x={edge(i)} y={H - 14} textAnchor={i === 48 ? "end" : i === 0 ? "start" : "middle"} className="fill-faint font-mono text-[15px]">
            {String(i / 2).padStart(2, "0")}:00
          </text>
        ))}

        {/* Step 3: charge and sell windows */}
        <AnimatePresence>
          {step >= 3 && (
            <motion.g key="windows" initial={{ opacity: 0 }} animate={{ opacity: step >= 4 ? 0.45 : 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.6 }}>
              <Window from={hook.charge.from} to={hook.charge.to} kind="charge" text="Charge" />
              <Window from={hook.sell.from} to={hook.sell.to} kind="sell" text="Sell" />
            </motion.g>
          )}
        </AnimatePresence>

        {/* Step 4: the uncertain band after "now" */}
        <AnimatePresence>
          {step >= 4 && (
            <motion.g key="band" {...fade} transition={{ duration: 0.8 }}>
              <path d={band} className="fill-glow stroke-ring" strokeWidth={1.25} strokeDasharray="5 5" fillOpacity={0.9} strokeOpacity={0.5} />
              <text
                x={x(bandMid)}
                y={y((hook.periods[bandMid].range_hi + hook.periods[bandMid].range_lo) / 2) + 5}
                textAnchor="middle"
                className={`fill-ring text-[15px] ${label}`}
              >
                Last {hook.range_days} days at this hour
              </text>
            </motion.g>
          )}
        </AnimatePresence>

        {/* Step 1: the price line draws itself */}
        <motion.path
          d={line(before)}
          fill="none"
          className="stroke-ink"
          strokeWidth={3}
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: step >= 1 ? 1 : 0 }}
          transition={{ duration: 0.25, ease: "linear" }}
        />
        <motion.path
          d={line(after)}
          fill="none"
          className="stroke-ink"
          strokeWidth={3}
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: step >= 1 ? 1 : 0, opacity: step >= 4 ? 0 : 1 }}
          transition={{ pathLength: { duration: 1.9, delay: 0.25, ease: "easeInOut" }, opacity: { duration: 0.6 } }}
        />

        {/* Step 2: the extremes */}
        <AnimatePresence>
          {step >= 2 && step < 4 && (
            <motion.g key="dots" {...fade}>
              <circle cx={x(hook.low.i)} cy={y(hook.low.price)} r={7} className="fill-charge stroke-card" strokeWidth={3} />
              <circle cx={x(hook.high.i)} cy={y(hook.high.price)} r={7} className="fill-sell stroke-card" strokeWidth={3} />
            </motion.g>
          )}
          {step === 2 && (
            <motion.g key="labels" {...fade}>
              <Callout
                at={[x(hook.low.i), y(hook.low.price)]}
                box={[x(hook.low.i) - 40, y(62)]}
                title={`${hook.low.t} · ${lowWind ? Math.round(lowWind * 100) : "?"}% wind`}
                sub={`${gbp(hook.low.price)}/MWh · paid to take power`}
                kind="charge"
              />
              <Callout
                at={[x(hook.high.i), y(hook.high.price)]}
                box={[x(hook.high.i) - 380, y(152)]}
                title={`${hook.high.t} · everyone home`}
                sub={`${gbp(hook.high.price)}/MWh`}
                kind="sell"
              />
            </motion.g>
          )}
        </AnimatePresence>

        {/* Step 3: the trade */}
        <AnimatePresence>
          {step === 3 && (
            <motion.g key="trade" {...fade}>
              <path
                d={`M${cx},${y(14)} C${cx + 120},${y(115)} ${sx - 260},${y(152)} ${sx - 56},${y(152)}`}
                fill="none"
                className="flow stroke-ring"
                strokeWidth={2}
              />
              <Battery x={cx - 24} y={y(34)} />
              <g transform={`translate(${(cx + sx) / 2 - 110},${y(96)})`}>
                <rect width={220} height={70} rx={10} className="fill-card stroke-node-line" />
                <text x={110} y={32} textAnchor="middle" className="fill-ink font-sans text-[24px] font-semibold">
                  {gbp(hook.spread)}/MWh
                </text>
                <text x={110} y={54} textAnchor="middle" className={`fill-body text-[13px] ${label}`}>
                  spread
                </text>
              </g>
            </motion.g>
          )}
        </AnimatePresence>

        {/* Step 4: now */}
        <AnimatePresence>
          {step >= 4 && (
            <motion.g key="now" initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.5 }}>
              <line x1={x(nowIdx)} x2={x(nowIdx)} y1={T} y2={H - B} className="stroke-brand" strokeWidth={2} />
              <circle cx={x(nowIdx)} cy={y(hook.periods[nowIdx].price)} r={7} className="fill-brand stroke-card" strokeWidth={3} />
              <rect x={x(nowIdx) + 12} y={T} width={150} height={34} rx={6} className="fill-brand" />
              <text x={x(nowIdx) + 87} y={T + 22} textAnchor="middle" className={`fill-paper text-[15px] ${label}`}>
                Now · {hook.now}
              </text>
              <text x={sx - 40} y={y(20)} textAnchor="middle" className="fill-ring font-serif text-[64px] font-bold">
                ?
              </text>
            </motion.g>
          )}
        </AnimatePresence>
      </svg>

      {/* Step 5: headline numbers */}
      <div className="mt-4 grid h-24 shrink-0 grid-cols-3 gap-8 border-t border-rule pt-5">
        {step >= 5 &&
          [
            { to: hook.headline.pct_of_perfect, fmt: (v: number) => `${v.toFixed(1)}%`, text: "of perfect foresight" },
            { to: hook.headline.pnl_gbp, fmt: (v: number) => `£${Math.round(v).toLocaleString("en-GB")}`, text: `on ${hook.headline.weeks} unseen weeks` },
            { to: hook.headline.losing_weeks, fmt: (v: number) => `${Math.round(v)}`, text: "losing weeks" },
          ].map((s, k) => (
            <motion.div key={s.text} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: k * 0.15 }}>
              <CountUp to={s.to} fmt={s.fmt} />
              <p className="mt-1 font-mono text-xs uppercase tracking-[0.15em] text-body">{s.text}</p>
            </motion.div>
          ))}
      </div>

      <p className="mt-2 text-right font-mono text-[11px] uppercase tracking-[0.2em] text-faint">
        {step} / {STEPS} {step < STEPS ? "· press →" : ""}
      </p>
    </div>
  );
}

function Window({ from, to, kind, text }: { from: number; to: number; kind: "charge" | "sell"; text: string }) {
  const x0 = edge(from);
  const w = edge(to + 1) - x0;
  return (
    <g>
      <rect x={x0} y={T} width={w} height={PH} className={kind === "charge" ? "fill-charge-bg stroke-charge-line" : "fill-sell-bg stroke-sell-line"} />
      <text x={x0 + w / 2} y={H - B - 12} textAnchor="middle" className={`text-[14px] font-medium ${label} ${kind === "charge" ? "fill-charge-ink" : "fill-sell-ink"}`}>
        {text}
      </text>
    </g>
  );
}

function Callout({ at, box, title, sub, kind }: { at: [number, number]; box: [number, number]; title: string; sub: string; kind: "charge" | "sell" }) {
  const bw = 330;
  const bh = 68;
  const charge = kind === "charge";
  return (
    <g>
      <line x1={at[0]} y1={at[1]} x2={box[0] + bw / 2} y2={box[1] + bh} className="stroke-faint" strokeDasharray="3 4" />
      <rect x={box[0]} y={box[1]} width={bw} height={bh} rx={10} className={charge ? "fill-charge-bg stroke-charge-line" : "fill-sell-bg stroke-sell-line"} />
      <circle cx={box[0] + 20} cy={box[1] + 24} r={5} className={charge ? "fill-charge" : "fill-sell"} />
      <text x={box[0] + 36} y={box[1] + 29} className={`text-[15px] font-medium ${label} ${charge ? "fill-charge-ink" : "fill-sell-ink"}`}>
        {title}
      </text>
      <text x={box[0] + 36} y={box[1] + 53} className="fill-label font-sans text-[17px]">
        {sub}
      </text>
    </g>
  );
}

// A battery icon that fills up, then drains, on a loop.
function Battery({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <rect width={48} height={26} rx={5} className="fill-card stroke-ring" strokeWidth={2} />
      <rect x={48} y={8} width={5} height={10} rx={1.5} className="fill-ring" />
      <motion.rect
        x={4}
        y={4}
        height={18}
        rx={2.5}
        className="fill-charge"
        initial={{ width: 0 }}
        animate={{ width: [0, 40, 40, 0] }}
        transition={{ duration: 3, times: [0, 0.4, 0.6, 1], repeat: Infinity, ease: "easeInOut" }}
      />
    </g>
  );
}

function CountUp({ to, fmt }: { to: number; fmt: (v: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const c = animate(0, to, { duration: 1.4, ease: "easeOut", onUpdate: (v) => ref.current && (ref.current.textContent = fmt(v)) });
    return () => c.stop();
  }, [to, fmt]);
  return (
    <span ref={ref} className="font-serif text-4xl font-bold text-ink">
      {fmt(0)}
    </span>
  );
}
