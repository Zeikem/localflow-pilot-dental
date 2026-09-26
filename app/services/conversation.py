from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.workflow import ConversationEngine
from app.models import Appointment, InboundEvent, Lead, OutboxMessage, Tenant
from app.services.calendar_provider import get_calendar_provider
from app.services.google_calendar import GoogleCalendarAPIError, GoogleCalendarConfigError
from app.services.intake import interpret_intake
from app.services.direct_booking import try_direct_booking
from app.services.scheduling import (
    AppointmentStateError,
    ScheduleConfigError,
    SlotUnavailable,
)
from app.services.webhook_parser import InboundWhatsAppMessage


HUMAN_KEYWORDS = {"humano", "persona", "asesor", "agente", "recepcionista"}
CONFIRM_KEYWORDS = {"confirmar", "confirmo", "sí", "si"}
CANCEL_KEYWORDS = {"cancelar", "cancelo"}
RESCHEDULE_KEYWORDS = {"reprogramar", "cambiar", "cambio"}


def _get_or_create_lead(db: Session, tenant: Tenant, wa_id: str) -> Lead:
    lead = db.scalar(
        select(Lead).where(Lead.tenant_id == tenant.id, Lead.wa_id == wa_id)
    )
    if lead:
        return lead

    lead = Lead(tenant_id=tenant.id, wa_id=wa_id, answers={})
    db.add(lead)
    db.flush()
    return lead


def _tokens(text: str) -> set[str]:
    return {part.strip(".,!?¡¿").casefold() for part in text.split()}


def _matches(text: str, keywords: set[str]) -> bool:
    return bool(_tokens(text) & keywords)


def _queue(db: Session, tenant: Tenant, lead: Lead, body: str) -> None:
    db.add(
        OutboxMessage(
            tenant_id=tenant.id,
            lead_id=lead.id,
            to_wa_id=lead.wa_id,
            body=body,
        )
    )


def _format_start(tenant: Tenant, start_at: datetime) -> str:
    tz = ZoneInfo(tenant.timezone)
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    local = start_at.astimezone(tz)
    weekdays = {
        0: "lunes",
        1: "martes",
        2: "miércoles",
        3: "jueves",
        4: "viernes",
        5: "sábado",
        6: "domingo",
    }
    return (
        f"{weekdays[local.weekday()]} {local.day:02d}/{local.month:02d} "
        f"a las {local.hour:02d}:{local.minute:02d}"
    )


def _completed_handoff_rule(tenant: Tenant, answers: dict) -> str | None:
    """Reusable post-qualification escalation rules configured per tenant/niche."""
    for rule in (tenant.workflow_spec or {}).get("handoff_rules", []):
        field = str(rule.get("field", "")).strip()
        values = {str(v).casefold() for v in rule.get("values", [])}
        actual = str((answers or {}).get(field, "")).strip()
        if field and actual.casefold() in values:
            return str(
                rule.get(
                    "message",
                    "Tu solicitud requiere atención personal. Una persona del equipo continuará contigo.",
                )
            )
    return None


def _schedule_service_key(tenant: Tenant, answer: str) -> str | None:
    schedule = (tenant.workflow_spec or {}).get("schedule", {})
    for service in schedule.get("services", []):
        if str(service.get("label", service.get("key", ""))).casefold() == answer.casefold():
            return str(service["key"])
        if str(service.get("key", "")).casefold() == answer.casefold():
            return str(service["key"])
    return None


