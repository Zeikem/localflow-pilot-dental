"""Privacy-preserving WhatsApp intake for a review-only dental pilot.

No original phone, name, message, attachments or message identifiers persist.
No outbound messages or booking actions are created.
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
    """The receiver must refuse events if the pseudonym key is absent."""


class InboundReviewStorageError(RuntimeError):
    """The receiver must ask Meta to retry after persistent DB conflicts."""


_ALLOWED_MESSAGE_TYPES = frozenset({
    "text", "audio", "image", "video", "document", "sticker",
    "location", "contacts", "interactive", "button", "order",
})


def _pseudonym(secret: bytes, tenant_id: str, kind: str, original: str) -> str:
    payload = f"localflow:{kind}:{tenant_id}:{original}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def record_review_only(
    db: Session, tenant: Tenant, message: InboundWhatsAppMessage
) -> bool:
    """Record minimum metadata and retry one uniqueness race safely."""
    key = get_settings().localflow_inbound_pseudonym_key
    if not isinstance(key, str) or len(key.encode("utf-8")) < 32:
        raise InboundReviewConfigurationError(
            "Private inbound pseudonym key is required to receive review-only events."
        )

    tenant_id = tenant.id
    secret = key.encode("utf-8")
    contact_id = _pseudonym(secret, tenant_id, "contact", message.wa_id)[:40]
    event_id = _pseudonym(secret, tenant_id, "message", message.message_id)
    safe_type = (
        message.message_type
        if message.message_type in _ALLOWED_MESSAGE_TYPES else "unknown"
    )

    for attempt in range(2):
        try:
            if db.scalar(
                select(InboundEvent.id).where(InboundEvent.message_id == event_id)
            ):
                return False

            lead = db.scalar(
                select(Lead).where(
                    Lead.tenant_id == tenant_id, Lead.wa_id == contact_id
                )
            )
            if lead is None:
                lead = Lead(
                    tenant_id=tenant_id,
                    wa_id=contact_id,
                    status="human_handoff",
                    answers={},
                )
                db.add(lead)
                db.flush()

            # An incoming message is not permission to reply or reserve.
            lead.status = "human_handoff"
            lead.current_step = None
            lead.last_user_message_at = datetime.now(timezone.utc)
            db.add(InboundEvent(
                message_id=event_id,
                tenant_id=tenant_id,
                lead_id=lead.id,
                wa_id=contact_id,
                message_type=safe_type,
                text=None,
                raw_payload={},
            ))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            if attempt:
                # Never acknowledge an unpersisted event as accepted. A true
                # duplicate was already recognized by the fresh lookup above.
                raise InboundReviewStorageError(
                    'Review-only event could not be persisted; retry required.'
                ) from None
            # Re-read on the second pass. This handles a contact or event
            # created by another request after the first lookup.
    return False
