"""Shared JSON-over-HTTP call with retries for judges backed by a web API."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from memworthy.judges.base import JudgeError

log = logging.getLogger("memworthy.judges.http")

RETRY_STATUS = frozenset({429, 500, 502, 503, 504, 529})


async def post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    label: str,
    timeout: float,
    retries: int,
    backoff: float,
    client: httpx.AsyncClient | None = None,
) -> tuple[dict[str, Any], int]:
    """POST ``body`` with retries; return the JSON object and latency in ms.

    Retries network errors and RETRY_STATUS with exponential backoff; other HTTP errors,
    invalid JSON and non-object bodies raise JudgeError. ``label`` names the provider in
    errors and logs.
    """
    http = client or httpx.AsyncClient(timeout=timeout)
    start = time.perf_counter()
    try:
        for attempt in range(retries + 1):
            try:
                resp = await http.post(url, json=body, headers=headers, timeout=timeout)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt >= retries:
                    raise JudgeError(f"{label} request failed: {type(exc).__name__}") from None
                log.warning("%s network error (%s); retrying", label, type(exc).__name__)
            else:
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        raise JudgeError(f"{label} returned invalid JSON") from None
                    if not isinstance(data, dict):
                        raise JudgeError(f"{label} returned a non-object body")
                    return data, int((time.perf_counter() - start) * 1000)
                if resp.status_code not in RETRY_STATUS or attempt >= retries:
                    raise JudgeError(f"{label} returned HTTP {resp.status_code}: "
                                     f"{_error_detail(resp)}")
                log.warning("%s HTTP %s; retrying", label, resp.status_code)
            await asyncio.sleep(backoff * (2**attempt))
        raise JudgeError(f"{label} request failed")  # pragma: no cover
    finally:
        if client is None:
            await http.aclose()


def _error_detail(resp: httpx.Response) -> str:
    try:
        text = resp.text
    except Exception:  # pragma: no cover
        return ""
    return text[:300]
