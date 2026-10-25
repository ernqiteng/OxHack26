import type { Metadata } from "next";
import { Archive, GitFork, Layers, Rows3 } from "lucide-react";
import FeatureRow from "@/components/FeatureRow";
import ProgressRail from "@/components/ProgressRail";
import Reveal from "@/components/Reveal";
import { Aggregates, Compression, Fork, FreeTier, Hypertable, OneDatabase } from "@/components/TigerDiagrams";

export const metadata: Metadata = { title: "Tiger Data · Tempo" };

const features = [
  { icon: Rows3, name: "Hypertables", text: "Tables split into chunks by time, so “give me last week” stays fast." },
  { icon: Layers, name: "Continuous aggregates", text: "Summary tables that update themselves as new data arrives." },
  { icon: Archive, name: "Compression", text: "Squeezes old data to about a tenth of its size." },
  { icon: GitFork, name: "Forks", text: "A full, writable copy of the whole database, made instantly." },
];

const code = "font-mono text-[0.9em] text-brand";

const rows = [
  {
    title: "Tempo's only database",
    diagram: <OneDatabase />,
    points: [
      <>
        <code className={code}>grid_raw</code>: two years of Elexon market data, plus every new half-hour
      </>,
      <>
        <code className={code}>forecasts</code> and <code className={code}>decisions</code>: 48 rows every half
        hour
      </>,
      <>Audit results, replay scratch data and the honesty table</>,
    ],
  },
  {
    title: "Hypertables",
    diagram: <Hypertable />,
    points: [
      <>The market data and the decisions log are hypertables</>,
      <>A query for last week reads only last week&apos;s chunk</>,
      <>Every row records when it became available, so no decision sees the future</>,
    ],
  },
  {
    title: "Continuous aggregates",
    diagram: <Aggregates />,
    points: [
      <>Half-hourly, daily and weekly prices, each built on the level below</>,
      <>They feed the model&apos;s features and the dashboard charts</>,
      <>They update themselves as new prices land</>,
    ],
  },
  {
    title: "Compression",
    diagram: <Compression />,
    points: [
      <>Two years of data would be about 1.2 GB</>,
      <>The free tier caps storage at 750 MB</>,
      <>Compressed, it fits in roughly 120–250 MB</>,
    ],
  },
  {
    title: "Forks power the timing audit",
    diagram: (
      <div className="divide-y divide-border-light">
        <div className="pb-4">
          <Fork />
        </div>
        <div className="pt-4">
          <FreeTier />
        </div>
      </div>
    ),
    points: [
      <>Click a decision and Tiger forks the live database in about 40 seconds</>,
      <>Copy-on-write: only the blocks the replays change are copied</>,
      <>Five replays write into one shared fork, never into live</>,
      <>
        The free tier holds only live plus one fork, so our plan of one fork per timeline became one shared
        fork, identical to the penny
      </>,
      <>The fork is deleted afterwards; only the results are kept</>,
    ],
  },
];

export default function TigerData() {
  return (
    <main>
      <section className="mx-auto max-w-6xl px-4 pt-32 pb-24 sm:px-6">
        <Reveal>
          <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">Tiger Data</p>
          <h1 className="mt-4 text-[2.5rem] leading-[1.05] font-bold tracking-tight sm:text-[3.75rem]">
            Postgres, built for time.
          </h1>
          <p className="mt-6 max-w-xl font-sans text-lg leading-relaxed text-text-secondary">
            Tiger Data (formerly Timescale) is PostgreSQL in the cloud, extended with TimescaleDB for time-series
            data: rows stamped with a time that never stop arriving. A new electricity price every half hour is
            exactly that shape.
          </p>
        </Reveal>
        <Reveal className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {features.map(({ icon: Icon, name, text }) => (
            <div key={name} className="rounded-xl border border-border-light bg-surface p-6">
              <Icon className="h-6 w-6 text-brand" strokeWidth={1.75} aria-hidden />
              <p className="mt-4 font-sans font-semibold">{name}</p>
              <p className="mt-2 font-sans text-sm leading-relaxed text-text-secondary">{text}</p>
            </div>
          ))}
        </Reveal>
      </section>

      <section id="uses" className="border-t border-border-light bg-surface-elevated">
        <ProgressRail sectionId="uses" items={rows.map((row, i) => ({ id: `point-${i + 1}`, label: row.title }))} />
        <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
          <Reveal>
            <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">In Tempo</p>
            <h2 className="mt-4 text-[1.875rem] leading-tight font-bold tracking-tight sm:text-[2.25rem]">
              How Tempo uses Tiger Data
            </h2>
          </Reveal>
          <div className="mt-16 space-y-24">
            {rows.map((row, i) => (
              <FeatureRow
                key={row.title}
                id={`point-${i + 1}`}
                number={String(i + 1).padStart(2, "0")}
                title={row.title}
                points={row.points}
                diagram={row.diagram}
                reverse={i % 2 === 1}
              />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