def _offer_slots(
    db: Session,
    tenant: Tenant,
    lead: Lead,
    *,
    service_key: str,
    rescheduling_from: str | None = None,
) -> str:
    provider = get_calendar_provider(tenant)
    answers = dict(lead.answers or {})
    requested_raw = answers.get("_requested_start")
    requested_start = None
    if requested_raw:
        try:
            requested_start = datetime.fromisoformat(str(requested_raw))
        except ValueError:
            requested_start = None

    try:
        if requested_start is not None:
            requested_local = requested_start.astimezone(ZoneInfo(tenant.timezone))
            slots = provider.list_available_slots(
                db,
                tenant,
                service_key,
                start_date=requested_local.date(),
                days=3,
                limit=30,
            )
            slots = sorted(
                slots,
                key=lambda slot: abs(
                    (slot.start_at - requested_start.astimezone(timezone.utc)).total_seconds()
                ),
            )[:5]
        else:
            slots = provider.list_available_slots(db, tenant, service_key, limit=5)
    except (GoogleCalendarAPIError, GoogleCalendarConfigError):
        lead.status = "human_handoff"
        lead.current_step = None
        return (
            "La agenda externa no está disponible en este momento. "
            "Voy a dejar tu solicitud para que recepción continúe personalmente."
        )
    if not slots:
        lead.status = "human_handoff"
        lead.current_step = None
        return (
            "No encontré horarios libres dentro de la ventana configurada. "
            "Voy a dejar tu solicitud para que recepción continúe personalmente."
        )

    offer = [
        {
            "resource_key": slot.resource_key,
            "start_at": slot.start_at.isoformat(),
            "end_at": slot.end_at.isoformat(),
        }
        for slot in slots
    ]

    answers = dict(lead.answers or {})
    answers["_schedule_offer"] = {
        "service_key": service_key,
        "slots": offer,
        "rescheduling_from": rescheduling_from,
    }
    lead.answers = answers
    lead.status = "awaiting_slot"

    lines = []
    for i, item in enumerate(offer, start=1):
        dt = datetime.fromisoformat(item["start_at"])
        lines.append(f"{i}. {_format_start(tenant, dt)}")

    return (
        "Tengo estos horarios disponibles:\n\n"
        + "\n".join(lines)
        + "\n\nResponde con el número del horario que prefieras."
    )


def _select_slot(
    db: Session,
    tenant: Tenant,
    lead: Lead,
    msg: InboundWhatsAppMessage,
) -> str:
    offer = (lead.answers or {}).get("_schedule_offer") or {}
    slots = offer.get("slots") or []
    service_key = offer.get("service_key")
    rescheduling_from = offer.get("rescheduling_from")

    text = (msg.text or "").strip()
    if not text.isdigit():
        return "Responde con el número del horario que prefieras."

    index = int(text) - 1
    if index < 0 or index >= len(slots):
        return "Ese número no corresponde a un horario disponible. Intenta de nuevo."

    selected = slots[index]
    try:
        provider = get_calendar_provider(tenant)
        appointment = provider.reserve_hold(
            db,
            tenant,
            lead_id=lead.id,
            service_key=service_key,
            resource_key=selected["resource_key"],
            start_at=datetime.fromisoformat(selected["start_at"]),
            idempotency_key=f"wa:{msg.message_id}:hold",
            supersedes_appointment_id=rescheduling_from,
        )
    except SlotUnavailable:
        return _offer_slots(
            db,
            tenant,
            lead,
            service_key=service_key,
            rescheduling_from=rescheduling_from,
        )

    answers = dict(lead.answers or {})
    answers["_pending_appointment_id"] = appointment.id
    answers.pop("_schedule_offer", None)
    lead.answers = answers
    lead.status = "awaiting_confirmation"

    return (
        f"Reservé temporalmente {_format_start(tenant, appointment.start_at)}. "
        "Responde *CONFIRMAR* para dejar la cita fija, *REPROGRAMAR* para elegir otro horario "
        "o *CANCELAR* para liberar esta reserva."
    )


def _current_confirmed(db: Session, lead: Lead) -> Appointment | None:
    appointment_id = (lead.answers or {}).get("_confirmed_appointment_id")
    return db.get(Appointment, appointment_id) if appointment_id else None


def _pending(db: Session, lead: Lead) -> Appointment | None:
    appointment_id = (lead.answers or {}).get("_pending_appointment_id")
    return db.get(Appointment, appointment_id) if appointment_id else None


