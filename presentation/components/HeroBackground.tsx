// Faint grid with pulses of current running along circuit traces. Animations live in globals.css.

const traces = [
  "M0 180 H420 L500 100 H900",
  "M1600 260 H1250 L1170 340 H980",
  "M0 640 H260 L340 720 H700",
  "M1600 700 H1320 L1240 620 H1100 V520",
  "M520 900 V780 L600 700 H760",
  "M1100 0 V120 L1180 200 H1450",
];

const nodes = [
  [900, 100],
  [980, 340],
  [700, 720],
  [1100, 520],
  [760, 700],
  [1450, 200],
  [420, 180],
  [260, 640],
];

export default function HeroBackground() {
  return (
    <svg
      viewBox="0 0 1600 900"
      preserveAspectRatio="xMidYMid slice"
      className="hero-fade pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden
    >
      {Array.from({ length: 11 }, (_, i) => (
        <path key={`v${i}`} d={`M${i * 160} 0 V900`} strokeWidth={1} className="stroke-border-light" />
      ))}
      {Array.from({ length: 7 }, (_, i) => (
        <path key={`h${i}`} d={`M0 ${i * 150} H1600`} strokeWidth={1} className="stroke-border-light" />
      ))}

      {traces.map((d) => (
        <path key={d} d={d} strokeWidth={1.25} className="fill-none stroke-border" />
      ))}
      {traces.map((d, i) => (
        <path
          key={`c${d}`}
          d={d}
          pathLength={1000}
          strokeWidth={2}
          strokeLinecap="round"
          className="current fill-none stroke-brand"
          style={{ animationDelay: `${i * 1.1}s` }}
        />
      ))}
      {nodes.map(([x, y], i) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r={4} className="soft-pulse fill-brand" fillOpacity={0.5} style={{ animationDelay: `${i * 0.3}s` }} />
      ))}
    </svg>
  );
}
