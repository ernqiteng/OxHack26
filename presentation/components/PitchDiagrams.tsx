// Inline SVG diagrams for the home page pipeline. Animations live in globals.css.

const svg = "h-auto w-full";

// A typical GB day from midnight: overnight trough, morning bump, evening peak. Illustrative shape only.
const price = (h: number) =>
  55 + 45 * Math.exp(-((h - 18) ** 2) / 5) + 15 * Math.exp(-((h - 8) ** 2) / 4) - 20 * Math.exp(-((h - 3.5) ** 2) / 5);
const py = (p: number) => 210 - (p - 20) * 1.6;

export function DayInMarket() {
  const hx = (h: number) => 44 + (h / 24) * 412;
  const curve = Array.from({ length: 49 }, (_, k) => `${k ? "L" : "M"}${hx(k / 2).toFixed(1)} ${py(price(k / 2)).toFixed(1)}`).join(" ");
  const low = py(price(3.5));
  const high = py(price(18));

  return (
    <svg viewBox="0 0 480 260" className={svg} role="img" aria-label="A day of GB electricity prices: cheap overnight, expensive at the evening peak; the battery charges in the trough and sells at the peak">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        one day · 48 half-hourly prices
      </text>
      <rect x={hx(2)} y={36} width={hx(5) - hx(2)} height={178} className="soft-pulse fill-brand-tint" />
      <rect x={hx(17)} y={36} width={hx(19.5) - hx(17)} height={178} className="soft-pulse fill-discharge" fillOpacity={0.1} style={{ animationDelay: "1.2s" }} />
      <text x={(hx(2) + hx(5)) / 2} y={50} textAnchor="middle" fontSize={10} fontWeight={600} className="fill-brand font-mono">
        charge
      </text>
      <text x={(hx(17) + hx(19.5)) / 2} y={50} textAnchor="middle" fontSize={10} fontWeight={600} className="fill-discharge font-mono">
        sell
      </text>

      <path d="M44 214 H456" strokeWidth={1} className="stroke-border" />
      <path d={curve} pathLength={1} strokeWidth={2} className="draw fill-none stroke-brand" />

      <path d={`M${hx(3.5)} ${low} H${hx(14)} M${hx(18)} ${high} H${hx(14)}`} strokeWidth={1} strokeDasharray="3 3" className="band-in stroke-text-secondary" />
      <path d={`M${hx(14)} ${low - 4} V${high + 4}`} strokeWidth={1.5} className="band-in stroke-accent-primary" />
      <path d={`M${hx(14) - 4} ${high + 9} L${hx(14)} ${high + 3} L${hx(14) + 4} ${high + 9}`} strokeWidth={1.5} className="band-in fill-none stroke-accent-primary" />
      <text x={hx(14) - 8} y={(low + high) / 2 + 4} textAnchor="end" fontSize={10} fontWeight={600} className="band-in fill-accent-primary font-mono">
        spread
      </text>

      {["00:00", "06:00", "12:00", "18:00", "24:00"].map((label, i) => (
        <text key={label} x={hx(i * 6)} y={232} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
          {label}
        </text>
      ))}
      <text x={16} y={254} fontSize={10} className="fill-text-secondary font-mono">
        profit = spread − round-trip loss − wear · illustrative day
      </text>
    </svg>
  );
}

