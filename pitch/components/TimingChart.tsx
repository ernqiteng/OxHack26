"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import timing from "@/data/timing.json";
import { API } from "@/lib/api";
import { useSteps } from "@/lib/useSteps";

// Chapter 05: the timing audit, live. One Tiger fork of the live database, five Vultr workers replaying the
// decision's plan shifted −1 h … +1 h on what actually happened, then the verdict and the self-grade
// (SPEC.md, 05). Falls back to in-process, or to the last recorded run, if the infrastructure misbehaves.
const STEPS = 4;
const CAPTIONS = ["", "Did it pick the right moment?", "One click · a fork of the live database · five workers", "The verdict", "Across every completed cycle"];
const SHIFTS = [-2, -1, 0, 1, 2] as const;
const LABEL: Record<number, string> = { [-2]: "1 h earlier", [-1]: "30 min earlier", 0: "as decided", 1: "30 min later", 2: "1 h later" };
const PHRASE: Record<number, string> = { [-2]: "an hour earlier", [-1]: "30 minutes earlier", 0: "as decided", 1: "30 minutes later", 2: "an hour later" };
type Mode = "fork" | "inprocess" | "recorded";
type State = "queued" | "forking" | "ready" | "replaying" | "done" | "failed";
type Row = { shift: number; label: string; pnl_gbp: number | null; pnl_delta_gbp: number | null; worker_id?: string | null };
type Run = {
  mode: Mode;
  phase: "idle" | "running" | "done" | "error";
  seconds: number;
  states: Record<number, State>;
  workers: Record<number, string>;
  rows: Row[];
  error?: string;
  log: string[];
};

const label = "font-mono uppercase tracking-[0.12em]";
const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.4 } };
const gbp = (v: number) => `${v < 0 ? "−" : v > 0 ? "+" : ""}£${Math.abs(v).toFixed(2)}`;
const idle = (mode: Mode): Run => ({ mode, phase: "idle", seconds: 0, states: Object.fromEntries(SHIFTS.map((s) => [s, "queued"])) as Run["states"], workers: {}, rows: [], log: [] });

