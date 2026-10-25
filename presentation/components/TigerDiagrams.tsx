// Inline SVG diagrams for the Tiger Data page. Animations live in globals.css.

const svg = "h-auto w-full";

export function OneDatabase() {
  const sources = [
    { y: 40, label: "Elexon API" },
    { y: 120, label: "Decision engine" },
    { y: 200, label: "Timing audit" },
  ];
  const tables = [
    { y: 64, names: ["grid_raw"] },
    { y: 135, names: ["forecasts", "decisions"] },
    { y: 206, names: ["audits", "battery_state", "backtest_results"] },
  ];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="Market data, the decision engine and the timing audit all write to one Tiger Data database">
      {sources.map((s) => (
        <g key={s.label}>
          <rect x={12} y={s.y} width={124} height={40} rx={8} className="fill-surface stroke-border" />
          <text x={74} y={s.y + 24} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
            {s.label}
          </text>
          <path d={`M136 ${s.y + 20} H196`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
          <path d={`M284 ${s.y + 20} H312`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
        </g>
      ))}

      <path d="M196 50 V226 A44 12 0 0 0 284 226 V50" className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <ellipse cx={240} cy={50} rx={44} ry={12} className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <text x={240} y={134} textAnchor="middle" fontSize={15} fontWeight={700} className="fill-brand font-serif">
        Tiger
      </text>
      <text x={240} y={153} textAnchor="middle" fontSize={15} fontWeight={700} className="fill-brand font-serif">
        Data
      </text>

      {tables.map((t) =>
        t.names.map((name, i) => (
          <text key={name} x={320} y={t.y + i * 18} fontSize={11} className="fill-accent-primary font-mono">
            {name}
          </text>
        )),
      )}
    </svg>
  );
}

export function Hypertable() {
  const labels = ["w−5", "w−4", "w−3", "w−2", "w−1", "this week"];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="A hypertable split into weekly chunks; a query for the last week reads only the newest chunk">
      <text x={24} y={28} fontSize={11} className="fill-text-secondary font-mono">
        grid_raw · hypertable
      </text>
      <text x={452} y={28} textAnchor="end" fontSize={10} className="fill-brand font-mono">
        WHERE time &gt; now() − 7 days
      </text>

      {labels.map((label, i) => {
        const x = 24 + i * 72;
        const latest = i === labels.length - 1;
        return (
          <g key={label} opacity={latest ? 1 : 0.55}>
            <rect
              x={x}
              y={50}
              width={62}
              height={140}
              rx={6}
              className={latest ? "fill-brand-tint stroke-brand" : "fill-surface-sunken stroke-border"}
            />
            {Array.from({ length: 6 }, (_, j) => (
              <rect
                key={j}
                x={x + 8}
                y={64 + j * 20}
                width={46}
                height={8}
                rx={2}
                className={`${latest ? "fill-brand" : "fill-border"} ${latest && j >= 4 ? "row-in" : ""}`}
                style={latest && j >= 4 ? { animationDelay: `${(j - 4) * 0.5}s` } : undefined}
                fillOpacity={latest ? 0.55 : 1}
              />
            ))}
            <text x={x + 31} y={212} textAnchor="middle" fontSize={10} className="fill-text-secondary font-mono">
              {label}
            </text>
          </g>
        );
      })}

      <rect x={378} y={44} width={74} height={152} rx={9} strokeDasharray="4 4" strokeWidth={1.5} className="soft-pulse fill-none stroke-brand" />

      <path d="M24 234 H436" strokeWidth={1} className="stroke-border" />
      <path d="M430 229 L438 234 L430 239" strokeWidth={1} className="fill-none stroke-border" />
      <text x={444} y={238} fontSize={10} className="fill-text-secondary font-mono">
        time
      </text>
      <text x={24} y={260} fontSize={10} className="fill-text-secondary font-mono">
        older chunks are skipped
      </text>
    </svg>
  );
}

