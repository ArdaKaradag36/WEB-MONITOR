import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.infrastructure.database import Database


@pytest.mark.asyncio
async def test_get_summary_stats_and_incidents(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    db = await Database.create(db_path)

    now = datetime.now(timezone.utc)

    # Insert simple pattern: up, down, down, up for a single URL.
    url = "https://example.com"
    await db.insert_check_result(url, 200, 100.0, True, timestamp=now)
    await db.insert_check_result(url, 500, 120.0, False, timestamp=now + timedelta(seconds=10))
    await db.insert_check_result(url, 500, 130.0, False, timestamp=now + timedelta(seconds=20))
    await db.insert_check_result(url, 200, 110.0, True, timestamp=now + timedelta(seconds=30))

    stats = await db.get_summary_stats()
    assert len(stats) == 1
    stat = stats[0]
    assert stat.url == url
    assert stat.total_checks == 4
    assert stat.up_checks == 2
    assert stat.uptime_percentage == pytest.approx(50.0)

    incidents = await db.get_incidents()
    # One incident: from first down to recovery.
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.url == url
    assert inc.down_checks == 2
    assert inc.started_at == now + timedelta(seconds=10)
    assert inc.ended_at == now + timedelta(seconds=30)

    await db.close()

