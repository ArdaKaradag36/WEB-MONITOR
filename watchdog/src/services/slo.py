from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

from src.infrastructure.database import Database, SummaryStat


class SloServiceConfig(BaseModel):
    name: str = Field(..., description="Logical service name.")
    url_contains: str = Field(
        ...,
        description="Substring used to match URLs belonging to this service.",
    )
    target_uptime_percent: float = Field(
        ...,
        gt=0.0,
        le=100.0,
        description="Target uptime percentage for the SLO window.",
    )
    target_p95_ms: float = Field(
        ...,
        gt=0.0,
        description="Target 95th percentile latency (ms) for the SLO window.",
    )
    window_hours: float = Field(
        24.0,
        gt=0.0,
        description="SLO evaluation window size in hours (default: 24h).",
    )


class SloConfig(BaseModel):
    services: List[SloServiceConfig]


@dataclass
class SloResult:
    service: str
    uptime_percent: float
    target_uptime_percent: float
    p95_ms: float
    target_p95_ms: float
    window_hours: float

    @property
    def uptime_ok(self) -> bool:
        return self.uptime_percent >= self.target_uptime_percent

    @property
    def latency_ok(self) -> bool:
        return self.p95_ms <= self.target_p95_ms

    @property
    def is_ok(self) -> bool:
        return self.uptime_ok and self.latency_ok

    @property
    def status(self) -> str:
        """
        Derived SLO status label used consistently across CLI, API and metrics.

        - PASS: both uptime and latency targets are met.
        - PARTIAL: only one of the targets is met.
        - FAIL: neither target is met.
        """
        if self.is_ok:
            return "PASS"
        if self.uptime_ok or self.latency_ok:
            return "PARTIAL"
        return "FAIL"


def load_slo_config(path: Path) -> SloConfig:
    if not path.exists():
        raise FileNotFoundError(f"SLO configuration file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return SloConfig(**raw)
    except ValidationError as exc:  # re-wrap for clearer error location
        raise ValidationError(exc.raw_errors, model=SloConfig) from exc


async def compute_slo_results(
    *,
    db: Database,
    config: SloConfig,
    now: Optional[datetime] = None,
) -> list[SloResult]:
    """
    Compute SLO results for all configured services over their respective windows.

    For now we evaluate all services over the same window defined by the
    maximum window_hours, then filter per service.
    """
    if not config.services:
        return []

    now = now or datetime.now(timezone.utc)
    max_window_hours = max(s.window_hours for s in config.services)
    since = now - timedelta(hours=max_window_hours)

    stats: list[SummaryStat] = await db.get_summary_stats(since=since)

    results: list[SloResult] = []
    for svc in config.services:
        # Hizmet URL'lerini substring ile eşle.
        matching = [s for s in stats if svc.url_contains in s.url]
        if not matching:
            # Hiç eşleşme yoksa, 0 uptime / 0 latency ile FAIL say.
            results.append(
                SloResult(
                    service=svc.name,
                    uptime_percent=0.0,
                    target_uptime_percent=svc.target_uptime_percent,
                    p95_ms=0.0,
                    target_p95_ms=svc.target_p95_ms,
                    window_hours=svc.window_hours,
                )
            )
            continue

        # Uptime ve p95'in basit ortalaması (tüm URL'ler eşit ağırlıklı).
        uptime = sum(s.uptime_percentage for s in matching) / len(matching)
        # Bazı URL'lerde p95 olmayabilir (None) – sadece mevcut değerleri al.
        p95_values = [s.p95_response_time_ms for s in matching if s.p95_response_time_ms is not None]
        if p95_values:
            p95 = sum(p95_values) / len(p95_values)
        else:
            p95 = 0.0

        results.append(
            SloResult(
                service=svc.name,
                uptime_percent=uptime,
                target_uptime_percent=svc.target_uptime_percent,
                p95_ms=p95,
                target_p95_ms=svc.target_p95_ms,
                window_hours=svc.window_hours,
            )
        )

    return results

