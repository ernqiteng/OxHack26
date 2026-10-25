"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import pred from "@/data/prediction.json";
import { useSteps } from "@/lib/useSteps";

// Chapter 02: the live forecast for 22 Oct against what happened, LightGBM against "same as yesterday",
// then what the model leans on (SPEC.md, 02).
const STEPS = 4;
const CAPTIONS = [
  "",
  `The live forecast made at ${pred.decided_at.slice(11)} on 22 Oct · 48 half-hours ahead`,
  "…and what actually happened",
  "Against the simplest guess: same as yesterday",
  "What the model leans on",
];

type Mode = "lgbm" | "persistence";

const W = 900;
const H = 520;
const L = 64;
const R = 16;
const T = 24;
const B = 44;
const N = pred.periods.length;
const ps = pred.periods;
const lo = Math.floor(Math.min(...ps.map((p) => Math.min(p.p10, p.actual, p.yesterday))) / 25) * 25;
const hi = Math.ceil(Math.max(...ps.map((p) => Math.max(p.p90, p.actual, p.yesterday))) / 25) * 25;
const x = (i: number) => L + ((i + 0.5) * (W - L - R)) / N;
const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
const band =
  ps.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.p90).toFixed(1)}`).join("") +
  ps.map((_, k) => `L${x(N - 1 - k).toFixed(1)},${y(ps[N - 1 - k].p10).toFixed(1)}`).join("") +
  "Z";
const lines = { lgbm: path(ps.map((p) => p.p50)), persistence: path(ps.map((p) => p.yesterday)) };
const actual = path(ps.map((p) => p.actual));
const ticks = ps.map((p, i) => ({ i, t: p.t })).filter(({ i }) => i % 8 === 0 || i === N - 1);

const label = "font-mono uppercase tracking-[0.12em]";
const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.5 } };

export function PredictionChart() {
  const [step, next] = useSteps(STEPS);
  const [mode, setMode] = useState<Mode>("lgbm");

  // Step 3 opens on the baseline so the presenter can flip to the model; step 4 is always the model.
  useEffect(() => {
    setMode(step === 3 ? "persistence" : "lgbm");
  }, [step]);

  const lgbm = mode === "lgbm";
  const forecast = (p: (typeof ps)[number]) => (lgbm ? p.p50 : p.yesterday);

  return (
    <div
      onClick={next}
      className="card-grid flex h-full cursor-pointer select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
    >
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">02 · Prediction</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <div className="mt-4 grid min-h-0 flex-1 grid-cols-[1fr_340px] gap-10">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label="Price forecast against actual price, 22 October 2026">
          {/* Axes */}
          {Array.from({ length: (hi - lo) / 25 + 1 }, (_, k) => lo + k * 25)
            .filter((v) => v % 50 === 0)
            .map((v) => (
              <g key={v}>
                <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="stroke-grid" />
                <text x={L - 12} y={y(v) + 5} textAnchor="end" className="fill-faint font-mono text-[14px]">
                  £{v}
                </text>
              </g>
            ))}
          {ticks.map(({ i, t }) => (
            <text key={i} x={x(i)} y={H - 14} textAnchor={i === 0 ? "start" : i === N - 1 ? "end" : "middle"} className="fill-faint font-mono text-[14px]">
              {t}
            </text>
          ))}

          {/* Band: LightGBM only */}
          <motion.path
            d={band}
            className="fill-glow stroke-ring"
            strokeWidth={1}
            strokeDasharray="4 4"
            strokeOpacity={0.5}
            initial={{ opacity: 0 }}
            animate={{ opacity: step >= 1 && lgbm ? 1 : 0 }}
            transition={{ duration: 0.8, delay: step === 1 ? 0.6 : 0 }}
          />

          {/* Error sticks from step 3 */}
          {step >= 3 &&
            ps.map((p, i) => (
              <motion.line
                key={i}
                x1={x(i)}
                x2={x(i)}
                y2={y(p.actual)}
                initial={{ y1: y(p.actual) }}
                animate={{ y1: y(forecast(p)) }}
                transition={{ duration: 0.8, ease: "easeInOut" }}
                className="stroke-sell"
                strokeWidth={2}
                opacity={0.55}
              />
            ))}

          {/* Forecast line: morphs between the model and "same as yesterday" */}
          <motion.path
            fill="none"
            strokeWidth={3}
            strokeLinejoin="round"
            initial={{ pathLength: 0, d: lines.lgbm }}
            animate={{ pathLength: step >= 1 ? 1 : 0, d: lines[mode] }}
            transition={{ pathLength: { duration: 1.6, ease: "easeInOut" }, d: { duration: 0.8, ease: "easeInOut" } }}
            className={lgbm ? "stroke-brand" : "stroke-faint"}
            strokeDasharray={lgbm ? undefined : "8 6"}
          />

          {/* Step 2: what happened */}
          <motion.path
            d={actual}
            fill="none"
            className="stroke-actual"
            strokeWidth={3}
            strokeLinejoin="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: step >= 2 ? 1 : 0, opacity: step >= 2 ? 1 : 0 }}
            transition={{ duration: 1.6, ease: "easeInOut" }}
          />
        </svg>

        {/* Side panel */}
        <div className="flex flex-col justify-center gap-6 border-l border-rule pl-8">
          {step < 4 && (
            <div className="space-y-3">
              <Key swatch={lgbm ? "line-brand" : "line-dash"} text={lgbm ? "LightGBM forecast (p50)" : "Same as yesterday"} />
              {lgbm && <Key swatch="band" text="p10–p90: its 80% range" />}
              {step >= 2 && <Key swatch="line-actual" text="What actually happened" />}
              {step >= 3 && <Key swatch="stick" text="How wrong, each half-hour" />}
            </div>
          )}

          <AnimatePresence mode="wait">
            {step === 3 && (
              <motion.div key="compare" {...fade} className="space-y-5">
                <div className="flex rounded-lg border border-rule bg-node p-1" onClick={(e) => e.stopPropagation()}>
                  {(["persistence", "lgbm"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      className={`flex-1 rounded-md px-3 py-2.5 font-mono text-xs font-medium uppercase tracking-[0.12em] transition-colors ${
                        mode === m ? "bg-brand text-paper" : "text-body hover:text-ink"
                      }`}
                    >
                      {m === "lgbm" ? "LightGBM" : "Same as yesterday"}
                    </button>
                  ))}
                </div>

                <div>
                  <p className={`text-[11px] text-faint ${label}`}>Average error · £/MWh · {pred.holdout.rows.toLocaleString("en-GB")} unseen half-hours</p>
                  <ErrorBar text="Same as yesterday" value={pred.holdout.persistence_mae} active={!lgbm} />
                  <ErrorBar text="LightGBM" value={pred.holdout.lgbm_mae} active={lgbm} />
                </div>

                <div className="h-16">
                  <AnimatePresence>
                    {lgbm && (
                      <motion.div {...fade}>
                        <p className="font-serif text-4xl font-bold text-ink">{Math.round(pred.holdout.pct_better)}% less wrong</p>
                        <p className="mt-1 font-sans text-sm text-body">
                          On 22 Oct itself: £{pred.day.lgbm_mae.toFixed(1)} against £{pred.day.persistence_mae.toFixed(1)}.
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            )}

            {step === 4 && (
              <motion.div key="features" {...fade} className="space-y-4">
                <p className={`text-[11px] text-faint ${label}`}>
                  Share of what the model learned · top 5 of {pred.feature_count} features
                </p>
                {pred.features.map((f, k) => (
                  <div key={f.name}>
                    <div className="flex items-baseline justify-between font-sans text-[15px]">
                      <span className="text-ink">{f.label}</span>
                      <span className="font-mono text-sm text-body">{Math.round(f.pct)}%</span>
                    </div>
                    <div className="mt-1.5 h-2.5 rounded-full bg-node">
                      <motion.div
                        className="h-full rounded-full bg-brand"
                        initial={{ width: 0 }}
                        animate={{ width: `${(f.pct / pred.features[0].pct) * 100}%` }}
                        transition={{ delay: 0.2 + k * 0.12, duration: 0.7, ease: "easeOut" }}
                      />
                    </div>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <p className="mt-2 text-right font-mono text-[11px] uppercase tracking-[0.2em] text-faint">
        {step} / {STEPS} {step < STEPS ? "· press →" : ""}
      </p>
    </div>
  );
}

function Key({ swatch, text }: { swatch: "line-brand" | "line-dash" | "line-actual" | "band" | "stick"; text: string }) {
  const sw = {
    "line-brand": <span className="h-[3px] w-7 rounded bg-brand" />,
    "line-dash": <span className="w-7 border-t-[3px] border-dashed border-faint" />,
    "line-actual": <span className="h-[3px] w-7 rounded bg-actual" />,
    band: <span className="h-4 w-7 rounded-sm border border-dashed border-ring/50 bg-glow" />,
    stick: <span className="h-4 w-[2px] bg-sell/60" />,
  }[swatch];
  return (
    <p className="flex items-center gap-3 font-sans text-[15px] text-label">
      <span className="flex w-7 justify-center">{sw}</span>
      {text}
    </p>
  );
}

function ErrorBar({ text, value, active }: { text: string; value: number; active: boolean }) {
  const max = Math.max(pred.holdout.persistence_mae, pred.holdout.lgbm_mae);
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between font-sans text-[15px]">
        <span className={active ? "font-medium text-ink" : "text-body"}>{text}</span>
        <span className={`font-mono text-sm ${active ? "text-ink" : "text-body"}`}>£{value.toFixed(1)}</span>
      </div>
      <div className="mt-1.5 h-3 rounded-full bg-node">
        <motion.div
          className={`h-full rounded-full ${active ? (text === "LightGBM" ? "bg-brand" : "bg-faint") : "bg-rule"}`}
          initial={{ width: 0 }}
          animate={{ width: `${(value / max) * 100}%` }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}
