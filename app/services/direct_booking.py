"""Opt-in exact-time booking. Calendar providers retain all booking authority."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.calendar_provider import get_calendar_provider
from app.services.google_calendar import GoogleCalendarAPIError, GoogleCalendarConfigError
from app.services.scheduling import AppointmentStateError, ScheduleConfigError, SlotUnavailable
from app.services.intake import _plain


def try_direct_booking(db, tenant, lead, msg, hints):
    spec = tenant.workflow_spec or {}
    config = spec.get('direct_booking', {})
    if not config.get('enabled') or lead.status != 'active':
        return None
    text = _plain(msg.text or '')
    # Only explicit affirmative booking requests qualify; inquiries and changes do not.
    if re.search(r'\b(no|cancelar|cancelo|reprogramar|cambiar)\b', text):
        return None
    if not re.search(r'\b(quiero|deseo|necesito|agendame|reservame)\b', text):
        return None
    if not (re.search(r'\bcita\b', text) or hints.answers.get('servicio')):
        return None
    if any(not (lead.answers or {}).get(key) for key in config.get('required_fields', [])):
        return None
    start = hints.requested_start
    if start is None:
        return 'Indícame la fecha y la hora con am o pm; por ejemplo: quiero una cita mañana a las 4 pm.'
    schedule = spec.get('schedule', {})
    services = schedule.get('services', [])
    label = hints.answers.get('servicio')
    service = next((item for item in services if
                    (label and item.get('label', item['key']) == label) or
                    (not label and item['key'] == config.get('default_service_key'))), None)
    if service is None:
        return None
    local_now = datetime.now(ZoneInfo(tenant.timezone))
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
        lead.status = 'human_handoff'
        lead.current_step = None
        return 'No pude confirmar la cita en la agenda. Recepción continuará contigo para revisar tu solicitud.'
    answers = dict(lead.answers or {})
    answers['_confirmed_appointment_id'] = appointment.id
    answers['servicio'] = service.get('label', service['key'])
    lead.answers = answers
    lead.status = 'booked'
    lead.current_step = None
    return (f"Listo. Tu cita de {answers['servicio']} quedó confirmada para "
            f"{start:%d/%m/%Y} a las {start:%H:%M} ({tenant.timezone}). "
            'Para cambiarla escribe REPROGRAMAR; para cancelarla, CANCELAR.')
