"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";
import { useAnimatedText } from "@/lib/useAnimatedText";

const LOADING_MESSAGES = ["Reading the decision...", "Lining up settled prices..."];

export default function DecisionSummary({ decisionId }) {
  const { data, error, loading } = useApi(`/decisions/${decisionId}/summary`);
  const [msg, setMsg] = useState(0);

  useEffect(() => {
    if (!loading) return;
    setMsg(0);
    const id = setInterval(() => setMsg((i) => (i + 1) % LOADING_MESSAGES.length), 1200);
    return () => clearInterval(id);
  }, [loading]);

  const animated = useAnimatedText(data?.text || "");

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center mt-8 animate-fade-in">
        <div className="w-8 h-8 border-4 border-slate-300 border-t-indigo-500 rounded-full animate-spin mb-3" />
        <p className="text-slate-700 text-lg font-medium">{LOADING_MESSAGES[msg]}</p>
        <div className="flex space-x-1 mt-2">
          {LOADING_MESSAGES.map((_, i) => (
            <div key={i} className={`w-2 h-2 rounded-full transition-all duration-300 ${i === msg ? "bg-indigo-500 scale-125" : "bg-slate-300"}`} />
          ))}
        </div>
      </div>
    );
  }
  if (error) return <p className="text-red-600 mt-6 text-center">Failed to load the summary: {error.message}</p>;
  if (!data) return null;

  return (
    <div className="max-w-4xl mx-auto px-4">
      <h3 className="text-2xl font-semibold text-center pb-2">Summary</h3>
      <p className="text-left text-lg leading-relaxed">
        {animated}
        <span className="inline-block w-2 animate-pulse">▌</span>
      </p>
      {data.run_id === "selftest" && (
        <p className="mt-2 text-sm text-amber-700">This is a rehearsal decision (run id selftest), not a live one.</p>
      )}
    </div>
  );
}
