from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, CalendarSyncTask, Lead, Tenant
from app.services.appointment_automations import (
    cancel_scheduled_appointment_messages,
    schedule_appointment_messages,
)
from app.services.google_calendar import (
    GoogleCalendarAPIError,
    GoogleCalendarConfigError,
    GoogleCalendarGateway,
)
from app.services.scheduling import (
    AppointmentStateError,
    AvailableSlot,
    SlotUnavailable,
    cancel_appointment,
    confirm_appointment,
    list_available_slots,
    reserve_hold,
)


class CalendarProvider(Protocol):
    def list_available_slots(
        self,
        db: Session,
        tenant: Tenant,
        service_key: str,
        *,
        start_date: date | None = None,
        days: int | None = None,
        limit: int = 6,
        now: datetime | None = None,
    ) -> list[AvailableSlot]: ...

    def reserve_hold(self, db: Session, tenant: Tenant, **kwargs) -> Appointment: ...

    def confirm(
        self,
        db: Session,
        tenant: Tenant,
        appointment: Appointment,
        *,
        now: datetime | None = None,
    ) -> Appointment: ...

    def cancel(
        self,
        db: Session,
        tenant: Tenant,
        appointment: Appointment,
    ) -> Appointment: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _schedule(tenant: Tenant) -> dict:
    return ((tenant.workflow_spec or {}).get("schedule") or {})


def _resource(tenant: Tenant, resource_key: str) -> dict:
    for item in _schedule(tenant).get("resources", []):
        if str(item.get("key", "")) == resource_key:
            return item
    raise GoogleCalendarConfigError(f"Recurso no configurado: {resource_key}")


def _queue_delete(
    db: Session,
    *,
    tenant: Tenant,
    appointment: Appointment,
    calendar_id: str,
    event_id: str,
) -> None:
    key = f"delete:{calendar_id}:{event_id}"
    exists = db.scalar(
        select(CalendarSyncTask.id).where(
            CalendarSyncTask.tenant_id == tenant.id,
            CalendarSyncTask.idempotency_key == key,
        )
    )
    if exists:
        return
    db.add(
        CalendarSyncTask(
            tenant_id=tenant.id,
            appointment_id=appointment.id,
            action="delete_event",
            payload={"calendar_id": calendar_id, "event_id": event_id},
            idempotency_key=key,
        )
    )


class InternalCalendarProvider:
    def list_available_slots(self, db, tenant, service_key, **kwargs):
        return list_available_slots(db, tenant, service_key, **kwargs)

    def reserve_hold(self, db, tenant, **kwargs):
        return reserve_hold(db, tenant, **kwargs)

    def confirm(self, db, tenant, appointment, **kwargs):
        previous_id = appointment.supersedes_appointment_id
        confirmed = confirm_appointment(db, appointment, **kwargs)
        if previous_id:
            cancel_scheduled_appointment_messages(db, previous_id)
        schedule_appointment_messages(db, tenant, confirmed)
        return confirmed

    def cancel(self, db, tenant, appointment):
        cancelled = cancel_appointment(db, appointment)
        cancel_scheduled_appointment_messages(db, appointment.id)
        return cancelled


