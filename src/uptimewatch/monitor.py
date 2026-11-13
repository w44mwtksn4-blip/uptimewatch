"""Glue: run every check, update state, notify on changes."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from .checks import CheckResult, run_check
from .config import CheckConfig, Settings
from .notifier import DiscordNotifier
from .state import DOWN, UP, CheckState, Transition, apply_result, load_state, save_state

log = logging.getLogger(__name__)


def run_cycle(
    settings: Settings,
    states: dict[str, CheckState],
    notifier: DiscordNotifier | None,
    stop: threading.Event | None = None,
) -> dict[str, CheckState]:
    """Run each check once and return the updated states (the input is not modified)."""
    states = dict(states)
    for check in settings.checks:
        if stop is not None and stop.is_set():
            break
        try:
            states[check.name] = _process_check(check, settings, states, notifier)
        except Exception:  # the loop must survive anything
            log.exception("Unexpected error while processing %r", check.name)
    return states


def _process_check(
    check: CheckConfig,
    settings: Settings,
    states: dict[str, CheckState],
    notifier: DiscordNotifier | None,
) -> CheckState:
    """Run one check, log the result and send a notification if the state changed."""
    result = run_check(check, settings.timeout)
    _log_result(check, result)

    previous = states.get(check.name, CheckState())
    current, transition = apply_result(
        check.name, previous, result.ok, result.error, check.failure_threshold, time.time()
    )
    if transition is None:
        return current

    log.warning("%r changed state to %s", check.name, transition.new_status.upper())
    if notifier is None or notifier.send(transition, check):
        return current
    return _undo_transition(previous, current, transition)


def _undo_transition(
    previous: CheckState, current: CheckState, transition: Transition
) -> CheckState:
    """Keep the old status when a notification failed, so the next run tries again.

    Failure and recovery details are kept, so the retried alert is still accurate.
    """
    if transition.new_status == DOWN:
        return replace(current, status=UP)  # failures >= threshold: re-triggers on next failure
    return previous  # still DOWN: re-triggers on next success


def _log_result(check: CheckConfig, result: CheckResult) -> None:
    """One log line per check run."""
    if result.ok:
        log.info("%s OK (%s, %.0f ms)", check.name, check.target, result.latency_ms or 0)
    else:
        log.warning("%s FAILED (%s): %s", check.name, check.target, result.error)


def run_once(settings: Settings, state_path: Path, notifier: DiscordNotifier | None) -> None:
    """Single cycle, for Task Scheduler or cron. State is loaded and saved around it."""
    states = _prune(load_state(state_path), settings)
    _save_quietly(state_path, run_cycle(settings, states, notifier))


def run_forever(
    settings: Settings,
    state_path: Path,
    notifier: DiscordNotifier | None,
    stop: threading.Event,
) -> None:
    """Run cycles until ``stop`` is set. State is saved after every cycle."""
    states = _prune(load_state(state_path), settings)
    while not stop.is_set():
        started = time.monotonic()
        states = run_cycle(settings, states, notifier, stop)
        _save_quietly(state_path, states)
        _sleep(settings.interval - (time.monotonic() - started), stop)


def _prune(states: dict[str, CheckState], settings: Settings) -> dict[str, CheckState]:
    """Drop saved state for checks that are no longer in the config."""
    names = {check.name for check in settings.checks}
    return {name: state for name, state in states.items() if name in names}


def _save_quietly(path: Path, states: dict[str, CheckState]) -> None:
    """Save state; a disk problem is logged but must not stop monitoring."""
    try:
        save_state(path, states)
    except OSError as exc:
        log.error("Could not save state to %s (%s)", path, exc.strerror or exc)


def _sleep(seconds: float, stop: threading.Event) -> None:
    """Sleep in short slices so Ctrl+C and service stops are handled quickly."""
    deadline = time.monotonic() + max(0.0, seconds)
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        stop.wait(min(1.0, remaining))
