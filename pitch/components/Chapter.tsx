import Link from "next/link";
import { Reveal } from "@/components/Reveal";
import { chapters, type ChapterId } from "@/lib/chapters";

// One chapter page: the chart card fills the screen, with previous / next links underneath.
// Until a chapter is confirmed with Ayo, its words sit in a strip above the chart; once confirmed they move
// to docs/demox.md and the page gets `full` (chart only).
export function Chapter({ id, full = false, children }: { id: ChapterId; full?: boolean; children?: React.ReactNode }) {
  const i = chapters.findIndex((c) => c.id === id);
  const c = chapters[i];
  const prev = chapters[i - 1];
  const next = chapters[i + 1];

  return (
    <main className="mx-auto flex h-[calc(100dvh-5rem-1px)] max-w-[1600px] flex-col px-4 sm:px-10 xl:pr-20">
      {!full && (
        <Reveal className="grid shrink-0 items-end gap-x-12 gap-y-3 pt-6 lg:grid-cols-[3fr_2fr]">
          <div>
            <p className="font-mono text-xs font-medium uppercase tracking-[0.25em] text-body">{c.eyebrow} · draft</p>
            <h1 className="mt-2 font-serif text-3xl font-bold leading-tight">{c.headline}</h1>
          </div>
          <p className="text-base leading-relaxed text-body">{c.body}</p>
        </Reveal>
      )}
      <Reveal delay={full ? 0 : 0.15} className="min-h-0 flex-1 py-6">
        {children ?? (
          <div className="card-grid flex h-full items-center justify-center rounded-2xl border border-rule shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
            <span className="font-mono text-xs uppercase tracking-[0.2em] text-faint">chart · {c.title}</span>
          </div>
        )}
      </Reveal>
      <footer className="flex shrink-0 justify-between border-t border-rule py-4 font-mono text-xs uppercase tracking-[0.2em] text-body">
        {prev ? <Link href={prev.href} className="hover:text-ink">← {prev.title}</Link> : <span />}
        {next ? <Link href={next.href} className="hover:text-ink">{next.title} →</Link> : <span />}
      </footer>
    </main>
  );
}
