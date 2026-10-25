// One-hue sequential ramp for price (light = cheap, dark = dear). Tailwind orange 50 → 900.
const STOPS = ["#fff7ed", "#fed7aa", "#fb923c", "#c2410c", "#7c2d12"].map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));

export function ramp(t) {
  const u = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(u));
  const f = u - i;
  const c = STOPS[i].map((a, k) => Math.round(a + (STOPS[i + 1][k] - a) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export const RAMP_CSS = `linear-gradient(to right, ${["#fff7ed", "#fed7aa", "#fb923c", "#c2410c", "#7c2d12"].join(",")})`;
