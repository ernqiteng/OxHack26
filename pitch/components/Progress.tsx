"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { chapterIndex, chapters } from "@/lib/chapters";

// Vertical chapter dots on the right, filled up to the current page. ← / → go to the previous / next chapter.
// A chapter with steps calls preventDefault on → until its last step, so the page only changes after that.
export function Progress() {
  const router = useRouter();
  const active = chapterIndex(usePathname());

  useEffect(() => {
    chapters.forEach((c) => router.prefetch(c.href));
  }, [router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.target instanceof HTMLInputElement) return;
      const step = e.key === "ArrowRight" || e.key === "PageDown" ? 1 : e.key === "ArrowLeft" || e.key === "PageUp" ? -1 : 0;
      const next = active + step;
      if (!step || next < 0 || next >= chapters.length) return;
      e.preventDefault();
      router.push(chapters[next].href);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, router]);

  return (
    <ol className="fixed right-6 top-1/2 z-10 hidden -translate-y-1/2 flex-col items-center xl:flex">
      {chapters.map((c, i) => (
        <li key={c.id} className="flex flex-col items-center">
          {i > 0 && <span className={`h-6 w-px ${i <= active ? "bg-brand" : "border-l border-dashed border-rule"}`} />}
          <Link
            href={c.href}
            aria-label={c.title}
            className={`rounded-full transition-all ${i <= active ? "h-7 w-7 bg-brand ring-4 ring-glow" : "h-4 w-4 bg-rule hover:bg-faint"}`}
          />
        </li>
      ))}
    </ol>
  );
}
