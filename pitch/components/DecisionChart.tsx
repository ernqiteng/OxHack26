"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import dec from "@/data/decision.json";
import { useSteps } from "@/lib/useSteps";

// Chapter 03: the 23 Oct 07:00 live run. The schedule and battery, why each half-hour did what it did, the
// overnight cycle the cost gate refused, and what-if sliders replayed by the real optimiser (SPEC.md, 03).
const STEPS = 4;
const CAPTIONS = [
  "",
  "The live decision made at 07:00 on 23 Oct · next 24 hours",
  "Every half-hour has a reason · click a bar",
  "The trade it refused",
  "Change the costs · the real optimiser replans",
];

type Period = (typeof dec.periods)[number];
type Code = "c" | "s" | "h";
const ps = dec.periods;
const N = ps.length;
const LIVE = { wear: dec.battery.wear_per_mwh, eff: Math.round(dec.battery.rt_efficiency * 100) };
const liveCodes = ps.map((p) => (p.action === "charge" ? "c" : p.action === "discharge" ? "s" : "h")) as Code[];
const hold = dec.hold;
const holdWhy = hold.why as { buy_t: string; sell_t: string; buy: number; sell: number; spread: number; loss: number; deg: number; cost: number };

const W = 900;
const H = 520;
const L = 64;
const R = 16;
const T = 24;
const PRICE_B = 360; // bottom of the price bars
const SOC_T = 400; // battery strip
const SOC_B = 480;
const Y_MAX = Math.ceil(Math.max(...ps.map((p) => p.p50)) / 50) * 50;
const slot = (W - L - R) / N;
const x = (i: number) => L + i * slot;
const y = (v: number) => T + ((Y_MAX - v) / Y_MAX) * (PRICE_B - T);
const socY = (v: number) => SOC_B - (v / dec.battery.capacity_mwh) * (SOC_B - SOC_T);
const idx = (t: string) => ps.findIndex((p) => p.t === t);

const label = "font-mono uppercase tracking-[0.12em]";
const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.4 } };
const fill: Record<Code, string> = { c: "fill-charge", s: "fill-sell", h: "fill-node-line" };
const gbp = (v: number) => `${v < 0 ? "−" : ""}£${Math.abs(v).toFixed(2)}`;

