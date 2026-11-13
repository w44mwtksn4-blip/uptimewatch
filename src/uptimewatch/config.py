"""Load and validate ``config.yaml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

DEFAULT_INTERVAL = 60.0
DEFAULT_TIMEOUT = 10.0
DEFAULT_FAILURE_THRESHOLD = 3

_TOP_LEVEL_KEYS = {"interval", "timeout", "failure_threshold", "checks"}
_COMMON_CHECK_KEYS = {"name", "type", "failure_threshold"}
_HTTP_KEYS = _COMMON_CHECK_KEYS | {"url", "expected_status"}
_TCP_KEYS = _COMMON_CHECK_KEYS | {"host", "port"}


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class CheckConfig:
    """One monitored target (an HTTP(S) URL or a TCP host:port)."""

    name: str
    type: str  # "http" or "tcp"
    failure_threshold: int
    url: str | None = None
    expected_status: int | None = None
    host: str | None = None
    port: int | None = None

    @property
    def target(self) -> str:
        """Human-readable target, shown in logs and notifications."""
        return self.url if self.type == "http" else f"{self.host}:{self.port}"


@dataclass(frozen=True)
class Settings:
    """Global settings plus the list of checks."""

    interval: float = DEFAULT_INTERVAL
    timeout: float = DEFAULT_TIMEOUT
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    checks: list[CheckConfig] = field(default_factory=list)


def load_config(path: Path) -> Settings:
    """Read ``path`` and return validated settings, or raise ``ConfigError``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {path} is not valid YAML: {exc}") from exc
    return parse_config(data)


def parse_config(data: Any) -> Settings:
    """Validate an already-parsed config mapping."""
    if not isinstance(data, dict):
        raise ConfigError("The config must be a mapping with a 'checks' list.")
    _reject_unknown_keys(data, _TOP_LEVEL_KEYS, "config")

    interval = _positive_number(data.get("interval", DEFAULT_INTERVAL), "interval")
    timeout = _positive_number(data.get("timeout", DEFAULT_TIMEOUT), "timeout")
    threshold = _positive_int(
        data.get("failure_threshold", DEFAULT_FAILURE_THRESHOLD), "failure_threshold"
    )

    raw_checks = data.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ConfigError("'checks' must be a non-empty list.")

    checks: list[CheckConfig] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_checks, start=1):
        check = _parse_check(raw, index, threshold)
        if check.name in seen:
            raise ConfigError(f"Duplicate check name: {check.name!r}.")
        seen.add(check.name)
        checks.append(check)
    return Settings(interval=interval, timeout=timeout, failure_threshold=threshold, checks=checks)


def _parse_check(raw: Any, index: int, default_threshold: int) -> CheckConfig:
    """Validate one entry of the ``checks`` list."""
    where = f"check #{index}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping.")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{where} needs a non-empty 'name'.")
    name = name.strip()
    where = f"check {name!r}"

    kind = raw.get("type")
    if kind not in ("http", "tcp"):
        raise ConfigError(f"{where}: 'type' must be 'http' or 'tcp'.")
    _reject_unknown_keys(raw, _HTTP_KEYS if kind == "http" else _TCP_KEYS, where)

    threshold = _positive_int(
        raw.get("failure_threshold", default_threshold), f"{where}: failure_threshold"
    )

    if kind == "http":
        url = raw.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(f"{where}: 'url' must be a full http:// or https:// URL.")
        status = raw.get("expected_status")
        if status is not None and (
            isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599
        ):
            raise ConfigError(f"{where}: 'expected_status' must be an HTTP status code.")
        return CheckConfig(
            name=name, type="http", failure_threshold=threshold, url=url, expected_status=status
        )

    host = raw.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ConfigError(f"{where}: 'host' must be a non-empty string.")
    port = raw.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError(f"{where}: 'port' must be an integer between 1 and 65535.")
    return CheckConfig(
        name=name, type="tcp", failure_threshold=threshold, host=host.strip(), port=port
    )


def _reject_unknown_keys(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    """Fail on unexpected keys so typos do not silently disable options."""
    unknown = sorted(str(key) for key in mapping if key not in allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown option(s): {', '.join(unknown)}.")


def _positive_number(value: Any, label: str) -> float:
    """Return ``value`` as a float if it is a number greater than zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{label} must be a number greater than 0.")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    """Return ``value`` if it is an integer of at least 1."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{label} must be a whole number of at least 1.")
    return value