export function Aggregates() {
  const levels = [
    { name: "grid_raw", sub: "raw rows", bars: 16, refresh: "" },
    { name: "prices_hh", sub: "per half-hour", bars: 10, refresh: "every 5 min" },
    { name: "prices_daily", sub: "per UK day", bars: 6, refresh: "every 30 min" },
    { name: "prices_weekly", sub: "per UK week", bars: 3, refresh: "every hour" },
  ];

  return (
    <svg viewBox="0 0 480 260" className={svg} role="img" aria-label="Raw prices roll up into half-hourly, daily and weekly views that feed the model and the dashboard">
      <defs>
        <marker id="agg-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto">
          <path d="M0 0 L8 4 L0 8 Z" className="fill-brand" />
        </marker>
      </defs>

      {levels.map((level, i) => {
        const x = 8 + i * 120;
        const raw = i === 0;
        const gap = 2;
        const barW = (88 - gap * (level.bars - 1)) / level.bars;
        return (
          <g key={level.name}>
            <rect x={x} y={24} width={104} height={118} rx={8} className={raw ? "fill-surface-sunken stroke-border" : "fill-brand-tint stroke-brand"} />
            <text x={x + 52} y={44} textAnchor="middle" fontSize={11} fontWeight={600} className={`font-mono ${raw ? "fill-accent-primary" : "fill-brand"}`}>
              {level.name}
            </text>
            {Array.from({ length: level.bars }, (_, k) => {
              const h = 12 + 26 * Math.abs(Math.sin(k * 1.7 + i * 0.9));
              return (
                <rect
                  key={k}
                  x={x + 8 + k * (barW + gap)}
                  y={104 - h}
                  width={barW}
                  height={h}
                  rx={1}
                  className={raw ? "fill-text-secondary" : "fill-brand"}
                  fillOpacity={raw ? 0.4 : 0.8}
                />
              );
            })}
            <text x={x + 52} y={126} textAnchor="middle" fontSize={10} className="fill-text-secondary font-sans">
              {level.sub}
            </text>
            {i > 0 && (
              <>
                <path d={`M${x - 16} 83 H${x - 2}`} strokeWidth={1.5} markerEnd="url(#agg-arrow)" className="stroke-brand" />
                <circle cx={x + 10} cy={157} r={3} className="soft-pulse fill-brand" style={{ animationDelay: `${i * 0.4}s` }} />
                <text x={x + 18} y={160} fontSize={9.5} className="fill-brand font-mono">
                  {level.refresh}
                </text>
              </>
            )}
          </g>
        );
      })}

      <path d="M180 172 V182 H420 V172 M300 182 V196 M190 196 H350 M190 196 V210 M350 196 V210" strokeWidth={1.5} className="fill-none stroke-brand" />
      {[
        { x: 120, label: "Model features" },
        { x: 280, label: "Dashboard charts" },
      ].map((out) => (
        <g key={out.label}>
          <rect x={out.x} y={210} width={140} height={36} rx={8} className="fill-surface stroke-border" />
          <text x={out.x + 70} y={232} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
            {out.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function Compression() {
  const x0 = 108;
  const scale = 0.3; // px per MB
  const cap = x0 + 750 * scale;

  return (
    <svg viewBox="0 0 480 220" className={svg} role="img" aria-label="Two years of data is 1.2 GB raw, over the 750 MB free-tier cap; compressed it is about 120 to 250 MB">
      <text x={96} y={72} textAnchor="end" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Raw
      </text>
      <rect x={x0} y={50} width={1200 * scale} height={34} rx={4} className="fill-border" />
      <rect x={cap} y={50} width={x0 + 1200 * scale - cap} height={34} className="fill-discharge" fillOpacity={0.25} />
      <text x={x0 + 1200 * scale - 8} y={72} textAnchor="end" fontSize={11} fontWeight={600} className="fill-accent-primary font-mono">
        1.2 GB
      </text>

      <text x={96} y={142} textAnchor="end" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Compressed
      </text>
      <rect x={x0} y={120} width={250 * scale} height={34} rx={4} className="squeeze fill-brand" />
      <text x={x0 + 250 * scale + 8} y={142} fontSize={11} fontWeight={600} className="squeeze-label fill-brand font-mono">
        ≈120–250 MB
      </text>

      <path d={`M${cap} 36 V170`} strokeWidth={1.5} strokeDasharray="4 4" className="stroke-discharge" />
      <text x={cap} y={188} textAnchor="middle" fontSize={10} className="fill-discharge font-mono">
        750 MB free-tier cap
      </text>
      <text x={x0} y={212} fontSize={10} className="fill-text-secondary font-mono">
        about a tenth of the size
      </text>
    </svg>
  );
}

export function Fork() {
  const blocks = [0, 1, 2, 3].map((i) => 200 + i * 66);

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="A fork shares the primary's data blocks and copies only the blocks it writes to">
      <text x={326} y={28} textAnchor="middle" fontSize={10} className="fill-text-secondary font-mono">
        shared blocks, stored once
      </text>

      {blocks.map((x) => (
        <path key={`p${x}`} d={`M136 58 L${x + 27} 112`} strokeWidth={1} className="stroke-text-secondary" strokeOpacity={0.5} />
      ))}
      <rect x={16} y={36} width={120} height={44} rx={8} className="fill-surface stroke-border" />
      <text x={76} y={62} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Primary (live)
      </text>

      {blocks.map((x, i) => (
        <g key={`b${x}`}>
          <rect x={x} y={112} width={54} height={40} rx={6} className="fill-surface-sunken stroke-border" />
          <text x={x + 27} y={136} textAnchor="middle" fontSize={10} className="fill-accent-primary font-mono">
            block {i + 1}
          </text>
        </g>
      ))}

      <g className="cow-fork">
        {blocks.map((x, i) =>
          i === 2 ? null : (
            <path key={`f${x}`} d={`M136 208 L${x + 27} 152`} strokeWidth={1.5} className="stroke-brand" />
          ),
        )}
        <rect x={16} y={186} width={120} height={44} rx={8} className="fill-brand-tint stroke-brand" />
        <text x={76} y={205} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-brand font-sans">
          Fork
        </text>
        <text x={76} y={221} textAnchor="middle" fontSize={9.5} className="fill-brand font-mono">
          ready in ~40 s
        </text>
      </g>

      <path d={`M136 208 L${blocks[2] + 27} 152`} strokeWidth={1.5} className="cow-shared stroke-brand" opacity={0} />

      <g className="cow-copy">
        <path d={`M136 216 L${blocks[2]} 226`} strokeWidth={1.5} className="stroke-brand" />
        <rect x={blocks[2]} y={206} width={54} height={40} rx={6} className="fill-brand stroke-brand" />
        <text x={blocks[2] + 27} y={230} textAnchor="middle" fontSize={10} className="fill-surface font-mono">
          block 3′
        </text>
        <text x={blocks[2] + 27} y={264} textAnchor="middle" fontSize={10} className="fill-brand font-mono">
          only changed blocks are copied
        </text>
      </g>
    </svg>
  );
}

export function FreeTier() {
  const shifts = ["−2", "−1", "0", "+1", "+2"];

  return (
    <svg viewBox="0 0 480 260" className={svg} role="img" aria-label="Planned: five forks, refused after the first. Now: one shared fork holding all five timelines">
      <text x={16} y={24} fontSize={10} className="fill-text-secondary font-mono">
        PLANNED · ONE FORK PER TIMELINE
      </text>
      <rect x={16} y={36} width={84} height={44} rx={8} className="fill-surface stroke-border" />
      <text x={58} y={62} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Primary
      </text>
      {shifts.map((_, i) => {
        const x = 112 + i * 72;
        const ok = i === 0;
        return (
          <g key={i}>
            <rect
              x={x}
              y={36}
              width={62}
              height={44}
              rx={8}
              strokeDasharray={ok ? undefined : "4 3"}
              className={ok ? "fill-brand-tint stroke-brand" : "fill-none stroke-discharge"}
            />
            <text x={x + 31} y={62} textAnchor="middle" fontSize={11} fontWeight={600} className={`font-sans ${ok ? "fill-brand" : "fill-discharge"}`} fillOpacity={ok ? 1 : 0.7}>
              Fork {i + 1}
            </text>
            {!ok && <path d={`M${x + 8} 44 L${x + 54} 72`} strokeWidth={1} className="stroke-discharge" strokeOpacity={0.5} />}
          </g>
        );
      })}
      <text x={323} y={100} textAnchor="middle" fontSize={10} className="fill-discharge font-mono">
        403 · free service limit
      </text>

      <text x={16} y={140} fontSize={10} className="fill-text-secondary font-mono">
        NOW · ONE SHARED FORK
      </text>
      <rect x={16} y={152} width={84} height={96} rx={8} className="fill-surface stroke-border" />
      <text x={58} y={198} textAnchor="middle" fontSize={12} fontWeight={600} className="fill-foreground font-sans">
        Primary
      </text>
      <text x={58} y={214} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
        untouched
      </text>
      <rect x={112} y={152} width={350} height={96} rx={8} className="fill-brand-tint stroke-brand" />
      <text x={124} y={170} fontSize={10} fontWeight={600} className="fill-brand font-mono">
        Fork · 5 timelines in parallel
      </text>
      {shifts.map((shift, i) => {
        const y = 180 + i * 13;
        return (
          <g key={shift}>
            <text x={144} y={y + 7} textAnchor="end" fontSize={9} className="fill-brand font-mono">
              {shift}
            </text>
            <rect x={152} y={y} width={296} height={7} rx={3} className="fill-surface" />
            <rect x={152} y={y} width={296} height={7} rx={3} className="lane fill-brand" style={{ animationDelay: `${i * 0.05}s` }} />
          </g>
        );
      })}
    </svg>
  );
}
