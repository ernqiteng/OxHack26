"""get_conn(), run_sql(), apply_schema(), copy_rows(), upsert_grid_raw(). psycopg 3.

Owner: Girik. See docs/girik.md.

CLI (the Tiger path, since Windows has no psql):
    python -m tempo.db.conn apply    # apply schema.sql to TEMPO_DATABASE_URL
    python -m tempo.db.conn check    # list hypertables, caggs and row counts
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

GRID_RAW_COLUMNS = (
    "start_time",
    "available_at",
    "dataset",
    "series",
    "value",
    "settlement_date",
    "settlement_period",
)
GRID_RAW_REQUIRED = ("start_time", "available_at", "dataset", "value")


def get_conn(url: str | None = None, autocommit: bool = True) -> psycopg.Connection:
    """Connect to `url`, or TEMPO_DATABASE_URL from the environment / .env."""
    if url is None:
        load_dotenv()
        url = os.environ.get("TEMPO_DATABASE_URL")
    if not url:
        raise RuntimeError("TEMPO_DATABASE_URL is not set (copy .env.example to .env)")
    return psycopg.connect(url, autocommit=autocommit)


def run_sql(conn: psycopg.Connection, query: str, params: Sequence | dict | None = None) -> list[tuple]:
    """Execute one statement and return its rows ([] for statements without a result)."""
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall() if cur.description else []


def split_statements(text: str) -> list[str]:
    """Split a SQL file into statements. Strips `--` comments first, so a ';' in a comment is safe.

    Deliberately simple: schema.sql must not contain $$ bodies or '--'/';' inside string literals.
    """
    if "$$" in text:
        raise ValueError("schema.sql contains a $$ body; split_statements cannot handle it")
    no_comments = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def apply_schema(conn: psycopg.Connection, path: Path = SCHEMA_PATH) -> int:
    """Apply schema.sql one statement at a time (like psql -f). Idempotent. Returns statements run."""
    statements = split_statements(path.read_text(encoding="utf-8"))
    for stmt in statements:
        conn.execute(stmt)
    return len(statements)


def copy_rows(conn: psycopg.Connection, table: str, rows: Iterable[Sequence], columns: Sequence[str]) -> int:
    """Bulk insert with COPY. No conflict handling: use upsert_grid_raw for grid_raw."""
    stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    n = 0
    with conn.cursor() as cur, cur.copy(stmt) as cp:
        for row in rows:
            cp.write_row(row)
            n += 1
    return n


def _to_utc(col: pd.Series, name: str) -> pd.Series:
    # Naive timestamps are rejected rather than assumed UTC: a silent 1-hour BST shift would leak the future.
    if not isinstance(col.dtype, pd.DatetimeTZDtype):
        col = pd.to_datetime(col)
        if not isinstance(col.dtype, pd.DatetimeTZDtype):
            raise ValueError(f"{name} must be timezone-aware (UTC); got naive timestamps")
    return col.dt.tz_convert("UTC")


def grid_raw_rows(df: pd.DataFrame) -> list[tuple]:
    """Validate a grid_raw-format DataFrame and turn it into COPY-ready tuples (None for missing)."""
    missing = [c for c in GRID_RAW_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"grid_raw frame missing columns: {missing}")
    out = pd.DataFrame(index=df.index)
    out["start_time"] = _to_utc(df["start_time"], "start_time")
    out["available_at"] = _to_utc(df["available_at"], "available_at")
    out["dataset"] = df["dataset"].astype(str)
    out["series"] = df["series"].fillna("").astype(str) if "series" in df else ""
    out["value"] = df["value"].astype(float)
    if out["value"].isna().any():
        raise ValueError("grid_raw value contains NaN")
    out["settlement_date"] = (
        pd.to_datetime(df["settlement_date"]).dt.date if "settlement_date" in df else None
    )
    out["settlement_period"] = df["settlement_period"] if "settlement_period" in df else None

    rows = []
    for st, av, ds, se, va, sd, sp in out.itertuples(index=False, name=None):
        rows.append(
            (
                st.to_pydatetime(),
                av.to_pydatetime(),
                ds,
                se,
                va,
                None if pd.isna(sd) else sd,
                None if pd.isna(sp) else int(sp),
            )
        )
    return rows


def upsert_grid_raw(conn: psycopg.Connection, df: pd.DataFrame) -> int:
    """Insert grid_raw rows, skipping any whose primary key already exists. Returns rows inserted.

    COPY into a temp staging table, then INSERT ... ON CONFLICT DO NOTHING: COPY is ~10x faster than
    executemany but has no conflict handling, so the staging table gives us both.
    """
    rows = grid_raw_rows(df)
    if not rows:
        return 0
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE _grid_raw_stage (LIKE grid_raw INCLUDING DEFAULTS) ON COMMIT DROP")
        copy_rows(conn, "_grid_raw_stage", rows, GRID_RAW_COLUMNS)
        cols = ", ".join(GRID_RAW_COLUMNS)
        cur.execute(
            f"INSERT INTO grid_raw ({cols}) SELECT {cols} FROM _grid_raw_stage ON CONFLICT DO NOTHING"
        )
        return cur.rowcount


def _check(conn: psycopg.Connection) -> None:
    (version,) = run_sql(conn, "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")[0]
    print(f"timescaledb {version}")
    hts = run_sql(
        conn,
        "SELECT hypertable_name FROM timescaledb_information.hypertables "
        "WHERE hypertable_schema = 'public' ORDER BY 1",
    )
    print("hypertables:", ", ".join(r[0] for r in hts))
    caggs = run_sql(conn, "SELECT view_name FROM timescaledb_information.continuous_aggregates ORDER BY 1")
    print("caggs:", ", ".join(r[0] for r in caggs))
    for table in ("grid_raw", "prices_hh", "prices_daily", "prices_weekly"):
        (n,) = run_sql(conn, sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))[0]
        print(f"{table}: {n} rows")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("apply", "check"):
        print("usage: python -m tempo.db.conn apply|check", file=sys.stderr)
        return 2
    with get_conn() as conn:
        if argv[0] == "apply":
            n = apply_schema(conn)
            print(f"applied {n} statements")
        _check(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