function useAudit(decisionId: number) {
  const [run, setRun] = useState<Run>(idle("fork"));
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clear = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(() => clear, []);

  const start = useCallback(
    async (mode: Mode) => {
      clear();
      const t0 = performance.now();
      const tick = () => setRun((r) => (r.phase === "running" ? { ...r, seconds: (performance.now() - t0) / 1000 } : r));
      const clock = setInterval(tick, 100);
      timers.current.push(clock as unknown as ReturnType<typeof setTimeout>);
      const finish = (patch: Partial<Run>) => {
        clearInterval(clock);
        setRun((r) => ({ ...r, ...patch, seconds: patch.seconds ?? (performance.now() - t0) / 1000 }));
      };
      setRun({ ...idle(mode), phase: "running" });

      if (mode === "recorded") {
        // Replays the stored timeline of the last real fork audit, clearly labelled, at its real pace.
        const rec = timing.recorded;
        const at = (s: number, fn: () => void) => timers.current.push(setTimeout(fn, s * 1000));
        at(0.2, () => setRun((r) => ({ ...r, states: Object.fromEntries(SHIFTS.map((s) => [s, "forking"])) as Run["states"] })));
        at(rec.elapsed_s * 0.82, () => setRun((r) => ({ ...r, states: Object.fromEntries(SHIFTS.map((s) => [s, "replaying"])) as Run["states"], workers: Object.fromEntries(rec.rows.map((x) => [x.shift, x.worker_id])) })));
        rec.rows.forEach((x, k) =>
          at(rec.elapsed_s * 0.9 + k * 0.4, () => setRun((r) => ({ ...r, states: { ...r.states, [x.shift]: "done" } }))),
        );
        at(rec.elapsed_s * 0.9 + 2.2, () => finish({ phase: "done", rows: rec.rows, seconds: rec.elapsed_s }));
        return;
      }

      if (mode === "inprocess") {
        setRun((r) => ({ ...r, states: Object.fromEntries(SHIFTS.map((s) => [s, "replaying"])) as Run["states"] }));
        try {
          const res = await fetch(`${API}/api/decisions/${decisionId}/audit`, { method: "POST", signal: AbortSignal.timeout(60_000) });
          if (!res.ok) throw new Error(`${res.status} ${(await res.json().catch(() => ({}))).detail ?? res.statusText}`);
          const body = await res.json();
          finish({ phase: "done", rows: body.rows, states: Object.fromEntries(SHIFTS.map((s) => [s, "done"])) as Run["states"], workers: Object.fromEntries(SHIFTS.map((s) => [s, "this laptop"])) });
        } catch (e) {
          finish({ phase: "error", error: String((e as Error).message ?? e) });
        }
        return;
      }

      // Real fork: start the job, then poll it.
      try {
        const res = await fetch(`${API}/api/decisions/${decisionId}/fork-audit`, { method: "POST", signal: AbortSignal.timeout(20_000) });
        if (!res.ok) throw new Error(`${res.status} ${(await res.json().catch(() => ({}))).detail ?? res.statusText}`);
      } catch (e) {
        finish({ phase: "error", error: String((e as Error).message ?? e) });
        return;
      }
      const poll = async () => {
        try {
          const res = await fetch(`${API}/api/decisions/${decisionId}/fork-audit`, { signal: AbortSignal.timeout(8_000) });
          const s = await res.json();
          const states = Object.fromEntries(Object.entries(s.states).map(([k, v]) => [Number(k), v])) as Run["states"];
          const workers = Object.fromEntries(Object.entries(s.workers).map(([k, v]) => [Number(k), v as string]));
          const log = (s.log as { t: number; message: string }[]).map((l) => `${l.t.toFixed(1)}s  ${l.message}`);
          if (s.done) {
            const ok = s.rows.length && !s.error;
            finish({ phase: ok ? "done" : "error", states, workers, rows: s.rows, log, error: s.error ?? (ok ? undefined : "the audit returned no rows"), seconds: s.running_s });
            return;
          }
          setRun((r) => ({ ...r, states, workers, log }));
        } catch {
          /* keep polling; the clock keeps running */
        }
        timers.current.push(setTimeout(poll, 1000));
      };
      poll();
    },
    [decisionId],
  );

  return { run, start, reset: () => (clear(), setRun(idle("fork"))) };
}