export function DecisionChart() {
  const [step, next] = useSteps(STEPS);
  const [selected, setSelected] = useState(idx(ps.find((p) => p.action === "charge")!.t));
  const [wear, setWear] = useState(LIVE.wear);
  const [eff, setEff] = useState(LIVE.eff);

  useEffect(() => {
    if (step < 4) {
      setWear(LIVE.wear);
      setEff(LIVE.eff);
    }
  }, [step]);

  const plan = useMemo(() => {
    const g = dec.whatif.grid[`${wear}_${eff}` as keyof typeof dec.whatif.grid];
    return { codes: g.a.split("") as Code[], soc: g.soc, trades: g.trades, expected: g.expected };
  }, [wear, eff]);
  const codes = step >= 4 ? plan.codes : liveCodes;
  const soc = step >= 4 ? plan.soc : ps.map((p) => p.soc);
  const socPath =
    `M${x(0)},${socY(dec.battery.start_soc)}` + soc.map((v, i) => `L${x(i + 1)},${socY(v)}`).join("") + `L${x(N)},${SOC_B}L${x(0)},${SOC_B}Z`;

  const pick = (i: number) => (e: React.MouseEvent) => {
    if (step !== 2) return;
    e.stopPropagation();
    setSelected(i);
  };
  const hb = idx(holdWhy.buy_t);
  const hs = idx(holdWhy.sell_t);

  return (
    <div
      onClick={next}
      className="card-grid flex h-full cursor-pointer select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
    >
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">03 · Decision</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <div className="mt-4 grid min-h-0 flex-1 grid-cols-[1fr_380px] gap-10">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label="Battery schedule for the next 24 hours">
          {/* Price axis */}
          {[0, 50, 100, 150, 200].filter((v) => v <= Y_MAX).map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="stroke-grid" />
              <text x={L - 12} y={y(v) + 5} textAnchor="end" className="fill-faint font-mono text-[14px]">
                £{v}
              </text>
            </g>
          ))}
          <text x={L} y={T - 8} className={`fill-faint text-[12px] ${label}`}>
            Forecast price (p50) · coloured by decision
          </text>

          {/* Bars */}
          {ps.map((p, i) => {
            const c = codes[i];
            const sel = step === 2 && i === selected;
            const inPair = step === 3 && (i === hb || i === hs);
            return (
              <g key={p.t} onClick={pick(i)} className={step === 2 ? "cursor-pointer" : ""}>
                <rect x={x(i)} y={T} width={slot} height={PRICE_B - T} fill="transparent" />
                <motion.rect
                  x={x(i) + 1.5}
                  width={slot - 3}
                  rx={2}
                  initial={{ y: PRICE_B, height: 0 }}
                  animate={{ y: y(p.p50), height: PRICE_B - y(p.p50), opacity: step === 3 && !inPair ? 0.35 : 1 }}
                  transition={{ delay: step <= 1 ? i * 0.02 : 0, duration: 0.5 }}
                  className={`${fill[c]} transition-[fill] duration-500`}
                />
                {(sel || inPair) && (
                  <rect x={x(i) - 1} y={y(p.p50) - 4} width={slot + 2} height={PRICE_B - y(p.p50) + 4} rx={3} className="fill-none stroke-ink" strokeWidth={2} />
                )}
              </g>
            );
          })}

          {/* Step 3: the refused trade */}
          <AnimatePresence>
            {step === 3 && (
              <motion.g key="refused" {...fade}>
                <path
                  d={`M${x(hb) + slot / 2},${y(ps[hb].p50) - 10} C${x(hb) + slot / 2},${y(ps[hb].p50) - 90} ${x(hs) + slot / 2},${y(ps[hs].p50) - 90} ${x(hs) + slot / 2},${y(ps[hs].p50) - 10}`}
                  fill="none"
                  className="flow stroke-ink"
                  strokeWidth={1.5}
                />
                <rect x={(x(hb) + x(hs)) / 2 - 40} y={y(Math.max(ps[hb].p50, ps[hs].p50)) - 104} width={80 + slot} height={30} rx={6} className="fill-ink" />
                <text x={(x(hb) + x(hs)) / 2 + slot / 2} y={y(Math.max(ps[hb].p50, ps[hs].p50)) - 84} textAnchor="middle" className={`fill-paper text-[13px] ${label}`}>
                  Hold
                </text>
              </motion.g>
            )}
          </AnimatePresence>

          {/* Battery strip */}
          <text x={L} y={SOC_T - 12} className={`fill-faint text-[12px] ${label}`}>
            Battery · 0–{dec.battery.capacity_mwh} MWh
          </text>
          <rect x={L} y={SOC_T} width={W - L - R} height={SOC_B - SOC_T} rx={4} className="fill-node" />
          <motion.path animate={{ d: socPath }} transition={{ duration: 0.6, ease: "easeInOut" }} className="fill-charge/40 stroke-charge-ink" strokeWidth={1.5} />

          {/* Hours */}
          {ps.map((p, i) => (i % 6 === 0 ? (
            <text key={p.t} x={x(i)} y={H - 12} textAnchor={i === 0 ? "start" : "middle"} className="fill-faint font-mono text-[14px]">
              {p.t}
            </text>
          ) : null))}
        </svg>

        {/* Side panel */}
        <div className="flex flex-col justify-center gap-6 border-l border-rule pl-8" onClick={(e) => step >= 2 && e.stopPropagation()}>
          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.div key="summary" {...fade} className="space-y-6">
                <Legend />
                <Stat value={`${liveCodes.filter((c) => c !== "h").length}`} text="half-hours trading" />
                <Stat value={`${liveCodes.filter((c) => c === "h").length}`} text="half-hours holding, on purpose" />
                <Stat value={gbp(dec.expected_pnl)} text="expected profit on the forecast" />
              </motion.div>
            )}
            {step === 2 && <Reason key={`r${selected}`} p={ps[selected]} />}
            {step === 3 && <Waterfall key="wf" />}
            {step === 4 && (
              <motion.div key="whatif" {...fade} className="space-y-7">
                <Slider text="Battery wear" unit="£/MWh" value={wear} min={0} max={30} step={1} live={LIVE.wear} onChange={setWear} fmt={(v) => `£${v}`} />
                <Slider text="Round-trip efficiency" unit="%" value={eff} min={75} max={95} step={5} live={LIVE.eff} onChange={setEff} fmt={(v) => `${v}%`} />
                <div className="grid grid-cols-2 gap-4 border-t border-rule pt-5">
                  <Stat value={`${plan.trades}`} text="half-hours trading" />
                  <Stat value={gbp(plan.expected)} text="expected profit" />
                </div>
                <button
                  onClick={() => {
                    setWear(LIVE.wear);
                    setEff(LIVE.eff);
                  }}
                  className={`font-mono text-xs uppercase tracking-[0.15em] ${wear === LIVE.wear && eff === LIVE.eff ? "text-faint" : "text-brand underline"}`}
                >
                  Reset to the live settings
                </button>
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

function Legend() {
  return (
    <div className="space-y-2.5">
      {[
        ["bg-charge", "Charge · buy power"],
        ["bg-sell", "Sell · discharge"],
        ["bg-node-line", "Hold"],
      ].map(([c, t]) => (
        <p key={t} className="flex items-center gap-3 font-sans text-[15px] text-label">
          <span className={`h-4 w-4 rounded-sm ${c}`} />
          {t}
        </p>
      ))}
    </div>
  );
}

function Stat({ value, text }: { value: string; text: string }) {
  return (
    <div>
      <p className="font-serif text-3xl font-bold text-ink">{value}</p>
      <p className={`mt-1 text-[11px] text-body ${label}`}>{text}</p>
    </div>
  );
}

function Reason({ p }: { p: Period }) {
  const why = p.why as { kind: string; text: string; spread?: number; cost?: number; loss?: number; deg?: number };
  const tone = p.action === "charge" ? "charge" : p.action === "discharge" ? "sell" : "hold";
  const pill = { charge: "bg-charge-bg text-charge-ink border-charge-line", sell: "bg-sell-bg text-sell-ink border-sell-line", hold: "bg-node text-label border-node-line" }[tone];
  return (
    <motion.div {...fade} className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="font-serif text-3xl font-bold text-ink">{p.t}</span>
        <span className={`rounded-md border px-2.5 py-1 font-mono text-xs font-medium uppercase tracking-[0.12em] ${pill}`}>
          {tone === "sell" ? "Sell" : tone === "charge" ? "Charge" : "Hold"}
          {p.mw !== 0 && ` · ${Math.abs(p.mw).toFixed(2)} MW`}
        </span>
      </div>
      <p className="font-sans text-sm text-body">Forecast price {gbp(p.p50)}/MWh</p>
      <p className="font-sans text-[17px] leading-snug text-ink">{why.text}</p>
      {why.spread != null && why.cost != null && (
        <p className="rounded-lg border border-rule bg-node px-4 py-3 font-sans text-sm leading-relaxed text-label">
          Spread <b>{gbp(why.spread)}</b> {why.spread > why.cost ? ">" : "≤"} costs <b>{gbp(why.cost)}</b>
          <br />
          <span className="text-body">
            efficiency loss {gbp(why.loss!)} + wear {gbp(why.deg!)} per MWh
          </span>
        </p>
      )}
      <p className={`text-[11px] text-faint ${label}`}>Decision #{p.id} · click any bar</p>
    </motion.div>
  );
}

function Waterfall() {
  const w = holdWhy;
  const result = w.spread - w.loss - w.deg;
  const rows = [
    { text: "Spread", sub: `buy ${w.buy_t} ${gbp(w.buy)} → sell ${w.sell_t} ${gbp(w.sell)}`, from: 0, to: w.spread, cls: "bg-charge" },
    { text: "Efficiency loss", sub: "10% of the energy is lost in the round trip", from: w.spread, to: w.spread - w.loss, cls: "bg-sell" },
    { text: "Battery wear", sub: `£${dec.battery.wear_per_mwh}/MWh on what it sells`, from: w.spread - w.loss, to: result, cls: "bg-sell" },
  ];
  const lo = Math.min(0, result);
  const span = w.spread - lo;
  const pos = (v: number) => ((v - lo) / span) * 100;
  return (
    <motion.div {...fade} className="space-y-4">
      <p className={`text-[11px] text-faint ${label}`}>The overnight cycle · per MWh · decision #{hold.id}</p>
      {rows.map((r, k) => (
        <div key={r.text}>
          <div className="flex items-baseline justify-between font-sans text-[15px]">
            <span className="text-ink">{r.text}</span>
            <span className="font-mono text-sm text-body">{gbp(r.to - r.from)}</span>
          </div>
          <div className="relative mt-1.5 h-3 rounded-full bg-node">
            <motion.div
              className={`absolute h-full rounded-full ${r.cls}`}
              style={{ left: `${pos(Math.min(r.from, r.to))}%` }}
              initial={{ width: 0 }}
              animate={{ width: `${(Math.abs(r.to - r.from) / span) * 100}%` }}
              transition={{ delay: 0.2 + k * 0.35, duration: 0.5 }}
            />
            <span className="absolute top-[-3px] h-[18px] w-px bg-faint" style={{ left: `${pos(0)}%` }} />
          </div>
          <p className="mt-1 font-sans text-xs text-body">{r.sub}</p>
        </div>
      ))}
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1.4 }} className="flex items-center gap-4 border-t border-rule pt-4">
        <span className="font-serif text-4xl font-bold text-ink">{gbp(result)}</span>
        <span className="rounded-md bg-ink px-3 py-1.5 font-mono text-xs font-medium uppercase tracking-[0.15em] text-paper">Hold</span>
      </motion.div>
    </motion.div>
  );
}

function Slider({ text, unit, value, min, max, step, live, onChange, fmt }: { text: string; unit: string; value: number; min: number; max: number; step: number; live: number; onChange: (v: number) => void; fmt: (v: number) => string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="font-sans text-[15px] text-ink">{text}</span>
        <span className="font-serif text-2xl font-bold text-ink">{fmt(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[var(--color-brand)]"
        aria-label={`${text} (${unit})`}
      />
      <div className={`flex justify-between text-[11px] text-faint ${label}`}>
        <span>{fmt(min)}</span>
        <span>live {fmt(live)}</span>
        <span>{fmt(max)}</span>
      </div>
    </div>
  );
}
