from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol

import aiohttp
import asyncio
import json
import smtplib
from email.message import EmailMessage
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.core.logger import get_logger


logger = get_logger("notifiers")
console = Console()


@dataclass
class CheckStatus:
    """
    In-memory state tracking for a single monitored target.
    """

    consecutive_failures: int = 0
    is_down: bool = False


class Notifier(Protocol):
    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        ...


class ConsoleNotifier:
    """
    Console-based notifier that prints rich alerts to the terminal.

    Maintains per-target consecutive failure counts and only emits:
    - 🚨 CRITICAL when a target crosses the failure threshold.
    - ✅ RESOLVED when a previously down target recovers.
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        self._failure_threshold = failure_threshold
        self._state: Dict[str, CheckStatus] = {}
        self._suppressed: bool = False
        self._suppression_reason: Optional[str] = None

    @property
    def is_suppressed(self) -> bool:
        """
        Whether global alert suppression is currently active.
        """
        return self._suppressed

    def set_suppression(self, active: bool, reason: Optional[str] = None) -> None:
        """
        Enable or disable global alert suppression.

        When suppression is enabled, CRITICAL alerts are not printed for new
        failures, but recovery (RESOLVED) messages are still emitted so that
        operators can see when the system stabilises.
        """
        if active and not self._suppressed:
            self._suppressed = True
            self._suppression_reason = reason
            logger.warning(
                "Global alert suppression ENABLED%s",
                f": {reason}" if reason else "",
            )
        elif not active and self._suppressed:
            logger.info(
                "Global alert suppression DISABLED%s",
                f": {self._suppression_reason}" if self._suppression_reason else "",
            )
            self._suppressed = False
            self._suppression_reason = None

    def _get_state(self, url: str) -> CheckStatus:
        if url not in self._state:
            self._state[url] = CheckStatus()
        return self._state[url]

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        """
        Update state based on a new check result and print alerts as needed.
        """
        state = self._get_state(url)
        display_name = name or url

        if is_up:
            if state.is_down:
                # Service has recovered.
                logger.info("Service recovered: %s", display_name)
                state.consecutive_failures = 0
                state.is_down = False
                self._print_resolved(display_name, url, status_code, response_time_ms)
            else:
                state.consecutive_failures = 0
            return

        # Service is down.
        state.consecutive_failures += 1
        logger.warning(
            "Service failure (%s): %s [status=%s, failures=%s]",
            "DOWN" if state.is_down else "DEGRADED",
            display_name,
            status_code,
            state.consecutive_failures,
        )

        # If global suppression is active, do not emit new CRITICAL alerts,
        # but continue tracking failure counters so that we keep an internal
        # view of service health.
        if self._suppressed:
            logger.debug(
                "Alert suppressed for %s (consecutive_failures=%s)",
                display_name,
                state.consecutive_failures,
            )
            return

        if (
            state.consecutive_failures >= self._failure_threshold
            and not state.is_down
        ):
            state.is_down = True
            self._print_critical(
                display_name,
                url,
                status_code,
                response_time_ms,
                state.consecutive_failures,
            )

    def _print_critical(
        self,
        display_name: str,
        url: str,
        status_code: int,
        response_time_ms: float,
        failure_count: int,
    ) -> None:
        text = Text.assemble(
            ("🚨 CRITICAL: Service down\n", "bold red"),
            ("Service: ", "bold"),
            (display_name + "\n",),
            ("URL: ", "bold"),
            (url + "\n",),
            ("Status: ", "bold"),
            (str(status_code) + "\n",),
            ("Consecutive failures: ", "bold"),
            (str(failure_count) + "\n",),
        )
        console.print(Panel(text, border_style="red", expand=False))

    def _print_resolved(
        self,
        display_name: str,
        url: str,
        status_code: int,
        response_time_ms: float,
    ) -> None:
        text = Text.assemble(
            ("✅ RESOLVED: Service recovered\n", "bold green"),
            ("Service: ", "bold"),
            (display_name + "\n",),
            ("URL: ", "bold"),
            (url + "\n",),
            ("Status: ", "bold"),
            (str(status_code) + "\n",),
            ("Response time (ms): ", "bold"),
            (f"{response_time_ms:.2f}\n",),
        )
        console.print(Panel(text, border_style="green", expand=False))


class SlackNotifier:
    """
    Slack webhook-based notifier.

    Sends CRITICAL and RESOLVED events to a configured Slack incoming webhook.
    It does not maintain its own state; it relies on upstream logic to decide
    when to send notifications.
    """

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        # SlackNotifier expects to receive only "interesting" events
        # (e.g. CRITICAL/RESOLVED) from a higher-level notifier, so this
        # implementation simply posts the message as given.
        display_name = name or url
        status_emoji = "✅" if is_up else "🚨"
        title = "Service recovered" if is_up else "Service down"
        color = "good" if is_up else "danger"

        text = (
            f"{status_emoji} *{title}*\n"
            f"*Service*: {display_name}\n"
            f"*URL*: {url}\n"
            f"*Status*: `{status_code}`\n"
            f"*Response time*: `{response_time_ms:.2f} ms`"
        )

        payload = {
            "attachments": [
                {
                    "color": color,
                    "text": text,
                }
            ]
        }

        async with aiohttp.ClientSession() as session:
            backoff = 1.0
            for attempt in range(3):
                try:
                    async with session.post(
                        self._webhook_url,
                        json=payload,
                        timeout=5,
                    ) as resp:
                        if resp.status >= 400:
                            logger.warning(
                                "Slack webhook responded with status %s for %s (attempt %d/3)",
                                resp.status,
                                display_name,
                                attempt + 1,
                            )
                            if attempt < 2:
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to send Slack notification for %s (attempt %d/3): %s",
                        display_name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(backoff)
                        backoff *= 2


class EmailNotifier:
    """
    SMTP-based email notifier.

    Maintains its own consecutive failure state so that emails are only sent
    on CRITICAL (threshold crossed) and RESOLVED transitions, mirroring the
    ConsoleNotifier behaviour.
    """

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_from: str,
        smtp_to: str,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        failure_threshold: int = 3,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_from = smtp_from
        self._smtp_to = smtp_to
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._failure_threshold = failure_threshold
        self._state: Dict[str, CheckStatus] = {}

    def _get_state(self, url: str) -> CheckStatus:
        if url not in self._state:
            self._state[url] = CheckStatus()
        return self._state[url]

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        state = self._get_state(url)
        display_name = name or url

        if is_up:
            if state.is_down:
                # Service has recovered; send RESOLVED email.
                state.consecutive_failures = 0
                state.is_down = False
                subject = f"[WatchDog] ✅ RESOLVED: {display_name}"
                body = (
                    f"Service recovered\n\n"
                    f"Service: {display_name}\n"
                    f"URL: {url}\n"
                    f"Status: {status_code}\n"
                    f"Response time (ms): {response_time_ms:.2f}\n"
                )
                await self._send_email(subject, body)
            else:
                state.consecutive_failures = 0
            return

        # Service is down.
        state.consecutive_failures += 1

        if (
            state.consecutive_failures >= self._failure_threshold
            and not state.is_down
        ):
            state.is_down = True
            subject = f"[WatchDog] 🚨 CRITICAL: {display_name}"
            body = (
                f"Service down\n\n"
                f"Service: {display_name}\n"
                f"URL: {url}\n"
                f"Status: {status_code}\n"
                f"Consecutive failures: {state.consecutive_failures}\n"
                f"Response time (ms): {response_time_ms:.2f}\n"
            )
            await self._send_email(subject, body)

    async def _send_email(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._smtp_from
        msg["To"] = self._smtp_to
        msg.set_content(body)

        def _send() -> None:
            try:
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
                    server.ehlo()
                    try:
                        server.starttls()
                        server.ehlo()
                    except Exception:
                        # If STARTTLS is not supported, continue without TLS.
                        pass
                    if self._smtp_username and self._smtp_password:
                        server.login(self._smtp_username, self._smtp_password)
                    server.send_message(msg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to send email alert: %s", exc)

        await asyncio.to_thread(_send)


class WebhookNotifier:
    """
    Generic JSON webhook notifier.

    This notifier keeps simple per-target state so that only transitions
    (CRITICAL/RESOLVED) are sent, similar to the email notifier.
    """

    def __init__(self, url: str, failure_threshold: int = 3) -> None:
        self._url = url
        self._failure_threshold = failure_threshold
        self._state: Dict[str, CheckStatus] = {}

    def _get_state(self, url: str) -> CheckStatus:
        if url not in self._state:
            self._state[url] = CheckStatus()
        return self._state[url]

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        state = self._get_state(url)
        display_name = name or url

        event_type: Optional[str] = None

        if is_up:
            if state.is_down:
                state.consecutive_failures = 0
                state.is_down = False
                event_type = "RESOLVED"
            else:
                state.consecutive_failures = 0
        else:
            state.consecutive_failures += 1
            if (
                state.consecutive_failures >= self._failure_threshold
                and not state.is_down
            ):
                state.is_down = True
                event_type = "CRITICAL"

        if event_type is None:
            return

        payload = {
            "type": event_type,
            "service": display_name,
            "url": url,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
        }

        async with aiohttp.ClientSession() as session:
            backoff = 1.0
            for attempt in range(3):
                try:
                    async with session.post(
                        self._url,
                        data=json.dumps(payload),
                        headers={"Content-Type": "application/json"},
                        timeout=5,
                    ) as resp:
                        if resp.status >= 400:
                            logger.warning(
                                "Webhook responded with status %s for %s (attempt %d/3)",
                                resp.status,
                                display_name,
                                attempt + 1,
                            )
                            if attempt < 2:
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to send webhook notification for %s (attempt %d/3): %s",
                        display_name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(backoff)
                        backoff *= 2


class PagerDutyNotifier:
    """
    Very small PagerDuty Events v2 notifier.

    Sends CRITICAL/RESOLVED events using a routing key.
    """

    def __init__(self, routing_key: str, failure_threshold: int = 3) -> None:
        self._routing_key = routing_key
        self._failure_threshold = failure_threshold
        self._state: Dict[str, CheckStatus] = {}

    def _get_state(self, url: str) -> CheckStatus:
        if url not in self._state:
            self._state[url] = CheckStatus()
        return self._state[url]

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        state = self._get_state(url)
        display_name = name or url

        event_action: Optional[str] = None

        if is_up:
            if state.is_down:
                state.consecutive_failures = 0
                state.is_down = False
                event_action = "resolve"
            else:
                state.consecutive_failures = 0
        else:
            state.consecutive_failures += 1
            if (
                state.consecutive_failures >= self._failure_threshold
                and not state.is_down
            ):
                state.is_down = True
                event_action = "trigger"

        if event_action is None:
            return

        payload = {
            "routing_key": self._routing_key,
            "event_action": event_action,
            "payload": {
                "summary": f"WatchDog: {display_name}",
                "source": "watchdog-monitor",
                "severity": "error" if event_action == "trigger" else "info",
                "custom_details": {
                    "url": url,
                    "status_code": status_code,
                    "response_time_ms": response_time_ms,
                },
            },
            "dedup_key": url,
        }

        async with aiohttp.ClientSession() as session:
            backoff = 1.0
            for attempt in range(3):
                try:
                    async with session.post(
                        "https://events.pagerduty.com/v2/enqueue",
                        json=payload,
                        timeout=5,
                    ) as resp:
                        if resp.status >= 400:
                            logger.warning(
                                "PagerDuty responded with status %s for %s (attempt %d/3)",
                                resp.status,
                                display_name,
                                attempt + 1,
                            )
                            if attempt < 2:
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to send PagerDuty notification for %s (attempt %d/3): %s",
                        display_name,
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(backoff)
                        backoff *= 2


class CompositeNotifier:
    """
    Fan-out notifier that forwards events to multiple notifier implementations.
    Proxies is_suppressed/set_suppression to notifiers that support them (e.g. circuit breaker).
    """

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = list(notifiers)

    @property
    def is_suppressed(self) -> bool:
        """True if any underlying notifier has suppression active."""
        for n in self._notifiers:
            if getattr(n, "is_suppressed", None) is not None and n.is_suppressed:
                return True
        return False

    def set_suppression(self, active: bool, reason: Optional[str] = None) -> None:
        """Forward suppression to all notifiers that support it."""
        for n in self._notifiers:
            set_suppression = getattr(n, "set_suppression", None)
            if callable(set_suppression):
                set_suppression(active, reason)

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: Optional[str] = None,
    ) -> None:
        for notifier in self._notifiers:
            try:
                await notifier.handle_check_result(
                    url=url,
                    is_up=is_up,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    name=name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Notifier %s failed for %s: %s", type(notifier).__name__, url, exc)


__all__ = [
    "ConsoleNotifier",
    "SlackNotifier",
    "EmailNotifier",
    "WebhookNotifier",
    "PagerDutyNotifier",
    "CompositeNotifier",
    "Notifier",
]


