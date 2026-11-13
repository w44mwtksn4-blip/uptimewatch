"""Run a single check. ``run_check`` never raises."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import requests

from .config import CheckConfig

USER_AGENT = "uptimewatch/0.1 (+https://github.com/w44mwtksn4-blip/uptimewatch)"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check run."""

    ok: bool
    error: str | None = None
    latency_ms: float | None = None


def run_check(check: CheckConfig, timeout: float) -> CheckResult:
    """Run ``check`` and return a result; any unexpected error becomes a failure."""
    started = time.perf_counter()
    try:
        error = _check_http(check, timeout) if check.type == "http" else _check_tcp(check, timeout)
    except Exception as exc:  # one broken check must not stop the others
        error = f"Unexpected error: {type(exc).__name__}"
    latency = (time.perf_counter() - started) * 1000
    return CheckResult(ok=error is None, error=error, latency_ms=round(latency, 1))


def _check_http(check: CheckConfig, timeout: float) -> str | None:
    """Return None if the URL answers as expected, otherwise a short reason."""
    assert check.url is not None
    try:
        with requests.get(
            check.url,
            timeout=timeout,
            stream=True,  # do not download the body, the status line is enough
            headers={"User-Agent": USER_AGENT},
        ) as response:
            status = response.status_code
    except requests.Timeout:
        return f"Timed out after {timeout:g}s"
    except requests.exceptions.SSLError:
        return "TLS/SSL error"
    except requests.ConnectionError:
        return "Connection failed (DNS error or connection refused)"
    except requests.RequestException as exc:
        return f"Request failed: {type(exc).__name__}"

    if check.expected_status is not None:
        if status != check.expected_status:
            return f"Expected HTTP {check.expected_status}, got {status}"
    elif status >= 400:
        return f"HTTP {status}"
    return None


def _check_tcp(check: CheckConfig, timeout: float) -> str | None:
    """Return None if a TCP connection can be opened, otherwise a short reason."""
    assert check.host is not None and check.port is not None
    try:
        with socket.create_connection((check.host, check.port), timeout=timeout):
            return None
    except socket.gaierror:
        return "DNS lookup failed"
    except TimeoutError:
        return f"Timed out after {timeout:g}s"
    except ConnectionRefusedError:
        return "Connection refused"
    except OSError as exc:
        return f"Connection failed: {exc.strerror or type(exc).__name__}"