export function Ingest() {
  const datasets = ["MID", "WINDFOR", "NDF", "INDO", "FUELHH", "DISEBSP"];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="Six Elexon datasets are polled and upserted into Tiger Data, each row stamped with when it became available">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        Elexon Insights · poll every 60 s
      </text>
      {datasets.map((name, i) => {
        const y = 34 + i * 36;
        return (
          <g key={name}>
            <rect x={16} y={y} width={92} height={26} rx={6} className="fill-surface stroke-border" />
            <text x={62} y={y + 17} textAnchor="middle" fontSize={10.5} fontWeight={600} className="fill-accent-primary font-mono">
              {name}
            </text>
            <path d={`M108 ${y + 13} C160 ${y + 13} 160 140 206 140`} strokeWidth={1.5} className="flow fill-none stroke-brand" />
          </g>
        );
      })}

      <path d="M206 72 V208 A44 12 0 0 0 294 208 V72" className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <ellipse cx={250} cy={72} rx={44} ry={12} className="fill-brand-tint stroke-brand" strokeWidth={1.5} />
      <text x={250} y={136} textAnchor="middle" fontSize={14} fontWeight={700} className="fill-brand font-serif">
        Tiger
      </text>
      <text x={250} y={154} textAnchor="middle" fontSize={14} fontWeight={700} className="fill-brand font-serif">
        Data
      </text>

      <text x={312} y={60} fontSize={10} fontWeight={600} className="fill-brand font-mono">
        grid_raw
      </text>
      {[0, 1, 2, 3, 4].map((j) => (
        <g key={j} className={j >= 3 ? "row-in" : undefined} style={j >= 3 ? { animationDelay: `${(j - 3) * 0.5}s` } : undefined}>
          <rect x={312} y={72 + j * 24} width={150} height={16} rx={3} className={j >= 3 ? "fill-brand" : "fill-border"} fillOpacity={j >= 3 ? 0.55 : 1} />
        </g>
      ))}
      <text x={312} y={210} fontSize={9.5} className="fill-text-secondary font-mono">
        start_time · value
      </text>
      <text x={312} y={226} fontSize={9.5} className="fill-brand font-mono">
        + available_at
      </text>
      <text x={16} y={262} fontSize={10} className="fill-text-secondary font-mono">
        same normalise + upsert as the 2-year backfill · idempotent
      </text>
    </svg>
  );
}

export function PointInTime() {
  const t = 300;
  const rows = [
    { x: 40, y: 70 },
    { x: 90, y: 100 },
    { x: 140, y: 60 },
    { x: 190, y: 90 },
    { x: 240, y: 70 },
    { x: 270, y: 110 },
    { x: 330, y: 80 },
    { x: 380, y: 105 },
    { x: 420, y: 65 },
  ];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="Only rows available before the decision time reach the model; later rows are blocked">
      <rect x={t} y={30} width={456 - t} height={130} className="fill-discharge" fillOpacity={0.06} />
      {rows.map((r) => {
        const ok = r.x < t;
        return (
          <g key={r.x}>
            <rect
              x={r.x - 14}
              y={r.y}
              width={28}
              height={14}
              rx={3}
              strokeDasharray={ok ? undefined : "3 3"}
              className={ok ? "fill-brand" : "soft-pulse fill-none stroke-discharge"}
              fillOpacity={ok ? 0.6 : 1}
            />
            {!ok && (
              <path d={`M${r.x - 5} ${r.y + 2} L${r.x + 5} ${r.y + 12} M${r.x + 5} ${r.y + 2} L${r.x - 5} ${r.y + 12}`} strokeWidth={1.5} className="stroke-discharge" />
            )}
          </g>
        );
      })}

      <path d="M24 160 H448" strokeWidth={1} className="stroke-border" />
      <path d="M442 155 L450 160 L442 165" strokeWidth={1} className="fill-none stroke-border" />
      <text x={452} y={178} textAnchor="end" fontSize={10} className="fill-text-secondary font-mono">
        available_at
      </text>

      <path d={`M${t} 26 V170`} strokeWidth={2} className="soft-pulse stroke-brand" />
      <text x={t} y={20} textAnchor="middle" fontSize={10} fontWeight={600} className="fill-brand font-mono">
        decision_time
      </text>
      <text x={150} y={185} textAnchor="middle" fontSize={10} className="fill-brand font-mono">
        usable
      </text>
      <text x={378} y={145} textAnchor="middle" fontSize={10} className="fill-discharge font-mono">
        the future: blocked
      </text>

      <rect x={16} y={204} width={448} height={28} rx={6} className="fill-surface-sunken stroke-border" />
      <text x={28} y={222} fontSize={10.5} className="fill-accent-primary font-mono">
        WHERE available_at &lt;= decision_time <tspan className="fill-brand">-- pit</tspan>
      </text>
      <text x={16} y={258} fontSize={10} className="fill-text-secondary font-mono">
        test_pit_leak.py deletes each filter in turn: the suite must fail
      </text>
    </svg>
  );
}

