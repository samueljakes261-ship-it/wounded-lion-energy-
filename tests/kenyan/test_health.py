from kenyan.health import HealthState, WorkerHealth


def test_repeated_failures_before_first_success_are_degraded_not_starting():
    state = HealthState()
    assert state.classify(last_good_at=None, now=100) == WorkerHealth.STARTING

    state.record_failure("blocked by anti-bot challenge (non-JSON challenge page returned)")
    state.record_failure("blocked by anti-bot challenge (non-JSON challenge page returned)")
    assert state.classify(last_good_at=None, now=110) == WorkerHealth.STARTING

    state.record_failure("blocked by anti-bot challenge (non-JSON challenge page returned)")
    assert state.is_degraded is True
    assert state.classify(last_good_at=None, now=120) == WorkerHealth.DEGRADED


def test_running_requires_a_successful_parse_not_just_an_alive_thread():
    state = HealthState()
    state.record_empty_but_ok()
    assert state.has_ever_succeeded is False
    assert state.classify(last_good_at=None, now=100) == WorkerHealth.STARTING

    state.record_success()
    assert state.classify(last_good_at=90, now=100) == WorkerHealth.RUNNING
