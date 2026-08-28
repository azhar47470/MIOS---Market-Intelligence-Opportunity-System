import logging
import time
from collections.abc import Callable


class ContinuousRunner:
    """Run one application cycle repeatedly without letting one failure stop monitoring."""

    def __init__(
        self,
        run_cycle: Callable[[], object],
        interval_seconds: float,
        *,
        logger: logging.Logger | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be zero or greater")
        self._run_cycle = run_cycle
        self._interval_seconds = interval_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._sleep = sleep
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self, *, max_cycles: int | None = None) -> int:
        completed_cycles = 0
        while not self._stop_requested:
            started_at = time.monotonic()
            try:
                self._run_cycle()
            except Exception:
                self._logger.exception("MIOS monitoring cycle failed; continuing")
            completed_cycles += 1
            if max_cycles is not None and completed_cycles >= max_cycles:
                break
            if self._stop_requested:
                break
            elapsed = time.monotonic() - started_at
            sleep_for = max(0.0, self._interval_seconds - elapsed)
            self._sleep(sleep_for)
        return completed_cycles
