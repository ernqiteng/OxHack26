# info.md: Project idea, research and strategy (OxHacks 2026)

One file with the idea, why it wins, and the research behind it. Read alongside `CLAUDE.md` and `docs/`.

> **Naming and conflicts.** The research brief called the project **GridEdge** and the repo docs call it **Tempo**. They are the same idea: forecast GB electricity prices, then decide when a battery charges or discharges. Where this file and `docs/description.md`, `docs/plan.md` or `docs/needs.md` disagree (price series, optimiser, model choices, demo flow), **the `docs/` files win**, because the team froze the plan there. In particular, the docs use the Elexon MID (market index) price series, LightGBM quantile forecasts, greedy and LP optimisers, and the fork-based timing audit. Treat the "fancy" items below (thousands of scenarios, CVaR, diffusion) as optional upgrades.

---

## 1. The idea in plain English

### In three sentences
1. Electricity in Britain has a **price that changes every half hour**: cheap when it's windy at night, expensive at 6pm when everyone is cooking.
2. The app **predicts upcoming prices**.
3. A pretend battery uses that prediction to **charge in the cheap hours and sell in the expensive hours**, and we show how much money it made.

Real companies own giant batteries and do exactly this for profit. We are building the brain that decides when to charge. One-line pitch: *"It's buy-low-sell-high for a battery, and our AI decides when 'low' and 'high' are."*

### The world it lives in
Britain's grid must balance supply and demand every second. Generators and suppliers promise in advance how much they will produce or use, in **half-hour slots** called settlement periods (48 per day). Reality never matches exactly: the wind drops, or everyone puts the kettle on at half-time. Whoever is off their promise pays or is paid the **imbalance price** for that half hour. When the grid is short, the price can spike very high. When there is too much (a very windy night), it can drop low or go negative. Elexon publishes all of this publicly and free every half hour. That is our data.

The battery is virtual (say 10 MWh in the research brief; the real defaults are in `docs/plan.md`). Nobody buys hardware. It has real limits: it cannot be more than full or less than empty, it can only charge so fast, and it loses about 10% of energy per round trip.

### The four steps
1. **Collect the data (Tiger Data).** A script pulls prices, wind generation, demand and more from Elexon every few minutes and stores it in Tiger Data. We also load about two years of history. Tiger keeps automatic summary tables (half-hour, daily, weekly) that feed the model and dashboard instantly.
2. **Predict a range, not one number.** Instead of "the price at 6pm will be £80", the model says "10% chance below £40, 50% below £80, 90% below £200". That is a **quantile forecast**. Prices are so unpredictable that a single guess misleads, and knowing how unsure you are is what makes a good decision possible.
3. **(Optional upgrade) Imagine thousands of possible futures on a Vultr GPU.** From the range, generate a few thousand realistic price paths for the next 24 hours. This is the heavy compute that justifies the GPU.
4. **Make the decision.** An optimiser asks which charge/discharge plan makes the most money while respecting the battery limits. Output example: "Next half hour: **discharge** at full power", or a **hold** with a readable reason.

### An analogy
It's like running an umbrella stall. You don't just guess "it'll rain tomorrow". You estimate how likely rain is each hour, picture many possible weather days, and decide when to stock up and when to sell so you do well across most of them. Then you check against last month's real weather whether your strategy beat "always stock umbrellas on Mondays".

---

## 2. Why this wins each track

### HRT: "Best use of data for predictions and decision making"
Most teams will do one of two things:
- **Prediction only:** "our model predicts X with 87% accuracy". No decision, so it hits half the brief.
- **Decision with no proof:** "our app recommends what to do". Nothing shows the recommendation is good.

We do all of it, and each part is visible:

| What judges want | What we show |
|---|---|
| Use of data | Real live UK grid data, years of history |
| Prediction | "Tomorrow at 6pm the price will be around £120" |
| Decision | "So: charge at 3am, sell at 6pm" |
| Proof the decision is good | "Over 8 past weeks our battery made £X. The simple rule made £Y. So using our prediction earned Z% more." |

The last row is the winning row. Quant firms ask one question all day: *did this prediction actually make money compared with doing something simple?* We answer it with a number in a fresh domain. HRT also talked about GPUs at the event, and our GPU does real work (training, scenario generation), not just hosting.

### Tiger Data
Built for data that arrives over time, and ours is literally a price every half hour plus years of history. We show: live data flowing in; a big number like "N million rows, compressed 90%+"; charts that load instantly because Tiger pre-calculates half-hourly and daily summaries; and database forking in the timing audit. That is their product used for exactly what it is designed for.

