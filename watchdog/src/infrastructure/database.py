from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import aiosqlite

from src.core.logger import get_logger

logger = get_logger("database")


SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_time_ms REAL NOT NULL,
    is_up INTEGER NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_telemetry (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class CheckResult:
    """
    Represents a single persisted health check result.
    """

    url: str
    status_code: int
    response_time_ms: float
    is_up: bool
    timestamp: datetime


@dataclass
class SummaryStat:
    """
    Aggregated statistics for a single monitored URL.

    :param url: Target URL.
    :param uptime_percentage: Percentage of successful checks.
    :param average_response_time_ms: Average response time in milliseconds.
    :param total_checks: Total number of recorded checks.
    :param up_checks: Number of checks where the target was up.
    """

    url: str
    uptime_percentage: float
    average_response_time_ms: float
    total_checks: int
    up_checks: int
    p50_response_time_ms: Optional[float] = None
    p95_response_time_ms: Optional[float] = None
    p99_response_time_ms: Optional[float] = None


@dataclass
class Incident:
    """
    Represents a downtime incident for a specific URL.

    An incident starts when the service transitions from up to down, and ends
    when it transitions back to up.
    """

    url: str
    started_at: datetime
    ended_at: Optional[datetime]
    down_checks: int


class Database:
    """
    Async SQLite database wrapper using aiosqlite.

    Handles schema initialization and provides methods to persist check results.
    Implements basic retry behaviour when encountering 'database is locked' errors.
    """

    def __init__(self, path: Path, connection: aiosqlite.Connection) -> None:
        self._path = path
        self._conn = connection

    @classmethod
    async def create(cls, path: Path) -> "Database":
        """
        Create and initialize a new Database instance.

        :param path: Path to the SQLite database file.
        :return: Initialized Database instance.
        """
        # Ensure parent directory exists if a path with dirs is provided.
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(path.as_posix())
        # Improve concurrency characteristics.
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA busy_timeout=5000;")  # 5 seconds
        await conn.commit()

        db = cls(path=path, connection=conn)
        await db._init_schema()
        return db

    async def _init_schema(self) -> None:
        """Create database schema if it does not exist."""
        await self._conn.executescript(SCHEMA)
        # Indexes to speed up common query patterns used in reports and incidents.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_checks_timestamp ON checks(timestamp);"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_checks_url_timestamp "
            "ON checks(url, timestamp);"
        )
        await self._conn.commit()
        logger.info("Database schema ensured at %s", self._path)

    async def close(self) -> None:
        """Close the underlying SQLite connection."""
        await self._conn.close()
        logger.info("Database connection closed")

    async def begin(self) -> None:
        """Begin an explicit transaction."""
        await self._conn.execute("BEGIN;")

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self._conn.rollback()

    async def _execute_with_retry(
        self,
        sql: str,
        params: Sequence[Any],
        *,
        retries: int = 3,
        delay: float = 0.2,
        autocommit: bool = True,
    ) -> None:
        """
        Execute a SQL statement with simple retry logic on database lock.

        :param sql: SQL query to execute.
        :param params: Positional parameters for the query.
        :param retries: Number of retry attempts on lock.
        :param delay: Delay between retries in seconds.
        """
        attempt = 0
        while True:
            try:
                await self._conn.execute(sql, params)
                if autocommit:
                    await self._conn.commit()
                return
            except aiosqlite.OperationalError as exc:
                # SQLite may signal a lock via 'database is locked'.
                message = str(exc).lower()
                if "database is locked" in message and attempt < retries:
                    attempt += 1
                    logger.warning(
                        "Database is locked while executing SQL (attempt %s/%s, path=%s); retrying in %.2fs",
                        attempt,
                        retries,
                        self._path,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

    async def insert_check_result(
        self,
        url: str,
        status_code: int,
        response_time_ms: float,
        is_up: bool,
        timestamp: Optional[datetime] = None,
        autocommit: bool = True,
    ) -> None:
        """
        Persist a health check result.

        :param url: Target URL.
        :param status_code: HTTP status code returned.
        :param response_time_ms: Response time in milliseconds.
        :param is_up: True if the service is considered up.
        :param timestamp: Optional override for timestamp; uses current UTC time otherwise.
        """
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        await self._execute_with_retry(
            """
            INSERT INTO checks (url, status_code, response_time_ms, is_up, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, status_code, response_time_ms, int(is_up), ts),
            autocommit=autocommit,
        )

    async def get_summary_stats(
        self, since: Optional[datetime] = None
    ) -> List[SummaryStat]:
        """
        Compute uptime percentage, average response time and latency percentiles per URL.

        :return: List of SummaryStat entries, one per distinct URL.
        """
        base_query = """
        SELECT
            url,
            COUNT(*) AS total_checks,
            SUM(is_up) AS up_checks,
            AVG(response_time_ms) AS avg_response_time_ms
        FROM checks
        {where_clause}
        GROUP BY url
        ORDER BY url;
        """
        params: Sequence[Any] = ()
        where_clause = ""
        if since is not None:
            where_clause = "WHERE timestamp >= ?"
            params = (since.isoformat(),)

        query = base_query.format(where_clause=where_clause)
        aggregates: Dict[str, SummaryStat] = {}
        async with self._conn.execute(query, params) as cursor:
            async for row in cursor:
                url, total_checks, up_checks, avg_response_time_ms = row
                total_checks_int = int(total_checks or 0)
                up_checks_int = int(up_checks or 0)
                if total_checks_int > 0:
                    uptime_percentage = (up_checks_int / total_checks_int) * 100.0
                else:
                    uptime_percentage = 0.0
                aggregates[url] = SummaryStat(
                    url=url,
                    uptime_percentage=uptime_percentage,
                    average_response_time_ms=float(avg_response_time_ms or 0.0),
                    total_checks=total_checks_int,
                    up_checks=up_checks_int,
                )

        if not aggregates:
            return []

        # Fetch per-URL response time samples to compute percentiles in Python.
        where_clause_rt = ""
        params_rt: Sequence[Any] = ()
        if since is not None:
            where_clause_rt = "WHERE timestamp >= ?"
            params_rt = (since.isoformat(),)

        rt_query = f"""
        SELECT url, response_time_ms
        FROM checks
        {where_clause_rt}
        ORDER BY url, response_time_ms;
        """

        current_url: Optional[str] = None
        samples: List[float] = []

        async def _finalise_url(url: str, values: List[float]) -> None:
            if not values:
                return

            def _percentile(sorted_values: List[float], p: float) -> float:
                if not sorted_values:
                    return 0.0
                k = (len(sorted_values) - 1) * p
                f = int(k)
                c = min(f + 1, len(sorted_values) - 1)
                if f == c:
                    return sorted_values[f]
                d0 = sorted_values[f] * (c - k)
                d1 = sorted_values[c] * (k - f)
                return d0 + d1

            stat = aggregates.get(url)
            if stat is None:
                return

            p50 = _percentile(values, 0.50)
            p95 = _percentile(values, 0.95)
            p99 = _percentile(values, 0.99)

            stat.p50_response_time_ms = p50
            stat.p95_response_time_ms = p95
            stat.p99_response_time_ms = p99

        async with self._conn.execute(rt_query, params_rt) as cursor:
            async for row in cursor:
                url, rt = row
                if url != current_url:
                    if current_url is not None:
                        await _finalise_url(current_url, samples)
                    current_url = url
                    samples = []
                samples.append(float(rt))

        if current_url is not None:
            await _finalise_url(current_url, samples)

        return list(aggregates.values())

    async def get_last_error_timestamps(
        self,
        since: Optional[datetime] = None,
    ) -> Dict[str, Optional[datetime]]:
        """
        Return the timestamp of the most recent failed check per URL.

        A failed check is defined as is_up = 0. If no failure exists for a URL
        in the given window, the entry will be absent from the result.
        """
        where_clause = "WHERE is_up = 0"
        params: list[Any] = []
        if since is not None:
            where_clause += " AND timestamp >= ?"
            params.append(since.isoformat())

        query = f"""
        SELECT url, MAX(timestamp) AS last_error_ts
        FROM checks
        {where_clause}
        GROUP BY url;
        """

        results: Dict[str, Optional[datetime]] = {}
        async with self._conn.execute(query, params) as cursor:
            async for row in cursor:
                url, ts_str = row
                if ts_str is None:
                    results[str(url)] = None
                else:
                    results[str(url)] = datetime.fromisoformat(str(ts_str))

        return results

    async def iter_checks(
        self,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> AsyncIterator[tuple[str, int, float, bool, str]]:
        """
        Asynchronously iterate over raw check records, optionally bounded by
        a timestamp range.

        :param since: Lower bound (inclusive) on ISO-8601 timestamp.
        :param until: Upper bound (inclusive) on ISO-8601 timestamp.
        :yield: Tuples of (url, status_code, response_time_ms, is_up, timestamp_str).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until.isoformat())
        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        query = f"""
        SELECT url, status_code, response_time_ms, is_up, timestamp
        FROM checks
        {where_clause}
        ORDER BY timestamp;
        """
        async with self._conn.execute(query, params) as cursor:
            async for row in cursor:
                url, status_code, rt_ms, is_up_int, ts_str = row
                yield url, int(status_code), float(rt_ms), bool(is_up_int), str(ts_str)

    async def delete_checks_in_range(
        self,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> None:
        """
        Delete check records within an optional timestamp range.

        :param since: Lower bound (inclusive) on timestamp.
        :param until: Upper bound (inclusive) on timestamp.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until.isoformat())
        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        query = f"DELETE FROM checks {where_clause};"
        await self._execute_with_retry(query, tuple(params), autocommit=True)

    async def get_incidents(self, since: Optional[datetime] = None) -> List[Incident]:
        """
        Derive downtime incidents per URL from the raw check history.

        :param since: Optional lower bound on timestamp (UTC). If provided,
                      only checks at or after this time are considered.
        :return: List of Incident objects ordered by URL and start time.
        """
        params: Sequence[Any] = ()
        where_clause = ""
        if since is not None:
            where_clause = "WHERE timestamp >= ?"
            params = (since.isoformat(),)

        query = f"""
        SELECT url, is_up, timestamp
        FROM checks
        {where_clause}
        ORDER BY url, timestamp;
        """

        incidents: List[Incident] = []
        current_url: Optional[str] = None
        last_was_up: Optional[bool] = None
        open_incident_start: Optional[datetime] = None
        open_incident_down_checks = 0

        async with self._conn.execute(query, params) as cursor:
            async for row in cursor:
                url, is_up_int, ts_str = row
                is_up = bool(is_up_int)
                ts = datetime.fromisoformat(ts_str)

                if url != current_url:
                    # Flush any open incident when switching URLs.
                    if current_url is not None and open_incident_start is not None:
                        incidents.append(
                            Incident(
                                url=current_url,
                                started_at=open_incident_start,
                                ended_at=None,
                                down_checks=open_incident_down_checks,
                            )
                        )
                    current_url = url
                    last_was_up = None
                    open_incident_start = None
                    open_incident_down_checks = 0

                if last_was_up is None:
                    # First sample for this URL.
                    last_was_up = is_up
                    if not is_up:
                        open_incident_start = ts
                        open_incident_down_checks = 1
                    continue

                if last_was_up and not is_up:
                    # Transition: UP -> DOWN: start incident.
                    open_incident_start = ts
                    open_incident_down_checks = 1
                elif not last_was_up and not is_up:
                    # Still down: extend incident.
                    if open_incident_start is None:
                        open_incident_start = ts
                    open_incident_down_checks += 1
                elif not last_was_up and is_up:
                    # Transition: DOWN -> UP: close incident.
                    if open_incident_start is not None:
                        incidents.append(
                            Incident(
                                url=url,
                                started_at=open_incident_start,
                                ended_at=ts,
                                down_checks=open_incident_down_checks,
                            )
                        )
                    open_incident_start = None
                    open_incident_down_checks = 0

                last_was_up = is_up

        # Flush any remaining open incident at EOF.
        if current_url is not None and open_incident_start is not None:
            incidents.append(
                Incident(
                    url=current_url,
                    started_at=open_incident_start,
                    ended_at=None,
                    down_checks=open_incident_down_checks,
                )
            )

        return incidents

    async def upsert_telemetry(self, key: str, value: str) -> None:
        """
        Upsert a telemetry key/value pair into the system_telemetry table.
        """
        await self._execute_with_retry(
            """
            INSERT INTO system_telemetry (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value;
            """,
            (key, value),
            autocommit=True,
        )

    async def get_telemetry(self, key: str) -> Optional[str]:
        """
        Retrieve a telemetry value by key from the system_telemetry table.
        """
        async with self._conn.execute(
            "SELECT value FROM system_telemetry WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = ["Database", "CheckResult", "SummaryStat", "Incident"]
