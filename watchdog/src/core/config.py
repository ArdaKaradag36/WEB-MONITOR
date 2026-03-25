from __future__ import annotations

# UYARI: AppSettings içindeki zaman tabanlı parametreleri (timeout / poll_interval)
# değiştirmeden önce _validate_time_relationships doğrulayıcısını ve
# docs/OPERASYON_VE_MIMARI_NOTLARI.md belgesini mutlaka inceleyin.
# Yanlış yapılandırma üretim ortamında izleme dalgası çakışmalarına yol açar.
#
# WARNING: Before modifying the time-based parameters in AppSettings
# (request_timeout_seconds / poll_interval_seconds), review the
# _validate_time_relationships validator and the operations documentation.
# Incorrect values will cause monitoring wave overlaps in production.
import os
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, BaseSettings, Field, ValidationError, root_validator

from src.models.target import Target

WATCHDOG_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = WATCHDOG_DIR.parent


def resolve_config_path(path: Path) -> Path:
    """
    Resolve configuration paths robustly across common working directories.

    This project is often run in two ways:
    - from repo root:   `python watchdog/main.py ...`
    - from watchdog/:   `python main.py ...` (or installed package)

    For relative paths, we try:
    1) as-is relative to current working directory
    2) relative to the `watchdog/` directory
    3) relative to the repo root
    """
    if path.is_absolute():
        return path
    if path.exists():
        return path
    candidate = WATCHDOG_DIR / path
    if candidate.exists():
        return candidate
    candidate = REPO_ROOT / path
    return candidate


class AppSettings(BaseSettings):
    """
    Application-level configuration loaded from environment variables.

    This class leverages pydantic's BaseSettings to provide a typed interface
    over environment configuration, with support for an optional `.env` file.
    """

    db_path: Path = Field(
        Path("watchdog.db"),
        env="WATCHDOG_DB_PATH",
        description="Path to the SQLite database file.",
    )
    poll_interval_seconds: float = Field(
        30.0,
        gt=0,
        env="WATCHDOG_POLL_INTERVAL_SECONDS",
        description="Interval between consecutive health checks.",
    )
    request_timeout_seconds: float = Field(
        10.0,
        gt=0,
        le=60.0,
        env="WATCHDOG_REQUEST_TIMEOUT_SECONDS",
        description=(
            "Default HTTP request timeout when not overridden by target. "
            "Must be positive and not exceed a hard upper bound suitable for "
            "production (default 60s)."
        ),
    )
    targets_file: Path = Field(
        Path("config/targets.yaml"),
        env="WATCHDOG_TARGETS_FILE",
        description="Path to the YAML file containing monitoring targets.",
    )
    max_concurrent_requests: int = Field(
        100,
        gt=0,
        env="WATCHDOG_MAX_CONCURRENT_REQUESTS",
        description="Global maximum number of concurrent HTTP requests.",
    )
    retention_days: int = Field(
        7,
        gt=0,
        env="WATCHDOG_RETENTION_DAYS",
        description="Number of days to retain check records in the database.",
    )
    max_retries: int = Field(
        2,
        ge=0,
        env="WATCHDOG_MAX_RETRIES",
        description="Default maximum number of retries for transient errors.",
    )
    slack_webhook_url: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SLACK_WEBHOOK_URL",
        description="Optional Slack webhook URL for external alerts.",
    )
    heartbeat_ping_url: Optional[str] = Field(
        default=None,
        env="WATCHDOG_HEARTBEAT_PING_URL",
        description=(
            "Optional URL to ping after each successful monitoring wave for "
            "external deadman switch / heartbeat monitoring."
        ),
    )
    allow_private_ips: bool = Field(
        default=False,
        env="WATCHDOG_ALLOW_PRIVATE_IPS",
        description=(
            "Whether targets are allowed to resolve to private/loopback IP "
            "addresses. When False, such targets are treated as DOWN and no "
            "request is performed."
        ),
    )
    smtp_host: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SMTP_HOST",
        description="SMTP server hostname for email alerts.",
    )
    smtp_port: int = Field(
        default=587,
        env="WATCHDOG_SMTP_PORT",
        description="SMTP server port for email alerts.",
    )
    smtp_username: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SMTP_USERNAME",
        description="SMTP username for email alerts (if required).",
    )
    smtp_password: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SMTP_PASSWORD",
        description="SMTP password for email alerts (if required).",
    )
    smtp_from: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SMTP_FROM",
        description="From address to use for email alerts.",
    )
    smtp_to: Optional[str] = Field(
        default=None,
        env="WATCHDOG_SMTP_TO",
        description="Destination address for email alerts.",
    )
    ci_critical_services_file: Optional[Path] = Field(
        default=None,
        env="WATCHDOG_CI_CRITICAL_SERVICES_FILE",
        description=(
            "Optional YAML file listing critical service URLs for CI checks. "
            "If set, CI mode evaluates only these services (after URL grouping)."
        ),
    )
    maintenance_windows_file: Optional[Path] = Field(
        default=None,
        env="WATCHDOG_MAINTENANCE_WINDOWS_FILE",
        description=(
            "Optional YAML file defining maintenance windows for alert suppression. "
            "If set, monitor mode will suppress alerts for matching URLs during "
            "the configured windows."
        ),
    )

    @root_validator
    def _validate_time_relationships(cls, values: dict) -> dict:  # type: ignore[override]
        """
        Enforce safe relationships between time-based settings.

        - request_timeout_seconds must be strictly less than poll_interval_seconds
          to avoid overlapping monitoring waves under normal conditions.
        """
        poll_interval = values.get("poll_interval_seconds")
        request_timeout = values.get("request_timeout_seconds")
        if poll_interval is not None and request_timeout is not None:
            if request_timeout >= poll_interval:
                raise ValueError(
                    "WATCHDOG_REQUEST_TIMEOUT_SECONDS must be strictly smaller than "
                    "WATCHDOG_POLL_INTERVAL_SECONDS to prevent overlapping waves "
                    "under production conditions."
                )
        return values

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


