import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models import Appointment, OutboxMessage
from app.services.whatsapp import WhatsAppClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox-worker")

BATCH_SIZE = 20
MAX_ATTEMPTS = 5
STALE_AFTER = timedelta(minutes=5)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def requeue_stale() -> None:
    with SessionLocal() as db:
        cutoff = utcnow() - STALE_AFTER
        rows = db.scalars(
            select(OutboxMessage).where(
                OutboxMessage.status == "sending",
                OutboxMessage.locked_at < cutoff,
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
            select(OutboxMessage)
            .where(
                OutboxMessage.status == "pending",
                OutboxMessage.next_attempt_at <= now,
            )
            .order_by(OutboxMessage.created_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()

        ids = []
        for row in rows:
            row.status = "sending"
            row.locked_at = now
            ids.append(row.id)

        db.commit()
        return ids


def deliver(message_id: str, client: WhatsAppClient) -> None:
    with SessionLocal() as db:
        row = db.get(OutboxMessage, message_id)
        if not row or row.status != "sending":
            return

        tenant = row.tenant

        # Appointment automations are only valid while the appointment remains confirmed.
        if row.appointment_id and row.message_kind == "template":
            appointment = db.get(Appointment, row.appointment_id)
            if not appointment or appointment.status != "confirmed":
                row.status = "cancelled"
                row.locked_at = None
                db.commit()
                return

        try:
            if row.message_kind == "template":
                if not row.template_name or not row.template_language:
                    raise ValueError("Outbox template sin nombre o idioma.")
                provider_id = client.send_template(
                    tenant=tenant,
                    to_wa_id=row.to_wa_id,
                    template_name=row.template_name,
                    language_code=row.template_language,
                    params=[str(x) for x in (row.template_params or [])],
                )
            else:
                provider_id = client.send_text(
                    tenant=tenant,
                    to_wa_id=row.to_wa_id,
                    body=row.body,
                )
            row.status = "sent"
            row.provider_message_id = provider_id
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
                delay_seconds = min(300, 2 ** row.attempts * 5)
                row.next_attempt_at = utcnow() + timedelta(seconds=delay_seconds)
            logger.exception("Error enviando outbox=%s", row.id)

        db.commit()


def main() -> None:
    client = WhatsAppClient()
    logger.info("Outbox worker iniciado")

    while True:
        requeue_stale()
        ids = claim_batch()

        if not ids:
            time.sleep(1.5)
            continue

        for message_id in ids:
            deliver(message_id, client)


if __name__ == "__main__":
    main()
