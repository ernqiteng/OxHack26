"use client";

import { useCallback, useEffect, useState } from "react";

// Presenter steps for a chapter. → (or a click) plays the next step; ← goes back one. `go` jumps to a step
// (e.g. when a live audit finishes).
// Listens in the capture phase and calls preventDefault, so Progress only changes page
// on → after the last step, and on ← from step 1.
export function useSteps(total: number, first = 1): [number, () => void, (s: number) => void] {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setTimeout(() => setStep(first), 300); // play step 1 on arrival
    return () => clearTimeout(id);
  }, [first]);

  const next = useCallback(() => setStep((s) => Math.min(total, s + 1)), [total]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if ((e.key === "ArrowRight" || e.key === "PageDown") && step < total) {
        e.preventDefault();
        setStep(step + 1);
      } else if ((e.key === "ArrowLeft" || e.key === "PageUp") && step > first) {
        e.preventDefault();
        setStep(step - 1);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [step, total, first]);

  const go = useCallback((s: number) => setStep(Math.min(total, Math.max(first, s))), [total, first]);

  return [step, next, go];
}
