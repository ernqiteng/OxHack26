"""storage_stats(conn) -> rows, bytes before/after compression, ratio; compress_chunks(); storage_mb().

Owner: Girik. See docs/girik.md (Phase 3, pulled forward because the backfill needs compression).
"""

from __future__ import annotations

import psycopg
from psycopg import sql

from tempo.db.conn import run_sql


def storage_mb(conn: psycopg.Connection) -> float:
    """Size of the whole database in MiB (the number the Tiger free-service cap is measured against)."""
    return run_sql(conn, "SELECT pg_database_size(current_database()) / 1048576.0")[0][0]


def compress_chunks(
    conn: psycopg.Connection, older_than: str = "7 days", table: str = "grid_raw", vacuum: bool = True
) -> int:
    """Compress uncompressed chunks and recompress partially compressed ones, for chunks whose range ends
    before now - older_than. Chunks that are fully compressed and untouched are skipped, so this is cheap
    enough to call after every backfill window.

    Returns the number of chunks touched. Rows inserted into a compressed chunk sit uncompressed until
    this runs again.
    """
    rows = run_sql(
        conn,
        "SELECT compress_chunk(c.relid, if_not_compressed => true) "
        "FROM _timescaledb_catalog.chunk c "
        "JOIN _timescaledb_catalog.hypertable h ON h.id = c.hypertable_id "
        "WHERE h.table_name = %s "
        "  AND c.relid IN (SELECT show_chunks(%s, older_than => %s::interval)) "
        "  AND ((c.status & 1) = 0 OR (c.status & 8) <> 0)",  # 1 = compressed, 8 = partial (new heap rows)
        (table, table, older_than),
    )
    # Compression empties the chunk heap but leaves its PK and index pages behind (measured: 3 MB of stale
    # index per chunk vs 64 kB of compressed data). REINDEX on the empty heap drops them to a page each.
    for (chunk,) in rows:
        conn.execute(sql.SQL("REINDEX TABLE {}").format(sql.Identifier(*str(chunk).split("."))))
    # Recompressing rewrites the compressed batches and leaves the old ones as dead tuples. On the 2-year
    # local run that showed as 193 MiB right after NDF versus 62 MB once autovacuum had run. Vacuum now so
    # the Tiger free-service cap sees the real size, not the transient one. Needs autocommit (VACUUM
    # cannot run in a transaction), which get_conn() gives by default.
    if rows and vacuum and conn.autocommit:
        conn.execute(sql.SQL("VACUUM {}").format(sql.Identifier(table)))
    return len(rows)


def chunk_residue(conn: psycopg.Connection, table: str = "grid_raw") -> dict:
    """What is left outside the columnstore on compressed chunks: rows still in the heap (not yet
    recompressed) and bytes of heap indexes. Both should be ~0 right after compress_chunks()."""
    chunks = run_sql(
        conn,
        "SELECT c.relid::text, pg_indexes_size(c.relid) FROM _timescaledb_catalog.chunk c "
        "JOIN _timescaledb_catalog.hypertable h ON h.id = c.hypertable_id "
        "WHERE h.table_name = %s AND (c.status & 1) = 1",
        (table,),
    )
    heap_rows = 0
    for relid, _ in chunks:
        heap_rows += run_sql(conn, sql.SQL("SELECT count(*) FROM ONLY {}").format(_ident(relid)))[0][0]
    return {
        "compressed_chunks": len(chunks),
        "heap_rows": heap_rows,
        "index_bytes": sum(b for _, b in chunks),
    }


def _ident(relid: str) -> sql.Composed:
    return sql.Identifier(*relid.split("."))


def tiger_storage_mb(client=None, service_id: str | None = None) -> float:
    """Tiger's own `metrics.storage_mb` for the primary service: the number the 750 MB free-service cap is
    enforced on. It includes ~340 MB of Tiger overhead that pg_database_size() does not see, so storage
    guards against Tiger must use this, never storage_mb(conn)."""
    from tempo.config import settings
    from tempo.infra.tiger import TigerClient

    service_id = service_id or settings().tiger.primary_service_id
    if not service_id:
        raise RuntimeError("TIGER_PRIMARY_SERVICE_ID is not set")
    client = client or TigerClient.from_env()
    metrics = client.get(service_id).raw.get("metrics") or {}
    if metrics.get("storage_mb") is None:
        raise RuntimeError(f"Tiger service {service_id} returned no metrics.storage_mb")
    return float(metrics["storage_mb"])


def storage_stats(conn: psycopg.Connection, table: str = "grid_raw") -> dict:
    """Rows, bytes before/after compression and the ratio: the dashboard's "X rows, compressed Y%" line."""
    (rows,) = run_sql(conn, f"SELECT count(*) FROM {table}")[0]  # noqa: S608 (table is ours)
    stats = run_sql(
        conn,
        "SELECT coalesce(total_chunks, 0), coalesce(number_compressed_chunks, 0), "
        "coalesce(before_compression_total_bytes, 0), coalesce(after_compression_total_bytes, 0) "
        "FROM hypertable_compression_stats(%s)",
        (table,),
    )
    total_chunks, compressed_chunks, before, after = stats[0] if stats else (0, 0, 0, 0)
    (size_bytes,) = run_sql(conn, "SELECT hypertable_size(%s)", (table,))[0]
    ratio = (before / after) if after else 1.0
    return {
        "rows": rows,
        "total_chunks": total_chunks,
        "compressed_chunks": compressed_chunks,
        "before_bytes": before,
        "after_bytes": after,
        "ratio": ratio,
        "pct_saved": (1 - 1 / ratio) * 100 if ratio else 0.0,
        "size_bytes": size_bytes,
        "database_mb": storage_mb(conn),
    }
