"use client";

import DecisionMap from "@/components/DecisionMap";
import DecisionInfo from "@/components/DecisionInfo";
import StatusBar from "@/components/StatusBar";

export default function Dashboard() {
  return (
    <main className="min-h-screen flex flex-col bg-slate-200">
      <StatusBar />
      <div className="overflow-hidden">
        <DecisionMap />
      </div>
      <div className="flex">
        <DecisionInfo />
      </div>
    </main>
  );
}
