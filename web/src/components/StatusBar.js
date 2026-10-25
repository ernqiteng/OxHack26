"use client";

import Link from "next/link";
import { ACTION, fmtTime, gbp, useApi } from "@/lib/api";

export default function StatusBar() {
  const { data: live } = useApi("/live", { refreshMs: 30_000 });
  const { data: status } = useApi("/status");
  const next = live?.next;
  const synthetic = status?.source === "synthetic";

  return (
    <header className="bg-slate-900 text-slate-100 px-6 py-3 flex flex-wrap items-center gap-x-8 gap-y-2">
      <Link href="/" className="text-xl font-bold tracking-tight hover:text-amber-200 transition-colors">⚡ Tempo</Link>
      <Kpi label="Period">{live ? `${live.period} of 48` : "…"}</Kpi>
      <Kpi label="Price now">{live ? `${gbp(live.latest_price)}/MWh` : "…"}</Kpi>
      <Kpi label="Next action">
        {next ? (
          <span style={{ color: next.action === "charge" ? "#4ade80" : "#fb7185" }}>
            {ACTION[next.action]?.glyph} {ACTION[next.action]?.label} {Math.abs(next.mw ?? 0)} MW at {fmtTime(next.target_time)}
          </span>
        ) : live ? "hold all day" : "…"}
      </Kpi>
      <Kpi label="Battery">{live?.battery ? `${live.battery.soc_mwh.toFixed(2)} MWh · ${gbp(live.battery.cum_pnl_gbp)}` : "—"}</Kpi>
      <Kpi label="Captured">{live?.captured_pct != null ? `${live.captured_pct.toFixed(0)}% of perfect` : "—"}</Kpi>
      {status && (
        <span
          title={status.note}
          className={`ml-auto text-xs font-semibold px-2.5 py-1 rounded-full ${synthetic ? "bg-amber-300 text-amber-950" : "bg-emerald-400 text-emerald-950"}`}
        >
          {synthetic ? "Synthetic data" : "Live: Tiger Data"}
        </span>
      )}
    </header>
  );
}

function Kpi({ label, children }) {
  return (
    <div className="leading-tight">
      <div className="text-[11px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className="font-semibold">{children}</div>
    </div>
  );
}
