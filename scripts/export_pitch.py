"""Export the data the pitch site (pitch/) draws, as small JSON files in pitch/data/.

Owner: Ayo. Read-only against TEMPO_DATABASE_URL. The site is a static export, so these files are the
snapshot it ships with; re-run before a rehearsal to refresh them.

    python scripts/export_pitch.py            # all chapters
    python scripts/export_pitch.py hook       # one chapter
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tempo.db.conn import get_conn

OUT = Path(__file__).resolve().parents[1] / "pitch" / "data"
LONDON = ZoneInfo("Europe/London")

HOOK_DAY = date(2026, 3, 25)
HOOK_WINDOW = 4  # half-hours to fill or empty the 2 MWh battery at 1 MW
HOOK_NOW = "02:00"  # where the "now" line drops in
RANGE_DAYS = 28  # the uncertain band: p10-p90 of the same half-hour over the previous 4 weeks
BACKTEST_RUN = "db-20261024T202144Z"  # the 100-week walk-forward run quoted in docs/description.md


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=LONDON)
    return start, start + timedelta(days=1)


def _best_windows(prices: list[float], n: int) -> tuple[int, int]:
    """Start index of the dearest n-period window, and of the cheapest n-period window that ends before it."""
    avg = [sum(prices[i : i + n]) / n for i in range(len(prices) - n + 1)]
    sell = max(range(len(avg)), key=avg.__getitem__)
    buy = min(range(sell - n + 1), key=avg.__getitem__)
    return buy, sell


def hook(conn) -> dict:
    start, end = _day_bounds(HOOK_DAY)
    prices = pd.DataFrame(
        conn.execute(
            "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket < %s ORDER BY bucket",
            (start, end),
        ).fetchall(),
        columns=["bucket", "price"],
    )
    if len(prices) != 48 or prices.price.isna().any():
        raise SystemExit(f"{HOOK_DAY}: expected 48 priced periods, got {prices.price.notna().sum()}")

    # Wind as a share of generation, per half-hour, to say why the night is cheap.
    mix = pd.DataFrame(
        conn.execute(
            """SELECT start_time, sum(value) FILTER (WHERE series = 'WIND') AS wind, sum(value) AS total
               FROM (SELECT DISTINCT ON (start_time, series) start_time, series, value FROM grid_raw
                     WHERE dataset = 'FUELHH' AND start_time >= %s AND start_time < %s
                     ORDER BY start_time, series, available_at DESC) latest
               GROUP BY 1 ORDER BY 1""",
            (start, end),
        ).fetchall(),
        columns=["bucket", "wind", "total"],
    )
    wind_share = dict(zip(mix.bucket, mix.wind / mix.total, strict=True))

    # Same half-hour over the previous four weeks, for the "you don't know tonight's price" band.
    hist = pd.DataFrame(
        conn.execute(
            "SELECT bucket, price FROM prices_hh WHERE bucket >= %s AND bucket < %s AND price IS NOT NULL",
            (start - timedelta(days=RANGE_DAYS), start),
        ).fetchall(),
        columns=["bucket", "price"],
    )
    hist["slot"] = [b.astimezone(LONDON).strftime("%H:%M") for b in hist.bucket]
    band = hist.groupby("slot").price.quantile([0.1, 0.9]).unstack()

    p = prices.price.round(2).tolist()
    buy, sell = _best_windows(p, HOOK_WINDOW)
    lo = min(range(48), key=p.__getitem__)
    hi = max(range(48), key=p.__getitem__)
    periods = []
    for i, row in prices.iterrows():
        t = row.bucket.astimezone(LONDON).strftime("%H:%M")
        ws = wind_share.get(row.bucket)
        periods.append(
            {
                "t": t,
                "price": p[i],
                "wind_share": None if ws is None else round(float(ws), 3),
                "range_lo": round(float(band.loc[t, 0.1]), 2),
                "range_hi": round(float(band.loc[t, 0.9]), 2),
            }
        )
    tempo = conn.execute(
        """SELECT count(*), sum(pnl_gbp), sum(perfect_pnl_gbp), count(*) FILTER (WHERE pnl_gbp < 0)
           FROM backtest_results WHERE run_id = %s AND strategy = 'tempo'""",
        (BACKTEST_RUN,),
    ).fetchone()
    weeks, pnl, perfect, losing = tempo
    buy_avg = sum(p[buy : buy + HOOK_WINDOW]) / HOOK_WINDOW
    sell_avg = sum(p[sell : sell + HOOK_WINDOW]) / HOOK_WINDOW
    return {
        "day": HOOK_DAY.isoformat(),
        "source": "APX MID price (prices_hh); wind share from FUELHH",
        "periods": periods,
        "low": {"i": lo, "t": periods[lo]["t"], "price": p[lo]},
        "high": {"i": hi, "t": periods[hi]["t"], "price": p[hi]},
        "charge": {"from": buy, "to": buy + HOOK_WINDOW - 1, "avg": round(buy_avg, 2)},
        "sell": {"from": sell, "to": sell + HOOK_WINDOW - 1, "avg": round(sell_avg, 2)},
        "spread": round(sell_avg - buy_avg, 2),
        "now": HOOK_NOW,
        "range_days": RANGE_DAYS,
        "headline": {
            "run_id": BACKTEST_RUN,
            "weeks": weeks,
            "pct_of_perfect": round(100 * pnl / perfect, 1),
            "pnl_gbp": round(pnl),
            "losing_weeks": losing,
        },
    }


CHAPTERS = {
    "hook": hook,
}


def main(names: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        for name in names or CHAPTERS:
            data = CHAPTERS[name](conn)
            path = OUT / f"{name}.json"
            path.write_text(json.dumps(data, indent=1) + "\n")
            print(f"wrote {path.relative_to(OUT.parents[1])}")


if __name__ == "__main__":
    main(sys.argv[1:])
