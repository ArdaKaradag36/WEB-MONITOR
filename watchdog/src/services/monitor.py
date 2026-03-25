from __future__ import annotations

# NOT: Bu modüldeki SSRF koruma mantığını (allow_private_ips, denied_ports) veya
# backpressure eşik değerlerini (HIGH_FAILURE_THRESHOLD, BATCH_SIZE) değiştirmeden
# önce ilgili test dosyalarını çalıştırın ve docs/OPERASYON_VE_MIMARI_NOTLARI.md
# belgesini gözden geçirin. Bu parametreler üretim güvenliğini doğrudan etkiler.
#
# NOTE: Before modifying the SSRF protection logic (allow_private_ips, denied_ports)
# or the backpressure threshold constants (HIGH_FAILURE_THRESHOLD, BATCH_SIZE),
# run the associated test suite and review docs/OPERASYON_VE_MIMARI_NOTLARI.md.
# These values directly affect production security and monitoring stability.
import asyncio
import ipaddress
import json
import random
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

import aiohttp
from yarl import URL

from src.core.config import AppSettings, MaintenanceWindow, load_maintenance_windows
from src.core.logger import get_logger
from src.infrastructure.database import Database
from src.infrastructure.notifiers import CompositeNotifier
from src.models.target import Target

logger = get_logger("monitor")

# Maximum number of bytes to read from a response body to avoid OOM.
MAX_BODY_BYTES = 50 * 1024


async def _is_safe_url(url: str, allow_private_ips: bool) -> bool:
    """
    Resolve the target URL and verify that it does not point to a private,
    loopback or link-local IP address unless explicitly allowed.

    Only HTTP(S) schemes are permitted and a small set of sensitive local
    ports is explicitly denied to reduce SSRF blast radius.
    """
    parsed = URL(url)

    if parsed.scheme not in ("http", "https"):
        logger.warning(
            "Blocked potential SSRF target %s with disallowed scheme %s",
            url,
            parsed.scheme,
        )
        return False

    host = parsed.host
    if host is None:
        logger.warning("Target URL %s has no resolvable host component.", url)
        return False

    # Deny-list a small set of sensitive ports for remote targets.
    # This is a defence-in-depth measure; the primary expectation is that
    # operators configure safe targets in YAML.
    denied_ports = {22, 23, 25, 110, 143}
    port = parsed.port or 80
    if port in denied_ports:
        logger.warning(
            "Blocked potential SSRF target %s using denied port %s",
            url,
            port,
        )
        return False

    # If the host is already an IP literal, we can evaluate it directly.
    resolved_ips: List[ipaddress._BaseAddress] = []
    try:
        resolved_ips.append(ipaddress.ip_address(host))
    except ValueError:
        # Not an IP literal, resolve via DNS.
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                host,
                parsed.port or 80,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            logger.warning("DNS resolution failed for %s: %s", url, exc)
            return False

        for _family, _, _, _, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                resolved_ips.append(ipaddress.ip_address(ip_str))
            except ValueError:
                continue

    for ip in resolved_ips:
        if ip.is_loopback or ip.is_link_local or ip.is_private:
            if not allow_private_ips:
                logger.warning(
                    "Blocked potential SSRF target %s resolved to restricted IP %s",
                    url,
                    ip,
                )
                return False

    return True


def _parse_utc(dt_str: str) -> Optional[datetime]:
    """
    Parse an ISO-8601 datetime string as UTC.
    """
    if not dt_str:
        return None
    # Accept both ...Z and offset-less timestamps; normalise to UTC.
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1]
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_within_maintenance(
    url: str,
    now: datetime,
    windows: List[MaintenanceWindow],
) -> bool:
    """
    Return True if the given URL is covered by any active maintenance window.
    """
    for window in windows:
        if window.url_substring not in url:
            continue
        start = _parse_utc(window.start)
        end = _parse_utc(window.end)
        if start is None or end is None:
            continue
        if start <= now <= end:
            return True
    return False


