import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pytest

from src.core.config import AppSettings
from src.infrastructure.database import Database
from src.infrastructure.notifiers import ConsoleNotifier
from src.models.target import Target
from src.services.monitor import _check_target


class DummySettings(AppSettings):
    class Config(AppSettings.Config):
        env_file = None


@pytest.mark.asyncio
async def test_check_target_allowed_statuses_and_latency(tmp_path: Path) -> None:
    db_path = tmp_path / "test_health.db"
    db = await Database.create(db_path)

    settings = DummySettings(
        db_path=db_path,
        poll_interval_seconds=30.0,
        request_timeout_seconds=5.0,
        targets_file=Path("config/targets.yaml"),
    )

    # Use a simple HTTP endpoint that should return 204.
    target = Target(
        url="https://httpbin.org/status/204",
        expected_status=200,
        allowed_statuses=[200, 204],
        timeout=5,
        method="GET",
    )

    connector = aiohttp.TCPConnector(limit_per_host=5)
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        await _check_target(session, db, target, settings)

    stats = await db.get_summary_stats()
    # There should be one entry and it should be considered up thanks to allowed_statuses.
    assert len(stats) == 1
    stat = stats[0]
    assert stat.url == str(target.url)
    assert stat.up_checks == 1

    await db.close()