### Vultr
The honest line: "the model trains on Vultr's GPU and the backend runs on Vultr", plus the worker pool that runs the audit replays. That is stronger than most entries, which just host a website. If GPU stock or credits fail, say so honestly and use CPU.

---

## 3. Simple version vs fancy version

The research brief's version (thousands of scenarios, risk-limited optimiser, calibration plots) is the "if everything goes perfectly" version. This simple version still wins:

| Part | Overcomplicated | Simple (do this first) |
|---|---|---|
| Prediction | Neural net giving a full range | **LightGBM** quantile model, plus a small neural net on the GPU to compare |
| Decision | Optimiser over thousands of scenarios | **Greedy rule:** charge in the cheapest predicted periods, sell in the most expensive, with a cost gate |
| Proof | Confidence intervals, calibration plots | **One table:** our money vs "same as yesterday" vs perfect knowledge |
| Dashboard | React app | **Streamlit** |

Only if well ahead of schedule, add the price range ("80% chance between £60 and £150"), the LP optimiser and the scenario generator. Upgrades, not the core.

---

## 4. How we prove it works

This is what HRT judges care about most. Take past weeks the model **has never seen**, replay them as if live with walk-forward evaluation (retrain per window, no feature newer than its `available_at`), and let the battery trade. Compare against:
- **A dumb rule:** charge at night, discharge 5 to 7pm.
- **A naive forecast:** today's price equals yesterday's at the same time (persistence).
- **The perfect ceiling:** what you would earn knowing the future. No strategy may ever exceed it. If one does, there is a leak.

Say things like: "we earned £X, beating the dumb rule by Y%, capturing Z% of the theoretical maximum." Also check the forecast is **honest**: when it says "90% chance below £200", that should happen about 90% of the time (calibration, 80% interval coverage). Report pinball loss against persistence and LightGBM, and a bootstrap confidence interval on the P&L difference if time allows.

**Honest verdict:**
- Strongest part: the "money made vs simple baseline" table. That one slide wins HRT.
- Weakest part: electricity markets are unfamiliar, so one sentence must make it click (the pitch line above).
- Biggest risk: the model may not beat the simple rule by much. That is fine. Saying "the simple rule was hard to beat, here is where we won and where we did not" is exactly what HRT respects, and it beats fake-looking great results.

---

## 5. Research: past hackathon winners (Phase A)

**Prize categories confirmed (winning projects mostly NOT verified):**

| Event | Prize | What it says / rewards |
|---|---|---|
| TreeHacks 2025 | Hudson River Trading: Best Use of Data Hack ($200 + HRT JBL earbuds each, 1 winner) | "Effective use of data is important to the decisions we make at Hudson River Trading… awarded to the hack that best integrates the use of data into their project." |
| TreeHacks 2024 | HRT data prize (same wording) | Same "strategize with data" text |
| IC Hack 22 (Imperial) | [Citadel] Best Use of Data; [Optiver] Market Making Challenge | Citadel, Optiver, Marshall Wace, Palantir Gold sponsors; HRT, Jane Street, G-Research Silver |
| IC Hack 24 | [Citadel] Most Innovative Use of Financial Data; [Optiver] Build Algorithms to Build Markets | Judging: Originality, Usefulness, Technical Challenge |
| Hacktech 2020 | [Citadel] Best Hack Using Machine Learning | Citadel and Citadel Securities engineers judged |
| Hex Cambridge 2021 | Optiver Challenge 1st/2nd | "The winning team will be the one that has developed the best trading strategy… (not the team that makes the most money)" |
| Hack the North 2024 to 2026, HackGT 12, HackHarvard | HRT/Citadel/Virtu as sponsors | Sponsor-level presence; firm-branded prizes not confirmed |

**Verified winning projects:**