def _get_tls_expiry_days(url: str) -> Optional[float]:
    """
    Perform a lightweight TLS handshake and return days until certificate expiry.

    Returns None if the URL is not HTTPS or if the expiry cannot be determined.
    """
    parsed = URL(url)
    if parsed.scheme not in ("https",):
        return None

    host = parsed.host
    port = parsed.port or 443
    if host is None:
        return None

    context = ssl.create_default_context()

    def _fetch_expiry() -> Optional[float]:
        with socket.create_connection((host, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        not_after_str = cert.get("notAfter")
        if not not_after_str:
            return None
        # Example format: 'Mar 16 12:00:00 2026 GMT'
        expiry = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
        expiry = expiry.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = expiry - now
        return delta.total_seconds() / 86400.0

    return _fetch_expiry()


async def _check_target(
    session: aiohttp.ClientSession,
    db: Database,
    target: Target,
    settings: AppSettings,
) -> tuple[str, bool, int, float, str | None]:
    """
    Perform a single HTTP health check for the given target.

    Persists the result to the database and returns a tuple containing
    the essential data for alerting and reporting:
    (url, is_up, status_code, response_time_ms, name).
    """
    url = str(target.url)
    expected_status = target.expected_status
    timeout = target.timeout or settings.request_timeout_seconds

    # Global timer includes all retries.
    start = time.perf_counter()
    status_code = 0
    is_up = False

    # SSRF protection: verify that the URL resolves to a public IP, unless
    # explicitly allowed to target private addresses.
    if not await _is_safe_url(url, settings.allow_private_ips):
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        await db.insert_check_result(
            url=url,
            status_code=0,
            response_time_ms=elapsed_ms,
            is_up=False,
            autocommit=False,
        )
        return url, False, status_code, elapsed_ms, target.name

    # Optional TLS certificate expiry check.
    if target.tls_days_before_expiry_warning is not None:
        try:
            days_left = await asyncio.to_thread(_get_tls_expiry_days, url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to evaluate TLS expiry for %s: %s", url, exc)
            days_left = None

        if days_left is not None and days_left < float(
            target.tls_days_before_expiry_warning
        ):
            logger.warning(
                "TLS certificate for %s expires in %.1f days (threshold=%s); "
                "treating target as DOWN.",
                url,
                days_left,
                target.tls_days_before_expiry_warning,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            await db.insert_check_result(
                url=url,
                status_code=0,
                response_time_ms=elapsed_ms,
                is_up=False,
                autocommit=False,
            )
            return url, False, 0, elapsed_ms, target.name

    # Determine how many retries we are allowed for this target.
    max_retries = (
        target.max_retries if target.max_retries is not None else settings.max_retries
    )

    attempt = 0
    while True:
        try:
            request_kwargs = {
                "timeout": timeout,
                "headers": target.headers or {},
            }
            method = target.method.upper()

            async with session.request(method, url, **request_kwargs) as resp:
                status_code = resp.status
                body_ok = True

                # Bounded read to protect against OOM.
                bytes_cache: Optional[bytes] = None
                if (
                    target.expected_body_substring is not None
                    or target.expected_json_key is not None
                ):
                    try:
                        bytes_cache = await resp.content.read(MAX_BODY_BYTES)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to read response body for %s: %s", url, exc
                        )

                # Optional plain-text substring check.
                text_cache: str | None = None
                if target.expected_body_substring is not None:
                    if bytes_cache is not None:
                        encoding = resp.charset or "utf-8"
                        try:
                            text_cache = bytes_cache.decode(
                                encoding,
                                errors="ignore",
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "Failed to decode response body for %s: %s",
                                url,
                                exc,
                            )
                            text_cache = ""
                    else:
                        text_cache = ""

                    body_ok = target.expected_body_substring in text_cache

                # Optional JSON key/value check.
                json_ok = True
                if target.expected_json_key is not None:
                    try:
                        if bytes_cache is not None:
                            encoding = resp.charset or "utf-8"
                            text_for_json = bytes_cache.decode(
                                encoding,
                                errors="ignore",
                            )
                            json_payload = json.loads(text_for_json)
                        else:
                            json_payload = await resp.json()

                        if target.expected_json_key not in json_payload:
                            json_ok = False
                        elif target.expected_json_value is not None:
                            json_ok = (
                                json_payload.get(target.expected_json_key)
                                == target.expected_json_value
                            )
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Failed to parse JSON for %s (possibly truncated): %s",
                            url,
                            exc,
                        )
                        json_ok = False
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to parse JSON for %s: %s", url, exc)
                        json_ok = False

                # HTTP status evaluation.
                if target.allowed_statuses:
                    status_ok = status_code in target.allowed_statuses
                else:
                    status_ok = status_code == expected_status

                is_up = status_ok and body_ok and json_ok

                # Retry on transient 5xx responses if still not healthy.
                is_transient_http_error = 500 <= status_code < 600
                if not is_up and is_transient_http_error and attempt < max_retries:
                    backoff = min(5.0, 0.5 * (2**attempt))
                    jitter = random.uniform(0, 0.1)
                    sleep_for = backoff + jitter
                    logger.warning(
                        "Transient HTTP %s for %s, retrying in %.2fs (attempt %d/%d)",
                        status_code,
                        url,
                        sleep_for,
                        attempt + 1,
                        max_retries,
                    )
                    attempt += 1
                    await asyncio.sleep(sleep_for)
                    continue

        except asyncio.TimeoutError:
            if attempt < max_retries:
                backoff = min(5.0, 0.5 * (2**attempt))
                jitter = random.uniform(0, 0.1)
                sleep_for = backoff + jitter
                logger.warning(
                    "Timeout while checking %s (timeout=%ss), retrying in %.2fs "
                    "(attempt %d/%d)",
                    url,
                    timeout,
                    sleep_for,
                    attempt + 1,
                    max_retries,
                )
                attempt += 1
                await asyncio.sleep(sleep_for)
                continue

            logger.warning(
                "Timeout while checking %s (timeout=%ss), no retries left",
                url,
                timeout,
            )
        except aiohttp.ClientError as exc:
            if attempt < max_retries:
                backoff = min(5.0, 0.5 * (2**attempt))
                jitter = random.uniform(0, 0.1)
                sleep_for = backoff + jitter
                logger.warning(
                    "HTTP error while checking %s: %s, retrying in %.2fs "
                    "(attempt %d/%d)",
                    url,
                    exc,
                    sleep_for,
                    attempt + 1,
                    max_retries,
                )
                attempt += 1
                await asyncio.sleep(sleep_for)
                continue

            logger.warning(
                "HTTP error while checking %s: %s, no retries left",
                url,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error while checking %s: %s", url, exc)
        finally:
            # Break after successful response processing or after terminal error.
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            break

    # Apply latency threshold if configured on the target.
    if (
        target.latency_threshold_ms is not None
        and elapsed_ms > target.latency_threshold_ms
    ):
        latency_ok = False
    else:
        latency_ok = True

    is_up = is_up and latency_ok

    await db.insert_check_result(
        url=url,
        status_code=status_code,
        response_time_ms=elapsed_ms,
        is_up=is_up,
        autocommit=False,
    )

    return url, is_up, status_code, elapsed_ms, target.name


def _adjust_concurrency(
    *,
    effective_limit: int,
    target_max: int,
    timeout_ratio: float,
    http_5xx_ratio: float,
    elapsed: float,
    poll_interval_seconds: float,
) -> int:
    """
    Pure function that encapsulates AIMD-style backpressure logic.

    This is intentionally side-effect free so that it can be unit-tested
    without running the full monitoring loop.
    """
    if effective_limit < 1:
        effective_limit = 1

    HIGH_TIMEOUT_THRESHOLD = 0.3
    HIGH_5XX_THRESHOLD = 0.5
    SLOW_WAVE_THRESHOLD = poll_interval_seconds * 0.8

    # Multiplicative decrease on high timeout ratio, high 5xx ratio,
    # or generally slow waves.
    if (
        timeout_ratio >= HIGH_TIMEOUT_THRESHOLD
        or http_5xx_ratio >= HIGH_5XX_THRESHOLD
        or elapsed > SLOW_WAVE_THRESHOLD
    ) and effective_limit > 1:
        return max(1, int(effective_limit * 0.7))

    # Additive increase when system is healthy and fast.
    if (
        timeout_ratio == 0.0
        and elapsed < poll_interval_seconds * 0.5
        and effective_limit < target_max
    ):
        return min(target_max, effective_limit + 1)

    return effective_limit


async def monitor_targets(
    *,
    settings: AppSettings,
    db: Database,
    notifier: CompositeNotifier,
    targets: Iterable[Target],
    stop_event: asyncio.Event,
) -> None:
    """
    Main monitoring loop.

    Uses a single shared aiohttp.ClientSession and runs checks for all targets
    concurrently on each iteration, with fan-out bounded by both an adaptive
    semaphore and per-wave batching to avoid overwhelming the event loop on
    very large target sets. The loop terminates when `stop_event` is set.
    """
    connector = aiohttp.TCPConnector(limit_per_host=10)
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=settings.request_timeout_seconds,
    )

    # Materialize targets once and log diagnostics.
    targets_list: List[Target] = list(targets)
    num_targets = len(targets_list)

    if num_targets > 500 and settings.poll_interval_seconds < 10:
        logger.warning(
            "Monitoring more than 500 targets with interval <10s may cause high "
            "load. Recommended poll_interval_seconds >= 15s."
        )

    if settings.request_timeout_seconds >= settings.poll_interval_seconds:
        logger.warning(
            "Timeout is larger than or equal to poll interval. Monitoring waves "
            "may overlap."
        )

    logger.info("Monitoring started with %d targets", num_targets)

    target_max = settings.max_concurrent_requests
    effective_limit = min(target_max, num_targets or 1)
    semaphore = asyncio.Semaphore(effective_limit)

    # Limit per-wave fan-out by batching very large target sets. This keeps
    # the number of concurrently scheduled tasks bounded even when there are
    # thousands of targets.
    BATCH_SIZE = 200
    batch_size = max(1, min(BATCH_SIZE, effective_limit, num_targets or 1))
    if num_targets > batch_size:
        logger.info(
            "Monitoring %d targets in batches of %d to limit per-wave fan-out.",
            num_targets,
            batch_size,
        )

    # Load maintenance windows once for the lifetime of this monitor process.
    maintenance_windows: List[MaintenanceWindow] = []
    if settings.maintenance_windows_file is not None:
        try:
            maintenance_windows = load_maintenance_windows(
                settings.maintenance_windows_file
            )
            logger.info(
                "Loaded %d maintenance windows from %s",
                len(maintenance_windows),
                settings.maintenance_windows_file,
            )
        except FileNotFoundError:
            logger.warning(
                "Maintenance windows file not found: %s",
                settings.maintenance_windows_file,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to load maintenance windows from %s: %s",
                settings.maintenance_windows_file,
                exc,
            )
            maintenance_windows = []

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while not stop_event.is_set():
            loop_start = time.perf_counter()

            # Begin single transaction for this wave.
            await db.begin()

            results: List[tuple[str, bool, int, float, str | None]] = []

            async def _run_check(
                target: Target,
            ) -> tuple[str, bool, int, float, str | None]:
                async with semaphore:
                    return await _check_target(session, db, target, settings)

            # Process targets in batches to avoid creating an excessive
            # number of tasks in a single gather() call when the target
            # list is very large.
            for i in range(0, num_targets, batch_size):
                batch = targets_list[i : i + batch_size]
                tasks = [_run_check(target) for target in batch]
                batch_results = await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )
                for item in batch_results:
                    if isinstance(item, Exception):
                        logger.warning(
                            "Health check task failed with exception: %s", item
                        )
                        continue
                    results.append(item)

            # Retention housekeeping: periodically purge old records based on
            # retention_days. This keeps the checks table size bounded in
            # long-running monitor deployments.
            try:
                if settings.retention_days > 0:
                    now_utc = datetime.now(timezone.utc)
                    cutoff = now_utc - timedelta(days=settings.retention_days)
                    await db.delete_checks_in_range(until=cutoff)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to apply retention policy: %s", exc)

            # Commit all inserts for this wave.
            await db.commit()

            # Circuit breaker / global alert suppression based on this wave.
            total = len(results)
            failed = sum(1 for _, is_up, _, _, _ in results if not is_up)
            failure_ratio = failed / total if total > 0 else 0.0

            HIGH_FAILURE_THRESHOLD = 0.8
            RECOVERY_THRESHOLD = 0.5

            if failure_ratio >= HIGH_FAILURE_THRESHOLD and not notifier.is_suppressed:
                notifier.set_suppression(
                    True,
                    reason=(
                        f"High global failure rate: {failed}/{total} "
                        f"targets down ({failure_ratio:.0%})"
                    ),
                )
            elif failure_ratio < RECOVERY_THRESHOLD and notifier.is_suppressed:
                notifier.set_suppression(
                    False,
                    reason=(
                        f"Failure rate back below {RECOVERY_THRESHOLD:.0%}: "
                        f"{failed}/{total} targets down ({failure_ratio:.0%})"
                    ),
                )

            # Feed results to notifier after suppression decision, applying
            # maintenance windows as an additional suppression layer.
            now_utc = datetime.now(timezone.utc)
            for url, is_up, status_code, response_time_ms, name in results:
                if maintenance_windows and _is_within_maintenance(
                    url,
                    now_utc,
                    maintenance_windows,
                ):
                    # Suppress alerts for this target during maintenance, but
                    # keep writing checks to the database.
                    logger.info(
                        "Suppressing alerts for %s due to active maintenance window.",
                        url,
                    )
                    continue

                await notifier.handle_check_result(
                    url=url,
                    is_up=is_up,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    name=name,
                )

            elapsed = time.perf_counter() - loop_start

            # Persist internal telemetry for cross-process metrics reporting.
            try:
                await db.upsert_telemetry(
                    "last_wave_timestamp_seconds",
                    f"{time.time():.6f}",
                )
                await db.upsert_telemetry(
                    "last_wave_duration_seconds",
                    f"{elapsed:.6f}",
                )
                await db.upsert_telemetry(
                    "current_concurrency_limit",
                    str(effective_limit),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to upsert telemetry: %s", exc)

            # Adaptive concurrency (AIMD-style backpressure).
            timeout_failures = sum(
                1
                for _, is_up, status_code, _, _ in results
                if status_code == 0 and not is_up
            )
            timeout_ratio = timeout_failures / total if total > 0 else 0.0

            http_5xx_failures = sum(
                1
                for _, is_up, status_code, _, _ in results
                if 500 <= status_code < 600 and not is_up
            )
            http_5xx_ratio = http_5xx_failures / total if total > 0 else 0.0

            new_limit = _adjust_concurrency(
                effective_limit=effective_limit,
                target_max=target_max,
                timeout_ratio=timeout_ratio,
                http_5xx_ratio=http_5xx_ratio,
                elapsed=elapsed,
                poll_interval_seconds=settings.poll_interval_seconds,
            )
            if new_limit != effective_limit:
                increasing = new_limit > effective_limit
                effective_limit = new_limit
                semaphore = asyncio.Semaphore(effective_limit)
                if increasing:
                    logger.info(
                        "Relaxing backpressure: increasing concurrency to %d "
                        "(wave_duration=%.2fs)",
                        effective_limit,
                        elapsed,
                    )
                else:
                    logger.warning(
                        "Applying backpressure: reducing concurrency to %d "
                        "(timeout_ratio=%.2f, wave_duration=%.2fs)",
                        effective_limit,
                        timeout_ratio,
                        elapsed,
                    )

            # Optional heartbeat ping (deadman switch).
            if settings.heartbeat_ping_url:

                async def _send_heartbeat(url: str) -> None:
                    try:
                        # Short timeout to avoid blocking the main loop.
                        async with session.get(url, timeout=5):
                            return
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Heartbeat ping to %s failed: %s", url, exc)

                asyncio.create_task(_send_heartbeat(settings.heartbeat_ping_url))

            sleep_for = max(0.0, settings.poll_interval_seconds - elapsed)
            if sleep_for > 0:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
                except asyncio.TimeoutError:
                    # Expected: timeout means we should run the next iteration.
                    continue

        logger.info("Monitoring loop stopped.")


__all__ = [
    "monitor_targets",
    "_check_target",
    "_adjust_concurrency",
]
