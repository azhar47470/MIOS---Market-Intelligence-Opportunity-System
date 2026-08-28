from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import Field

from app.application.event_bus import EventBus
from app.domain.common import DomainModel
from app.domain.events import (
    CalendarUpdatedEvent,
    COTUpdatedEvent,
    DXYUpdatedEvent,
    ETFUpdatedEvent,
    EventPriority,
    NewsUpdatedEvent,
)


class PollJobName(StrEnum):
    PRICE = "price"
    CALENDAR = "calendar"
    NEWS = "news"
    ETF = "etf"
    COT = "cot"


class PollJob(DomainModel):
    name: PollJobName
    interval_seconds: int = Field(gt=0)
    next_run_at: datetime


class PollingScheduler:
    def __init__(self, event_bus: EventBus, jobs: tuple[PollJob, ...] | None = None) -> None:
        self._event_bus = event_bus
        now = datetime.now(UTC)
        self._jobs = {
            job.name: job
            for job in (
                jobs
                or (
                    PollJob(
                        name=PollJobName.PRICE,
                        interval_seconds=15,
                        next_run_at=now,
                    ),
                    PollJob(
                        name=PollJobName.CALENDAR,
                        interval_seconds=300,
                        next_run_at=now,
                    ),
                    PollJob(
                        name=PollJobName.NEWS,
                        interval_seconds=900,
                        next_run_at=now,
                    ),
                    PollJob(
                        name=PollJobName.ETF,
                        interval_seconds=86_400,
                        next_run_at=now,
                    ),
                    PollJob(
                        name=PollJobName.COT,
                        interval_seconds=604_800,
                        next_run_at=now,
                    ),
                )
            )
        }

    def publish_due_events(self, now: datetime | None = None) -> tuple[PollJobName, ...]:
        current = now or datetime.now(UTC)
        published: list[PollJobName] = []
        for name, job in tuple(self._jobs.items()):
            if current < job.next_run_at:
                continue
            self._publish_job_event(name, current)
            self._jobs[name] = job.model_copy(
                update={"next_run_at": current + timedelta(seconds=job.interval_seconds)}
            )
            published.append(name)
        return tuple(published)

    def _publish_job_event(self, name: PollJobName, now: datetime) -> None:
        if name == PollJobName.COT:
            self._event_bus.publish(
                COTUpdatedEvent(
                    event_id=f"poll-cot-{now.isoformat()}",
                    priority=EventPriority.NORMAL,
                    payload={"source": "scheduler"},
                )
            )
        elif name == PollJobName.ETF:
            self._event_bus.publish(
                ETFUpdatedEvent(
                    event_id=f"poll-etf-{now.isoformat()}",
                    priority=EventPriority.NORMAL,
                    payload={"source": "scheduler"},
                )
            )
        elif name == PollJobName.NEWS:
            self._event_bus.publish(
                NewsUpdatedEvent(
                    event_id=f"poll-news-{now.isoformat()}",
                    priority=EventPriority.NORMAL,
                    payload={"source": "scheduler"},
                )
            )
        elif name == PollJobName.CALENDAR:
            self._event_bus.publish(
                CalendarUpdatedEvent(
                    event_id=f"poll-calendar-{now.isoformat()}",
                    priority=EventPriority.NORMAL,
                    payload={"source": "scheduler"},
                )
            )
        elif name == PollJobName.PRICE:
            self._event_bus.publish(
                DXYUpdatedEvent(
                    event_id=f"poll-price-{now.isoformat()}",
                    priority=EventPriority.NORMAL,
                    payload={"source": "scheduler"},
                )
            )
