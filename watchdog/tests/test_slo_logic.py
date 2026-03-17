from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.infrastructure.database import Database
from src.services.slo import SloConfig, compute_slo_results, load_slo_config


@pytest.mark.asyncio
async def test_compute_slo_results_with_sample_data(tmp_path: Path) -> None:
    db_path = tmp_path / "slo.db"
    db = await Database.create(db_path)

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)

    # Two URLs for the same logical service (tccb).
    await db.insert_check_result(
        "https://www.tccb.gov.tr",
        status_code=200,
        response_time_ms=1000.0,
        is_up=True,
        timestamp=past,
    )
    await db.insert_check_result(
        "https://www.tccb.gov.tr",
        status_code=500,
        response_time_ms=2000.0,
        is_up=False,
        timestamp=past + timedelta(minutes=1),
    )
    await db.insert_check_result(
        "https://mirror.tccb.gov.tr",
        status_code=200,
        response_time_ms=1500.0,
        is_up=True,
        timestamp=past + timedelta(minutes=2),
    )

    # Minimal inline SLO config.
    cfg = SloConfig.parse_obj(
        {
            "services": [
                {
                    "name": "tccb",
                    "url_contains": "tccb.gov.tr",
                    "target_uptime_percent": 50.0,
                    "target_p95_ms": 5000.0,
                }
            ]
        }
    )

    results = await compute_slo_results(db=db, config=cfg, now=now)
    await db.close()

    assert len(results) == 1
    res = results[0]
    assert res.service == "tccb"
    # Uptime somewhere between 0 and 100 and p95 > 0
    assert 0.0 <= res.uptime_percent <= 100.0
    assert res.p95_ms > 0.0


def test_load_slo_config(tmp_path: Path) -> None:
    path = tmp_path / "slo.yaml"
    path.write_text(
        """
services:
  - name: "demo"
    url_contains: "example.com"
    target_uptime_percent: 99.0
    target_p95_ms: 5000
        """,
        encoding="utf-8",
    )

    cfg = load_slo_config(path)
    assert len(cfg.services) == 1
    svc = cfg.services[0]
    assert svc.name == "demo"
    assert svc.url_contains == "example.com"
    assert svc.target_uptime_percent == 99.0
    assert svc.target_p95_ms == 5000


@pytest.mark.asyncio
async def test_slo_status_pass_partial_fail(tmp_path: Path) -> None:
    """
    Verify that SloResult.status derives PASS / PARTIAL / FAIL correctly
    based on uptime_ok and latency_ok.
    """
    db_path = tmp_path / "slo_status.db"
    db = await Database.create(db_path)

    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)

    # Helper to create a config with single service and compute result.
    async def _compute_for(
        uptime_percent: float,
        p95_ms: float,
        target_uptime: float,
        target_p95: float,
    ) -> str:
        # We bypass real stats aggregation by directly inserting one synthetic URL
        # whose aggregated values will match the provided uptime/p95 pair.
        url = "https://status.example.com"

        # Encode uptime_percent via up/total checks: use 100 checks for simplicity.
        total_checks = 100
        up_checks = int(total_checks * max(0.0, min(100.0, uptime_percent)) / 100.0)

        # Insert up_checks successes and the rest failures with the same response time
        # so that p95 ~= p95_ms.
        for _ in range(up_checks):
            await db.insert_check_result(
                url,
                status_code=200,
                response_time_ms=p95_ms,
                is_up=True,
                timestamp=past,
            )
        for _ in range(total_checks - up_checks):
            await db.insert_check_result(
                url,
                status_code=500,
                response_time_ms=p95_ms,
                is_up=False,
                timestamp=past,
            )

        cfg = SloConfig.parse_obj(
            {
                "services": [
                    {
                        "name": "demo",
                        "url_contains": "status.example.com",
                        "target_uptime_percent": target_uptime,
                        "target_p95_ms": target_p95,
                    }
                ]
            }
        )

        results = await compute_slo_results(db=db, config=cfg, now=now)
        assert len(results) == 1
        return results[0].status

    # PASS: both uptime and latency targets are met.
    status_pass = await _compute_for(
        uptime_percent=99.9,
        p95_ms=1000.0,
        target_uptime=99.0,
        target_p95=2000.0,
    )
    assert status_pass == "PASS"

    # PARTIAL: uptime target met, latency target violated.
    status_partial_uptime_only = await _compute_for(
        uptime_percent=99.9,
        p95_ms=6000.0,
        target_uptime=99.0,
        target_p95=4000.0,
    )
    assert status_partial_uptime_only == "PARTIAL"

    # FAIL: neither target met.
    status_fail = await _compute_for(
        uptime_percent=80.0,
        p95_ms=8000.0,
        target_uptime=99.0,
        target_p95=4000.0,
    )
    assert status_fail == "FAIL"

    await db.close()

