"use client";

import { useSelection } from "@/lib/selection";
import { ACTION, fmtDay, fmtTime } from "@/lib/api";
import DecisionSummary from "./DecisionSummary";
import ForecastCompare from "./ForecastCompare";
import ReplaySimulation from "./ReplaySimulation";
import TimingAudit from "./TimingAudit";
import Honesty from "./Honesty";

const Divider = () => <hr className="my-6 border-slate-300" />;

export default function DecisionInfo() {
  const { selected } = useSelection();

  return (
    <div className="bg-slate-200 p-4 md:p-8 text-center flex-1 min-w-0">
      {selected ? (
        <div key={selected.decision_id} className="animate-fade-in">
          <h2 className="text-3xl font-bold mb-2">
            <span style={{ color: ACTION[selected.action]?.color }}>{ACTION[selected.action]?.glyph}</span>{" "}
            {ACTION[selected.action]?.label} {Math.abs(selected.mw ?? 0)} MW at {fmtTime(selected.target_time)}, {fmtDay(selected.target_time)}
          </h2>
          <p className="text-slate-600">Decision #{selected.decision_id}</p>
          <Divider />
          <DecisionSummary decisionId={selected.decision_id} />
        </div>
      ) : (
        <div>
          <h2 className="text-3xl font-bold mb-2">No Decision Selected</h2>
          <p className="text-xl">Select a decision on the map to see its summary and audit its timing.</p>
        </div>
      )}
      <Divider />
      <h2 className="text-2xl font-bold mb-4">Timing Audit</h2>
      <TimingAudit />
      <Divider />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold">Forecast vs What Actually Happened</h2>
          <p className="text-slate-600 mb-4">Drag the divider: forecast on the left, settled prices on the right, one replay week.</p>
          <ForecastCompare />
        </div>
        <div className="min-w-0">
          <h2 className="text-2xl font-bold">Replay Simulation</h2>
          <p className="text-slate-600 mb-4">The same week played back half-hour by half-hour, as Tempo traded it.</p>
          <ReplaySimulation />
        </div>
      </div>
      <Divider />
      <h2 className="text-2xl font-bold mb-4">Honesty</h2>
      <Honesty />
    </div>
  );
}
