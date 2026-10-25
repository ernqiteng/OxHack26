# Tempo web frontend

A Next.js frontend modelled on the ICHack26 wildfire app (github.com/ltanak/ICHack26): a gradient splash page,
a full-width interactive "map" hero, and a detail panel driven by what you click on it.

| ICHack26 | Tempo |
|---|---|
| World map with wildfire markers | Decision map: settled prices as terrain, decision pins, today's forecast plan past the "now" line. Scroll to zoom, drag to pan |
| Claude-written fire summary with typewriter reveal | Decision summary built from stored numbers only, same typewriter reveal |
| Mitigation allocator (canvas + control panel + instructions) | Timing audit: replays the decision ±30 and ±60 min, bars per timeline, headline sentence |
| Drag-to-compare satellite overlay | Forecast p50 vs settled price over the replay week |
| Percolation simulation grid with Start / Pause / Reset | Replay simulation: the week played back half-hour by half-hour with state of charge and running P&L |

Fork-mode audits (Tiger fork + Vultr workers) stay in the Streamlit dashboard; this frontend runs the
in-process replay.

## Run

```bash
make api    # FastAPI JSON layer, tempo/api/server.py, on 127.0.0.1:8000
make web    # npm install + next dev on http://localhost:3000
```

`/api/*` is proxied to the API (set `TEMPO_API_URL` to point elsewhere). The API reads the same data source
as the dashboard: Tiger when `TEMPO_DATABASE_URL` is reachable, synthetic data otherwise, shown by the pill
in the top bar. Running an audit against Tiger writes `battery_state` rows under `audit-*` run ids, as the
dashboard's in-process audit does.
