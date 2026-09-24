from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Appointment, Lead, OutboxMessage, Tenant


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)



def _service_label(tenant: Tenant, service_key: str) -> str:
    schedule = ((tenant.workflow_spec or {}).get("schedule") or {})
    for service in schedule.get("services", []):
        if str(service.get("key", "")).casefold() == service_key.casefold():
            return str(service.get("label", service_key))
    return service_key


def _format_local_start(tenant: Tenant, value: datetime) -> str:
    local = _utc(value).astimezone(ZoneInfo(tenant.timezone))
    return local.strftime("%d/%m/%Y %H:%M")

def _automations(tenant: Tenant) -> dict:
    return ((tenant.workflow_spec or {}).get("automations") or {})


def _template_message(
    *,
    tenant: Tenant,
    lead: Lead,
    appointment: Appointment,
    template_key: str,
    run_at: datetime,
    params: list[str],
) -> OutboxMessage | None:
    config = _automations(tenant).get(template_key) or {}
    name = str(config.get("template_name", "")).strip()
    if not name:
        return None

    language = str(config.get("language", "es_MX")).strip() or "es_MX"
    return OutboxMessage(
        tenant_id=tenant.id,
        lead_id=lead.id,
        appointment_id=appointment.id,
        to_wa_id=lead.wa_id,
        message_kind="template",
        body=f"[template:{name}]",
        template_name=name,
        template_language=language,
        template_params=params,
        next_attempt_at=_utc(run_at),
    )


def cancel_scheduled_appointment_messages(db: Session, appointment_id: str) -> int:
    rows = db.scalars(
        select(OutboxMessage).where(
            OutboxMessage.appointment_id == appointment_id,
            OutboxMessage.status == "pending",
            OutboxMessage.message_kind == "template",
        )
    ).all()

    for row in rows:
        row.status = "cancelled"
        row.locked_at = None

    if rows:
        db.flush()
    return len(rows)


def schedule_appointment_messages(
    db: Session,
    tenant: Tenant,
    appointment: Appointment,
) -> list[OutboxMessage]:
    if not appointment.lead_id:
        return []

    lead = db.get(Lead, appointment.lead_id)
    if not lead:
        return []

    # Replace pending automations for the same appointment if confirmation is retried.
    cancel_scheduled_appointment_messages(db, appointment.id)

    config = _automations(tenant)
    now = datetime.now(timezone.utc)
    name = str((lead.answers or {}).get("nombre", "")).strip() or "cliente"
    service = _service_label(tenant, appointment.service_key)
    start_local = _format_local_start(tenant, appointment.start_at)
    review_url = str(config.get("google_review_url", "")).strip()

    created: list[OutboxMessage] = []

    reminder_cfg = config.get("appointment_reminder") or {}
    if reminder_cfg.get("enabled", False):
        before_minutes = int(reminder_cfg.get("before_minutes", 1440))
        run_at = _utc(appointment.start_at) - timedelta(minutes=before_minutes)
        if run_at < now:
            run_at = now
        message = _template_message(
            tenant=tenant,
            lead=lead,
            appointment=appointment,
            template_key="appointment_reminder",
            run_at=run_at,
            params=[name, service, start_local],
        )
        if message:
            db.add(message)
            created.append(message)

    review_cfg = config.get("review_request") or {}
    if review_cfg.get("enabled", False) and review_url:
        after_minutes = int(review_cfg.get("after_minutes", 120))
        run_at = _utc(appointment.end_at) + timedelta(minutes=after_minutes)
        message = _template_message(
            tenant=tenant,
            lead=lead,
            appointment=appointment,
            template_key="review_request",
            run_at=run_at,
            params=[name, review_url],
        )
        if message:
            db.add(message)
            created.append(message)

    if created:
        db.flush()

    return created
