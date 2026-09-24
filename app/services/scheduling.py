from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentSlot, Tenant


class ScheduleConfigError(ValueError):
    pass


class SlotUnavailable(ValueError):
    pass


class AppointmentStateError(ValueError):
    pass


@dataclass(frozen=True)
class AvailableSlot:
    resource_key: str
    start_at: datetime
    end_at: datetime


def _utc(value: datetime) -> datetime:
    """Normaliza a UTC aware; SQLite puede devolver timestamps naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def schedule_spec(tenant: Tenant) -> dict:
    spec = (tenant.workflow_spec or {}).get("schedule", {})
    validate_schedule_spec(spec)
    return spec


def validate_schedule_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise ScheduleConfigError("schedule debe ser un objeto JSON.")

    slot_minutes = int(spec.get("slot_minutes", 15))
    if slot_minutes <= 0 or 60 % slot_minutes != 0:
        raise ScheduleConfigError("schedule.slot_minutes debe ser divisor positivo de 60.")

    hold_minutes = int(spec.get("hold_minutes", 10))
    if hold_minutes <= 0:
        raise ScheduleConfigError("schedule.hold_minutes debe ser positivo.")

    horizon = int(spec.get("booking_horizon_days", 14))
    if horizon <= 0 or horizon > 365:
        raise ScheduleConfigError("schedule.booking_horizon_days debe estar entre 1 y 365.")

    resources = spec.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ScheduleConfigError("schedule.resources debe contener al menos un recurso.")
    resource_keys = []
    for resource in resources:
        key = str(resource.get("key", "")).strip()
        if not key:
            raise ScheduleConfigError("Cada recurso necesita key.")
        resource_keys.append(key)
    if len(resource_keys) != len(set(resource_keys)):
        raise ScheduleConfigError("Hay resource keys duplicados.")

    services = spec.get("services")
    if not isinstance(services, list) or not services:
        raise ScheduleConfigError("schedule.services debe contener al menos un servicio.")
    service_keys = []
    for service in services:
        key = str(service.get("key", "")).strip()
        if not key:
            raise ScheduleConfigError("Cada servicio necesita key.")
        service_keys.append(key)
        duration = int(service.get("duration_minutes", slot_minutes))
        if duration <= 0 or duration % slot_minutes != 0:
            raise ScheduleConfigError(
                f"duration_minutes de {key} debe ser múltiplo de slot_minutes."
            )
        assigned = [str(x) for x in service.get("resource_keys", [])]
        if not assigned:
            raise ScheduleConfigError(f"El servicio {key} necesita resource_keys.")
        unknown = set(assigned) - set(resource_keys)
        if unknown:
            raise ScheduleConfigError(f"Recursos desconocidos en {key}: {sorted(unknown)}")
    if len(service_keys) != len(set(service_keys)):
        raise ScheduleConfigError("Hay service keys duplicados.")

    weekly = spec.get("weekly_hours")
    if not isinstance(weekly, dict):
        raise ScheduleConfigError("schedule.weekly_hours debe ser un objeto.")
    for weekday, intervals in weekly.items():
        if str(weekday) not in {str(i) for i in range(7)}:
            raise ScheduleConfigError(f"Día inválido en weekly_hours: {weekday}")
        if not isinstance(intervals, list):
            raise ScheduleConfigError("Cada día de weekly_hours debe ser una lista.")
        for interval in intervals:
            if not isinstance(interval, list) or len(interval) != 2:
                raise ScheduleConfigError("Cada horario debe ser [inicio, fin].")
            start = _parse_hhmm(str(interval[0]))
            end = _parse_hhmm(str(interval[1]))
            if end <= start:
                raise ScheduleConfigError("El fin del horario debe ser posterior al inicio.")


def _service(spec: dict, service_key: str) -> dict:
    for item in spec["services"]:
        if str(item["key"]).casefold() == service_key.casefold():
            return item
    raise ScheduleConfigError(f"Servicio no configurado: {service_key}")


def _parse_hhmm(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        parsed = time(int(hour), int(minute))
    except (ValueError, TypeError) as exc:
        raise ScheduleConfigError(f"Hora inválida: {value}") from exc
    return parsed


def _atomic_starts(start_at: datetime, end_at: datetime, slot_minutes: int) -> list[datetime]:
    result: list[datetime] = []
    cursor = _utc(start_at)
    end_at = _utc(end_at)
    step = timedelta(minutes=slot_minutes)
    while cursor < end_at:
        result.append(cursor)
        cursor += step
    return result


def cleanup_expired_holds(
    db: Session,
    tenant_id: str,
    *,
    now: datetime | None = None,
) -> int:
    now_utc = _utc(now or datetime.now(timezone.utc))
    expired = db.scalars(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status == "held",
            Appointment.hold_expires_at.is_not(None),
            Appointment.hold_expires_at <= now_utc,
        )
    ).all()

    for appointment in expired:
        db.execute(delete(AppointmentSlot).where(AppointmentSlot.appointment_id == appointment.id))
        appointment.status = "expired"
        appointment.hold_expires_at = None

    if expired:
        db.flush()
    return len(expired)


def list_available_slots(
    db: Session,
    tenant: Tenant,
    service_key: str,
    *,
    start_date: date | None = None,
    days: int | None = None,
    limit: int = 6,
    now: datetime | None = None,
) -> list[AvailableSlot]:
    spec = schedule_spec(tenant)
    service = _service(spec, service_key)

    slot_minutes = int(spec.get("slot_minutes", 15))
    duration_minutes = int(service.get("duration_minutes", slot_minutes))
    resources = [str(x) for x in service["resource_keys"]]

    tz = ZoneInfo(tenant.timezone)
    now_utc = _utc(now or datetime.now(timezone.utc))
    cleanup_expired_holds(db, tenant.id, now=now_utc)

    local_now = now_utc.astimezone(tz)
    first_date = start_date or local_now.date()
    horizon = int(days or spec.get("booking_horizon_days", 14))
    min_notice = timedelta(minutes=int(spec.get("min_notice_minutes", 60)))
    earliest_utc = now_utc + min_notice
    closed_dates = {str(x) for x in spec.get("closed_dates", [])}

    window_start = datetime.combine(first_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    window_end = datetime.combine(
        first_date + timedelta(days=horizon), time.max, tzinfo=tz
    ).astimezone(timezone.utc)

    locked_rows = db.scalars(
        select(AppointmentSlot).where(
            AppointmentSlot.tenant_id == tenant.id,
            AppointmentSlot.resource_key.in_(resources),
            AppointmentSlot.slot_start >= window_start,
            AppointmentSlot.slot_start <= window_end,
        )
    ).all()
    locked = {(row.resource_key, _utc(row.slot_start)) for row in locked_rows}

    available: list[AvailableSlot] = []
    step = timedelta(minutes=slot_minutes)
    duration = timedelta(minutes=duration_minutes)

    for day_offset in range(horizon):
        local_date = first_date + timedelta(days=day_offset)
        if local_date.isoformat() in closed_dates:
            continue

        intervals = spec["weekly_hours"].get(str(local_date.weekday()), [])
        for start_text, end_text in intervals:
            window_local_start = datetime.combine(
                local_date, _parse_hhmm(start_text), tzinfo=tz
            )
            window_local_end = datetime.combine(
                local_date, _parse_hhmm(end_text), tzinfo=tz
            )

            cursor_local = window_local_start
            while cursor_local + duration <= window_local_end:
                start_utc = cursor_local.astimezone(timezone.utc)
                end_utc = (cursor_local + duration).astimezone(timezone.utc)

                if start_utc >= earliest_utc:
                    atomics = _atomic_starts(start_utc, end_utc, slot_minutes)
                    for resource_key in resources:
                        if all((resource_key, atomic) not in locked for atomic in atomics):
                            available.append(
                                AvailableSlot(
                                    resource_key=resource_key,
                                    start_at=start_utc,
                                    end_at=end_utc,
                                )
                            )
                            break

                cursor_local += step

    available.sort(key=lambda item: item.start_at)
    return available[: max(1, int(limit))]


def reserve_hold(
    db: Session,
    tenant: Tenant,
    *,
    lead_id: str | None,
    service_key: str,
    resource_key: str,
    start_at: datetime,
    idempotency_key: str,
    supersedes_appointment_id: str | None = None,
    now: datetime | None = None,
) -> Appointment:
    spec = schedule_spec(tenant)
    service = _service(spec, service_key)
    allowed_resources = {str(x) for x in service["resource_keys"]}
    if resource_key not in allowed_resources:
        raise ScheduleConfigError(
            f"El recurso {resource_key} no está habilitado para {service_key}."
        )

    slot_minutes = int(spec.get("slot_minutes", 15))
    duration_minutes = int(service.get("duration_minutes", slot_minutes))
    hold_minutes = int(spec.get("hold_minutes", 10))

    now_utc = _utc(now or datetime.now(timezone.utc))
    start_utc = _utc(start_at)
    end_utc = start_utc + timedelta(minutes=duration_minutes)

    cleanup_expired_holds(db, tenant.id, now=now_utc)

    existing = db.scalar(
        select(Appointment).where(
            Appointment.tenant_id == tenant.id,
            Appointment.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing

    appointment = Appointment(
        tenant_id=tenant.id,
        lead_id=lead_id,
        service_key=service_key,
        resource_key=resource_key,
        start_at=start_utc,
        end_at=end_utc,
        status="held",
        hold_expires_at=now_utc + timedelta(minutes=hold_minutes),
        idempotency_key=idempotency_key,
        supersedes_appointment_id=supersedes_appointment_id,
        external_provider="internal",
    )

    try:
        # SAVEPOINT: si el horario fue tomado por otra petición, solo deshace esta reserva.
        with db.begin_nested():
            db.add(appointment)
            db.flush()
            for atomic in _atomic_starts(start_utc, end_utc, slot_minutes):
                db.add(
                    AppointmentSlot(
                        appointment_id=appointment.id,
                        tenant_id=tenant.id,
                        resource_key=resource_key,
                        slot_start=atomic,
                    )
                )
            db.flush()
    except IntegrityError as exc:
        raise SlotUnavailable("Ese horario acaba de ocuparse. Elige otro.") from exc

    return appointment


def confirm_appointment(
    db: Session,
    appointment: Appointment,
    *,
    now: datetime | None = None,
) -> Appointment:
    now_utc = _utc(now or datetime.now(timezone.utc))

    if appointment.status == "confirmed":
        return appointment
    if appointment.status != "held":
        raise AppointmentStateError("La cita ya no está pendiente de confirmación.")

    if appointment.hold_expires_at and _utc(appointment.hold_expires_at) <= now_utc:
        db.execute(delete(AppointmentSlot).where(AppointmentSlot.appointment_id == appointment.id))
        appointment.status = "expired"
        appointment.hold_expires_at = None
        db.flush()
        raise AppointmentStateError("La reserva temporal expiró.")

    # Reprogramación segura: la cita anterior solo se libera después de confirmar la nueva.
    if appointment.supersedes_appointment_id:
        previous = db.get(Appointment, appointment.supersedes_appointment_id)
        if previous and previous.status == "confirmed":
            db.execute(delete(AppointmentSlot).where(AppointmentSlot.appointment_id == previous.id))
            previous.status = "cancelled"
            previous.hold_expires_at = None

    appointment.status = "confirmed"
    appointment.hold_expires_at = None
    db.flush()
    return appointment


def cancel_appointment(db: Session, appointment: Appointment) -> Appointment:
    if appointment.status in {"cancelled", "expired"}:
        return appointment

    db.execute(delete(AppointmentSlot).where(AppointmentSlot.appointment_id == appointment.id))
    appointment.status = "cancelled"
    appointment.hold_expires_at = None
    db.flush()
    return appointment
