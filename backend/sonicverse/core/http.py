"""Shared HTTP client so provider searches reuse keep-alive connections."""

from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None

_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
_LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16)


def http_client() -> httpx.AsyncClient:
    """Process-wide AsyncClient. Safe to call from concurrent tasks."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            limits=_LIMITS,
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
