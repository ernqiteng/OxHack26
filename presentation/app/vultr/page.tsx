import type { Metadata } from "next";
import { Camera, Server, Tag, Terminal } from "lucide-react";
import FeatureRow from "@/components/FeatureRow";
import ProgressRail from "@/components/ProgressRail";
import Reveal from "@/components/Reveal";
import { Fleet, Provisioning, Scheduler } from "@/components/VultrDiagrams";

export const metadata: Metadata = { title: "Vultr · Tempo" };

const features = [
  { icon: Server, name: "Cloud compute", text: "vc2 instances: 1 vCPU workers in New Jersey, a 2 GB backend in London." },
  { icon: Camera, name: "Snapshots", text: "One bootstrapped image, cloned into every worker." },
  { icon: Tag, name: "Instance tags", text: "tempo-worker marks the pool; anything untagged is never dispatched to." },
  { icon: Terminal, name: "v2 API", text: "Create, list, lease and tear down the fleet from Python." },
];

const code = "font-mono text-[0.9em] text-brand";

const rows = [
  {
    title: "Five workers replay in parallel",
    diagram: <Fleet />,
    points: [
      <>
        Five <code className={code}>vc2-1c-1gb</code> instances in <code className={code}>ewr</code>, beside
        Tiger&apos;s us-east-1
      </>,
      <>Pre-warmed all day: a cold boot takes ~40 s to active and ~80 s to SSH, too slow for a click</>,
      <>One click takes one Tiger zero-copy fork and sends five shifted timelines to five workers at once</>,
      <>
        Each worker is a stateless FastAPI app under systemd: <code className={code}>POST /replay</code> returns
        the P&amp;L, <code className={code}>GET /health</code> reports liveness
      </>,
      <>
        A shared bearer token guards <code className={code}>/replay</code>, so no one can aim a public worker at
        their own database
      </>,
    ],
  },
  {
    title: "Lease-based scheduling",
    diagram: <Scheduler />,
    points: [
      <>
        <code className={code}>VultrClient</code> lists instances tagged <code className={code}>tempo-worker</code>{" "}
        over the v2 API, following cursor pagination
      </>,
      <>Idle means Vultr reports active and no job holds a lease</>,
      <>
        <code className={code}>lease()</code> → <code className={code}>mark_busy()</code> →{" "}
        <code className={code}>mark_idle()</code>: one job per worker, always released
      </>,
      <>When every worker is busy, jobs queue, so five timelines still finish on three workers</>,
      <>Without Vultr credentials it falls back to the same worker app in-process, labelled local-1..n</>,
    ],
  },
  {
    title: "Snapshot to fleet in one command",
    diagram: <Provisioning />,
    points: [
      <>
        <code className={code}>build_worker_image.py</code>: rsync the repo, bootstrap, verify{" "}
        <code className={code}>/health</code> and the token, snapshot, delete the build box
      </>,
      <>
        <code className={code}>create_workers.py</code>: clone five workers from the snapshot; idempotent, with{" "}
        <code className={code}>--count</code>, <code className={code}>--status</code> and{" "}
        <code className={code}>--delete</code>
      </>,
      <>
        <code className={code}>create_backend.py</code>: a separate <code className={code}>lhr</code> box running
        the dashboard and the poller, never tagged as a worker
      </>,
      <>
        <code className={code}>time_vultr.py</code> benchmarks create → active → SSH-ready
      </>,
      <>Snapshot ID, SSH key and worker token are written straight into .env</>,
    ],
  },
];

export default function Vultr() {
  return (
    <main>
      <section className="mx-auto max-w-6xl px-4 pt-32 pb-24 sm:px-6">
        <Reveal>
          <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">Vultr</p>
          <h1 className="mt-4 text-[2.5rem] leading-[1.05] font-bold tracking-tight sm:text-[3.75rem]">
            The compute layer.
          </h1>
          <p className="mt-6 max-w-xl font-sans text-lg leading-relaxed text-text-secondary">
            Tiger supplies the data forks; Vultr supplies the machines that replay against them. Five pre-warmed
            workers turn one click into five parallel timelines, and a London box keeps Tempo running live.
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
              How Tempo uses Vultr
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
