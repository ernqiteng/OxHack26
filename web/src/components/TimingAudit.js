"use client";

import { useEffect, useState } from "react";
import { api, gbp } from "@/lib/api";
import { useSelection } from "@/lib/selection";
import { SimButton } from "./ReplaySimulation";

const SHIFT_LABELS = { "-2": "1 h earlier", "-1": "30 min earlier", 0: "As decided", 1: "30 min later", 2: "1 h later" };

export default function TimingAudit() {
  const { selected } = useSelection();
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [selected?.decision_id]);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setResult(await api(`/decisions/${selected.decision_id}/audit`, { method: "POST" }));
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto text-left">
      <div className="flex flex-col lg:flex-row gap-8 mb-8">
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="bg-white rounded-lg shadow p-4 flex-1">
            {result ? (
              <AuditChart rows={result.rows} hover={hover} setHover={setHover} />
            ) : (
              <div className="h-full min-h-72 flex items-center justify-center text-center text-slate-500">
                {selected ? "Press “Run timing audit” to replay this decision at five different times." : "Select a decision on the map first."}
              </div>
            )}
          </div>
          {(result || running || error) && (
            <div className="mt-4 p-3 rounded-md bg-slate-100 text-center min-h-10">
              {running && <p className="text-slate-600">Replaying five timelines…</p>}
              {error && <p className="text-red-600">Audit failed: {error}</p>}
              {result && !running && (
                <>
                  <p className="text-xl font-semibold text-slate-900">{result.sentence || "Not enough settled prices to compare the shifts."}</p>
                  <p className="text-sm text-slate-500 mt-1">In-process replay in {result.elapsed_s.toFixed(1)} s · simulator: {result.simulator}</p>
                </>
              )}
            </div>
          )}
        </div>

        <div className="w-full lg:w-80 bg-slate-50 p-5 rounded-lg shadow-sm">
          <PanelHeading>Parameters</PanelHeading>
          <div className="mb-5 text-sm text-slate-600 space-y-1">
            <p>Decision: <b className="text-slate-900">{selected ? `#${selected.decision_id}` : "none selected"}</b></p>
            <p>Shifts: −60, −30, 0, +30, +60 minutes</p>
            <p>Battery: 1 MW / 2 MWh, 90% round trip</p>
          </div>
          <PanelHeading>Mode</PanelHeading>
          <div className="mb-5 text-sm text-slate-600 space-y-2">
            <label className="flex items-center gap-2"><input type="radio" checked readOnly className="accent-blue-600" /> In-process replay</label>
            <label className="flex items-center gap-2 opacity-50" title="Fork mode runs from the Streamlit dashboard (make dashboard)">
              <input type="radio" disabled /> Tiger fork + Vultr workers
            </label>
            <p className="text-xs">Fork mode stays in the Streamlit dashboard, which manages the fork&apos;s lifetime.</p>
          </div>
          <PanelHeading>Actions</PanelHeading>
          <div className="flex flex-col gap-2 mb-5">
            <SimButton color="bg-green-600 hover:bg-green-700" onClick={run} disabled={!selected || running} className={running ? "busy" : ""}>
              {running ? "Replaying…" : "Run timing audit"}
            </SimButton>
            <SimButton color="bg-orange-500 hover:bg-orange-600" onClick={() => setResult(null)} disabled={!result || running}>Clear</SimButton>
          </div>
          <PanelHeading>Legend</PanelHeading>
          <div className="space-y-2 text-sm text-slate-600">
            <Swatch color="#2563eb">As decided</Swatch>
            <Swatch color="#94a3b8">Shifted timeline</Swatch>
          </div>
        </div>
      </div>

      <div className="bg-amber-50 p-5 rounded-lg border-l-4 border-amber-400 text-amber-900">
        <h3 className="font-semibold mb-2">How the audit works</h3>
        <ul className="list-disc pl-6 space-y-1.5 leading-relaxed">
          <li>Pick a decision on the map. Only decisions whose whole day has settled are shown, so every replay uses real outcomes.</li>
          <li><b>Run timing audit</b> replays the same plan five times: as decided, and moved 30 or 60 minutes earlier or later.</li>
          <li>Each bar is that timeline&apos;s profit. If a shifted bar beats “as decided”, the headline says Tempo mistimed it.</li>
        </ul>
      </div>
    </div>
  );
}

function AuditChart({ rows, hover, setHover }) {
  const vals = rows.map((r) => r.pnl_gbp).filter((v) => v != null);
  const max = Math.max(...vals, 1) * 1.15; // headroom for the value labels
  const min = Math.min(0, ...vals);
  const base = rows.find((r) => r.shift === 0)?.pnl_gbp;
  const H = 260;
  const yOf = (v) => ((max - v) / (max - min)) * H;

  return (
    <div>
      <p className="text-sm text-slate-500 mb-3">Profit of each timeline, £</p>
      <div className="relative flex items-end gap-4 px-2" style={{ height: H + 24 }}>
        <div className="absolute left-0 right-0 border-t border-slate-300" style={{ top: yOf(0) }} />
        {rows.map((r) => {
          const isBase = r.shift === 0;
          const v = r.pnl_gbp;
          const top = v == null ? yOf(0) : yOf(Math.max(v, 0));
          const height = v == null ? 0 : Math.abs(yOf(v) - yOf(0));
          return (
            <div
              key={r.shift}
              className="relative flex-1 h-full"
              onMouseEnter={() => setHover(r.shift)}
              onMouseLeave={() => setHover(null)}
            >
              <div
                className="absolute left-[12%] right-[12%] transition-all duration-500"
                style={{ top, height, background: isBase ? "#2563eb" : "#94a3b8", borderRadius: v >= 0 ? "4px 4px 0 0" : "0 0 4px 4px", opacity: hover == null || hover === r.shift ? 1 : 0.55 }}
              />
              <div className="absolute left-0 right-0 text-center text-sm font-semibold text-slate-800" style={{ top: Math.max(0, top - 22) }}>
                {v == null ? "failed" : isBase ? gbp(v) : `${r.pnl_delta_gbp >= 0 ? "+" : "−"}£${Math.abs(r.pnl_delta_gbp).toFixed(2)}`}
              </div>
              {hover === r.shift && v != null && (
                <div className="absolute z-10 left-1/2 -translate-x-1/2 top-2 whitespace-nowrap rounded-md bg-slate-900 text-white text-xs px-2 py-1.5 shadow">
                  {SHIFT_LABELS[r.shift]}: {gbp(v)}{!isBase && base != null && <> ({r.pnl_delta_gbp >= 0 ? "+" : "−"}{gbp(Math.abs(r.pnl_delta_gbp))} vs as decided)</>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 px-2 mt-2">
        {rows.map((r) => (
          <div key={r.shift} className={`flex-1 text-center text-sm ${r.shift === 0 ? "font-semibold text-blue-700" : "text-slate-600"}`}>{SHIFT_LABELS[r.shift]}</div>
        ))}
      </div>
    </div>
  );
}

const PanelHeading = ({ children }) => <h3 className="font-semibold text-slate-800 mb-3 pb-2 border-b-2 border-slate-200">{children}</h3>;
const Swatch = ({ color, children }) => (
  <div className="flex items-center gap-2"><span className="w-7 h-5 rounded-[3px] border border-slate-700" style={{ background: color }} />{children}</div>
);