def _handle_schedule_state(
    db: Session,
    tenant: Tenant,
    lead: Lead,
    msg: InboundWhatsAppMessage,
) -> str | None:
    text = msg.text or ""

    if lead.status == "awaiting_slot":
        return _select_slot(db, tenant, lead, msg)

    if lead.status == "awaiting_confirmation":
        pending = _pending(db, lead)
        if not pending:
            lead.status = "active"
            return "La reserva temporal ya no existe. Escribe *ASESOR* para continuar."

        if _matches(text, CONFIRM_KEYWORDS):
            old_id = pending.supersedes_appointment_id
            try:
                get_calendar_provider(tenant).confirm(db, tenant, pending)
            except (AppointmentStateError, SlotUnavailable):
                answers = dict(lead.answers or {})
                answers.pop("_pending_appointment_id", None)
                lead.answers = answers
                return _offer_slots(
                    db,
                    tenant,
                    lead,
                    service_key=pending.service_key,
                    rescheduling_from=old_id,
                )
            except (GoogleCalendarAPIError, GoogleCalendarConfigError):
                lead.status = "human_handoff"
                lead.current_step = None
                return (
                    "No pude confirmar la cita en el calendario externo. "
                    "No la marcaré como confirmada para evitar errores; recepción continuará contigo."
                )

            answers = dict(lead.answers or {})
            answers["_confirmed_appointment_id"] = pending.id
            answers.pop("_pending_appointment_id", None)
            lead.answers = answers
            lead.status = "booked"
            return (
                f"Listo. Tu cita quedó confirmada para "
                f"{_format_start(tenant, pending.start_at)}. "
                "Si luego necesitas moverla, escribe *REPROGRAMAR*; "
                "si deseas cancelarla, escribe *CANCELAR*."
            )

        if _matches(text, RESCHEDULE_KEYWORDS):
            old_id = pending.supersedes_appointment_id
            service_key = pending.service_key
            try:
                get_calendar_provider(tenant).cancel(db, tenant, pending)
            except (GoogleCalendarAPIError, GoogleCalendarConfigError):
                lead.status = "human_handoff"
                return (
                    "No pude sincronizar la cancelación con el calendario externo. "
                    "Recepción continuará contigo para evitar inconsistencias."
                )
            answers = dict(lead.answers or {})
            answers.pop("_pending_appointment_id", None)
            lead.answers = answers
            return _offer_slots(
                db,
                tenant,
                lead,
                service_key=service_key,
                rescheduling_from=old_id,
            )

        if _matches(text, CANCEL_KEYWORDS):
            old_id = pending.supersedes_appointment_id
            try:
                get_calendar_provider(tenant).cancel(db, tenant, pending)
            except (GoogleCalendarAPIError, GoogleCalendarConfigError):
                lead.status = "human_handoff"
                return (
                    "No pude sincronizar la cancelación con el calendario externo. "
                    "Recepción continuará contigo para evitar inconsistencias."
                )
            answers = dict(lead.answers or {})
            answers.pop("_pending_appointment_id", None)
            lead.answers = answers

            if old_id:
                old = db.get(Appointment, old_id)
                if old and old.status == "confirmed":
                    lead.status = "booked"
                    return (
                        "Cancelé el cambio de horario. Tu cita original sigue confirmada para "
                        f"{_format_start(tenant, old.start_at)}."
                    )

            lead.status = "active"
            return "La reserva temporal quedó cancelada."

        return "Responde *CONFIRMAR*, *REPROGRAMAR* o *CANCELAR*."

    if lead.status == "booked":
        current = _current_confirmed(db, lead)

        if _matches(text, CANCEL_KEYWORDS):
            if current:
                try:
                    get_calendar_provider(tenant).cancel(db, tenant, current)
                except (GoogleCalendarAPIError, GoogleCalendarConfigError):
                    lead.status = "human_handoff"
                    return (
                        "No pude sincronizar la cancelación con el calendario externo. "
                        "Recepción continuará contigo para evitar inconsistencias."
                    )
            answers = dict(lead.answers or {})
            answers.pop("_confirmed_appointment_id", None)
            lead.answers = answers
            lead.status = "active"
            return "Tu cita quedó cancelada. Si quieres agendar otra, escribe *ASESOR*."

        if _matches(text, RESCHEDULE_KEYWORDS):
            if not current or current.status != "confirmed":
                lead.status = "active"
                return "No encontré una cita activa. Escribe *ASESOR* para continuar."
            return _offer_slots(
                db,
                tenant,
                lead,
                service_key=current.service_key,
                rescheduling_from=current.id,
            )

        if current and current.status == "confirmed":
            return (
                f"Tu cita está confirmada para {_format_start(tenant, current.start_at)}. "
                "Escribe *REPROGRAMAR*, *CANCELAR* o *ASESOR*."
            )

    return None


