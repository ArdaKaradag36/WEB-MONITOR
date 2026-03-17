from __future__ import annotations

import argparse
import asyncio
import csv
import os
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NoReturn, Optional
from urllib.parse import parse_qsl, urlparse, urlunparse, urlencode

from aiohttp import web
from rich.console import Console
from rich.live import Live
from rich.table import Table

from src.core.config import (
    AppSettings,
    TargetsConfig,
    load_critical_services,
    load_settings,
    load_targets,
)
from src.core.logger import configure_logging, get_logger
from src.infrastructure.database import Database, Incident, SummaryStat
from src.infrastructure.notifiers import (
    CompositeNotifier,
    ConsoleNotifier,
    EmailNotifier,
    PagerDutyNotifier,
    SlackNotifier,
    WebhookNotifier,
)
from src.services.monitor import monitor_targets
from src.services.slo import SloConfig, compute_slo_results, load_slo_config


logger = get_logger("main")
console = Console()


async def _run_monitor() -> None:
    """
    Monitoring mode entry point.

    Initializes configuration, logging, database, notifier, and monitoring loop.
    Handles graceful shutdown on SIGINT / SIGTERM.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Starting WatchDog in monitor mode")

    targets = load_targets(settings.targets_file)
    if not targets:
        logger.warning("No monitoring targets configured; exiting.")
        return

    db = await Database.create(settings.db_path)
    console_notifier = ConsoleNotifier(failure_threshold=3)

    notifiers: list = [console_notifier]

    if settings.slack_webhook_url:
        slack_notifier = SlackNotifier(settings.slack_webhook_url)
        notifiers.append(slack_notifier)
        logger.info("Slack notifier configured; alerts will be sent to console and Slack.")

    # Configure email notifier if SMTP settings are provided.
    if (
        settings.smtp_host
        and settings.smtp_from
        and settings.smtp_to
    ):
        email_notifier = EmailNotifier(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_from=settings.smtp_from,
            smtp_to=settings.smtp_to,
            smtp_username=settings.smtp_username,
            smtp_password=settings.smtp_password,
            failure_threshold=3,
        )
        notifiers.append(email_notifier)
        logger.info(
            "Email notifier configured; alerts will be sent to %s.",
            settings.smtp_to,
        )

    webhook_url = os.getenv("WATCHDOG_WEBHOOK_URL")
    if webhook_url:
        notifiers.append(WebhookNotifier(webhook_url, failure_threshold=3))
        logger.info("Generic webhook notifier configured: %s", webhook_url)

    pagerduty_routing_key = os.getenv("WATCHDOG_PAGERDUTY_ROUTING_KEY")
    if pagerduty_routing_key:
        notifiers.append(PagerDutyNotifier(pagerduty_routing_key, failure_threshold=3))
        logger.info("PagerDuty notifier configured.")

    notifier = CompositeNotifier(*notifiers)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("Received signal %s; initiating graceful shutdown.", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # Signal handlers may not be available on some platforms (e.g. Windows).
            logger.warning("Signal handling not fully supported on this platform.")
            break

    try:
        await monitor_targets(
            settings=settings,
            db=db,
            notifier=notifier,
            targets=targets,
            stop_event=stop_event,
        )
    finally:
        logger.info("Shutting down WatchDog...")
        await db.close()
        logger.info("Shutdown complete.")


def _compute_since(since_str: Optional[str], last_hours: Optional[float]) -> Optional[datetime]:
    """
    Derive a UTC datetime lower bound from CLI arguments.

    - If last_hours is provided, it takes precedence.
    - Otherwise, since_str is parsed as ISO-8601.
    """
    if last_hours is not None:
        return datetime.now(timezone.utc) - timedelta(hours=last_hours)
    if since_str:
        try:
            dt = datetime.fromisoformat(since_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            console.print(
                "[bold red]Invalid --since value. "
                "Use ISO-8601 format, e.g. 2026-03-11T12:00:00[/bold red]"
            )
            raise SystemExit(1)
    return None


async def _run_report(
    *,
    since: Optional[datetime] = None,
    url_contains: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
) -> None:
    """
    Report mode entry point.

    Connects to the database, aggregates uptime and performance statistics,
    and renders them as a rich table in the console.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Generating WatchDog report from %s", settings.db_path)

    db = await Database.create(settings.db_path)
    try:
        stats = await db.get_summary_stats(since=since)
    finally:
        await db.close()

    if not stats:
        console.print("[bold yellow]No check data found in the database.[/bold yellow]")
        return

    # Optional URL substring filter (case-insensitive).
    if url_contains:
        needle = url_contains.lower()
        stats = [s for s in stats if needle in s.url.lower()]
        if not stats:
            console.print(
                f"[bold yellow]No targets matched URL filter: '{url_contains}'[/bold yellow]"
            )
            return

    # Optional sorting.
    # Varsayılan: en yavaştan en hızlıya (latency desc)
    effective_sort_by = sort_by or "latency"
    reverse = sort_order == "desc"
    if effective_sort_by == "uptime":
        stats.sort(key=lambda s: s.uptime_percentage, reverse=reverse)
    elif effective_sort_by == "latency":
        stats.sort(key=lambda s: s.average_response_time_ms, reverse=reverse)
    elif effective_sort_by == "checks":
        stats.sort(key=lambda s: s.total_checks, reverse=reverse)

    table = Table(title="WatchDog Uptime Report (sorted by latency desc)")
    table.add_column("URL", style="cyan", overflow="fold")
    table.add_column("Uptime %", style="green", justify="right")
    table.add_column("Avg Response (ms)", style="magenta", justify="right")
    table.add_column("P50 (ms)", style="yellow", justify="right")
    table.add_column("P95 (ms)", style="yellow", justify="right")
    table.add_column("P99 (ms)", style="yellow", justify="right")
    table.add_column("Total Checks", style="white", justify="right")
    table.add_column("Up Checks", style="white", justify="right")

    for stat in stats:
        table.add_row(
            stat.url,
            f"{stat.uptime_percentage:.2f}",
            f"{stat.average_response_time_ms:.2f}",
            f"{(stat.p50_response_time_ms or 0.0):.2f}",
            f"{(stat.p95_response_time_ms or 0.0):.2f}",
            f"{(stat.p99_response_time_ms or 0.0):.2f}",
            str(stat.total_checks),
            str(stat.up_checks),
        )

    console.print(table)