export function Forecast() {
  const pts = Array.from({ length: 48 }, (_, k) => {
    const p = price(k * 0.5);
    const w = 5 + k * 0.35;
    return { x: 44 + (k * 412) / 47, p50: py(p), p90: py(p + w), p10: py(p - w * 0.8) };
  });
  const line = (key: "p10" | "p50" | "p90") => pts.map((pt, i) => `${i ? "L" : "M"}${pt.x.toFixed(1)} ${pt[key].toFixed(1)}`).join(" ");
  const band = `${line("p90")} ${[...pts].reverse().map((pt) => `L${pt.x.toFixed(1)} ${pt.p10.toFixed(1)}`).join(" ")} Z`;
  const last = pts[pts.length - 1];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="A p50 price forecast for the next 48 half-hours inside a p10 to p90 band that widens with the horizon">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        LightGBM × 3 · objective=quantile
      </text>
      <path d="M44 214 H456 M44 40 V214" strokeWidth={1} className="fill-none stroke-border" />
      <text x={36} y={44} textAnchor="end" fontSize={9} className="fill-text-secondary font-mono">
        £/MWh
      </text>
      <path d={band} className="band-in fill-brand-tint" />
      <path d={line("p90")} strokeWidth={1} strokeDasharray="3 3" className="band-in fill-none stroke-brand" />
      <path d={line("p10")} strokeWidth={1} strokeDasharray="3 3" className="band-in fill-none stroke-brand" />
      <path d={line("p50")} pathLength={1} strokeWidth={2} className="draw fill-none stroke-brand" />
      {(["p90", "p50", "p10"] as const).map((key) => (
        <text key={key} x={last.x - 4} y={last[key] + (key === "p90" ? -6 : key === "p10" ? 14 : -6)} textAnchor="end" fontSize={9.5} fontWeight={600} className="fill-brand font-mono">
          {key}
        </text>
      ))}
      {["now", "+6 h", "+12 h", "+18 h", "+24 h"].map((label, i) => (
        <text key={label} x={44 + i * 103} y={232} textAnchor="middle" fontSize={9.5} className="fill-text-secondary font-mono">
          {label}
        </text>
      ))}
      <text x={16} y={262} fontSize={10} className="fill-text-secondary font-mono">
        48 half-hours ahead · band widens with horizon · re-run every 30 min
      </text>
    </svg>
  );
}

export function Optimiser() {
  const bars = Array.from({ length: 24 }, (_, i) => price(i + 0.5));
  const sorted = [...bars].sort((a, b) => a - b);
  const kind = (p: number) => (p <= sorted[1] ? "charge" : p >= sorted[22] ? "discharge" : "hold");

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="The optimiser charges in the two cheapest hours, discharges in the two dearest and holds otherwise">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        trade only if eff·sell − buy &gt; eff·wear
      </text>
      <path d="M44 214 H456" strokeWidth={1} className="stroke-border" />
      {bars.map((p, i) => {
        const k = kind(p);
        const h = 214 - py(p);
        return (
          <rect
            key={i}
            x={46 + i * 17.1}
            y={214 - h}
            width={13}
            height={h}
            rx={2}
            className={`grow-y ${k === "charge" ? "fill-brand" : k === "discharge" ? "fill-discharge" : "fill-border"}`}
            style={{ animationDelay: `${i * 0.04}s` }}
          />
        );
      })}
      {[
        { x: 70, label: "charge", cls: "fill-brand" },
        { x: 170, label: "discharge", cls: "fill-discharge" },
        { x: 290, label: "hold", cls: "fill-border" },
      ].map((l) => (
        <g key={l.label}>
          <rect x={l.x - 18} y={226} width={10} height={10} rx={2} className={l.cls} />
          <text x={l.x - 4} y={235} fontSize={10} className="fill-accent-primary font-mono">
            {l.label}
          </text>
        </g>
      ))}
      <text x={16} y={262} fontSize={10} className="fill-text-secondary font-mono">
        2 MWh · 1 MW · 90% round trip · £20 per cycle wear
      </text>
    </svg>
  );
}

