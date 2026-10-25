"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LiveBadge } from "@/components/LiveBadge";
import { chapterIndex, chapters } from "@/lib/chapters";

// The logo leaves this site for the presentation site: "/" on the box (this site lives at /app/), its dev server
// locally. A plain <a>, since next/link would prefix the base path and land on this site's own Hook chapter.
const PRESENTATION_URL =
  process.env.NEXT_PUBLIC_PRESENTATION_URL ?? (process.env.NEXT_PUBLIC_BASE_PATH ? "/" : "http://localhost:3000");

export function Nav() {
  const active = chapterIndex(usePathname());

  return (
    <header className="sticky top-0 z-20 border-b border-rule bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-4 sm:px-10">
        <a href={PRESENTATION_URL} className="flex items-center gap-5" aria-label="Back to the Tempo presentation">
          <span className="flex h-10 w-10 items-center justify-center bg-brand font-serif text-xl font-bold text-paper">t</span>
          <span className="font-serif text-xl font-bold">Tempo</span>
        </a>
        <nav className="hidden gap-10 lg:flex">
          {chapters.slice(1).map((c, i) => (
            <Link
              key={c.id}
              href={c.href}
              className={`border-b-2 py-1 text-sm font-medium uppercase tracking-[0.18em] transition-colors ${
                i + 1 === active ? "border-brand text-ink" : "border-transparent text-body hover:text-ink"
              }`}
            >
              {c.title}
            </Link>
          ))}
        </nav>
        <div className="flex min-w-40 justify-end">
          <LiveBadge />
        </div>
      </div>
    </header>
  );
}