async def _run_incidents(
    *,
    since: Optional[datetime] = None,
    url_contains: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
) -> None:
    """
    Incident report entry point.

    Reads historical checks and derives downtime incidents per URL.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Generating WatchDog incidents report from %s", settings.db_path)

    db = await Database.create(settings.db_path)
    try:
        incidents = await db.get_incidents(since=since)
    finally:
        await db.close()

    if not incidents:
        console.print("[bold yellow]No incidents found in the database.[/bold yellow]")
        return

    # Optional URL filter.
    if url_contains:
        needle = url_contains.lower()
        incidents = [i for i in incidents if needle in i.url.lower()]
        if not incidents:
            console.print(
                f"[bold yellow]No incidents matched URL filter: '{url_contains}'[/bold yellow]"
            )
            return

    # Optional sorting: default by start time ascending.
    reverse = sort_order == "desc"
    if sort_by == "duration":
        def _duration_minutes(inc: Incident) -> float:
            if inc.ended_at is None:
                return 0.0
            return (inc.ended_at - inc.started_at).total_seconds() / 60.0

        incidents.sort(key=_duration_minutes, reverse=reverse)
    elif sort_by == "down_checks":
        incidents.sort(key=lambda i: i.down_checks, reverse=reverse)
    else:
        incidents.sort(key=lambda i: i.started_at, reverse=reverse)

    table = Table(title="WatchDog Incidents")
    table.add_column("URL", style="cyan", overflow="fold")
    table.add_column("Started At (UTC)", style="white")
    table.add_column("Ended At (UTC)", style="white")
    table.add_column("Duration (min)", style="magenta", justify="right")
    table.add_column("Down Checks", style="red", justify="right")

    for inc in incidents:
        started = inc.started_at.astimezone(timezone.utc)
        ended_display = "-"
        duration_min = "-"
        if inc.ended_at is not None:
            ended = inc.ended_at.astimezone(timezone.utc)
            ended_display = ended.isoformat(timespec="seconds")
            duration = (ended - started).total_seconds() / 60.0
            duration_min = f"{duration:.1f}"

        table.add_row(
            inc.url,
            started.isoformat(timespec="seconds"),
            ended_display,
            duration_min,
            str(inc.down_checks),
        )

    console.print(table)


async def _run_validate_config() -> None:
    """
    Validate .env and targets.yaml configuration and report any issues.
    """
    configure_logging()
    console.print("[bold]Validating WatchDog configuration...[/bold]")

    errors: list[str] = []

    # Validate environment/.env via AppSettings.
    try:
        settings: AppSettings = load_settings()
        console.print(
            f"[green]✓[/green] Loaded settings from [bold]{settings.targets_file}[/bold] "
            f"and DB path [bold]{settings.db_path}[/bold]"
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Environment / .env validation failed: {exc}")

    # Validate targets.yaml structure using TargetsConfig directly.
    try:
        if "settings" in locals():
            path = settings.targets_file
        else:
            # Fallback to default path if settings failed.
            path = Path("config/targets.yaml")

        if not path.exists():
            errors.append(f"Targets file not found: {path}")
        else:
            # Reuse load_targets to leverage pydantic validation.
            targets = load_targets(path)
            console.print(
                f"[green]✓[/green] Loaded [bold]{len(targets)}[/bold] targets from [bold]{path}[/bold]"
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Targets configuration validation failed: {exc}")

    if errors:
        console.print("\n[bold red]Configuration validation failed:[/bold red]")
        for err in errors:
            console.print(f"- [red]{err}[/red]")
        raise SystemExit(1)

    console.print("\n[bold green]All configuration checks passed successfully.[/bold green]")


async def _run_ci_check(
    *,
    since: Optional[datetime],
    url_contains: Optional[str],
    min_uptime: Optional[float],
    max_latency_ms: Optional[float],
) -> None:
    """
    CI/CD mode: evaluate simple SLAs and exit with non-zero on failure.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Running WatchDog CI check against %s", settings.db_path)

    db = await Database.create(settings.db_path)
    try:
        stats = await db.get_summary_stats(since=since)
    finally:
        await db.close()

    if not stats:
        logger.warning("No check data found for CI evaluation.")
        raise SystemExit(1)

    # Optional URL substring filter on raw stats (before grouping).
    if url_contains:
        needle = url_contains.lower()
        stats = [s for s in stats if needle in s.url.lower()]
        if not stats:
            logger.warning("No targets matched CI URL filter: '%s'", url_contains)
            raise SystemExit(1)

    def _ci_group_key(url: str) -> str:
        """
        Normalise URLs for CI evaluation.

        - Groups synthetic shards like ?shard=N back into a single logical service.
        - Preserves other query parameters (if any) so real APIs can still differ.
        """
        parsed = urlparse(url)
        if not parsed.query:
            return url

        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered = [(k, v) for k, v in query_pairs if k.lower() != "shard"]
        new_query = urlencode(filtered, doseq=True)
        grouped = parsed._replace(query=new_query)
        return urlunparse(grouped)

    def _aggregate_for_ci(stats_list: list[SummaryStat]) -> list[SummaryStat]:
        """
        Aggregate per-URL stats into logical CI services using _ci_group_key.
        """
        aggregates: dict[str, SummaryStat] = {}
        for s in stats_list:
            key = _ci_group_key(s.url)
            existing = aggregates.get(key)
            if existing is None:
                aggregates[key] = SummaryStat(
                    url=key,
                    uptime_percentage=s.uptime_percentage,
                    average_response_time_ms=s.average_response_time_ms,
                    total_checks=s.total_checks,
                    up_checks=s.up_checks,
                )
                continue

            total_checks = existing.total_checks + s.total_checks
            up_checks = existing.up_checks + s.up_checks
            if total_checks > 0:
                uptime_pct = (up_checks / total_checks) * 100.0
                avg_latency = (
                    (existing.average_response_time_ms * existing.total_checks)
                    + (s.average_response_time_ms * s.total_checks)
                ) / total_checks
            else:
                uptime_pct = 0.0
                avg_latency = 0.0

            existing.total_checks = total_checks
            existing.up_checks = up_checks
            existing.uptime_percentage = uptime_pct
            existing.average_response_time_ms = avg_latency

        return list(aggregates.values())

    grouped_stats = _aggregate_for_ci(stats)

    # Optional critical services filter from configuration.
    if settings.ci_critical_services_file is not None:
        try:
            critical_services = load_critical_services(settings.ci_critical_services_file)
        except FileNotFoundError:
            logger.warning(
                "CI critical services file not found: %s",
                settings.ci_critical_services_file,
            )
            critical_services = []
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to load CI critical services from %s: %s",
                settings.ci_critical_services_file,
                exc,
            )
            critical_services = []

        if critical_services:
            critical_set = {svc.strip() for svc in critical_services if svc.strip()}
            grouped_stats = [s for s in grouped_stats if s.url in critical_set]
            if not grouped_stats:
                logger.warning(
                    "No CI stats matched the configured critical services list."
                )
                raise SystemExit(1)

    violations: list[str] = []
    for stat in grouped_stats:
        if min_uptime is not None and stat.uptime_percentage < min_uptime:
            violations.append(
                f"Uptime {stat.uptime_percentage:.2f}% < {min_uptime:.2f}% for {stat.url}"
            )
        if max_latency_ms is not None and stat.average_response_time_ms > max_latency_ms:
            violations.append(
                f"Avg latency {stat.average_response_time_ms:.2f}ms > {max_latency_ms:.2f}ms for {stat.url}"
            )

    if violations:
        console.print("[bold red]CI health check failed:[/bold red]")
        for v in violations:
            console.print(f"- [red]{v}[/red]")
        raise SystemExit(1)

    console.print("[bold green]CI health check passed.[/bold green]")


