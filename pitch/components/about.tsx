import type { Section } from "@/components/InfoPage";

const results = [
  { strategy: "Simple rule (charge 1am to 5am, sell 5pm to 7pm)", money: "£29,265", share: "33.1%" },
  { strategy: "Persistence forecast + same optimiser", money: "£46,798", share: "52.9%" },
  { strategy: "Tempo (LightGBM + greedy, what runs live)", money: "£58,711", share: "66.4%" },
  { strategy: "Tempo LP (LightGBM + LP optimiser)", money: "£60,391", share: "68.3%" },
  { strategy: "Perfect knowledge of the future", money: "£88,388", share: "100%" },
];

export const aboutEyebrow = "About";
export const aboutTitle = "It's buy-low-sell-high for a battery. The hard part is the timing.";
export const aboutLead =
  "Tempo forecasts Britain's half-hourly electricity prices, decides when a grid battery should charge, sell or deliberately do nothing, and then proves whether each decision was made at the right time.";

export const aboutSections: Section[] = [
  {
    heading: "The market",
    body: (
      <p>
        Great Britain&apos;s wholesale electricity market is settled in 48 half-hour blocks a day, each
        with its own price. At 3am on a windy night prices collapse, sometimes below zero. At 6pm on a
        cold weekday everyone gets home and prices spike. A grid battery makes money between those two
        moments.
      </p>
    ),
  },
  {
    heading: "Why it's hard",
    body: (
      <ul>
        <li>
          <strong>You have to predict the future.</strong> Charging now is a bet on the next 24 hours.
        </li>
        <li>
          <strong>The battery has physical limits.</strong> It holds 2 MWh, moves 1 MW at a time and loses
          about 10% of the energy on every round trip.
        </li>
        <li>
          <strong>Doing nothing is a real decision.</strong> On a flat day the spread doesn&apos;t cover
          the losses, so Tempo holds and logs why.
        </li>
      </ul>
    ),
  },
  {
    heading: "Three layers",
    body: (
      <ul>
        <li>
          <strong>Live decision engine.</strong> Elexon market data flows into Tiger Data, a LightGBM
          model forecasts the next 48 prices as a p10, p50 and p90 band, and a cost-gated optimiser
          picks charge, discharge or hold every half hour.
        </li>
        <li>
          <strong>Timing audit.</strong> Click any decision and Tempo replays it an hour earlier, half an
          hour earlier, on time, half an hour later and an hour later, then shows in pounds what rushing
          or hesitating would have cost.
        </li>
        <li>
          <strong>Honesty panel.</strong> Results on weeks the model never saw, against honest
          baselines, with calibration and the places it&apos;s weak on screen at all times.
        </li>
      </ul>
    ),
  },
  {
    heading: "Results on 100 unseen weeks",
    body: (
      <>
        <div className="overflow-x-auto rounded-xl border border-border-light bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-text-secondary uppercase">
              <tr>
                <th className="px-4 py-3 font-medium">Strategy</th>
                <th className="px-4 py-3 text-right font-medium">Money made</th>
                <th className="px-4 py-3 text-right font-medium">% of perfect</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={row.strategy} className="border-t border-border-light">
                  <td className="px-4 py-3">{row.strategy}</td>
                  <td className="px-4 py-3 text-right font-mono">{row.money}</td>
                  <td className="px-4 py-3 text-right font-mono">{row.share}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-sm text-text-secondary">
          Walk-forward backtest, 24 Oct 2024 to 24 Oct 2026: 28 days of training, retrained for every
          7-day test week.
        </p>
      </>
    ),
  },
];
