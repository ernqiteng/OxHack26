// The story, in demo order. One page per chapter (see SPEC.md).
export const chapters = [
  { id: "hook", href: "/", eyebrow: "00 · Why this is hard", title: "Hook", headline: "Cheap at 3am. Expensive at 6pm. The hard part is when.", body: "Electricity in Britain is priced every half hour. A battery makes money in between, but it has to commit before it knows the future." },
  { id: "data", href: "/data", eyebrow: "01 · Data", title: "Data", headline: "Every row knows when it became available.", body: "Official Elexon market data flows into Tiger hypertables, stamped with its publish time, so nothing from the future can leak into a decision." },
  { id: "prediction", href: "/prediction", eyebrow: "02 · Prediction", title: "Prediction", headline: "28% less wrong than yesterday’s prices.", body: "LightGBM forecasts all 48 half-hours ahead with an uncertainty band, and beats the “same as yesterday” baseline on data it never saw." },
  { id: "decision", href: "/decision", eyebrow: "03 · Decision", title: "Decision", headline: "It trades when it pays. It holds when it doesn’t.", body: "Every cycle has to cover efficiency losses and battery wear. If the spread falls short, Tempo holds, and says why." },
  { id: "proof", href: "/proof", eyebrow: "04 · Proof", title: "Proof", headline: "66% of perfect foresight, on 100 unseen weeks.", body: "Walk-forward tested against a fixed schedule, a persistence forecast and the theoretical ceiling. It never lost money in a week." },
  { id: "timing", href: "/timing", eyebrow: "05 · Timing", title: "Timing", headline: "Proof it picked the right moment.", body: "One click forks the live database on Tiger and five Vultr workers replay the decision shifted earlier and later, in parallel." },
] as const;

export type ChapterId = (typeof chapters)[number]["id"];

// Index of the chapter whose page is at `pathname` (0 for anything unknown).
export function chapterIndex(pathname: string): number {
  const clean = pathname.replace(/\/+$/, "") || "/";
  return Math.max(0, chapters.findIndex((c) => c.href === clean));
}
