"use client";

import { useEffect, useState } from "react";

type ProgressRailProps = {
  sectionId: string;
  items: { id: string; label: string }[];
};

const clamp = (n: number) => Math.min(1, Math.max(0, n));

export default function ProgressRail({ sectionId, items }: ProgressRailProps) {
  const [progress, setProgress] = useState<number[]>(() => items.map(() => 0));
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const line = window.innerHeight / 2;
      const section = document.getElementById(sectionId)?.getBoundingClientRect();
      setVisible(!!section && section.top < line && section.bottom > line);
      setProgress(
        items.map(({ id }) => {
          const rect = document.getElementById(id)?.getBoundingClientRect();
          return rect ? clamp((line - rect.top) / rect.height) : 0;
        }),
      );
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [sectionId, items]);

  return (
    <nav
      aria-label="Progress through the points"
      className={`fixed top-1/2 right-6 z-40 hidden -translate-y-1/2 transition-opacity duration-300 xl:block ${
        visible ? "opacity-100" : "pointer-events-none opacity-0"
      }`}
    >
      <ol className="flex flex-col items-center">
        {items.map((item, i) => {
          const p = progress[i];
          const started = p > 0;
          return (
            <li key={item.id} className="flex flex-col items-center">
              {i > 0 && (
                <span
                  aria-hidden
                  className={`h-6 w-0.5 transition-colors duration-300 ${started ? "bg-brand" : "bg-border"}`}
                />
              )}
              <button
                type="button"
                onClick={() => document.getElementById(item.id)?.scrollIntoView({ block: "center" })}
                aria-label={`${String(i + 1).padStart(2, "0")} ${item.label}`}
                aria-current={started && p < 1 ? "step" : undefined}
                className={`grid h-8 w-8 cursor-pointer place-items-center rounded-full transition-colors duration-300 ${
                  started ? "bg-brand-tint" : ""
                }`}
              >
                <span
                  className={`relative block overflow-hidden rounded-full bg-border transition-all duration-300 ${
                    started ? "h-5 w-5" : "h-4 w-4"
                  }`}
                >
                  <span className="absolute inset-x-0 top-0 bg-brand" style={{ height: `${p * 100}%` }} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
