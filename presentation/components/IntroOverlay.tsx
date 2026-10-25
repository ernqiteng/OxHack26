"use client";

// Click-to-start intro: a blurred overlay with the wordmark holds until a click, Space or Enter, then the
// page staggers in underneath. Plays once per page load; R replays it. Animations live in globals.css.

import { useCallback, useEffect, useState } from "react";

type Phase = "hold" | "in" | "idle";

const EXIT_MS = 680;

function stamp(d: Date) {
  const day = d.toLocaleDateString("en-GB", { weekday: "short" });
  const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day} ${date} · ${time}`;
}

export default function IntroOverlay() {
  const [phase, setPhase] = useState<Phase>("hold");
  const [now, setNow] = useState("");

  useEffect(() => {
    document.documentElement.dataset.intro = phase;
  }, [phase]);

  // While holding: live clock, page pinned to the top (About) unless the URL names a section.
  useEffect(() => {
    if (phase !== "hold") return;
    const tick = () => setNow(stamp(new Date()));
    tick();
    const id = setInterval(tick, 1000);
    if (!window.location.hash) {
      window.history.scrollRestoration = "manual";
      window.scrollTo(0, 0);
    }
    document.body.style.overflow = "hidden";
    return () => {
      clearInterval(id);
      document.body.style.overflow = "";
    };
  }, [phase]);

  useEffect(() => {
    if (phase !== "in") return;
    const id = setTimeout(() => setPhase("idle"), EXIT_MS);
    return () => clearTimeout(id);
  }, [phase]);

  const begin = useCallback(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setPhase((p) => (p === "hold" ? (reduced ? "idle" : "in") : p));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.key === " " || e.key === "Enter") && document.documentElement.dataset.intro === "hold") {
        e.preventDefault();
        begin();
      } else if (e.key === "r" || e.key === "R") {
        setPhase("hold");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [begin]);

  if (phase === "idle") return null;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Enter Tempo"
      onClick={begin}
      className={`intro-overlay fixed inset-0 z-[60] flex cursor-pointer flex-col items-center justify-center px-4 ${
        phase === "in" ? "intro-out" : ""
      }`}
    >
      <div className="intro-text flex flex-col items-center text-center">
        <p className="min-h-[1.5em] font-mono text-[13px] font-medium tracking-[0.08em] text-text-secondary uppercase">
          {now}
        </p>
        <p className="mt-5 font-serif text-[4.5rem] leading-none font-bold tracking-[-0.03em] text-foreground sm:text-[7rem]">
          Tempo
        </p>
        <span className="intro-rule mt-8 block h-0.5 w-[120px] bg-brand" aria-hidden />
      </div>
      <p className="intro-hint absolute bottom-12 font-mono text-xs tracking-[0.1em] text-text-secondary uppercase">
        Click anywhere to begin
      </p>
    </div>
  );
}