export function TimingChart() {
  const [step, , go] = useSteps(STEPS);
  const [decisionId, setDecisionId] = useState(timing.decision.id);
  useEffect(() => {
    const q = Number(new URLSearchParams(window.location.search).get("decision"));
    if (q) setDecisionId(q);
  }, []);
  const custom = decisionId !== timing.decision.id;
  const [mode, setMode] = useState<Mode>("fork");
  const { run, start } = useAudit(decisionId);

  // When the results land, show the verdict.
  useEffect(() => {
    if (run.phase === "done") {
      const id = setTimeout(() => go(3), 900);
      return () => clearTimeout(id);
    }
  }, [run.phase, go]);

  const launch = (m: Mode) => {
    setMode(m);
    start(m);
    go(2);
  };

  return (
    <div className="card-grid flex h-full select-none flex-col rounded-2xl border border-rule px-8 py-6 shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
      <div className="flex items-baseline justify-between gap-6 font-mono text-sm uppercase tracking-[0.2em]">
        <span className="font-medium text-ink">05 · Timing</span>
        <AnimatePresence mode="wait">
          <motion.span key={step} {...fade} className="text-body">
            {CAPTIONS[step]}
          </motion.span>
        </AnimatePresence>
      </div>

      <div className="relative mt-4 min-h-0 flex-1">
        <AnimatePresence mode="wait">
          {step === 1 && (
            <motion.div key="card" className="absolute inset-0" {...fade}>
              <DecisionCard custom={custom} decisionId={decisionId} mode={mode} setMode={setMode} onRun={() => launch(mode)} />
            </motion.div>
          )}
          {step === 2 && (
            <motion.div key="flow" className="absolute inset-0" {...fade}>
              <Flow run={run} onRun={() => launch(mode)} onRecorded={custom ? undefined : () => launch("recorded")} onInprocess={() => launch("inprocess")} />
            </motion.div>
          )}
          {step === 3 && (
            <motion.div key="verdict" className="absolute inset-0" {...fade}>
              <Verdict run={run} />
            </motion.div>
          )}
          {step === 4 && (
            <motion.div key="grade" className="absolute inset-0" {...fade}>
              <Grade />
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

/* ------------------------------------------------------------------ step 1 */

function DecisionCard({ custom, decisionId, mode, setMode, onRun }: { custom: boolean; decisionId: number; mode: Mode; setMode: (m: Mode) => void; onRun: () => void }) {
  const d = timing.decision;
  const [summary, setSummary] = useState<{ title: string; text: string } | null>(null);
  useEffect(() => {
    if (!custom) return;
    fetch(`${API}/api/decisions/${decisionId}/summary`, { signal: AbortSignal.timeout(6000) })
      .then((r) => (r.ok ? r.json() : null))
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [custom, decisionId]);

  return (
    <div className="grid h-full grid-cols-[1fr_380px] items-center gap-12">
      <div className="space-y-6">
        <p className={`text-xs text-faint ${label}`}>Decision #{decisionId}{custom ? "" : ` · made ${d.decided_at} · the plan from Decision`}</p>
        {custom ? (
          <>
            <p className="font-serif text-5xl font-bold leading-tight text-ink">{summary?.title ?? `Decision #${decisionId}`}</p>
            <p className="max-w-2xl font-sans text-lg leading-relaxed text-body">{summary?.text ?? "Loading the decision from the API…"}</p>
          </>
        ) : (
          <>
            <p className="font-serif text-6xl font-bold leading-tight text-ink">
              Charge {d.mw} MW at {d.target}
            </p>
            <p className="font-sans text-xl text-body">{d.day}</p>
            <div className="max-w-xl rounded-xl border border-charge-line bg-charge-bg px-6 py-5">
              <p className="font-sans text-lg text-charge-ink">{d.why.text}</p>
              <p className="mt-1 font-sans text-sm text-charge-ink/80">
                Spread £{d.why.spread?.toFixed(2)} &gt; costs £{d.why.cost?.toFixed(2)}
              </p>
            </div>
            <p className="max-w-xl font-sans text-base text-body">
              The forecast said this was the moment. Was it? We replay the whole plan an hour earlier, 30 minutes earlier, as decided, 30 minutes later and an hour later, on the prices that actually happened.
            </p>
          </>
        )}
      </div>
      <div className="space-y-5 border-l border-rule pl-10">
        <button onClick={onRun} className="w-full rounded-xl bg-brand px-6 py-6 font-mono text-lg font-medium uppercase tracking-[0.15em] text-paper shadow-sm transition-transform hover:scale-[1.01]">
          ▶ Run timing audit
        </button>
        <div>
          <p className={`mb-2 text-[11px] text-faint ${label}`}>How</p>
          <div className="flex rounded-lg border border-rule bg-node p-1">
            {(["fork", "inprocess"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className={`flex-1 rounded-md px-3 py-2 font-mono text-[11px] uppercase tracking-[0.1em] ${mode === m ? "bg-ink text-paper" : "text-body"}`}>
                {m === "fork" ? "Tiger fork + Vultr" : "In-process"}
              </button>
            ))}
          </div>
        </div>
        <p className="font-sans text-sm text-body">A fork takes about 30–40 s. One at a time: the free tier has a single fork slot.</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ step 2 */

function Flow({ run, onRun, onRecorded, onInprocess }: { run: Run; onRun: () => void; onRecorded?: () => void; onInprocess: () => void }) {
  const W = 1200;
  const H = 460;
  const fork = run.mode === "fork" || run.mode === "recorded";
  const anyForking = SHIFTS.some((s) => run.states[s] === "forking");
  const ready = SHIFTS.some((s) => ["ready", "replaying", "done"].includes(run.states[s]));
  const ring = { x: 420, y: H / 2, r: 74 };
  const wy = (k: number) => 50 + k * 90;
  const wx = 760;
  const ww = 300;

  return (
    <div className="grid h-full grid-cols-[1fr_300px] gap-8">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label="The timing audit as it runs">
        {/* Decision → fork */}
        <rect x={20} y={ring.y - 50} width={220} height={100} rx={12} className="fill-charge-bg stroke-charge-line" />
        <text x={130} y={ring.y - 12} textAnchor="middle" className={`fill-charge-ink text-[15px] font-semibold ${label}`}>
          Decision #{timing.decision.id}
        </text>
        <text x={130} y={ring.y + 14} textAnchor="middle" className="fill-charge-ink font-sans text-[15px]">
          {timing.decision.action === "charge" ? "Charge" : "Trade"} at {timing.decision.target}
        </text>
        <path d={`M240,${ring.y} L${ring.x - ring.r - 6},${ring.y}`} className={`${run.phase === "running" ? "flow" : ""} stroke-faint`} strokeWidth={1.6} fill="none" />

        {/* Fork (or this laptop) */}
        <circle cx={ring.x} cy={ring.y} r={ring.r + 36} className="fill-glow" opacity={anyForking || ready ? 0.8 : 0.3} />
        <circle cx={ring.x} cy={ring.y} r={ring.r} className="fill-card stroke-ring" strokeWidth={2.5} />
        {anyForking && (
          <motion.circle cx={ring.x} cy={ring.y} r={ring.r} className="fill-none stroke-ring" strokeWidth={2} initial={{ scale: 1, opacity: 0.6 }} animate={{ scale: 1.35, opacity: 0 }} transition={{ duration: 1.6, repeat: Infinity }} style={{ transformOrigin: `${ring.x}px ${ring.y}px` }} />
        )}
        <text x={ring.x} y={ring.y - 18} textAnchor="middle" className={`fill-ring text-[16px] font-semibold ${label}`}>
          {fork ? "Tiger fork" : "In-process"}
        </text>
        <text x={ring.x} y={ring.y + 12} textAnchor="middle" className="fill-ink font-serif text-[30px] font-bold">
          {run.seconds.toFixed(1)} s
        </text>
        <text x={ring.x} y={ring.y + 36} textAnchor="middle" className="fill-body font-sans text-[13px]">
          {run.phase === "idle" ? "not started" : anyForking ? "copy-on-write fork…" : ready || run.phase === "done" ? (fork ? "fork ready" : "replaying") : run.phase === "error" ? "stopped" : "starting…"}
        </text>
        <text x={ring.x} y={ring.y + ring.r + 60} textAnchor="middle" className={`fill-faint text-[11px] ${label}`}>
          {fork ? "a writable copy of everything Tempo knew" : "same replay, on this machine"}
        </text>

        {/* Five workers */}
        {SHIFTS.map((s, k) => {
          const st = run.states[s];
          const row = run.rows.find((r) => r.shift === s);
          const y = wy(k);
          const live = st === "replaying" || st === "ready";
          const done = st === "done";
          return (
            <g key={s}>
              <path
                d={`M${ring.x + ring.r + 6},${ring.y} C${ring.x + ring.r + 120},${ring.y} ${wx - 120},${y + 30} ${wx - 6},${y + 30}`}
                fill="none"
                strokeWidth={1.5}
                className={`${live ? "flow stroke-ring" : done ? "stroke-charge" : "stroke-rule"}`}
              />
              <rect x={wx} y={y} width={ww} height={60} rx={10} className={done ? "fill-charge-bg stroke-charge-line" : s === 0 ? "fill-card stroke-ring" : "fill-node stroke-node-line"} strokeWidth={s === 0 ? 2 : 1} />
              <text x={wx + 18} y={y + 25} className={`fill-label text-[13px] font-semibold ${label}`}>
                {LABEL[s]}
              </text>
              <text x={wx + 18} y={y + 46} className="fill-body font-sans text-[13px]">
                {run.workers[s] ? `${run.workers[s]}${fork ? " · Vultr" : ""}` : fork ? "Vultr worker" : "local"}
              </text>
              <text x={wx + ww - 16} y={y + 37} textAnchor="end" className={`text-[14px] ${done ? "fill-charge-ink font-semibold" : "fill-body"} ${label}`}>
                {done && row?.pnl_gbp != null ? `£${row.pnl_gbp.toFixed(2)}` : st === "failed" ? "failed" : live ? "replaying…" : st === "forking" ? "waiting" : "queued"}
              </text>
              {live && <motion.circle cx={wx + ww - 120} cy={y + 32} r={4} className="fill-ring" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1, repeat: Infinity }} />}
            </g>
          );
        })}
      </svg>

      <div className="flex flex-col justify-center gap-4 border-l border-rule pl-6" onClick={(e) => e.stopPropagation()}>
        {run.mode === "recorded" && (
          <p className="rounded-md bg-sell-bg px-3 py-2 font-mono text-xs uppercase tracking-[0.12em] text-sell-ink">
            Recorded run · {timing.recorded.started_at} · {timing.recorded.elapsed_s} s
          </p>
        )}
        {run.phase === "idle" && (
          <button onClick={onRun} className="rounded-xl bg-brand px-5 py-4 font-mono text-sm font-medium uppercase tracking-[0.15em] text-paper">
            ▶ Run timing audit
          </button>
        )}
        {run.phase === "error" && (
          <div className="space-y-3">
            <p className="font-sans text-sm text-sell-ink">The audit didn&apos;t finish: {run.error}</p>
            <button onClick={onInprocess} className="w-full rounded-lg border border-rule bg-node px-4 py-3 font-mono text-xs uppercase tracking-[0.12em] text-ink">
              Run in-process instead
            </button>
          </div>
        )}
        <div className="max-h-64 space-y-1 overflow-hidden font-mono text-[11px] leading-relaxed text-body">
          {run.log.slice(-9).map((l, k) => (
            <p key={k} className="truncate">{l}</p>
          ))}
        </div>
        {onRecorded && run.mode !== "recorded" && (run.phase === "error" || run.phase === "idle") && (
          <button onClick={onRecorded} className="text-left font-mono text-[11px] uppercase tracking-[0.12em] text-faint underline">
            Show last recorded run
          </button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ step 3 */

function Verdict({ run }: { run: Run }) {
  const rows = SHIFTS.map((s) => run.rows.find((r) => r.shift === s)).filter((r): r is Row => !!r && r.pnl_delta_gbp != null);
  if (!rows.length)
    return <p className="flex h-full items-center justify-center font-sans text-lg text-body">Run the audit to see the verdict.</p>;
  const worst = rows.reduce((a, b) => (b.pnl_delta_gbp! < a.pnl_delta_gbp! ? b : a));
  const best = rows.reduce((a, b) => (b.pnl_delta_gbp! > a.pnl_delta_gbp! ? b : a));
  const span = Math.max(...rows.map((r) => Math.abs(r.pnl_delta_gbp!)), 1);
  const sentence =
    best.shift !== 0 && best.pnl_delta_gbp! > 0.005
      ? `${cap(PHRASE[best.shift])} would have made ${gbp(best.pnl_delta_gbp!).slice(1)} more.`
      : `As decided was the best of the five. ${cap(PHRASE[worst.shift])} would have cost £${Math.abs(worst.pnl_delta_gbp!).toFixed(2)}.`;
  return (
    <div className="flex h-full flex-col">
      <p className="font-serif text-4xl font-bold text-ink">{sentence}</p>
      <p className={`mt-2 text-[11px] text-faint ${label}`}>
        Profit of the whole plan, shifted, on the prices that actually happened · against as decided
        {run.mode === "recorded" ? ` · recorded run ${timing.recorded.started_at}` : run.mode === "inprocess" ? " · in-process" : ` · ${run.seconds.toFixed(1)} s on a Tiger fork`}
      </p>
      <div className="mt-6 grid min-h-0 flex-1 grid-cols-5 gap-6">
        {rows.map((r, k) => {
          const d = r.pnl_delta_gbp!;
          const h = (Math.abs(d) / span) * 34;
          const zero = r.shift === 0;
          return (
            <div key={r.shift} className="flex flex-col items-center">
              <div className="relative w-full flex-1">
                <span className="absolute inset-x-0 top-1/2 h-px bg-rule" />
                {zero ? (
                  <span className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand ring-4 ring-glow" />
                ) : (
                  <motion.div
                    className={`absolute left-[15%] right-[15%] rounded-md ${d < 0 ? "bg-sell" : "bg-charge"}`}
                    style={d < 0 ? { top: "50%" } : { bottom: "50%" }}
                    initial={{ height: 0 }}
                    animate={{ height: `${h}%` }}
                    transition={{ delay: 0.2 + k * 0.15, duration: 0.6 }}
                  />
                )}
                <motion.p
                  className={`absolute inset-x-0 text-center font-serif text-2xl font-bold ${zero ? "text-brand" : d < 0 ? "text-sell-ink" : "text-charge-ink"}`}
                  style={d < 0 || zero ? { top: `calc(50% ${zero ? "- 3.2rem" : `+ ${h}% + 0.5rem`})` } : { bottom: `calc(50% + ${h}% + 0.5rem)` }}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.6 + k * 0.15 }}
                >
                  {zero ? "£0" : gbp(d)}
                </motion.p>
              </div>
              <p className={`mt-3 text-center font-sans text-base ${zero ? "font-semibold text-ink" : "text-label"}`}>{cap(r.label)}</p>
              <p className="text-center font-mono text-[11px] text-body">
                £{r.pnl_gbp?.toFixed(2)}
                {r.worker_id ? ` · ${r.worker_id}` : ""}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/* ------------------------------------------------------------------ step 4 */

function Grade() {
  const g = timing.self_grade;
  return (
    <div className="grid h-full grid-cols-[1fr_1fr] items-center gap-16">
      <div>
        <p className="font-serif text-[9rem] font-bold leading-none text-ink">
          {g.within_one}
          <span className="text-faint"> / {g.n_cycles}</span>
        </p>
        <p className="mt-6 max-w-lg font-sans text-2xl leading-snug text-label">completed cycles timed within half an hour of the best possible moment</p>
      </div>
      <div className="space-y-10">
        <div className="flex flex-wrap gap-3">
          {Array.from({ length: g.n_cycles }, (_, k) => (
            <motion.span
              key={k}
              className={`h-12 w-12 rounded-full ${k < g.within_one ? "bg-charge" : "bg-sell"}`}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.2 + k * 0.12, type: "spring", stiffness: 260, damping: 18 }}
            />
          ))}
        </div>
        <div>
          <p className="font-serif text-5xl font-bold text-ink">£{g.mean_cost_gbp.toFixed(2)}</p>
          <p className={`mt-2 text-xs text-body ${label}`}>average cost of mistiming, per cycle</p>
        </div>
        <p className="font-sans text-base text-body">
          Every completed cycle is replayed at −1 h … +1 h on settled prices, automatically. {g.n_cycles} cycles is a small sample: live decisions started on 21 Oct.
        </p>
      </div>
    </div>
  );
}
