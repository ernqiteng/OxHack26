"use client";

import { gbp, useApi } from "@/lib/api";

export default function Honesty() {
  const { data, error, loading } = useApi("/honesty");
  if (loading) return <p className="text-slate-600">Loading backtest…</p>;
  if (error) return <p className="text-red-600">Could not load the backtest: {error.message}</p>;
  if (!data) return null;
  const rows = data.summary || [];
  const g = data.self_grade || {};

  return (
    <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-6 text-left">
      <div className="lg:col-span-3 bg-white rounded-lg shadow p-5">
        <h3 className="font-semibold text-lg">How much of the perfect-hindsight profit each strategy captured</h3>
        <p className="text-sm text-slate-500 mb-4">
          Walk-forward backtest{data.weeks ? ` over ${data.weeks} weeks` : ""}. Same battery, same costs, only the forecast or rule changes.
        </p>
        <div className="space-y-3">
          {rows.map((r) => {
            const tempo = r.strategy.startsWith("Tempo (");
            const perfect = r.strategy.toLowerCase().startsWith("perfect");
            return (
              <div key={r.strategy}>
                <div className="flex justify-between text-sm mb-1">
                  <span className={tempo ? "font-semibold text-blue-700" : "text-slate-700"}>{r.strategy}</span>
                  <span className="text-slate-800 font-mono">{r.pct_of_perfect?.toFixed(0)}% · {gbp(r.pnl_gbp, 0)}</span>
                </div>
                <div className="h-3 bg-slate-100 rounded-r">
                  <div
                    className="h-3 rounded-r transition-all duration-700"
                    style={{ width: `${Math.max(0, Math.min(100, r.pct_of_perfect ?? 0))}%`, background: tempo ? "#2563eb" : perfect ? "#334155" : "#94a3b8" }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="lg:col-span-2 space-y-6">
        <div className="bg-white rounded-lg shadow p-5">
          <h3 className="font-semibold text-lg mb-3">Self-grade</h3>
          <dl className="grid grid-cols-3 gap-3 text-center">
            <Stat label="within one period of best">{g.pct_within_one_period != null ? `${g.pct_within_one_period.toFixed(0)}%` : "—"}</Stat>
            <Stat label="cycles graded">{g.n_cycles ?? "—"}</Stat>
            <Stat label="mean cost of mistiming">{gbp(g.mean_cost_of_mistiming_gbp)}</Stat>
          </dl>
          {data.calibration_sentence && <p className="mt-4 text-sm text-slate-700">{data.calibration_sentence}</p>}
        </div>
        <div className="bg-amber-50 p-5 rounded-lg border-l-4 border-amber-400 text-amber-900">
          <h3 className="font-semibold mb-2">Where Tempo is weak</h3>
          <ul className="list-disc pl-6 space-y-1.5 text-sm leading-relaxed">
            {(data.weak_points || []).map((w) => <li key={w}>{w}</li>)}
          </ul>
        </div>
      </div>
    </div>
  );
}

const Stat = ({ label, children }) => (
  <div>
    <dd className="text-2xl font-bold text-slate-900">{children}</dd>
    <dt className="text-xs text-slate-500">{label}</dt>
  </div>
);