| Project | Event / prize | What it did | Data | Technique | Why it likely won (inference) |
|---|---|---|---|---|---|
| Money Making Market Maker #team-14 | HackZurich 2021, Winner, Optiver workshop | Market-making bot on Optibook quoting around an estimated fair value | Optiver simulated exchange | Square-root "credit factor" shrinking margin to exit position limits | Explicit risk/position management, not just price prediction |
| Haven | SwampHacks XII (483 hackers, 141 projects), MLH Best Use of Tiger Data | Rehab coach: camera + armband guide exercises; PT dashboard | Armband arm angle at 20 Hz | TimescaleDB on Tiger Cloud | A genuinely high-frequency stream with Tiger as the natural store; worked live |
| Nice Out | DEV Hacktoberfest "Touch Grass", Best Use of Tiger Data | Learns your kind of nice weather | Weather | Personalised preference model on Tiger | Time-series personalisation |
| PaidYet | DEV Hacktoberfest "Build for a Friend", Best Use of Tiger Data | Shop helper for a WhatsApp business | Voice notes / transactions | Tiger as the ledger | Real user, real data |
| Agentic Postgres Challenge winner | DEV x Tiger Data | Rust database-native ML system | n/a | Tiger Fluid Storage, "95% cost savings" | Used many Tiger features, with numbers |

**Patterns (inference):**
- Rewarded: data *driving a decision*; explicit risk and constraint handling (Optiver winner managed position limits; Hex Cambridge judged strategy over raw profit); live working demos on real streams.
- Overdone, likely to bore quant judges: "LSTM predicts stock price", "tweet sentiment to buy/sell", toy backtests with no costs, no baseline and no uncertainty, anything with lookahead. HRT's own data post uses lookahead-tainted "Market Moving News Articles" as its example of a dataset "rendered effectively unusable".
- **Gap:** 15 named quant-prize winners could not be confirmed. **Do not cite "past HRT winners did X" in the pitch.**

---

## 6. Research: HRT deep-dive (Phase B)

**What they care about (sourced):**
- **Prediction then optimisation split.** Iain Dunning (HRT Head of AI, ex-DeepMind) describes one AI that "simply predict[s] the future" and a second that does "optimization", converting predictions into allocations under risk constraints. He also notes "in trading we have only one reality, and acquire new data in real time – i.e., very slowly."
- **Simplicity, reproducibility, generality.** "If a linear model is as good as a random forest model, we'd prefer the linear model." Also "it is easy to lie to ourselves while resolving small differences in our low signal-to-noise domain", and they contrast academic point estimates with their own "standardized ways we run 'backtests'". The same post cites Agarwal et al. on reporting uncertainty in results.
- **Data quality and provenance.** "Garbage in, garbage out"; avoiding lookahead is a headline section of "How HRT Thinks About Data".
- **What HAIL (HRT AI Labs) works on:**
  - 2022 interns: LLMs on financial news, transformers for market data.
  - 2023 interns: genetic-algorithm signal search; graybox Bayesian optimisation to cut costly backtests; GPU tall-and-skinny matrix workloads.
  - 2025 intern: diffusion models generating synthetic stock returns, where "a key challenge persists in defining meaningful evaluation metrics".
  - 2026 intern: RL for sequential decision-making in noisy markets.
- **Infra and data obsession.** Recent posts cover eBPF tracing of global research traffic, scaling Prometheus to billions of samples a second, an alerting DSL, and a real-time trading viewer. Algo intern postings ask for "machine learning and time series techniques" on "large and complex datasets" and "predictive models… using a combination of market and non-market data".

**GPU spend (the signal from the opening talk):**
- **20 Aug 2026:** CoreWeave announced a multi-year agreement giving HRT NVIDIA Vera Rubin NVL72 and HGX B200 clusters, reported as multibillion-dollar. CoreWeave CRO Jon Jones told Bloomberg it was "a material expansion" of a relationship that began in March 2026. Kevin Lee, HRT's head of R&D: "the AI platform we build on matters as much as the models we build". To Bloomberg: "Having access to more compute resources just allows our researchers to try more things and hopefully find more interesting results."
- **May 2026:** DatacenterDynamics reports HRT "selected AI cloud Lambda to provide AI compute for its model training and trading simulation workloads" on NVIDIA HGX B200s. Gerard Bernabeu Altayo, HRT's compute systems lead: "Lambda stood out for its technical depth and operational clarity."
- Bloomberg (13 Jan 2026) put HRT's 2025 net trading revenue at about $12.3B per people familiar. That is an estimate, not a published result.

**What impresses vs bores an HRT engineer (inference):**
- Impresses: a baseline that is hard to beat; walk-forward evaluation with no leakage; uncertainty bands on P&L; calibrated probabilistic forecasts; a decision layer with constraints; showing the simple model wins where it does; GPU use that buys *more experiments or scenarios*.
- Bores: accuracy on a random train/test split; one cherry-picked backtest; "AI" with no counterfactual; a dashboard with no decision.
- **How they phrase "good use of data":** data that improves *decisions*, clean provenance, honest evaluation.

