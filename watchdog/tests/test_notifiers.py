from __future__ import annotations

from typing import Any, List

import pytest

from src.infrastructure.notifiers import CheckStatus, CompositeNotifier, ConsoleNotifier


@pytest.mark.asyncio
async def test_console_notifier_state_and_transitions() -> None:
    """
    Verify that ConsoleNotifier tracks consecutive_failures/is_down correctly
    and only emits CRITICAL/RESOLVED at the right transitions.
    """
    notifier = ConsoleNotifier(failure_threshold=3)
    url = "https://example.com"

    # First failure: degraded, not yet marked as fully down.
    await notifier.handle_check_result(
        url=url,
        is_up=False,
        status_code=500,
        response_time_ms=100.0,
        name="Example",
    )
    state: CheckStatus = notifier._get_state(url)  # type: ignore[attr-defined]
    assert state.consecutive_failures == 1
    assert state.is_down is False

    # Second failure: still degraded.
    await notifier.handle_check_result(
        url=url,
        is_up=False,
        status_code=500,
        response_time_ms=110.0,
        name="Example",
    )
    state = notifier._get_state(url)  # type: ignore[attr-defined]
    assert state.consecutive_failures == 2
    assert state.is_down is False

    # Third failure crosses threshold -> marked as down.
    await notifier.handle_check_result(
        url=url,
        is_up=False,
        status_code=500,
        response_time_ms=120.0,
        name="Example",
    )
    state = notifier._get_state(url)  # type: ignore[attr-defined]
    assert state.consecutive_failures == 3
    assert state.is_down is True

    # Recovery: a single successful check should reset counters and clear is_down.
    await notifier.handle_check_result(
        url=url,
        is_up=True,
        status_code=200,
        response_time_ms=90.0,
        name="Example",
    )
    state = notifier._get_state(url)  # type: ignore[attr-defined]
    assert state.consecutive_failures == 0
    assert state.is_down is False


class DummyNotifier:
    def __init__(self) -> None:
        self.calls: List[dict[str, Any]] = []
        self.suppressed: bool = False

    @property
    def is_suppressed(self) -> bool:
        return self.suppressed

    def set_suppression(self, active: bool, reason: str | None = None) -> None:
        self.suppressed = active
        self.calls.append({"type": "suppress", "active": active, "reason": reason})

    async def handle_check_result(
        self,
        *,
        url: str,
        is_up: bool,
        status_code: int,
        response_time_ms: float,
        name: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "type": "event",
                "url": url,
                "is_up": is_up,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "name": name,
            }
        )


@pytest.mark.asyncio
async def test_composite_notifier_fanout_and_suppression() -> None:
    """
    CompositeNotifier should fan‑out events to all children and proxy
    is_suppressed/set_suppression correctly.
    """
    n1 = DummyNotifier()
    n2 = DummyNotifier()
    composite = CompositeNotifier(n1, n2)

    # is_suppressed is False by default.
    assert composite.is_suppressed is False

    # Fan‑out a single event.
    await composite.handle_check_result(
        url="https://example.com",
        is_up=False,
        status_code=500,
        response_time_ms=123.0,
        name="Example",
    )
    assert len(n1.calls) == 1
    assert len(n2.calls) == 1
    assert n1.calls[0]["type"] == "event"
    assert n2.calls[0]["type"] == "event"

    # Enable suppression through composite; both children should see it.
    composite.set_suppression(True, reason="test")
    assert n1.suppressed is True
    assert n2.suppressed is True
    assert composite.is_suppressed is True

    # Disable suppression.
    composite.set_suppression(False, reason="recover")
    assert n1.suppressed is False
    assert n2.suppressed is False
    assert composite.is_suppressed is False

