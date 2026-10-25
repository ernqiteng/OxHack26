// Arrange the replay week's rows into days × half-hours (London time).
const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", weekday: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export function toWeekGrid(rows) {
  const days = [];
  const index = new Map();
  rows.forEach((r, i) => {
    const parts = Object.fromEntries(fmt.formatToParts(new Date(r.ts)).map((p) => [p.type, p.value]));
    const key = `${parts.weekday} ${parts.day}`;
    if (!index.has(key)) {
      index.set(key, days.length);
      days.push({ label: key, cells: [] });
    }
    const slot = Number(parts.hour) * 2 + (Number(parts.minute) >= 30 ? 1 : 0);
    days[index.get(key)].cells.push({ ...r, i, slot, time: `${parts.hour}:${parts.minute}` });
  });
  return days;
}
