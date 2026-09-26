import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import verify_meta_signature
from app.db import get_db
from app.services.conversation import process_inbound_message
from app.services.webhook_parser import extract_inbound_messages


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
        if process_inbound_message(db, msg):
            processed += 1
        else:
            logger.warning(
                "whatsapp_message_not_processed phone_number_id=%s message_id=%s type=%s",
                msg.phone_number_id,
                msg.message_id,
                msg.message_type,
            )

    logger.info(
        "whatsapp_webhook_received messages_found=%s processed=%s",
        len(messages),
        processed,
    )

    # Siempre responder rápido a Meta. El envío de salida lo hace el worker.
    return {"received": True, "messages_found": len(messages), "processed": processed}
