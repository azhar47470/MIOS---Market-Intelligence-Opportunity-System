import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import NewsEventSnapshot
from app.infrastructure.providers.base import ProviderBase, logger, optional_decimal, parse_datetime

_DEFAULT_COOLDOWN_STATE_PATH = Path("data") / "gdelt_cooldown.json"


class GDELTProvider(ProviderBase):
    # GDELT's own error message says "one every 5 seconds", but real-world runs
    # show it still rejecting requests ~13 seconds after a rate-limit hit - their
    # actual enforcement appears stricter than documented (possibly a longer
    # penalty window after a rejection, not just a flat per-request gap). 20s
    # gives real headroom; run-once/run_forever's own cycle time (60s) easily
    # absorbs it.
    _cooldown_seconds = 20.0
    _last_request_at: float | None = None  # in-process cache; see _read_last_request_at

    def __init__(
        self,
        *args,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        cooldown_state_path: Path | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # Wall-clock time, not time.monotonic(): the cooldown timestamp must be
        # comparable against one written by a *previous, separate process* (the
        # last `run-once` invocation), and a monotonic clock's reference point
        # isn't comparable across processes.
        self._clock = clock or time.time
        self._sleep = sleep or asyncio.sleep
        self._cooldown_state_path = cooldown_state_path or _DEFAULT_COOLDOWN_STATE_PATH

    async def news_events(self, query: str) -> ProviderResult[tuple[NewsEventSnapshot, ...]]:
        await self._respect_cooldown()
        status, payload, error = self._get_json("doc_articles", {"query": query})
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            events = tuple(
                NewsEventSnapshot(
                    headline=str(row.get("title")),
                    url=str(row.get("url")),
                    tone=optional_decimal(row.get("tone")),
                    date=parse_datetime(row.get("seendate")),
                )
                for row in payload.get("articles", ())
                if row.get("title") and row.get("url") and row.get("seendate")
            )
            return self._result(ContractStatus.SUCCESS, data=events)
        except (TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))

    async def _respect_cooldown(self) -> None:
        last_request_at = self._read_last_request_at()
        if last_request_at is not None:
            elapsed = self._clock() - last_request_at
            remaining = self._cooldown_seconds - elapsed
            if remaining > 0:
                logger.info("GDELTProvider cooldown active; waiting %.2f seconds.", remaining)
                await self._sleep(remaining)
        now = self._clock()
        GDELTProvider._last_request_at = now
        self._write_last_request_at(now)

    def _read_last_request_at(self) -> float | None:
        # GDELT enforces its rate limit (one request per five seconds) per IP,
        # not per process. A `run-once` invocation started a couple of seconds
        # after the previous one is a brand new process with no memory of that
        # previous call, so the in-memory class attribute alone can't protect
        # against back-to-back manual runs - only a persisted timestamp can.
        # Read both and trust whichever is more recent.
        candidates = [GDELTProvider._last_request_at]
        try:
            if self._cooldown_state_path.exists():
                raw = json.loads(self._cooldown_state_path.read_text(encoding="utf-8"))
                candidates.append(float(raw["last_request_at"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.info("GDELTProvider could not read cooldown state file: %s", exc)
        known = [value for value in candidates if value is not None]
        return max(known) if known else None

    def _write_last_request_at(self, timestamp: float) -> None:
        try:
            self._cooldown_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._cooldown_state_path.write_text(
                json.dumps({"last_request_at": timestamp}), encoding="utf-8"
            )
        except OSError as exc:
            # Cooldown tracking degrading to in-process-only isn't fatal - the
            # actual GDELT request below still proceeds either way.
            logger.info("GDELTProvider could not persist cooldown state: %s", exc)