export function Audit() {
  const lanes = [
    { shift: "−1 h", off: -2, pnl: 0.55 },
    { shift: "−30 m", off: -1, pnl: 0.82 },
    { shift: "on time", off: 0, pnl: 1 },
    { shift: "+30 m", off: 1, pnl: 0.86 },
    { shift: "+1 h", off: 2, pnl: 0.6 },
  ];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="The same decision replayed one hour early to one hour late; on time makes the most money">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        1 Tiger fork → 5 Vultr workers → replay at actual prices
      </text>
      <text x={290} y={44} fontSize={9.5} className="fill-text-secondary font-mono">
        P&amp;L
      </text>
      {lanes.map((l, i) => {
        const y = 54 + i * 36;
        const base = i === 2;
        return (
          <g key={l.shift}>
            <text x={70} y={y + 15} textAnchor="end" fontSize={10} fontWeight={base ? 700 : 400} className={`font-mono ${base ? "fill-brand" : "fill-accent-primary"}`}>
              {l.shift}
            </text>
            <rect x={80} y={y} width={196} height={22} rx={4} className="fill-surface-sunken" />
            <rect x={110 + l.off * 12} y={y + 4} width={30} height={14} rx={2} className="fill-brand" fillOpacity={0.7} />
            <rect x={200 + l.off * 12} y={y + 4} width={30} height={14} rx={2} className="fill-discharge" fillOpacity={0.7} />
            <rect x={290} y={y + 4} width={170} height={14} rx={3} className="fill-surface" />
            <rect
              x={290}
              y={y + 4}
              width={170 * l.pnl}
              height={14}
              rx={3}
              className={`lane ${base ? "fill-brand" : "fill-text-secondary"}`}
              fillOpacity={base ? 1 : 0.5}
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          </g>
        );
      })}
      <text x={16} y={262} fontSize={10} className="fill-text-secondary font-mono">
        Δ£ vs on time = the cost of rushing or hesitating
      </text>
    </svg>
  );
}

export function Results() {
  const rows = [
    { name: "Perfect foresight", pct: 100, money: "£88,388" },
    { name: "Tempo LP", pct: 68.3, money: "£60,391" },
    { name: "Tempo (live)", pct: 66.4, money: "£58,711" },
    { name: "Persistence", pct: 52.9, money: "£46,798" },
    { name: "Simple rule", pct: 33.1, money: "£29,265" },
  ];

  return (
    <svg viewBox="0 0 480 270" className={svg} role="img" aria-label="Walk-forward backtest: Tempo earns 66 percent of perfect foresight, double the simple rule">
      <text x={16} y={20} fontSize={10} className="fill-brand font-mono">
        % of perfect foresight · 100 unseen weeks
      </text>
      {rows.map((r, i) => {
        const y = 40 + i * 40;
        const tempo = r.name.startsWith("Tempo");
        const perfect = i === 0;
        return (
          <g key={r.name}>
            <text x={16} y={y + 16} fontSize={10.5} fontWeight={tempo ? 700 : 400} className={`font-sans ${tempo ? "fill-brand" : "fill-accent-primary"}`}>
              {r.name}
            </text>
            <rect x={130} y={y + 4} width={270} height={16} rx={3} className="fill-surface-sunken" />
            <rect
              x={130}
              y={y + 4}
              width={2.7 * r.pct}
              height={16}
              rx={3}
              strokeDasharray={perfect ? "4 3" : undefined}
              className={`lane ${perfect ? "fill-none stroke-border" : tempo ? "fill-brand" : "fill-text-secondary"}`}
              fillOpacity={tempo ? 1 : 0.45}
              style={{ animationDelay: `${i * 0.12}s` }}
            />
            <text x={408} y={y + 16} fontSize={10} fontWeight={tempo ? 700 : 400} className={`font-mono ${tempo ? "fill-brand" : "fill-text-secondary"}`}>
              {r.pct}%
            </text>
          </g>
        );
      })}
      <text x={16} y={250} fontSize={10} className="fill-text-secondary font-mono">
        28-day train window, retrained each test week
      </text>
      <text x={16} y={264} fontSize={10} className="fill-text-secondary font-mono">
        24 Oct 2024 – 24 Oct 2026
      </text>
    </svg>
  );
}
