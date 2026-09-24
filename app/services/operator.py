from sqlalchemy.orm import Session

from app.models import Appointment, Lead


class LeadOperationError(ValueError):
    pass


def reactivate_lead(
    db: Session,
    lead_id: str,
    *,
    reset_flow: bool = False,
) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead:
        raise LeadOperationError("Lead no encontrado.")

    answers = dict(lead.answers or {})

    if reset_flow:
        answers.pop("_schedule_offer", None)
        answers.pop("_pending_appointment_id", None)
        lead.current_step = None

    confirmed_id = answers.get("_confirmed_appointment_id")
    confirmed = db.get(Appointment, confirmed_id) if confirmed_id else None

    if confirmed and confirmed.status == "confirmed" and not reset_flow:
        lead.status = "booked"
    else:
        lead.status = "active"

    lead.answers = answers
    db.commit()
    db.refresh(lead)
    return lead
