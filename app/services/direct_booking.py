"""Opt-in exact-time booking. Calendar providers retain all booking authority."""
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.calendar_provider import get_calendar_provider
from app.services.google_calendar import GoogleCalendarAPIError, GoogleCalendarConfigError
from app.services.scheduling import AppointmentStateError, ScheduleConfigError, SlotUnavailable
from app.services.intake import _parse_date, _parse_time, _plain


def try_direct_booking(db, tenant, lead, msg, hints):
    spec = tenant.workflow_spec or {}
    config = spec.get('direct_booking', {})
    if not config.get('enabled') or lead.status != 'active':
        return None
    text = _plain(msg.text or '')
    answers = dict(lead.answers or {})
    pending_value = answers.get('_direct_booking_pending')
    pending = pending_value if isinstance(pending_value, dict) else {}
    # A previous unanswered booking request may be resumed without repeating "cita".
    if re.search(r'\b(no|cancelar|cancelo|reprogramar|cambiar)\b', text):
        answers.pop('_direct_booking_pending', None)
        lead.answers = answers
        return None
    explicit_request = bool(re.search(
        r'\b(quiero|deseo|necesito|agendame|reservame)\b', text
    ))
    if not explicit_request and not pending_value:
        return None
    if not (re.search(r'\bcita\b', text) or hints.answers.get('servicio') or pending_value):
        return None
    if any(not answers.get(key) for key in config.get('required_fields', [])):
        return None

    schedule = spec.get('schedule', {})
    services = schedule.get('services', [])
    label = hints.answers.get('servicio') or answers.get('servicio')
    requested_service_key = pending.get('service_key')
    service = next((item for item in services if
                    (label and item.get('label', item['key']) == label) or
                    (not label and item['key'] == (requested_service_key or config.get('default_service_key')))), None)
    if service is None:
        return None

    # Store only the date/time pieces the user explicitly supplied.
    # "Mañana a las 4" -> "4 pm", or "a las 4 pm" -> "mañana".
    local_now = datetime.now(ZoneInfo(tenant.timezone))
    parsed_date = _parse_date(text, local_now)
    parsed_time = _parse_time(text)
    day = parsed_date.date().isoformat() if parsed_date else pending.get('date')
    clock = list(parsed_time) if parsed_time else pending.get('time')
    answers['_direct_booking_pending'] = {
        'service_key': service['key'],
        'date': day,
        'time': clock,
    }
    lead.answers = answers
    if not day:
        return 'Indícame qué día quieres la cita; por ejemplo: mañana.'
    if not clock:
        return 'Indícame la hora con am o pm; por ejemplo: 4 pm.'
    try:
        start = datetime.combine(
            date.fromisoformat(day),
            time(*clock),
            tzinfo=ZoneInfo(tenant.timezone),
        )
    except (TypeError, ValueError):
        answers.pop('_direct_booking_pending', None)
        lead.answers = answers
        return 'No pude interpretar la fecha y hora. Indícame ambas de nuevo.'
    if not local_now.date() <= start.date() < local_now.date() + timedelta(
            days=int(schedule.get('booking_horizon_days', 14))):
        return 'Esa fecha está fuera del periodo de reservas. Indícame una fecha más próxima.'
    appointment = None
    try:
        provider = get_calendar_provider(tenant)
        slots = provider.list_available_slots(db, tenant, service['key'],
                    start_date=start.date(), days=1, limit=1440)
        slot = next((item for item in slots if item.start_at == start), None)
        if slot is None:
            return 'Ese horario no está disponible. Indícame otra fecha y hora para tu cita.'
        appointment = provider.reserve_hold(db, tenant, lead_id=lead.id,
                    service_key=service['key'], resource_key=slot.resource_key,
                    start_at=slot.start_at, idempotency_key=f'wa:{msg.message_id}:direct')
        provider.confirm(db, tenant, appointment)
    except (SlotUnavailable, AppointmentStateError):
        return 'Ese horario acaba de dejar de estar disponible. Indícame otra fecha y hora.'
    except (GoogleCalendarAPIError, GoogleCalendarConfigError, ScheduleConfigError):
        answers = dict(lead.answers or {})
        answers.pop('_direct_booking_pending', None)
        lead.answers = answers
        lead.status = 'human_handoff'
        lead.current_step = None
        return 'No pude confirmar la cita en la agenda. Recepción continuará contigo para revisar tu solicitud.'
    answers = dict(lead.answers or {})
    answers.pop('_direct_booking_pending', None)
    answers['_confirmed_appointment_id'] = appointment.id
    answers['servicio'] = service.get('label', service['key'])
    lead.answers = answers
    lead.status = 'booked'
    lead.current_step = None
    return (f"Listo. Tu cita de {answers['servicio']} quedó confirmada para "
            f"{start:%d/%m/%Y} a las {start:%H:%M} ({tenant.timezone}). "
            'Para cambiarla escribe REPROGRAMAR; para cancelarla, CANCELAR.')
