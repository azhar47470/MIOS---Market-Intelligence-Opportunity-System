import logging

from app.scheduler.continuous_runner import ContinuousRunner


def test_continuous_runner_keeps_running_after_cycle_failure(caplog):
    calls: list[int] = []

    def run_cycle() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 2:
            raise RuntimeError("simulated provider failure")

    runner = ContinuousRunner(
        run_cycle,
        interval_seconds=0,
        logger=logging.getLogger("test.runner"),
        sleep=lambda _seconds: None,
    )

    with caplog.at_level(logging.ERROR):
        completed = runner.run(max_cycles=3)

    assert completed == 3
    assert calls == [1, 2, 3]
    assert "MIOS monitoring cycle failed; continuing" in caplog.text


def test_continuous_runner_can_be_stopped_by_cycle():
    calls = 0
    runner: ContinuousRunner | None = None

    def run_cycle() -> None:
        nonlocal calls
        calls += 1
        assert runner is not None
        runner.request_stop()

    runner = ContinuousRunner(run_cycle, interval_seconds=0, sleep=lambda _seconds: None)

    completed = runner.run()

    assert completed == 1
    assert calls == 1