class GoogleCalendarProvider:
    """Internal DB is the booking source of truth; Google is synchronized on confirmation."""

    def _gateway(self, tenant: Tenant) -> GoogleCalendarGateway:
        google = _schedule(tenant).get("google", {})
        credentials_env = str(google.get("credentials_env", "")).strip()
        if not credentials_env:
            raise GoogleCalendarConfigError(
                "schedule.google.credentials_env es obligatorio para google_calendar."
            )
        delegated_subject_env = str(google.get("delegated_subject_env", "")).strip() or None
        return GoogleCalendarGateway(
            credentials_env=credentials_env,
            delegated_subject_env=delegated_subject_env,
        )

    def _calendar_id(self, tenant: Tenant, resource_key: str) -> str:
        resource = _resource(tenant, resource_key)
        env_name = str(resource.get("calendar_id_env", "")).strip()
        if not env_name:
            raise GoogleCalendarConfigError(
                f"El recurso {resource_key} necesita calendar_id_env."
            )
        calendar_id = os.getenv(env_name, "").strip()
        if not calendar_id:
            raise GoogleCalendarConfigError(
                f"Falta la variable de entorno {env_name} con el calendar id."
            )
        return calendar_id

    def list_available_slots(self, db, tenant, service_key, **kwargs):
        requested_limit = max(1, int(kwargs.pop("limit", 6)))
        # Fetch a wider internal candidate set first; otherwise a few externally busy
        # Google slots could hide later valid availability.
        candidates = list_available_slots(
            db,
            tenant,
            service_key,
            limit=max(50, requested_limit * 10),
            **kwargs,
        )
        if not candidates:
            return []

        gateway = self._gateway(tenant)
        calendar_ids = {
            slot.resource_key: self._calendar_id(tenant, slot.resource_key)
            for slot in candidates
        }
        start = min(slot.start_at for slot in candidates)
        end = max(slot.end_at for slot in candidates)
        busy = gateway.busy(
            calendar_ids=sorted(set(calendar_ids.values())),
            start=start,
            end=end,
        )

        result = []
        for slot in candidates:
            calendar_id = calendar_ids[slot.resource_key]
            if not any(
                interval.overlaps(slot.start_at, slot.end_at)
                for interval in busy.get(calendar_id, [])
            ):
                result.append(slot)
                if len(result) >= requested_limit:
                    break
        return result

    def reserve_hold(self, db, tenant, **kwargs):
        return reserve_hold(db, tenant, **kwargs)

    def confirm(self, db, tenant, appointment, *, now=None):
        if appointment.status == "confirmed":
            return appointment

        now_utc = _utc(now or datetime.now(timezone.utc))
        if appointment.status != "held":
            raise AppointmentStateError("La cita ya no está pendiente de confirmación.")
        if appointment.hold_expires_at and _utc(appointment.hold_expires_at) <= now_utc:
            return confirm_appointment(db, appointment, now=now_utc)

        gateway = self._gateway(tenant)
        calendar_id = self._calendar_id(tenant, appointment.resource_key)

        previous = None
        previous_calendar_id = None
        if appointment.supersedes_appointment_id:
            previous = db.get(Appointment, appointment.supersedes_appointment_id)
            if previous and previous.external_event_id:
                # Validate the old route before creating the replacement so a bad
                # configuration cannot produce a half-reprogrammed appointment.
                previous_calendar_id = self._calendar_id(
                    tenant,
                    previous.resource_key,
                )

        # Recheck external availability immediately before creating the event.
        busy = gateway.busy(
            calendar_ids=[calendar_id],
            start=appointment.start_at,
            end=appointment.end_at,
        )
        if any(
            interval.overlaps(appointment.start_at, appointment.end_at)
            for interval in busy.get(calendar_id, [])
        ):
            cancel_appointment(db, appointment)
            raise SlotUnavailable(
                "Ese horario se ocupó directamente en Google Calendar. Elige otro."
            )

        idempotency_key = f"localflow:{tenant.id}:{appointment.id}"
        event_id = gateway.find_event_id_by_idempotency(
            calendar_id=calendar_id,
            idempotency_key=idempotency_key,
            start=_utc(appointment.start_at) - timedelta(days=1),
            end=_utc(appointment.end_at) + timedelta(days=1),
        )

        if not event_id:
            lead = db.get(Lead, appointment.lead_id) if appointment.lead_id else None
            display_name = str((lead.answers or {}).get("nombre", "")).strip() if lead else ""
            summary = f"{tenant.name} · {appointment.service_key}"
            description = (
                f"Reserva LocalFlow {appointment.id}"
                + (f"\nCliente: {display_name}" if display_name else "")
            )
            event_id = gateway.create_event(
                calendar_id=calendar_id,
                summary=summary,
                description=description,
                start=appointment.start_at,
                end=appointment.end_at,
                timezone_name=tenant.timezone,
                idempotency_key=idempotency_key,
            )

        try:
            confirmed = confirm_appointment(db, appointment, now=now_utc)
        except Exception:
            # Compensation: do not leave a phantom external event if DB confirmation fails.
            try:
                gateway.delete_event(calendar_id=calendar_id, event_id=event_id)
            except Exception:
                _queue_delete(
                    db,
                    tenant=tenant,
                    appointment=appointment,
                    calendar_id=calendar_id,
                    event_id=event_id,
                )
            raise

        confirmed.external_provider = "google_calendar"
        confirmed.external_event_id = event_id
        if confirmed.supersedes_appointment_id:
            cancel_scheduled_appointment_messages(
                db,
                confirmed.supersedes_appointment_id,
            )
        schedule_appointment_messages(db, tenant, confirmed)

        # Safe reschedule: new event exists and DB switched before old external event is removed.
        if previous and previous.external_event_id and previous_calendar_id:
            _queue_delete(
                db,
                tenant=tenant,
                appointment=previous,
                calendar_id=previous_calendar_id,
                event_id=previous.external_event_id,
            )

        return confirmed

    def cancel(self, db, tenant, appointment):
        calendar_id = None
        if appointment.external_event_id:
            # Validate before changing internal state, so configuration errors cannot
            # leave Google confirmed while LocalFlow says cancelled.
            calendar_id = self._calendar_id(tenant, appointment.resource_key)

        cancelled = cancel_appointment(db, appointment)
        cancel_scheduled_appointment_messages(db, appointment.id)
        if appointment.external_event_id and calendar_id:
            _queue_delete(
                db,
                tenant=tenant,
                appointment=appointment,
                calendar_id=calendar_id,
                event_id=appointment.external_event_id,
            )
        return cancelled


_INTERNAL = InternalCalendarProvider()
_GOOGLE = GoogleCalendarProvider()


def get_calendar_provider(tenant: Tenant) -> CalendarProvider:
    provider = str(_schedule(tenant).get("provider", "internal")).casefold()
    if provider == "internal":
        return _INTERNAL
    if provider == "google_calendar":
        return _GOOGLE
    raise ValueError(f"Proveedor de calendario no configurado: {provider}")
