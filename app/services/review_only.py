"""Safest pilot ingress: store only pseudonymous signals for human reception.

Not a conversation bot. A signed incoming event is registered without phone,
name, free text, original event ID, medical information or reply queue.
"""
from datetime import datetime, timezone
import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import InboundEvent, Lead, Tenant
from app.services.webhook_parser import InboundWhatsAppMessage


class InboundReviewConfigurationError(RuntimeError):
    """Fail closed when protected review-only reception lacks its privacy key."""


def _pseudonym(secret: bytes, tenant_id: str, kind: str, original: str) -> str:
    payload = f"localflow:{kind}:{tenant_id}:{original}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def record_review_only(
    db: Session, tenant: Tenant, message: InboundWhatsAppMessage
) -> bool:
    """Register only metadata. No conversation processing, bookings or outbound."""
    key = get_settings().localflow_inbound_pseudonym_key
    if not isinstance(key, str) or len(key.encode("utf-8")) < 32:
        raise InboundReviewConfigurationError(
            "Private inbound pseudonym key is required to receive review-only events."
        )
    secret = key.encode("utf-8")
    contact_id = _pseudonym(secret, tenant.id, "contact", message.wa_id)[:40]
    event_id = _pseudonym(secret, tenant.id, "message", message.message_id)

    if db.scalar(select(InboundEvent.id).where(InboundEvent.message_id == event_id)):
        return False

    lead = db.scalar(
        select(Lead).where(Lead.tenant_id == tenant.id, Lead.wa_id == contact_id)
    )
    if lead is None:
        lead = Lead(
            tenant_id=tenant.id,
            wa_id=contact_id,
            status="human_handoff",
            answers={},
        )
        db.add(lead)
        db.flush()

    # An incoming message never authorizes messaging the sender.
    # Existing records also stay under human-only handling.
    lead.status = "human_handoff"
    lead.current_step = None
    lead.last_user_message_at = datetime.now(timezone.utc)

    allowed_types = {
        'text', 'audio', 'image', 'video', 'document', 'sticker',
        'location', 'contacts', 'interactive', 'button', 'order',
    }
    safe_type = message.message_type if message.message_type in allowed_types else 'unknown'
    db.add(InboundEvent(
        message_id=event_id,
        tenant_id=tenant.id,
        lead_id=lead.id,
        wa_id=contact_id,
        message_type=safe_type,
        text=None,
        raw_payload={},
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # An identical message delivered concurrently must not duplicate work.
        return False
    return True
