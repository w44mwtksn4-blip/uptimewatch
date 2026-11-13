"""State transition logic: thresholds, recovery and no duplicate alerts."""

from uptimewatch.state import (
    DOWN,
    UP,
    CheckState,
    apply_result,
    format_duration,
    load_state,
    save_state,
)

THRESHOLD = 3


def feed(state, results, start=1000.0, step=60.0):
    """Apply a list of booleans in order and collect any transitions."""
    transitions = []
    for i, ok in enumerate(results):
        state, transition = apply_result(
            "svc", state, ok, None if ok else "boom", THRESHOLD, start + i * step
        )
        if transition:
            transitions.append(transition)
    return state, transitions


def test_healthy_check_never_alerts():
    state, transitions = feed(CheckState(), [True] * 5)
    assert state.status == UP
    assert transitions == []


def test_failures_below_threshold_do_not_alert():
    state, transitions = feed(CheckState(), [False, False])
    assert state.status == UP
    assert state.failures == 2
    assert transitions == []


def test_down_alert_fires_exactly_at_threshold():
    state, transitions = feed(CheckState(), [False] * THRESHOLD)
    assert state.status == DOWN
    assert len(transitions) == 1
    assert transitions[0].new_status == DOWN
    assert transitions[0].error == "boom"
    assert transitions[0].failures == THRESHOLD


def test_no_duplicate_down_alerts_while_still_down():
    _, transitions = feed(CheckState(), [False] * 10)
    assert len(transitions) == 1


def test_success_resets_failure_streak():
    state, transitions = feed(CheckState(), [False, False, True, False, False])
    assert state.status == UP
    assert state.failures == 2
    assert transitions == []


def test_recovery_alert_reports_downtime_from_first_failure():
    # Failures at t=1000, 1060, 1120 (DOWN), then success at t=1180.
    state, transitions = feed(CheckState(), [False, False, False, True])
    assert [t.new_status for t in transitions] == [DOWN, UP]
    assert transitions[1].downtime_seconds == 180.0
    assert state == CheckState()


def test_no_duplicate_recovery_alerts():
    _, transitions = feed(CheckState(), [False] * 3 + [True] * 5)
    assert [t.new_status for t in transitions] == [DOWN, UP]


def test_second_outage_alerts_again():
    _, transitions = feed(CheckState(), [False] * 3 + [True] + [False] * 3 + [True])
    assert [t.new_status for t in transitions] == [DOWN, UP, DOWN, UP]


def test_threshold_of_one_alerts_on_first_failure():
    _, transition = apply_result("svc", CheckState(), False, "boom", 1, 0.0)
    assert transition is not None and transition.new_status == DOWN


def test_format_duration():
    assert format_duration(45) == "45s"
    assert format_duration(125) == "2m 05s"
    assert format_duration(3725) == "1h 02m 05s"


def test_state_survives_save_and_load(tmp_path):
    path = tmp_path / "state.json"
    down = CheckState(status=DOWN, failures=4, first_failure_at=123.0, last_error="boom")
    save_state(path, {"svc": down})
    assert load_state(path) == {"svc": down}


def test_down_state_loaded_from_disk_gives_one_recovery_alert():
    """Simulates --once runs: each run starts from the previous run's saved state."""
    down = CheckState(status=DOWN, failures=3, first_failure_at=1000.0)
    state, transition = apply_result("svc", down, True, None, THRESHOLD, 1300.0)
    assert transition is not None and transition.downtime_seconds == 300.0
    _, again = apply_result("svc", state, True, None, THRESHOLD, 1360.0)
    assert again is None


def test_missing_or_corrupt_state_file_means_fresh_start(tmp_path):
    assert load_state(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_state(bad) == {}
