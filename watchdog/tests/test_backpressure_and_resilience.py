from pathlib import Path
from typing import List

import aiosqlite
import pytest
from aiohttp import ClientSession, web

from src.core.config import AppSettings
from src.infrastructure.database import Database
from src.services.monitor import _adjust_concurrency, _check_target
from src.models.target import Target


class DummySettings(AppSettings):
    class Config(AppSettings.Config):
        env_file = None


@pytest.mark.parametrize(
    "effective,target_max,timeout_ratio,http_5xx_ratio,elapsed,poll,expected",
    [
        # High timeout ratio -> multiplicative decrease.
        (10, 20, 0.5, 0.0, 5.0, 10.0, 7),
        # Slow wave -> multiplicative decrease.
        (10, 20, 0.0, 0.0, 9.0, 10.0, 7),
        # Healthy & fast -> additive increase.
        (5, 10, 0.0, 0.0, 2.0, 10.0, 6),
        # At max already -> no increase.
        (10, 10, 0.0, 0.0, 2.0, 10.0, 10),
        # Below 1 is normalised to 1.
        (0, 10, 0.0, 0.0, 2.0, 10.0, 2),
    ],
)
def test_adjust_concurrency_behavior(
    effective: int,
    target_max: int,
    timeout_ratio: float,
    http_5xx_ratio: float,
    elapsed: float,
    poll: float,
    expected: int,
) -> None:
    """
    Ensure AIMD backpressure helper adjusts concurrency as expected.
    """
    new_limit = _adjust_concurrency(
        effective_limit=effective,
        target_max=target_max,
        timeout_ratio=timeout_ratio,
        http_5xx_ratio=http_5xx_ratio,
        elapsed=elapsed,
        poll_interval_seconds=poll,
    )
    assert new_limit == expected


@pytest.mark.asyncio
async def test_database_locked_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Simulate a 'database is locked' scenario and verify that _execute_with_retry
    performs retries instead of failing immediately.
    """
    db_path = tmp_path / "locked.db"
    db = await Database.create(db_path)

    original_execute = db._conn.execute
    call_count: List[int] = [0]

    async def flaky_execute(sql: str, params: tuple) -> None:  # type: ignore[override]
        call_count[0] += 1
        # First two attempts raise 'database is locked', third succeeds.
        if call_count[0] <= 2:
            raise aiosqlite.OperationalError("database is locked")
        await original_execute(sql, params)

    monkeypatch.setattr(db._conn, "execute", flaky_execute)

    await db.insert_check_result("https://example.com", 200, 100.0, True)
    # Should have retried at least twice before succeeding.
    assert call_count[0] >= 3

    await db.close()


@pytest.mark.asyncio
async def test_check_target_with_invalid_json_body(tmp_path: Path, unused_tcp_port: int) -> None:
    """
    Run _check_target against a local aiohttp server that returns invalid JSON.

    When expected_json_key is set, the target should be marked as down if the
    payload cannot be parsed, even if HTTP 200 is returned.
    """

    async def handler(_request: web.Request) -> web.Response:
        # Deliberately invalid JSON payload.
        return web.Response(text="{ this is not valid json", content_type="application/json")

    app = web.Application()
    app.router.add_get("/bad-json", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()

    try:
        db_path = tmp_path / "bad_json.db"
        db = await Database.create(db_path)

        settings = DummySettings(
            db_path=db_path,
            poll_interval_seconds=30.0,
            request_timeout_seconds=5.0,
            allow_private_ips=True,  # test server runs on 127.0.0.1
        )

        target = Target(
            url=f"http://127.0.0.1:{unused_tcp_port}/bad-json",
            expected_status=200,
            timeout=5,
            method="GET",
            expected_json_key="foo",
        )

        async with ClientSession() as session:
            url, is_up, status_code, elapsed_ms, _ = await _check_target(
                session,
                db,
                target,
                settings,
            )

        # Request succeeded at HTTP level but JSON parsing failed, so target
        # must be considered down.
        assert url == str(target.url)
        assert status_code == 200
        assert not is_up
        assert elapsed_ms > 0.0

        stats = await db.get_summary_stats()
        assert len(stats) == 1
        stat = stats[0]
        assert stat.url == str(target.url)
        assert stat.up_checks == 0

        await db.close()
    finally:
        await runner.cleanup()

