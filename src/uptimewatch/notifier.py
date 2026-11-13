"""Send state-change embeds to a Discord webhook. Failures are logged, never raised."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests

from .config import CheckConfig
from .state import DOWN, Transition, format_duration

log = logging.getLogger(__name__)

RED = 0xE74C3C
GREEN = 0x2ECC71
MAX_RETRY_WAIT = 10.0  # seconds; never block the monitor for longer on a rate limit
FIELD_LIMIT = 1024  # Discord's maximum length for an embed field value


def is_valid_webhook_url(url: str) -> bool:
    """Basic sanity check: an http(s) URL with a host."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def build_payload(transition: Transition, check: CheckConfig) -> dict[str, Any]:
    """Build the JSON body for the webhook request."""
    is_down = transition.new_status == DOWN
    fields = [{"name": "Target", "value": _clip(f"`{check.target}`"), "inline": False}]
    if is_down:
        fields.append(
            {"name": "Reason", "value": _clip(transition.error or "Unknown"), "inline": False}
        )
        fields.append(
            {"name": "Failed checks in a row", "value": str(transition.failures), "inline": True}
        )
    else:
        downtime = format_duration(transition.downtime_seconds or 0)
        fields.append({"name": "Downtime", "value": downtime, "inline": True})

    embed = {
        "title": f"\U0001f534 {check.name} is DOWN"
        if is_down
        else f"\U0001f7e2 {check.name} is back UP",
        "color": RED if is_down else GREEN,
        "fields": fields,
        "footer": {"text": "uptimewatch"},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    # allowed_mentions stops error text from pinging anyone.
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


class DiscordNotifier:
    """Posts embeds to one webhook URL."""

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self._url = webhook_url
        self._timeout = timeout

    def send(self, transition: Transition, check: CheckConfig) -> bool:
        """Send a notification. Returns True on success; never raises."""
        payload = build_payload(transition, check)
        try:
            response = self._post(payload)
            if response.status_code == 429:
                wait = _retry_after(response)
                log.warning("Discord rate limit hit, retrying once in %.1fs", wait)
                time.sleep(wait)
                response = self._post(payload)
            if response.status_code >= 300:
                log.error(
                    "Discord webhook rejected the notification (HTTP %s)", response.status_code
                )
                return False
        except Exception as exc:
            # Only the exception type is logged: requests puts the full URL
            # (which contains the webhook token) in its error messages.
            log.error("Could not deliver Discord notification (%s)", type(exc).__name__)
            return False
        log.info("Notification sent for %r (%s)", check.name, transition.new_status)
        return True

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        """Single POST to the webhook."""
        return requests.post(self._url, json=payload, timeout=self._timeout)


def _retry_after(response: requests.Response) -> float:
    """Seconds to wait after a 429, taken from the body or header, capped."""
    value: Any = None
    try:
        value = response.json().get("retry_after")
    except ValueError:
        pass
    if value is None:
        value = response.headers.get("Retry-After")
    try:
        return min(max(float(value), 0.0), MAX_RETRY_WAIT)
    except (TypeError, ValueError):
        return 1.0


def _clip(text: str) -> str:
    """Trim text to Discord's field limit."""
    return text if len(text) <= FIELD_LIMIT else text[: FIELD_LIMIT - 3] + "..."
