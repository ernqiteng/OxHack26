import { ArrowDown, ArrowUpRight, BatteryCharging, LineChart, ShieldCheck } from "lucide-react";
import Link from "next/link";
import FeatureRow from "@/components/FeatureRow";
import HeroBackground from "@/components/HeroBackground";
import { Audit, DayInMarket, Forecast, Ingest, Optimiser, PointInTime, Results } from "@/components/PitchDiagrams";
import ProgressRail from "@/components/ProgressRail";
import Reveal from "@/components/Reveal";

const facts = [
  { name: "48 prices a day", text: "Every half-hour settles at its own price, sometimes below zero." },
  { name: "2 MWh · 1 MW · 90%", text: "Real limits: capacity, power, and about 10% lost on every round trip." },
  { name: "Hold is a decision", text: "When the spread doesn't cover the losses, Tempo waits and says why." },
  { name: "Built to be checked", text: "No look-ahead, honest baselines, and every decision can be replayed." },
];

const jobs = [
  {
    icon: LineChart,
    name: "Forecast",
    text: "Predict the next 24 hours of prices as a range, not a single guess.",
  },
  {
    icon: BatteryCharging,
    name: "Decide",
    text: "Charge, sell or hold, only when the spread beats the losses. Every choice comes with a reason.",
  },
  {
    icon: ShieldCheck,
    name: "Prove",
    text: "Replay any decision earlier and later to show, in pounds, whether the timing was right.",
  },
];

const stats = [
  { value: "66%", label: "of perfect-foresight profit" },
  { value: "2×", label: "the fixed-hours baseline" },
  { value: "100", label: "unseen test weeks" },
  { value: "30 min", label: "between live decisions" },
];

const pipeline = [
  { name: "Elexon", sub: "6 datasets, polled" },
  { name: "Tiger Data", sub: "hypertables" },
  { name: "Features", sub: "point-in-time" },
  { name: "LightGBM", sub: "p10 · p50 · p90" },
  { name: "Optimiser", sub: "charge · sell · hold" },
  { name: "Audit", sub: "Tiger fork + Vultr" },
];

// The pitch dashboard (pitch/), served next to this site at /app/ on the tempo-backend Vultr box (lhr).
// Override at build time with NEXT_PUBLIC_APP_URL, e.g. http://localhost:3001 when running both locally.
const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "/app/";

// Stagger delay for the intro's rise-in (globals.css, html[data-intro="in"] .intro-rise).
const rise = (ms: number) => ({ "--rise-delay": `${ms}ms` }) as React.CSSProperties;

const code = "font-mono text-[0.9em] text-brand";
const link = "font-semibold text-brand underline decoration-brand/30 underline-offset-4 hover:decoration-brand";

const rows = [
  {
    title: "Live ingest: Elexon → Tiger Data",
    diagram: <Ingest />,
    points: [
      <>Six Elexon datasets: prices, wind and demand forecasts, generation mix</>,
      <>A metadata-driven poller fetches only datasets that changed</>,
      <>
        Every row stamped with <code className={code}>available_at</code>: when Tempo could first have seen it
      </>,
      <>
        Stored in{" "}
        <Link href="/tiger-data/" className={link}>
          Tiger Data
        </Link>{" "}
        hypertables, rolled up by continuous aggregates
      </>,
    ],
  },
  {
    title: "Point-in-time features, zero leakage",
    diagram: <PointInTime />,
    points: [
      <>
        Features use only rows with <code className={code}>available_at ≤ decision_time</code>
      </>,
      <>Price lags, rolling spreads, wind and demand forecasts, UK calendar</>,
      <>
        Each filter is tagged <code className={code}>-- pit</code>; a test removes each one and must fail
      </>,
    ],
  },
  {
    title: "Quantile forecast: p10 · p50 · p90",
    diagram: <Forecast />,
    points: [
      <>Three LightGBM quantile models predict the next 48 half-hourly prices</>,
      <>The band shows uncertainty, not just a best guess</>,
      <>Deterministic training: same rows, same model</>,
      <>
        Re-run every 30 min on a{" "}
        <Link href="/vultr/" className={link}>
          Vultr
        </Link>{" "}
        box in London
      </>,
    ],
  },
  {
    title: "Cost-gated battery optimiser",
    diagram: <Optimiser />,
    points: [
      <>Greedy pairing: cheapest buy period with the dearest later sell</>,
      <>LP alternative (cvxpy) over all 48 periods with full battery physics</>,
      <>Trades only when the spread beats round-trip loss plus wear</>,
      <>Hold is a decision too: every row logs its reason</>,
    ],
  },
  {
    title: "Timing audit: one fork, five replays",
    diagram: <Audit />,
    points: [
      <>Click any decision; Tempo replays it 1 h early to 1 h late</>,
      <>One Tiger zero-copy fork, five timelines on five Vultr workers in parallel</>,
      <>Shows in pounds what rushing or hesitating would have cost</>,
      <>The fork is deleted afterwards; only the results are kept</>,
    ],
  },
  {
    title: "Walk-forward backtest: 66% of perfect",
    diagram: <Results />,
    points: [
      <>Retrained every week, tested only on weeks it never saw</>,
      <>£58,711 earned vs £29,265 for a fixed-hours rule: 2× the baseline</>,
      <>Scored against perfect foresight on the same weeks</>,
    ],
  },
];

