import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import CalendarSyncTask
from app.services.calendar_provider import GoogleCalendarProvider
from app.services.google_calendar import GoogleCalendarAPIError, GoogleCalendarConfigError


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calendar-sync-worker")

BATCH_SIZE = 20
MAX_ATTEMPTS = 8
STALE_AFTER = timedelta(minutes=5)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def requeue_stale() -> None:
    with SessionLocal() as db:
        cutoff = utcnow() - STALE_AFTER
        rows = db.scalars(
            select(CalendarSyncTask).where(
                CalendarSyncTask.status == "sending",
                CalendarSyncTask.locked_at < cutoff,
            )
        ).all()
        for row in rows:
            row.status = "pending"
            row.locked_at = None
        db.commit()


def claim_batch() -> list[str]:
    now = utcnow()
    with SessionLocal() as db:
        rows = db.scalars(
            select(CalendarSyncTask)
            .where(
                CalendarSyncTask.status == "pending",
                CalendarSyncTask.next_attempt_at <= now,
            )
            .order_by(CalendarSyncTask.created_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()

        ids: list[str] = []
        for row in rows:
            row.status = "sending"
            row.locked_at = now
            ids.append(row.id)
        db.commit()
        return ids


def deliver(task_id: str) -> None:
    with SessionLocal() as db:
        row = db.get(CalendarSyncTask, task_id)
        if not row or row.status != "sending":
            return

        try:
            if row.action != "delete_event":
                raise ValueError(f"Acción de calendar sync no soportada: {row.action}")

            tenant = row.tenant
            provider = GoogleCalendarProvider()
            gateway = provider._gateway(tenant)
            gateway.delete_event(
                calendar_id=str(row.payload["calendar_id"]),
                event_id=str(row.payload["event_id"]),
            )
            row.status = "sent"
            row.last_error = None
            row.locked_at = None
        except Exception as exc:
            row.attempts += 1
            row.last_error = str(exc)[:2000]
            row.locked_at = None

            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
            else:
                row.status = "pending"
                delay_seconds = min(1800, (2 ** row.attempts) * 10)
                row.next_attempt_at = utcnow() + timedelta(seconds=delay_seconds)
            logger.exception("Error calendar-sync task=%s", row.id)

        db.commit()


def main() -> None:
    logger.info("Calendar sync worker iniciado")
    while True:
        requeue_stale()
        ids = claim_batch()
        if not ids:
            time.sleep(2)
            continue
        for task_id in ids:
            deliver(task_id)


if __name__ == "__main__":
    main()
