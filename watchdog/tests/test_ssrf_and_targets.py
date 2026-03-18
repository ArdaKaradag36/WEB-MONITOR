from __future__ import annotations

import pytest
from src.services.monitor import _is_safe_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,allow_private,expected",
    [
        ("https://example.com", False, True),
        ("http://127.0.0.1", False, False),
        ("http://127.0.0.1", True, True),
        ("http://10.0.0.1", False, False),
        ("http://10.0.0.1", True, True),
    ],
)
async def test_is_safe_url_private_and_public(
    url: str, allow_private: bool, expected: bool
) -> None:
    """
    Pure SSRF helper test: verify that private/loopback addresses are rejected
    when allow_private_ips=False and allowed when True, while public hosts are
    always allowed.
    """
    result = await _is_safe_url(url, allow_private)
    assert result is expected
