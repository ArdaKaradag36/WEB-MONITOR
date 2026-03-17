from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import AppSettings, load_settings
from src.infrastructure.database import Database
from src.services.slo import SloConfig, compute_slo_results, load_slo_config


app = FastAPI(title="WatchDog API")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


async def _get_db(settings: AppSettings) -> Database:
    return await Database.create(settings.db_path)


@app.get("/api/status")
async def api_status(last_minutes: float = 5.0) -> List[dict[str, Any]]:
    settings: AppSettings = load_settings()
    db = await _get_db(settings)
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=last_minutes)
        stats = await db.get_summary_stats(since=since)
        last_errors = await db.get_last_error_timestamps(since=since)
    finally:
        await db.close()

    items: List[dict[str, Any]] = []
    for s in stats:
        last_err = last_errors.get(s.url)
        last_err_str = (
            last_err.astimezone(timezone.utc).isoformat(timespec="seconds")
            if last_err is not None
            else None
        )
        items.append(
            {
                "url": s.url,
                "uptime_percent": s.uptime_percentage,
                "avg_ms": s.average_response_time_ms,
                "p50_ms": s.p50_response_time_ms,
                "p95_ms": s.p95_response_time_ms,
                "p99_ms": s.p99_response_time_ms,
                "total_checks": s.total_checks,
                "up_checks": s.up_checks,
                "last_error_utc": last_err_str,
            }
        )
    return items


@app.get("/api/incidents")
async def api_incidents(last_hours: float = 24.0) -> List[dict[str, Any]]:
    settings: AppSettings = load_settings()
    db = await _get_db(settings)
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=last_hours)
        incidents = await db.get_incidents(since=since)
    finally:
        await db.close()

    items: List[dict[str, Any]] = []
    for inc in incidents:
        items.append(
            {
                "url": inc.url,
                "started_at": inc.started_at.astimezone(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "ended_at": (
                    inc.ended_at.astimezone(timezone.utc).isoformat(timespec="seconds")
                    if inc.ended_at is not None
                    else None
                ),
                "down_checks": inc.down_checks,
            }
        )
    return items


@app.get("/api/slo")
async def api_slo() -> List[dict[str, Any]]:
    settings: AppSettings = load_settings()
    slo_path = Path("config/slo.yaml")
    if not slo_path.exists():
        return []

    db = await _get_db(settings)
    try:
        cfg: SloConfig = load_slo_config(slo_path)
        results = await compute_slo_results(db=db, config=cfg)
    finally:
        await db.close()

    items: List[dict[str, Any]] = []
    for res in results:
        items.append(
            {
                "service": res.service,
                "uptime_percent": res.uptime_percent,
                "target_uptime_percent": res.target_uptime_percent,
                "p95_ms": res.p95_ms,
                "target_p95_ms": res.target_p95_ms,
                "window_hours": res.window_hours,
                "status": res.status,
            }
        )
    return items


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_path = static_dir / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            content=(
                "WatchDog API is running. "
                "Static dashboard bulunamadı, API için /api/status, /api/incidents, /api/slo uçlarını kullanın."
            ),
            status_code=200,
        )

    content = index_path.read_text(encoding="utf-8")
    return HTMLResponse(content=content, status_code=200)