def process_inbound_message(db: Session, msg: InboundWhatsAppMessage) -> bool:
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.whatsapp_phone_number_id == msg.phone_number_id,
            Tenant.active.is_(True),
        )
    )
    if not tenant:
        return False

    exists = db.scalar(select(InboundEvent.id).where(InboundEvent.message_id == msg.message_id))
    if exists:
        return False

    lead = _get_or_create_lead(db, tenant, msg.wa_id)
    db.add(
        InboundEvent(
            message_id=msg.message_id,
            tenant_id=tenant.id,
            lead_id=lead.id,
            wa_id=msg.wa_id,
            message_type=msg.message_type,
            text=msg.text,
            raw_payload=msg.raw,
        )
    )

    lead.last_user_message_at = datetime.now(timezone.utc)

    if lead.status == "human_handoff":
        # También guardar multimedia sin interrumpir la atención humana.
        db.commit()
        return True

    if msg.message_type != "text" or not msg.text:
        _queue(
            db,
            tenant,
            lead,
            "Por ahora puedo continuar por texto. Si prefieres atención de una persona, "
            "escribe *ASESOR*.",
        )
        db.commit()
        return True

    if _matches(msg.text, HUMAN_KEYWORDS):
        lead.status = "human_handoff"
        lead.current_step = None
        _queue(
            db,
            tenant,
            lead,
            tenant.workflow_spec.get(
                "handoff_message",
                "Claro. Una persona del equipo continuará contigo.",
            ),
        )
        db.commit()
        return True

    # Extraemos hechos útiles del lenguaje natural sin dar autoridad a la IA
    # sobre disponibilidad. El backend conserva la decisión y la agenda valida.
    hints = interpret_intake(tenant, msg.text)
    answers = dict(lead.answers or {})
    for key, value in hints.answers.items():
        if key not in answers:
            answers[key] = value
    if hints.requested_start is not None:
        answers["_requested_start"] = hints.requested_start.isoformat()
    lead.answers = answers

    handoff = _completed_handoff_rule(tenant, hints.answers)
    if handoff:
        lead.status = "human_handoff"
        lead.current_step = None
        _queue(db, tenant, lead, handoff)
        db.commit()
        return True

    direct_reply = try_direct_booking(db, tenant, lead, msg, hints)
    if direct_reply is not None:
        _queue(db, tenant, lead, direct_reply)
        db.commit()
        return True

    schedule_reply = _handle_schedule_state(db, tenant, lead, msg)
    if schedule_reply is not None:
        _queue(db, tenant, lead, schedule_reply)
        db.commit()
        return True

    engine = ConversationEngine()
    result = engine.process(
        spec=tenant.workflow_spec,
        current_step=lead.current_step,
        answers=lead.answers,
        user_text=msg.text,
    )

    lead.current_step = result.current_step
    lead.answers = result.answers
    reply = result.reply

    if result.completed:
        handoff_message = _completed_handoff_rule(tenant, result.answers)
        if handoff_message:
            lead.status = "human_handoff"
            lead.current_step = None
            reply = handoff_message
            _queue(db, tenant, lead, reply)
            db.commit()
            return True

        service_answer = str(result.answers.get("servicio", "")).strip()
        service_key = _schedule_service_key(tenant, service_answer)

        if service_key:
            try:
                reply = _offer_slots(db, tenant, lead, service_key=service_key)
            except ScheduleConfigError:
                lead.status = "human_handoff"
                reply = (
                    "Ya registré tus datos, pero este servicio requiere que recepción revise "
                    "la agenda. Una persona continuará contigo."
                )
        else:
            lead.status = "human_handoff"
            reply = (
                "Ya registré tus datos. Para este servicio prefiero que una persona del equipo "
                "revise tu solicitud y continúe contigo."
            )

    _queue(db, tenant, lead, reply)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False

    return True
