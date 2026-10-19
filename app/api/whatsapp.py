import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import verify_meta_signature
from app.db import get_db
from app.services.conversation import process_inbound_message
from app.services.review_only import (
    InboundReviewConfigurationError, InboundReviewStorageError,
)
from app.services.webhook_parser import extract_inbound_messages


MAX_WHATSAPP_PAYLOAD_BYTES = 131072

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
logger = logging.getLogger("localflow.webhook")


@router.get("")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()

    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")

    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    raw_body = await request.body()
    if len(raw_body) > MAX_WHATSAPP_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail='Webhook payload exceeds limit')

    if not verify_meta_signature(
        raw_body=raw_body,
        signature_header=request.headers.get("X-Hub-Signature-256"),
        app_secret=settings.whatsapp_app_secret,
    ):
        logger.warning(
            "whatsapp_webhook_rejected reason=invalid_signature content_length=%s",
            len(raw_body),
        )
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    messages = extract_inbound_messages(payload)
    processed = 0

    for msg in messages:
        try:
            accepted = process_inbound_message(db, msg)
        except (InboundReviewConfigurationError, InboundReviewStorageError):
            # A temporary DB failure must not cause silent message loss;
            # Meta will retry non-2xx responses.
            logger.error('whatsapp_review_only_unavailable')
            raise HTTPException(status_code=503, detail='Review-only receiver unavailable') from None
        if accepted:
            processed += 1
        else:
            # Do not write sender, number or event identifiers to application logs.
            logger.info('whatsapp_message_ignored_unbound_or_duplicate')

    logger.info(
        "whatsapp_webhook_received messages_found=%s processed=%s",
        len(messages),
        processed,
    )

    # Siempre responder rápido a Meta. El envío de salida lo hace el worker.
    return {"received": True, "messages_found": len(messages), "processed": processed}