async def _run_status(
    *,
    last_minutes: float,
) -> None:
    """
    NOC / harekat merkezi için daraltılmış durum görünümü.

    Örnek:
        python main.py --status --last-minutes 5
    """
    configure_logging()
    settings: AppSettings = load_settings()

    since = datetime.now(timezone.utc) - timedelta(minutes=last_minutes)

    db = await Database.create(settings.db_path)
    try:
        stats = await db.get_summary_stats(since=since)
        last_errors = await db.get_last_error_timestamps(since=since)
    finally:
        await db.close()

    if not stats:
        console.print(
            f"[bold yellow]No check data found in the last {last_minutes} minutes.[/bold yellow]"
        )
        return

    # En sorunlu hedefler en üstte olacak şekilde, önce uptime sonra latency’ye göre sırala.
    stats.sort(
        key=lambda s: (
            s.uptime_percentage,
            -s.average_response_time_ms,
        )
    )

    table = Table(title=f"WatchDog Status (last {last_minutes:.1f} minutes)")
    table.add_column("DURUM", style="bold", justify="left")
    table.add_column("Name", style="white")
    table.add_column("URL", style="cyan", overflow="fold")
    table.add_column("Avg (ms)", style="magenta", justify="right")
    table.add_column("Last Error (UTC)", style="red", justify="right")
    table.add_column("Uptime %", style="green", justify="right")

    for stat in stats:
        # DURUM: basit sınıflandırma
        if stat.uptime_percentage >= 99.0:
            status_label = "[green]OK[/green]"
        elif stat.uptime_percentage >= 95.0:
            status_label = "[yellow]WARN[/yellow]"
        else:
            status_label = "[red]CRIT[/red]"

        last_err = last_errors.get(stat.url)
        last_err_str = "-"
        if last_err is not None:
            last_err_utc = last_err.astimezone(timezone.utc)
            last_err_str = last_err_utc.isoformat(timespec="seconds")

        table.add_row(
            status_label,
            "",  # Name alanı ileride Target.name ile doldurulabilir.
            stat.url,
            f"{stat.average_response_time_ms:.2f}",
            last_err_str,
            f"{stat.uptime_percentage:.2f}",
        )

    console.print(table)


