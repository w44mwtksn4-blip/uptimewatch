"""Monitor loop: failed notifications are retried, broken checks do not crash the loop."""

from uptimewatch import monitor
from uptimewatch.checks import CheckResult
from uptimewatch.config import CheckConfig, Settings
from uptimewatch.state import DOWN, UP, CheckState

CHECK = CheckConfig(name="Web", type="http", failure_threshold=2, url="https://example.com")
SETTINGS = Settings(checks=[CHECK])


class FakeNotifier:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.sent = []

    def send(self, transition, check):
        self.sent.append(transition.new_status)
        return self.succeed


def patch_results(monkeypatch, *results):
    it = iter(results)
    monkeypatch.setattr(monitor, "run_check", lambda _c, _t: next(it))


FAIL = CheckResult(ok=False, error="boom")
OK = CheckResult(ok=True)


def test_down_then_recovery_sends_one_alert_each(monkeypatch):
    patch_results(monkeypatch, FAIL, FAIL, FAIL, OK, OK)
    notifier = FakeNotifier()
    states = {}
    for _ in range(5):
        states = monitor.run_cycle(SETTINGS, states, notifier)
    assert notifier.sent == [DOWN, UP]


def test_failed_down_notification_is_retried_next_cycle(monkeypatch):
    patch_results(monkeypatch, FAIL, FAIL, FAIL)
    notifier = FakeNotifier(succeed=False)
    states = {}
    for _ in range(3):
        states = monitor.run_cycle(SETTINGS, states, notifier)
    assert notifier.sent == [DOWN, DOWN]  # tried at failure 2 and again at failure 3


def test_failed_recovery_notification_is_retried_next_cycle(monkeypatch):
    patch_results(monkeypatch, OK, OK)
    notifier = FakeNotifier(succeed=False)
    states = {"Web": CheckState(status=DOWN, failures=2, first_failure_at=1.0)}
    for _ in range(2):
        states = monitor.run_cycle(SETTINGS, states, notifier)
    assert notifier.sent == [UP, UP]


def test_unexpected_error_in_one_check_does_not_stop_the_cycle(monkeypatch):
    other = CheckConfig(name="Other", type="tcp", failure_threshold=1, host="h", port=1)
    settings = Settings(checks=[CHECK, other])

    def fake_run_check(check, _timeout):
        if check.name == "Web":
            raise RuntimeError("bug")
        return OK

    monkeypatch.setattr(monitor, "run_check", fake_run_check)
    states = monitor.run_cycle(settings, {}, None)
    assert "Other" in states and "Web" not in states


def test_run_once_keeps_state_between_runs(monkeypatch, tmp_path):
    """Task Scheduler mode: each run starts from the previous run's state file."""
    path = tmp_path / "state.json"
    patch_results(monkeypatch, FAIL, FAIL, FAIL, OK, OK)
    notifier = FakeNotifier()
    for _ in range(5):
        monitor.run_once(SETTINGS, path, notifier)
    assert notifier.sent == [DOWN, UP]
