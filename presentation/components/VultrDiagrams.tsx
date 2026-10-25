// Inline SVG diagrams for the Vultr page. Animations live in globals.css.

const svg = "h-auto w-full";
const shifts = ["−2", "−1", "0", "+1", "+2"];

export function Fleet() {
  const workers = shifts.map((shift, i) => ({ shift, y: 22 + i * 48 }));

  return (
    <svg viewBox="0 0 480 280" className={svg} role="img" aria-label="The orchestrator sends five shifted replays to five Vultr workers in parallel; each worker reads the same Tiger fork">
      {workers.map((w) => (
        <g key={w.shift}>
          <path d={`M120 135 C145 135 145 ${w.y + 18} 170 ${w.y + 18}`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
          <path d={`M310 ${w.y + 18} C345 ${w.y + 18} 345 135 380 135`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
        </g>
      ))}

      <rect x={16} y={113} width={104} height={44} rx={8} className="fill-surface stroke-border" />
      <text x={68} y={133} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Orchestrator
      </text>
      <text x={68} y={148} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
        one click
      </text>

      {workers.map((w, i) => (
        <g key={w.shift}>
          <rect x={170} y={w.y} width={140} height={36} rx={8} className="fill-brand-tint stroke-brand" />
          <text x={180} y={w.y + 15} fontSize={10} fontWeight={600} className="fill-brand font-mono">
            tempo-worker-{i + 1}
          </text>
          <text x={300} y={w.y + 15} textAnchor="end" fontSize={9.5} className="fill-brand font-mono">
            {w.shift}
          </text>
          <rect x={180} y={w.y + 23} width={120} height={5} rx={2.5} className="fill-surface" />
          <rect x={180} y={w.y + 23} width={120} height={5} rx={2.5} className="lane fill-brand" style={{ animationDelay: `${i * 0.12}s` }} />
        </g>
      ))}

      <path d="M380 92 V178 A40 10 0 0 0 460 178 V92" className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <ellipse cx={420} cy={92} rx={40} ry={10} className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <text x={420} y={134} textAnchor="middle" fontSize={13} fontWeight={700} className="fill-brand font-serif">
        Tiger
      </text>
      <text x={420} y={151} textAnchor="middle" fontSize={13} fontWeight={700} className="fill-brand font-serif">
        fork
      </text>

      <text x={16} y={272} fontSize={10} className="fill-text-secondary font-mono">
        POST /replay {"{database_url, decision_id, shift}"} · Bearer token
      </text>
    </svg>
  );
}

export function Scheduler() {
  const rows = [
    { active: true, job: "shift −2" },
    { active: true, job: "shift −1" },
    { active: true, job: "shift 0" },
    { active: true, job: "shift +1" },
    { active: false, job: "" },
  ];

  return (
    <svg viewBox="0 0 480 280" className={svg} role="img" aria-label="The scheduler lists tagged instances, leases each active idle worker to one replay, skips inactive ones and queues the remaining job">
      <text x={16} y={22} fontSize={10} className="fill-brand font-mono">
        GET /v2/instances?tag=tempo-worker
      </text>
      {["instance", "status", "lease"].map((h, i) => (
        <text key={h} x={[28, 210, 318][i]} y={44} fontSize={9.5} className="fill-text-secondary font-mono">
          {h.toUpperCase()}
        </text>
      ))}

      {rows.map((row, i) => {
        const y = 52 + i * 32;
        return (
          <g key={i} opacity={row.active ? 1 : 0.6}>
            <rect x={16} y={y} width={448} height={26} rx={6} className="fill-surface stroke-border" />
            <text x={28} y={y + 17} fontSize={10.5} className="fill-accent-primary font-mono">
              tempo-worker-{i + 1}
            </text>
            <rect
              x={204}
              y={y + 5}
              width={64}
              height={16}
              rx={8}
              strokeDasharray={row.active ? undefined : "3 3"}
              className={row.active ? "fill-brand-tint stroke-brand" : "fill-none stroke-discharge"}
            />
            <text x={236} y={y + 16.5} textAnchor="middle" fontSize={9.5} className={`font-mono ${row.active ? "fill-brand" : "fill-discharge"}`}>
              {row.active ? "active" : "pending"}
            </text>
            {row.active ? (
              <g className="row-in" style={{ animationDelay: `${i * 0.4}s` }}>
                <rect x={312} y={y + 5} width={96} height={16} rx={8} className="fill-brand" />
                <text x={360} y={y + 16.5} textAnchor="middle" fontSize={9.5} className="fill-surface font-mono">
                  {row.job}
                </text>
              </g>
            ) : (
              <text x={318} y={y + 16.5} fontSize={9.5} className="fill-discharge font-mono">
                skipped
              </text>
            )}
          </g>
        );
      })}

      <rect x={16} y={218} width={150} height={26} rx={13} strokeDasharray="4 3" strokeWidth={1.5} className="soft-pulse fill-none stroke-brand" />
      <text x={91} y={235} textAnchor="middle" fontSize={10} className="fill-brand font-mono">
        shift +2 · queued
      </text>
      <text x={180} y={235} fontSize={10} className="fill-text-secondary font-mono">
        runs on the first worker released
      </text>
      <text x={16} y={270} fontSize={10} className="fill-text-secondary font-mono">
        idle = Vultr says active AND not leased in memory
      </text>
    </svg>
  );
}

export function Provisioning() {
  const workers = [0, 1, 2, 3, 4].map((i) => 16 + i * 92);

  return (
    <svg viewBox="0 0 480 300" className={svg} role="img" aria-label="A build box is bootstrapped and snapshotted; five workers are created from the snapshot in New Jersey; a separate backend box runs in London">
      <defs>
        <marker id="prov-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
          <path d="M0 0 L8 4 L0 8 Z" className="fill-brand" />
        </marker>
      </defs>

      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        build_worker_image.py
      </text>
      <rect x={16} y={32} width={124} height={48} rx={8} strokeDasharray="4 3" className="soft-pulse fill-surface stroke-border" />
      <text x={78} y={53} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Build box
      </text>
      <text x={78} y={69} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
        rsync · bootstrap
      </text>
      <path d="M140 56 H202" strokeWidth={1.5} markerEnd="url(#prov-arrow)" className="stroke-brand" />
      <text x={171} y={48} textAnchor="middle" fontSize={9} className="fill-brand font-mono">
        /health ✓
      </text>
      <rect x={206} y={32} width={124} height={48} rx={8} className="fill-brand-tint stroke-brand" />
      <text x={268} y={53} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-brand font-sans">
        Snapshot
      </text>
      <text x={268} y={69} textAnchor="middle" fontSize={9.5} className="fill-brand font-mono">
        id → .env
      </text>
      <text x={346} y={53} fontSize={9.5} className="fill-discharge font-mono">
        build box
      </text>
      <text x={346} y={67} fontSize={9.5} className="fill-discharge font-mono">
        deleted
      </text>

      <text x={16} y={184} fontSize={10} className="fill-brand font-mono">
        create_workers.py · ewr
      </text>
      {workers.map((x) => (
        <path key={`p${x}`} d={`M268 80 C268 104 ${x + 40} 104 ${x + 40} 128`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
      ))}
      {workers.map((x, i) => (
        <g key={x} className="row-in" style={{ animationDelay: `${i * 0.25}s` }}>
          <rect x={x} y={128} width={80} height={36} rx={8} className="fill-brand-tint stroke-brand" />
          <text x={x + 40} y={150} textAnchor="middle" fontSize={10} fontWeight={600} className="fill-brand font-mono">
            worker-{i + 1}
          </text>
        </g>
      ))}

      <text x={16} y={216} fontSize={10} className="fill-brand font-mono">
        create_backend.py · lhr
      </text>
      <rect x={16} y={226} width={210} height={48} rx={8} className="fill-surface stroke-border" />
      <text x={121} y={247} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        tempo-backend
      </text>
      <text x={121} y={263} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
        dashboard :8501 · poller
      </text>
      <text x={240} y={247} fontSize={9.5} className="fill-text-secondary font-mono">
        tagged tempo-backend,
      </text>
      <text x={240} y={262} fontSize={9.5} className="fill-text-secondary font-mono">
        never dispatched to
      </text>
      <text x={16} y={294} fontSize={10} className="fill-text-secondary font-mono">
        idempotent: re-running keeps existing labels
      </text>
    </svg>
  );
}

export function Gpu() {
  const steps = [
    { x: 16, label: "create", sub: "A16 · lhr" },
    { x: 126, label: "nvidia-smi ✓", sub: "driver, CUDA" },
    { x: 236, label: "torch.cuda ✓", sub: "device found" },
    { x: 346, label: "delete", sub: "$0.48 min. hour", warn: true },
  ];

  return (
    <svg viewBox="0 0 480 300" className={svg} role="img" aria-label="gpu_box.py creates one NVIDIA A16 in London, checks it and deletes it; training 500 models took 17.4 s on the GPU against 28.0 s on the CPU, 1.6 times faster, with no better forecasts, so the live system stays on CPU">
      <defs>
        <marker id="gpu-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
          <path d="M0 0 L8 4 L0 8 Z" className="fill-brand" />
        </marker>
      </defs>

      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        gpu_box.py · one NVIDIA A16, by the minute
      </text>
      {steps.map((s, i) => (
        <g key={s.label}>
          {i > 0 && <path d={`M${s.x - 12} 54 H${s.x - 2}`} strokeWidth={1.5} markerEnd="url(#gpu-arrow)" className="stroke-brand" />}
          <rect x={s.x} y={32} width={98} height={44} rx={8} className={s.warn ? "fill-surface stroke-discharge" : "fill-brand-tint stroke-brand"} />
          <text x={s.x + 49} y={51} textAnchor="middle" fontSize={10.5} fontWeight={600} className={`${s.warn ? "fill-discharge" : "fill-brand"} font-mono`}>
            {s.label}
          </text>
          <text x={s.x + 49} y={66} textAnchor="middle" fontSize={9} className={`${s.warn ? "fill-discharge" : "fill-text-secondary"} font-mono`}>
            {s.sub}
          </text>
        </g>
      ))}

      {/* The race: the same 500 LightGBM models, on the box's CPU and on its GPU. */}
      <text x={16} y={116} fontSize={10} className="fill-brand font-mono">
        train 500 models · same box, same data
      </text>
      {[
        { y: 130, name: "CPU", sub: "6 vCPU", bar: "race-cpu", tag: "race-tag-cpu", time: "28.0 s" },
        { y: 178, name: "GPU", sub: "A16 · 16 GB", bar: "race-gpu", tag: "race-tag-gpu", time: "17.4 s" },
      ].map((lane) => (
        <g key={lane.name}>
          <text x={16} y={lane.y + 17} fontSize={12} fontWeight={600} className="fill-foreground font-sans">
            {lane.name}
          </text>
          <text x={16} y={lane.y + 31} fontSize={9} className="fill-text-secondary font-mono">
            {lane.sub}
          </text>
          <rect x={96} y={lane.y + 4} width={300} height={24} rx={6} className="fill-surface stroke-border" />
          <rect x={96} y={lane.y + 4} width={300} height={24} rx={6} className={`${lane.bar} fill-brand`} />
          <text x={404} y={lane.y + 20} fontSize={11} fontWeight={600} className={`${lane.tag} fill-brand font-mono`}>
            {lane.time}
          </text>
        </g>
      ))}
      <g className="verdict-in">
        <rect x={16} y={226} width={448} height={56} rx={8} className="fill-brand-tint stroke-brand" />
        <text x={32} y={248} fontSize={13} fontWeight={700} className="fill-brand font-serif">
          1.6× faster, same forecasts.
        </text>
        <text x={32} y={267} fontSize={9.5} className="fill-brand font-mono">
          trees on tabular data don&apos;t need a GPU → the live system stays CPU-only
        </text>
      </g>
      <text x={16} y={296} fontSize={10} className="fill-text-secondary font-mono">
        three A16 boxes · about 29 box-minutes · $1.44 · deleted when idle
      </text>
    </svg>
  );
}