---

## 7. Research: Tiger Data (Phase B)

- MLH quickstart: new signups get **$1,000 credits valid 30 days**. MLH promotes Tiger CLI and the **Tiger MCP** server, hypertables and hypercore.
- Prize brief (same across MLH events): "Unified Data Stack… Instant Dashboards… pre-computed Continuous Aggregates… 90%+ Data Compression", judged on "most innovative, impactful, and performance-driven use". It name-checks "financial prediction engines". Prize for this event: Stream Deck Mini.
- **Hypercore:** 90 to 98% compression in the columnstore; INSERT/UPDATE/DELETE/UPSERT work directly on compressed data.
- **Continuous aggregates:** incrementally refreshed; can be **hierarchical** (cagg on cagg) and compressed into the columnstore. Real-time aggregation is **off by default** on caggs, so turn it on for the live dashboard.
- v2.23 / v2.24: automatic columnstore; caggs no longer use triggers; direct-to-columnstore ingest supported with caggs.
- Whitepaper: vectorised aggregation; column-level delta, run-length and Gorilla encoding. pgvector is used by Tiger winners (HNSW + hybrid search).
- **Visibly impressive on screen (inference):** `hypertable_columnstore_stats` before/after ratio; a multi-level cagg behind a live chart; a full-history scan returning in milliseconds on compressed data.
- **Not verified:** pgai, pgvectorscale and DB-forking specifics. Check the docs before claiming them. (Fork timing is measured in Phase 0 of `docs/ayo.md`.)

---

## 8. Research: Vultr (Phase B)

- MLH credit flow: register at mlh.link/vultr-discover (Company = school name, Job Title = Student), verify email, sign up at mlh.link/vultr-signup, then Billing → Gift Code for **$100 credits**. "Multiple registrations are not allowed." Prize for this event: M5Stack Tab5.
- Offering: Cloud GPUs, VMs, Managed Kubernetes. NVIDIA HGX H100, A100, L40S, A40, A16 and GH200 in the lineup; AMD Instinct MI355X added in 2025. Fractional A100 (Vultr Talon) launched in 2022 at "as low as $0.134/hour (or $90/month)" for a twentieth of an A100 (2022 launch pricing, not a 2026 rate). GPU Stack + Container Registry gives access to NGC containers.
- Spheron's 5 Aug 2026 snapshot of Vultr list prices (secondary source): 8x H100 bare metal about $23.92/hr (~$2.99/GPU-hr), A100 PCIe $2.397/hr, GH200 $1.99/hr. On those prices $100 buys about 4 hours of an 8x H100 node or about 41 hours of one A100. Plan a single A100/L40S-class instance for training plus batch inference, and **check live pricing and stock in the console before relying on it**.
- Past "Best Use of Vultr" winners: **not verified.** Inference: visibly necessary GPU work beats "we hosted on a VM".

---

## 9. Data sources (Phase C)

| Source | Access | Cadence / volume | Setup | Limits / caveats |
|---|---|---|---|---|
| **Elexon Insights (BMRS)** `data.elexon.co.uk/bmrs/api/v1` | Public, **no API key** | Settlement-period prices, imbalance, generation, BOAs; stream endpoints; **IRIS** free near-real-time push feed | ~15 min | **5,000 req/min/user**, 429 above; some endpoints have extra limits; attribute "Contains BMRS data © Elexon Limited" |
| **NESO Carbon Intensity API** | Open, **no key**, CC BY 4.0 | 30-min; national actual + forecast; 18 regions (forecast only); forecasts 96+ h ahead | ~5 min | History to 2017 in windows of 14 days or less; regional has no actuals. Co-developed with **Oxford's Dept of Computer Science** (a free local hook) |
| energydashboard.co.uk (reference only) | Web | 5-min mix | n/a | Sanity check: at 19:45 on 23 Oct, wind was 41.4% of 39.1 GW and intensity 82 gCO₂/kWh. A windy, volatile weekend is good for price dynamics |
| Coinbase/Binance WS, Wikipedia EventStreams, Bluesky Jetstream, GitHub events, OpenSky, TfL, Open-Meteo | Generally keyless (**not verified**) | High-frequency | 10 to 30 min | Check current rate limits before committing |

Pick exact Elexon endpoint paths from the Swagger spec. Details and quirks for our six datasets are in `docs/needs.md`.

---

