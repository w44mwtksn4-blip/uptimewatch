"""Command line entry point: ``python -m uptimewatch``."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import ConfigError, load_config
from .logging_setup import setup_logging
from .monitor import run_forever, run_once
from .notifier import DiscordNotifier, is_valid_webhook_url

log = logging.getLogger("uptimewatch")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="uptimewatch",
        description="Monitor URLs and TCP ports and report state changes to Discord.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="path to the config file (default: ./config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run every check once and exit (for Task Scheduler or cron)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="state file (default: state.json next to the config file)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="log file (default: logs/monitor.log next to the config file)",
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    parser.add_argument("--version", action="version", version=f"uptimewatch {__version__}")
    return parser.parse_args(argv)


def build_notifier(timeout: float) -> DiscordNotifier | None:
    """Create a notifier from DISCORD_WEBHOOK_URL, or None if it is missing or invalid."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        log.warning("DISCORD_WEBHOOK_URL is not set: checks will run, but nothing will be sent.")
        return None
    if not is_valid_webhook_url(url):
        log.error("DISCORD_WEBHOOK_URL is not a valid http(s) URL: notifications are disabled.")
        return None
    return DiscordNotifier(url, timeout=timeout)


def install_signal_handlers(stop: threading.Event) -> None:
    """Turn Ctrl+C / termination signals into a clean shutdown request."""

    def handler(signum: int, _frame: object) -> None:
        log.info("Received signal %s, shutting down after the current check.", signum)
        stop.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK exists on Windows only
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, handler)


def main(argv: list[str] | None = None) -> int:
    """Run the monitor. Returns the process exit code."""
    args = parse_args(argv)
    base_dir = args.config.resolve().parent
    load_dotenv(base_dir / ".env")  # the .env file lives next to config.yaml
    setup_logging(args.log_file or base_dir / "logs" / "monitor.log", args.log_level)

    try:
        settings = load_config(args.config)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2

    state_path = args.state_file or base_dir / "state.json"
    notifier = build_notifier(settings.timeout)

    if args.once:
        run_once(settings, state_path, notifier)
        return 0

    stop = threading.Event()
    install_signal_handlers(stop)
    log.info(
        "uptimewatch %s started: %d check(s) every %gs",
        __version__,
        len(settings.checks),
        settings.interval,
    )
    run_forever(settings, state_path, notifier, stop)
    log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