class TargetsConfig(BaseModel):
    """
    Wrapper for the list of targets defined in the YAML configuration file.
    """

    targets: List[Target]


class CriticalServicesConfig(BaseModel):
    """
    Wrapper for the list of critical service URLs used by CI health checks.
    """

    services: List[str]


class MaintenanceWindow(BaseModel):
    """
    Single maintenance window definition used for alert suppression.

    Times are expected to be ISO-8601 strings in UTC (e.g. 2026-03-16T12:00:00Z).
    """

    url_substring: str = Field(
        ...,
        description=(
            "Substring to match against the target URL. "
            "If present in the URL, the window applies to that target."
        ),
    )
    start: str = Field(
        ...,
        description="Maintenance window start time (ISO-8601, UTC).",
    )
    end: str = Field(
        ...,
        description="Maintenance window end time (ISO-8601, UTC).",
    )


class MaintenanceWindowsConfig(BaseModel):
    """
    Wrapper for the list of maintenance windows loaded from YAML.
    """

    windows: List[MaintenanceWindow]


def load_settings() -> AppSettings:
    """
    Load application settings from environment variables and `.env`.

    :return: Validated AppSettings instance.
    :raises ValidationError: If environment configuration is invalid.
    """
    profile = os.getenv("WATCHDOG_PROFILE")

    load_dotenv()
    if profile:
        load_dotenv(f".env.{profile}")

    settings: AppSettings = AppSettings()  # type: ignore[call-arg]

    if profile and not os.getenv("WATCHDOG_TARGETS_FILE"):
        settings.targets_file = Path(f"config/targets_{profile}.yaml")

    # Normalise paths so defaults work from repo root or watchdog/.
    settings.targets_file = resolve_config_path(settings.targets_file)
    if settings.ci_critical_services_file is not None:
        settings.ci_critical_services_file = resolve_config_path(
            settings.ci_critical_services_file
        )
    if settings.maintenance_windows_file is not None:
        settings.maintenance_windows_file = resolve_config_path(
            settings.maintenance_windows_file
        )

    return settings


def load_targets(path: Path) -> List[Target]:
    """
    Load and validate monitoring targets from a configuration file.

    Supported formats:
    - YAML: targets file with structure `{ "targets": [ ... ] }`
    - TXT : plain text file with one URL per line (comments with `#` supported)

    :param path: Path to the YAML file.
    :return: List of validated Target instances.
    :raises FileNotFoundError: If the file does not exist.
    :raises ValidationError: If the YAML content is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Targets configuration file not found: {path}")

    # Plain links file support (one URL per line).
    if path.suffix.lower() in {".txt", ".links"}:
        lines = path.read_text(encoding="utf-8").splitlines()
        urls: List[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.append(stripped)
        if not urls:
            raise ValidationError(
                [
                    {
                        "loc": ("targets",),
                        "msg": f"No URLs found in links file: {path}",
                        "type": "value_error",
                    }
                ],
                model=TargetsConfig,
            )

        raw = {
            "targets": [
                {
                    "name": f"Link {i}",
                    "url": url,
                    "expected_status": 200,
                    "timeout": 8,
                    "method": "GET",
                    "latency_threshold_ms": 5000,
                }
                for i, url in enumerate(urls, start=1)
            ]
        }
    else:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    try:
        cfg = TargetsConfig(**raw)
    except ValidationError as exc:
        raise ValidationError(
            exc.raw_errors,
            model=TargetsConfig,
        ) from exc

    return cfg.targets


def load_critical_services(path: Path) -> List[str]:
    """
    Load a list of critical service URLs from a YAML configuration file.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Critical services configuration file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        cfg = CriticalServicesConfig(**raw)
    except ValidationError as exc:
        raise ValidationError(
            exc.raw_errors,
            model=CriticalServicesConfig,
        ) from exc

    return cfg.services


def load_maintenance_windows(path: Path) -> List[MaintenanceWindow]:
    """
    Load maintenance windows from a YAML configuration file.

    The expected structure is:

    windows:
      - url_substring: "example.com"
        start: "2026-03-16T10:00:00Z"
        end:   "2026-03-16T12:00:00Z"
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Maintenance windows configuration file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        cfg = MaintenanceWindowsConfig(**raw)
    except ValidationError as exc:
        raise ValidationError(
            exc.raw_errors,
            model=MaintenanceWindowsConfig,
        ) from exc

    return cfg.windows


__all__ = [
    "AppSettings",
    "TargetsConfig",
    "CriticalServicesConfig",
    "MaintenanceWindow",
    "MaintenanceWindowsConfig",
    "resolve_config_path",
    "load_settings",
    "load_targets",
    "load_critical_services",
    "load_maintenance_windows",
]
