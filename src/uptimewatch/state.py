"""Per-check state machine and its JSON persistence.

``apply_result`` is a pure function: it takes the previous state and one check
result and returns the new state plus a ``Transition`` only when a notification
should be sent. All "no spam" logic lives here.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

UP = "up"
DOWN = "down"


@dataclass(frozen=True)
class CheckState:
    """What we remember about one check between runs."""

    status: str = UP
    failures: int = 0  # consecutive failed checks
    first_failure_at: float | None = None  # unix time the current failure streak began
    last_error: str | None = None


@dataclass(frozen=True)
class Transition:
    """A state change that should be announced."""

    name: str
    new_status: str
    error: str | None = None
    failures: int = 0
    downtime_seconds: float | None = None  # only set when recovering


def apply_result(
    name: str,
    state: CheckState,
    ok: bool,
    error: str | None,
    threshold: int,
    now: float,
) -> tuple[CheckState, Transition | None]:
    """Fold one check result into ``state``.

    A check is only declared DOWN after ``threshold`` consecutive failures, and
    only the first DOWN and the first success afterwards produce a transition.
    """
    if ok:
        if state.status == DOWN:
            started = state.first_failure_at if state.first_failure_at is not None else now
            transition = Transition(name, UP, downtime_seconds=max(0.0, now - started))
            return CheckState(), transition
        return CheckState(), None  # a success resets any partial failure streak

    failures = state.failures + 1
    first_failure_at = state.first_failure_at if state.first_failure_at is not None else now
    updated = replace(state, failures=failures, first_failure_at=first_failure_at, last_error=error)

    if state.status == UP and failures >= threshold:
        updated = replace(updated, status=DOWN)
        return updated, Transition(name, DOWN, error=error, failures=failures)
    return updated, None  # still counting, or already DOWN (no repeat alert)


def format_duration(seconds: float) -> str:
    """Format a duration such as ``1h 02m 05s`` or ``45s``."""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def load_state(path: Path) -> dict[str, CheckState]:
    """Load saved states. A missing or damaged file just means a fresh start."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable state file %s (%s)", path, type(exc).__name__)
        return {}

    states: dict[str, CheckState] = {}
    if not isinstance(raw, dict):
        return states
    for name, entry in raw.items():
        try:
            states[str(name)] = CheckState(**entry)
        except TypeError:
            log.warning("Ignoring malformed state entry for %r", name)
    return states


def save_state(path: Path, states: dict[str, CheckState]) -> None:
    """Write states atomically so a crash cannot leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({n: asdict(s) for n, s in states.items()}, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)