## 10. Idea shortlist (Phase D)

**15 raw ideas, cut to 3:**
1. GridEdge: GB imbalance-price quantile forecast → battery dispatch **(TOP 3, chosen; = Tempo)**
2. CarbonShift: carbon-aware GPU job scheduler that corrects NESO's forecast error **(TOP 3)**
3. EditStorm: Wikipedia edit-burst forecast → cache prewarm / moderation triage **(TOP 3)**
4. Crypto order-book microprice predictor (overdone trading bot, cut)
5. Polymarket calibration arbitrage (near trading bot; resolution data too sparse for 24h)
6. TfL bus-bunching predictor (feed reliability unknown)
7. OpenSky go-around predictor (rare-event labels, weak eval)
8. EV-charging price-aware scheduler (subset of #1, weaker)
9. Bluesky virality forecaster (sentiment-adjacent, overdone)
10. GitHub CI-failure predictor (data too sparse live)
11. Heat-pump pre-heating optimiser (needs house data)
12. Wind-curtailment predictor from BOAs (strong but niche; folded into #1 as a feature)
13. Weather-driven demand forecaster (NESO already publishes this)
14. Synthetic grid-price diffusion generator (folded into #1 as the scenario engine)
15. LLM agent over BMRS via Tiger MCP (decorative; stretch feature in #1)

### #1 GridEdge / Tempo (chosen)
**Pitch.** A live probabilistic forecaster of GB electricity prices that dispatches a virtual battery and shows its walk-forward P&L against honest baselines.

**30-second judge pitch.** "Every half hour, Britain's grid settles a price that swings with wind. We stream Elexon data into Tiger Data, forecast the next periods as full distributions, run the optimiser on Vultr, and decide when a battery charges or discharges. On held-out weeks we beat persistence by £X, capture Y% of the perfect-foresight ceiling, and our 80% intervals cover 80% of outcomes. Here it is running live."

**Why it wins HRT.** It mirrors Dunning's predict-then-optimise split. It is a low signal-to-noise, real-time, "one reality" market where honest walk-forward backtests and a perfect-foresight ceiling show rigour. Calibration tackles the "evaluation metric" problem HAIL's diffusion intern names. GPU scenario generation is literally "trading simulation workloads", the phrase in HRT's Lambda deal. It is a market but not a stock bot: fresh, and still in HRT's comfort zone (inference).

**Tiger and Vultr.**
- Tiger: Elexon stream into hypertables; relational config tables in the same DB; hierarchical caggs feed features and dashboard (real-time aggregation on); columnstore policy on older chunks with the compression ratio shown live; two-plus years of backfill so the full-history query looks impressive.
- Vultr: train the quantile model on a GPU instance; optionally batch-generate 2,000 to 5,000 price paths per decision step; backend and workers on Vultr; FastAPI inference on the same box.

**Data and model (defensible choices).**
- Data: Elexon prices, generation mix, demand, wind forecasts; NESO carbon intensity as an optional exogenous feature.
- Models: (a) persistence baseline; (b) **LightGBM quantile regression**, fast, strong on tabular data, and HRT's "simplest model that works"; (c) stretch: small temporal neural net with pinball-loss quantile heads on GPU, plus a Gaussian-copula scenario generator (conditional diffusion as a further stretch, echoing HAIL). Keep the neural net only if it beats LightGBM on real weeks.
- Decision: greedy with cost gate first; LP (cvxpy/HiGHS) maximising mean scenario P&L, optionally with a CVaR penalty, subject to SoC, power and ~90% round-trip efficiency.

**Architecture.** Elexon REST/IRIS poller → Tiger hypertables → caggs → point-in-time feature view → model (train on GPU, infer per period) → optimiser → `decisions` hypertable → Streamlit dashboard reading caggs and decisions.

**Build plan from the research brief (the `docs/` plan supersedes the split).**

| Hours | Data / Tiger | ML / Vultr | Decision / UI |
|---|---|---|---|
| H0-1 | Tiger signup, schema, hypertables | Vultr credit claim, GPU instance, CUDA check | Repo, skeleton, battery spec |
| H1-4 | Elexon backfill + live poller | Persistence + LightGBM baselines | Perfect-foresight ceiling |
| H4-8 | Caggs, columnstore policy, stats query | Neural quantile model on GPU; walk-forward harness | Dashboard: live price, cagg charts, compression panel |
| H8-12 | Feature view, leakage audit | Scenario generator; seed sweep | Stochastic LP; backtest loop |
| H12-16 | Sleep shifts | Full walk-forward run | P&L curve, calibration plot |
| H16-20 | Live poll hardening | Inference endpoint, latency numbers | Live "next decision" panel |
| H20-22 | Freeze; record backup demo | Freeze model | Write-up, slides |
| H22-24 | Rehearse x3 | Rehearse | Submit |

**Fallbacks.** If Vultr GPU stock or credits fail, train on CPU and say so. If IRIS is flaky, poll REST. If the neural model loses, present LightGBM as the winner (still an HRT-friendly story).

**Risks and cut order.** Imbalance and market prices are spiky, so P&L can look bad; mitigate by reporting % of ceiling. Cut first: diffusion generator → CVaR → live IRIS (use polling) → React (use Streamlit).

**3-minute demo.**
- 0:00 The problem and the live price chart fed by a cagg.
- 0:30 Tiger panel: N million rows, compression ratio, full-history query time.
- 1:00 Forecast fan chart for the next periods (GPU scenarios overlaid if built).
- 1:30 Battery decision for the next period with its reason.
- 2:00 Walk-forward table: persistence vs LightGBM vs neural; P&L, % of ceiling, calibration.
- 2:40 "What we'd do with HRT's compute" close. (The repo's demo script adds the timing-audit fork demo; follow `docs/description.md` section 6.)

**Scores (research brief):** HRT 9, Tiger 9, Vultr 8, Novelty 8, Feasibility 8, Wow 8 = 50/60 (52 if the diffusion stretch ships).

### #2 CarbonShift (backup, 45/60)
Predicts the error in NESO's regional carbon-intensity forecast and schedules deferrable GPU jobs across time and region to minimise gCO₂ with deadlines. Strengths: residual correction of an expert forecast is classic quant thinking; Vultr GPU jobs are the object being scheduled. Weaknesses: not a market; forecast-vintage history must be built live, so there is little training data in 24h; regional actuals do not exist, so validate nationally. Scores: HRT 7, Tiger 8, Vultr 9, Novelty 8, Feasibility 6, Wow 7. Use only if Elexon is down in the first hour.

### #3 EditStorm (45/60)
Forecasts per-page Wikipedia edit/revert bursts from the live recent-changes stream and ranks pages for patrol or cache prewarm. Strengths: highest-frequency stream, ideal for showing Tiger compression; GPU embeddings with pgvector. Weaknesses: labels arrive late, no £ value, weakest HRT story. Scores: HRT 6, Tiger 10, Vultr 7, Novelty 7, Feasibility 7, Wow 8.

---

## 11. Recommendation and first steps

**Build the Tempo/GridEdge idea.** It is the only one where the decision has a £ number, the baseline and ceiling are clean, and the structure (forecast → optimise under constraints) is how HRT's Head of AI describes trading AI. It gives HRT's GPU spend a credible counterpart (simulation and training), and the data is free, keyless, high-frequency and local.

**First steps (also covered in `docs/`):**
1. **Accounts (one person, 15 min):** Tiger via mlh.link/tigerdata-quickstart ($1,000 credits for 30 days). Vultr via mlh.link/vultr-discover then mlh.link/vultr-signup then Billing → Gift Code ($100). Launch the cheapest GPU plan and run `nvidia-smi`.
2. **Schema:** hypertable for prices, a half-hour cagg, columnstore enabled with a policy (already drafted in `tempo/db/schema.sql`).
3. **Data:** pull one day from the Elexon price endpoint (no key), then write the backfill loop within rate limits, and fit persistence + LightGBM baselines before anyone touches a neural net.

---

## 12. Caveats

- **Past winners:** most named HRT/Citadel/Jane Street winning projects could not be verified. Prize categories and wording are confirmed; winners are not. Do not claim precedent in the pitch.
- **Unverified:** Vultr 2026 GPU pricing and stock; Tiger pgai, pgvectorscale and forking specifics; keyless status and limits for Coinbase, Wikipedia, Bluesky, OpenSky, TfL and Open-Meteo. Check each in the first hour.
- **Secondary sources:** some HRT figures (2025 revenue) come from press and secondary sites; the CoreWeave deal is confirmed by CoreWeave's own release.
- **Inference labels:** judge-preference claims are inferences from HRT's blog and prize text, not statements by OxHacks judges.
- **Elexon endpoints:** pick exact paths from the Swagger spec; rate limits apply per user and vary on some endpoints.