async def _run_slo_report(
    *,
    last_hours: Optional[float],
    slo_config_path: Path,
) -> None:
    """
    Evaluate SLOs over a rolling window and render a compact table.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Running SLO report against %s", settings.db_path)

    db = await Database.create(settings.db_path)
    try:
        config: SloConfig = load_slo_config(slo_config_path)
        # last_hours argümanı verilmişse tüm servisler için onu kullan,
        # aksi halde her servis kendi window_hours değerini kullanır.
        if last_hours is not None:
            # Konfigi kopyalayıp tüm window_hours alanlarını override edebilirdik;
            # basitlik için compute_slo_results içinde max window hesaplanıyor
            # ve servis başına window_hours yine konfigden okunuyor.
            pass
        results = await compute_slo_results(db=db, config=config)
    finally:
        await db.close()

    if not results:
        console.print("[bold yellow]No SLO services configured.[/bold yellow]")
        return

    table = Table(title="WatchDog SLO Report")
    table.add_column("Service", style="cyan")
    table.add_column("Uptime %", style="green", justify="right")
    table.add_column("Target Uptime %", style="green", justify="right")
    table.add_column("P95 (ms)", style="magenta", justify="right")
    table.add_column("Target P95 (ms)", style="magenta", justify="right")
    table.add_column("Status", style="bold")

    for res in results:
        if res.status == "PASS":
            status = "[green]PASS[/green]"
        elif res.status == "PARTIAL":
            status = "[yellow]PARTIAL[/yellow]"
        else:  # FAIL or any other fallback
            status = "[red]FAIL[/red]"

        table.add_row(
            res.service,
            f"{res.uptime_percent:.2f}",
            f"{res.target_uptime_percent:.2f}",
            f"{res.p95_ms:.2f}",
            f"{res.target_p95_ms:.2f}",
            status,
        )

    console.print(table)


async def _run_export_csv(
    *,
    output_path: Path,
    since: Optional[datetime],
    until: Optional[datetime],
    and_delete: bool,
) -> None:
    """
    Export raw checks from the SQLite database into a CSV file and optionally
    delete the exported records.
    """
    configure_logging()
    settings: AppSettings = load_settings()

    logger.info("Exporting checks from %s to %s", settings.db_path, output_path)

    db = await Database.create(settings.db_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["url", "status_code", "response_time_ms", "is_up", "timestamp"]
            )
            async for url, status_code, rt_ms, is_up, ts in db.iter_checks(
                since=since,
                until=until,
            ):
                writer.writerow([url, status_code, f"{rt_ms:.6f}", int(is_up), ts])

        if and_delete:
            await db.delete_checks_in_range(since=since, until=until)
            logger.info("Deleted exported records from checks table.")
    finally:
        await db.close()

    logger.info("Export completed to %s", output_path)

async def _run_dashboard(refresh_interval: float = 5.0) -> None:
    """
    Live TUI dashboard that periodically refreshes uptime statistics.
    Shows only URLs from the current targets file so the table matches the active monitor set.
    """
    configure_logging()
    settings: AppSettings = load_settings()
    targets = load_targets(settings.targets_file)
    # DB stores URL as str; Target.url is AnyHttpUrl — normalize to str for matching
    current_urls: set[str] = {str(t.url) for t in targets}

    logger.info("Starting WatchDog dashboard (refresh interval: %.1fs)", refresh_interval)

    async def _build_table() -> Table:
        db = await Database.create(settings.db_path)
        try:
            # Dashboard: son 1 saatlik pencereyi kullan (900 hedef + düşük concurrency ile
            # tek wave süresi uzun olduğundan 5 dakika penceresi çoğu zaman boş kalabiliyor).
            since = datetime.now(timezone.utc) - timedelta(hours=1)
            stats = await db.get_summary_stats(since=since)
            # Sadece şu anki hedef listesindeki URL'leri göster (veri seti ile uyumlu)
            stats = [s for s in stats if s.url in current_urls]
            # En yavaştan en hızlıya doğru sırala (ortalama gecikmeye göre, azalan)
            stats.sort(key=lambda s: s.average_response_time_ms, reverse=True)
        finally:
            await db.close()

        table = Table(
            title=f"WatchDog Live Dashboard (last 1h, sorted by Avg desc) — {len(current_urls)} targets"
        )
        table.add_column("URL", style="cyan", overflow="fold")
        table.add_column("Uptime %", style="green", justify="right")
        table.add_column("Avg (ms)", style="magenta", justify="right")
        table.add_column("P50 (ms)", style="yellow", justify="right")
        table.add_column("P95 (ms)", style="yellow", justify="right")
        table.add_column("P99 (ms)", style="yellow", justify="right")
        table.add_column("Total Checks", style="white", justify="right")
        table.add_column("Up Checks", style="white", justify="right")

        for stat in stats:
            table.add_row(
                stat.url,
                f"{stat.uptime_percentage:.2f}",
                f"{stat.average_response_time_ms:.2f}",
                f"{(stat.p50_response_time_ms or 0.0):.2f}",
                f"{(stat.p95_response_time_ms or 0.0):.2f}",
                f"{(stat.p99_response_time_ms or 0.0):.2f}",
                str(stat.total_checks),
                str(stat.up_checks),
            )
        return table

    # Live döngüsü
    with Live(refresh_per_second=4, console=console) as live:
        try:
            while True:
                table = await _build_table()
                live.update(table)
                await asyncio.sleep(refresh_interval)
        except asyncio.CancelledError:
            pass


async def _metrics_handler(request: web.Request) -> web.Response:
    """
    HTTP handler that exposes WatchDog metrics in Prometheus text format.
    """
    settings: AppSettings = load_settings()
    db = await Database.create(settings.db_path)
    try:
        stats = await db.get_summary_stats()
        # Telemetry values are optional; they may not exist if the monitor
        # has not executed a wave yet.
        last_wave_ts_str = await db.get_telemetry("last_wave_timestamp_seconds")
        last_wave_dur_str = await db.get_telemetry("last_wave_duration_seconds")
        current_conc_str = await db.get_telemetry("current_concurrency_limit")

        # Optional SLO metrics if slo.yaml exists.
        slo_results = []
        slo_path = Path("config/slo.yaml")
        if slo_path.exists():
            try:
                slo_cfg: SloConfig = load_slo_config(slo_path)
                slo_results = await compute_slo_results(db=db, config=slo_cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to compute SLO metrics: %s", exc)
    finally:
        await db.close()

    lines: list[str] = []
    lines.append("# HELP watchdog_uptime_percent Uptime percentage for each URL.")
    lines.append("# TYPE watchdog_uptime_percent gauge")
    lines.append("# HELP watchdog_avg_response_ms Average response time in milliseconds for each URL.")
    lines.append("# TYPE watchdog_avg_response_ms gauge")
    lines.append("# HELP watchdog_p50_response_ms 50th percentile response time in milliseconds for each URL.")
    lines.append("# TYPE watchdog_p50_response_ms gauge")
    lines.append("# HELP watchdog_p95_response_ms 95th percentile response time in milliseconds for each URL.")
    lines.append("# TYPE watchdog_p95_response_ms gauge")
    lines.append("# HELP watchdog_p99_response_ms 99th percentile response time in milliseconds for each URL.")
    lines.append("# TYPE watchdog_p99_response_ms gauge")
    lines.append("# HELP watchdog_total_checks Total number of checks recorded for each URL.")
    lines.append("# TYPE watchdog_total_checks counter")
    lines.append("# HELP watchdog_up_checks Total number of successful checks recorded for each URL.")
    lines.append("# TYPE watchdog_up_checks counter")

    lines.append("# HELP watchdog_last_wave_timestamp_seconds Unix timestamp of the last completed monitoring wave.")
    lines.append("# TYPE watchdog_last_wave_timestamp_seconds gauge")
    lines.append("# HELP watchdog_wave_duration_seconds Duration of the last monitoring wave in seconds.")
    lines.append("# TYPE watchdog_wave_duration_seconds gauge")
    lines.append("# HELP watchdog_active_concurrency_limit Current effective concurrency limit used by the monitor.")
    lines.append("# TYPE watchdog_active_concurrency_limit gauge")

    lines.append("# HELP watchdog_slo_uptime_percent SLO uptime percentage per logical service.")
    lines.append("# TYPE watchdog_slo_uptime_percent gauge")
    lines.append("# HELP watchdog_slo_latency_p95_ms SLO p95 latency in ms per logical service.")
    lines.append("# TYPE watchdog_slo_latency_p95_ms gauge")
    lines.append("# HELP watchdog_slo_error_budget_ratio Ratio of error budget consumed per service (0-1).")
    lines.append("# TYPE watchdog_slo_error_budget_ratio gauge")

    for stat in stats:
        url_label = stat.url.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'watchdog_uptime_percent{{url="{url_label}"}} {stat.uptime_percentage:.6f}'
        )
        lines.append(
            f'watchdog_avg_response_ms{{url="{url_label}"}} {stat.average_response_time_ms:.6f}'
        )
        if stat.p50_response_time_ms is not None:
            lines.append(
                f'watchdog_p50_response_ms{{url="{url_label}"}} {stat.p50_response_time_ms:.6f}'
            )
        if stat.p95_response_time_ms is not None:
            lines.append(
                f'watchdog_p95_response_ms{{url="{url_label}"}} {stat.p95_response_time_ms:.6f}'
            )
        if stat.p99_response_time_ms is not None:
            lines.append(
                f'watchdog_p99_response_ms{{url="{url_label}"}} {stat.p99_response_time_ms:.6f}'
            )
        lines.append(
            f'watchdog_total_checks{{url="{url_label}"}} {stat.total_checks}'
        )
        lines.append(
            f'watchdog_up_checks{{url="{url_label}"}} {stat.up_checks}'
        )

    # SLO metrics per service.
    for res in slo_results:
        svc_label = res.service.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'watchdog_slo_uptime_percent{{service="{svc_label}"}} {res.uptime_percent:.6f}'
        )
        lines.append(
            f'watchdog_slo_latency_p95_ms{{service="{svc_label}"}} {res.p95_ms:.6f}'
        )
        # Basit error-budget oranı: negatif değerler 0'a, >1 değerler 1'e kırpılır.
        if res.target_uptime_percent > 0:
            shortfall = max(0.0, res.target_uptime_percent - res.uptime_percent)
            ratio = min(1.0, shortfall / res.target_uptime_percent)
        else:
            ratio = 0.0
        lines.append(
            f'watchdog_slo_error_budget_ratio{{service="{svc_label}"}} {ratio:.6f}'
        )

    # Internal telemetry metrics from the database (may be absent if monitor
    # has not yet written any telemetry).
    if last_wave_ts_str is not None:
        try:
            last_wave_ts = float(last_wave_ts_str)
            lines.append(
                f"watchdog_last_wave_timestamp_seconds {last_wave_ts:.6f}"
            )
        except ValueError:
            logger.warning(
                "Invalid telemetry value for last_wave_timestamp_seconds: %s",
                last_wave_ts_str,
            )
    if last_wave_dur_str is not None:
        try:
            last_wave_dur = float(last_wave_dur_str)
            lines.append(
                f"watchdog_wave_duration_seconds {last_wave_dur:.6f}"
            )
        except ValueError:
            logger.warning(
                "Invalid telemetry value for last_wave_duration_seconds: %s",
                last_wave_dur_str,
            )
    if current_conc_str is not None:
        try:
            current_conc = float(current_conc_str)
            lines.append(
                f"watchdog_active_concurrency_limit {current_conc:.0f}"
            )
        except ValueError:
            logger.warning(
                "Invalid telemetry value for current_concurrency_limit: %s",
                current_conc_str,
            )

    body = "\n".join(lines) + "\n"
    return web.Response(text=body, content_type="text/plain; version=0.0.4")


async def _health_handler(request: web.Request) -> web.Response:
    """
    Deep healthcheck endpoint.

    Performs a simple SELECT 1 on the database to ensure it is reachable and not locked.
    """
    try:
        settings: AppSettings = load_settings()
        db = await Database.create(settings.db_path)
        try:
            async with db._conn.execute("SELECT 1") as cursor:  # type: ignore[attr-defined]
                await cursor.fetchone()
        finally:
            await db.close()
    except Exception:  # noqa: BLE001
        return web.json_response(
            {"status": "degraded"},
            status=503,
        )

    return web.json_response({"status": "ok"}, status=200)


async def _run_metrics_server(host: str, port: int) -> None:
    """
    Start a small HTTP server exposing /metrics in Prometheus format.
    """
    configure_logging()
    app = web.Application()
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("Metrics server listening on http://%s:%d/metrics", host, port)

    # Run until cancelled (e.g. via Ctrl+C).
    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("Received signal %s; stopping metrics server.", sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            break

    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()
        logger.info("Metrics server shut down.")


def main() -> NoReturn:
    """
    Synchronous entry point for WatchDog CLI.

    Modes:
    - --monitor: start the asynchronous monitoring loop.
    - --report: print a summary report from the database and exit.
    """
    parser = argparse.ArgumentParser(description="WatchDog - Uptime & Service Monitor")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--monitor",
        action="store_true",
        help="Run in monitoring mode (continuous checks).",
    )
    group.add_argument(
        "--report",
        action="store_true",
        help="Print a summary uptime/performance report and exit.",
    )
    group.add_argument(
        "--incidents",
        action="store_true",
        help="Print a derived incidents report and exit.",
    )
    group.add_argument(
        "--metrics-server",
        action="store_true",
        help="Run a Prometheus-compatible metrics HTTP server.",
    )
    group.add_argument(
        "--ci",
        action="store_true",
        help="Run a CI health check and exit with non-zero status on failure.",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Show a compact NOC status view for the last N minutes.",
    )
    group.add_argument(
        "--monitor-dashboard",
        action="store_true",
        help="Run a live TUI dashboard (read-only).",
    )
    group.add_argument(
        "--export-csv",
        action="store_true",
        help="Export raw checks to a CSV file (optionally deleting them).",
    )
    group.add_argument(
        "--slo-report",
        action="store_true",
        help="Evaluate SLOs over a rolling window and print a compact table.",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Only include data at or after this UTC timestamp (ISO-8601).",
    )
    parser.add_argument(
        "--last-hours",
        type=float,
        help="Only include data from the last N hours (overrides --since if both are set).",
    )
    parser.add_argument(
        "--last-minutes",
        type=float,
        help="Only include data from the last N minutes (for --status).",
    )
    parser.add_argument(
        "--until",
        type=str,
        help="Upper bound (inclusive) on UTC timestamp for export (ISO-8601).",
    )
    parser.add_argument(
        "--url-contains",
        type=str,
        help="Only include targets whose URL contains this substring (case-insensitive).",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        choices=["uptime", "latency", "checks"],
        help="Sort report rows by this field.",
    )
    parser.add_argument(
        "--sort-order",
        type=str,
        choices=["asc", "desc"],
        default="desc",
        help="Sort order for --sort-by (default: desc).",
    )
    parser.add_argument(
        "--incidents-url-contains",
        type=str,
        help="Filter incidents to URLs containing this substring (case-insensitive).",
    )
    parser.add_argument(
        "--incidents-sort-by",
        type=str,
        choices=["duration", "down_checks", "start"],
        default="start",
        help="Sort incidents by duration, down_checks, or start time (default).",
    )
    parser.add_argument(
        "--incidents-sort-order",
        type=str,
        choices=["asc", "desc"],
        default="asc",
        help="Sort order for incidents (default: asc).",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate .env and targets.yaml configuration and exit.",
    )
    parser.add_argument(
        "--export-output",
        type=str,
        help="Output CSV file path for --export-csv mode.",
    )
    parser.add_argument(
        "--export-and-delete",
        action="store_true",
        help="After successful export, delete the exported records from the database.",
    )
    parser.add_argument(
        "--metrics-host",
        type=str,
        default="0.0.0.0",
        help="Host for the metrics server (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=9100,
        help="Port for the metrics server (default: 9100).",
    )
    parser.add_argument(
        "--ci-url-contains",
        type=str,
        help="Limit CI evaluation to URLs containing this substring.",
    )
    parser.add_argument(
        "--ci-min-uptime",
        type=float,
        help="Minimum acceptable uptime percentage for CI checks.",
    )
    parser.add_argument(
        "--ci-max-latency-ms",
        type=float,
        help="Maximum acceptable average latency (ms) for CI checks.",
    )
    parser.add_argument(
        "--profile",
        type=str,
        help=(
            "Optional configuration profile name (e.g. prod, staging, chaos). "
            "When set, .env.{profile} and config/targets_{profile}.yaml are used by default "
            "unless WATCHDOG_TARGETS_FILE is explicitly configured."
        ),
    )
    parser.add_argument(
        "--slo-config",
        type=str,
        default="config/slo.yaml",
        help="Path to SLO configuration file (default: config/slo.yaml).",
    )
    args = parser.parse_args()

    # If a profile is provided, expose it via environment so load_settings/load_targets
    # can adjust configuration accordingly.
    if args.profile:
        os.environ["WATCHDOG_PROFILE"] = args.profile

    since = (
        _compute_since(args.since, args.last_hours)
        if not args.validate_config
        and not args.metrics_server
        and not args.monitor_dashboard
        and not args.status
        else None
    )

    try:
        if args.monitor:
            asyncio.run(_run_monitor())
        elif args.report:
            asyncio.run(
                _run_report(
                    since=since,
                    url_contains=args.url_contains,
                    sort_by=args.sort_by,
                    sort_order=args.sort_order,
                )
            )
        elif args.incidents:
            asyncio.run(
                _run_incidents(
                    since=since,
                    url_contains=args.incidents_url_contains,
                    sort_by=args.incidents_sort_by,
                    sort_order=args.incidents_sort_order,
                )
            )
        elif args.monitor_dashboard:
            try:
                asyncio.run(_run_dashboard())
            except KeyboardInterrupt:
                logger.info("Dashboard interrupted by user, exiting.")
        elif args.metrics_server:
            asyncio.run(_run_metrics_server(args.metrics_host, args.metrics_port))
        elif args.ci:
            asyncio.run(
                _run_ci_check(
                    since=since,
                    url_contains=args.ci_url_contains,
                    min_uptime=args.ci_min_uptime,
                    max_latency_ms=args.ci_max_latency_ms,
                )
            )
        elif args.status:
            last_minutes = args.last_minutes if args.last_minutes is not None else 5.0
            asyncio.run(
                _run_status(
                    last_minutes=last_minutes,
                )
            )
        elif args.validate_config:
            asyncio.run(_run_validate_config())
        elif args.export_csv:
            if not args.export_output:
                parser.error("--export-output is required when using --export-csv")
            output_path = Path(args.export_output)
            until_dt: Optional[datetime] = None
            if args.until:
                until_dt = datetime.fromisoformat(args.until)
            asyncio.run(
                _run_export_csv(
                    output_path=output_path,
                    since=since,
                    until=until_dt,
                    and_delete=args.export_and_delete,
                )
            )
        elif args.slo_report:
            # SLO raporu için last-hours argümanı doğrudan pencere olarak kullanılır;
            # None ise konfig içindeki window_hours değerleri kullanılır.
            slo_path = Path(args.slo_config)
            asyncio.run(
                _run_slo_report(
                    last_hours=args.last_hours,
                    slo_config_path=slo_path,
                )
            )
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")


if __name__ == "__main__":
    main()


