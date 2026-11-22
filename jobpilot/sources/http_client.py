from __future__ import annotations

import logging
import time

import httpx

from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def make_client() -> httpx.Client:
    return httpx.Client(timeout=15.0, follow_redirects=True)


def get_json(
    client: httpx.Client, url: str, limiter: HostRateLimiter, **kwargs
) -> dict | list:
    last_exc: Exception | None = None
    for attempt in range(3):
        limiter.wait(url)
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code in _RETRY_STATUSES and attempt < 2:
                delay = 2**attempt
                logger.warning("HTTP %s from %s, retry in %ss", resp.status_code, url, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _RETRY_STATUSES and attempt < 2:
                time.sleep(2**attempt)
                last_exc = exc
                continue
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError(f"Failed after retries: {url}") from last_exc


def get_text(client: httpx.Client, url: str, limiter: HostRateLimiter) -> str:
    last_exc: Exception | None = None
    for attempt in range(3):
        limiter.wait(url)
        try:
            resp = client.get(url)
            if resp.status_code in _RETRY_STATUSES and attempt < 2:
                delay = 2**attempt
                logger.warning("HTTP %s from %s, retry in %ss", resp.status_code, url, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _RETRY_STATUSES and attempt < 2:
                time.sleep(2**attempt)
                last_exc = exc
                continue
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError(f"Failed after retries: {url}") from last_exc