export default function Home() {
  return (
    <main>
      <section id="about" className="scroll-mt-16">
        <div className="relative overflow-hidden">
          <div className="intro-grid absolute inset-0">
            <HeroBackground />
          </div>
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pt-32 pb-24 sm:px-6 lg:grid-cols-2 lg:gap-16">
            <div>
              <p className="intro-rise font-mono text-xs tracking-[0.2em] text-text-secondary uppercase" style={rise(60)}>
                About
              </p>
              <h2
                className="intro-rise mt-4 text-[1.875rem] leading-tight font-bold tracking-tight sm:text-[2.25rem]"
                style={rise(60)}
              >
                A battery trader that shows its working.
              </h2>
              <div className="intro-rise" style={rise(120)}>
                <p className="mt-6 font-sans text-lg leading-relaxed text-text-secondary">
                  Great Britain prices electricity in 48 half-hour blocks a day. Prices crash overnight when the
                  wind blows and spike at 6pm when everyone gets home. A grid battery profits from that gap, but
                  only if it buys and sells at the right moments.
                </p>
                <p className="mt-4 font-sans text-lg leading-relaxed text-text-secondary">
                  Tempo makes that call every half hour, explains each one, and lets anyone check the timing
                  afterwards.
                </p>
              </div>
              <div
                className="intro-rise mt-8 flex flex-col gap-3 font-sans font-semibold sm:flex-row"
                style={rise(180)}
              >
                <Link
                  href="/#how-it-works"
                  className="inline-flex items-center justify-center gap-2 rounded-lg border border-brand bg-background px-6 py-3 text-brand transition-colors hover:bg-brand-tint"
                >
                  See how it works
                  <ArrowDown className="h-4 w-4" aria-hidden />
                </Link>
                <a
                  href={APP_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand px-6 py-3 text-white transition-opacity hover:opacity-90"
                >
                  Open the app
                  <ArrowUpRight className="h-4 w-4" aria-hidden />
                </a>
              </div>
            </div>
            <div className="intro-rise grid gap-4 sm:grid-cols-2" style={rise(240)}>
              {facts.map((fact) => (
                <div key={fact.name} className="rounded-xl border border-border-light bg-surface p-6">
                  <p className="font-mono text-sm font-semibold text-brand">{fact.name}</p>
                  <p className="mt-2 font-sans text-sm leading-relaxed text-text-secondary">{fact.text}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-24 sm:px-6 lg:grid-cols-2 lg:gap-16">
          <Reveal className="overflow-hidden rounded-xl border border-border-light bg-surface p-4 shadow-sm sm:p-6">
            <DayInMarket />
          </Reveal>
          <Reveal>
            <h3 className="text-2xl font-bold tracking-tight sm:text-3xl">Three jobs, every half hour</h3>
            <ul className="mt-6 space-y-6">
              {jobs.map(({ icon: Icon, name, text }) => (
                <li key={name} className="flex gap-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-tint">
                    <Icon className="h-5 w-5 text-brand" strokeWidth={1.75} aria-hidden />
                  </span>
                  <div>
                    <p className="font-sans font-semibold">{name}</p>
                    <p className="mt-1 font-sans leading-relaxed text-text-secondary">{text}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Reveal>
        </div>

        <div className="border-t border-border-light">
          <Reveal className="mx-auto grid max-w-6xl grid-cols-2 gap-px px-4 py-16 sm:px-6 lg:grid-cols-4">
            {stats.map((stat) => (
              <div key={stat.label} className="px-2 py-4 text-center">
                <p className="text-[2.25rem] leading-none font-bold tracking-tight text-brand sm:text-[2.75rem]">
                  {stat.value}
                </p>
                <p className="mt-3 font-sans text-sm text-text-secondary">{stat.label}</p>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-16 border-t border-border-light bg-surface-elevated">
        <ProgressRail sectionId="how-it-works" items={rows.map((row, i) => ({ id: `point-${i + 1}`, label: row.title }))} />
        <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
          <Reveal>
            <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">How it works</p>
            <h2 className="mt-4 text-[1.875rem] leading-tight font-bold tracking-tight sm:text-[2.25rem]">
              Grid data in, a proven decision out, every 30 minutes.
            </h2>
          </Reveal>
          <Reveal className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {pipeline.map((step, i) => (
              <div key={step.name} className="relative rounded-xl border border-border-light bg-surface p-4">
                <span
                  className="soft-pulse absolute top-4 right-4 h-2 w-2 rounded-full bg-brand"
                  style={{ animationDelay: `${i * 0.4}s` }}
                  aria-hidden
                />
                <p className="font-mono text-xs text-text-secondary">{String(i + 1).padStart(2, "0")}</p>
                <p className="mt-2 font-sans font-semibold">{step.name}</p>
                <p className="mt-1 font-mono text-xs text-brand">{step.sub}</p>
              </div>
            ))}
          </Reveal>
          <div className="mt-24 space-y-24">
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
