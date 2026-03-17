from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import AnyHttpUrl, BaseModel, Field, PositiveInt, root_validator


class Target(BaseModel):
    """
    Represents a single HTTP(S) endpoint to monitor.

    :param url: The full URL of the service.
    :param expected_status: Default HTTP status code considered healthy.
    :param timeout: Request timeout in seconds.
    :param name: Optional human-readable name for the target.
    :param method: HTTP method to use (GET, POST, etc.).
    :param headers: Optional HTTP headers to include in the request.
    :param latency_threshold_ms: Optional latency threshold above which the
                                 service is considered degraded/down.
    :param expected_body_substring: Optional substring that must appear in the
                                    response body for the service to be
                                    considered healthy.
    :param expected_json_key: Optional JSON key that must be present in the
                              response payload for the service to be
                              considered healthy.
    :param expected_json_value: Optional expected value for the JSON key. If
                                provided, key must exist and value must equal
                                this for the service to be considered healthy.
    :param tls_days_before_expiry_warning: Optional threshold (in days) before
                                           certificate expiry used to treat the
                                           target as degraded/down.
    """

    url: AnyHttpUrl = Field(..., description="Full URL of the service to monitor.")
    expected_status: PositiveInt = Field(
        200, description="HTTP status code considered healthy."
    )
    timeout: float = Field(5.0, gt=0, description="Request timeout in seconds.")
    name: Optional[str] = Field(
        default=None, description="Optional human-readable name for the target."
    )

    method: Literal["GET", "POST", "HEAD"] = Field(
        "GET", description="HTTP method to use for the request."
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None, description="Optional HTTP headers to include in the request."
    )
    latency_threshold_ms: Optional[float] = Field(
        default=None,
        gt=0,
        description=(
            "If set, responses slower than this threshold (in ms) are treated as down."
        ),
    )
    expected_body_substring: Optional[str] = Field(
        default=None,
        description=(
            "If set, the response body must contain this substring for the "
            "service to be considered healthy."
        ),
    )
    allowed_statuses: Optional[List[int]] = Field(
        default=None,
        description=(
            "Optional list of HTTP status codes considered healthy. "
            "If provided, it takes precedence over expected_status."
        ),
    )
    expected_json_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional JSON key that must exist in the response body for the "
            "service to be considered healthy."
        ),
    )
    expected_json_value: Optional[Any] = Field(
        default=None,
        description=(
            "Optional expected JSON value for expected_json_key. If provided, "
            "the key must exist and have this exact value to be considered "
            "healthy."
        ),
    )
    tls_days_before_expiry_warning: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "If set and the target uses HTTPS, treat the service as down when "
            "the TLS certificate expires in fewer than this many days."
        ),
    )
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Optional override for maximum number of retries on transient errors. "
            "If not set, the global setting from AppSettings is used."
        ),
    )

    class Config:
        anystr_strip_whitespace = True

    @root_validator
    def _validate_timeouts(cls, values: dict) -> dict:  # type: ignore[override]
        """
        Apply conservative caps on per-target settings to avoid pathological
        configurations that could starve the monitor loop.

        - timeout is hard-capped at 60s.
        - max_retries is capped at 5 to keep total per-target time bounded.
        """
        timeout = values.get("timeout")
        if timeout is not None and timeout > 60.0:
            values["timeout"] = 60.0

        max_retries = values.get("max_retries")
        if max_retries is not None and max_retries > 5:
            values["max_retries"] = 5

        return values


__all__ = ["Target"]

