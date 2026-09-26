import json
import logging
import os

import httpx

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


# Diagnóstico temporal del piloto. Protegido con WHATSAPP_VERIFY_TOKEN y sin
# devolver secretos. Se retirará después de validar Meta end-to-end.
META_APP_ID = "1980805382588533"
META_WABA_ID = "1421117863485820"
META_CALLBACK_URL = "https://api-image-production-7f8d.up.railway.app/webhooks/whatsapp"


def _require_diagnostic_token(token: str) -> None:
    if token != get_settings().whatsapp_verify_token:
        raise HTTPException(status_code=403, detail="Invalid diagnostic token")


@router.get("/diagnostic")
def meta_diagnostic(token: str = Query(...)):
    _require_diagnostic_token(token)
    settings = get_settings()
    whatsapp_token = os.getenv("DENTAL_PILOT_WHATSAPP_TOKEN", "")
    app_access_token = f"{META_APP_ID}|{settings.whatsapp_app_secret}"

    if not whatsapp_token or not settings.whatsapp_app_secret:
        raise HTTPException(status_code=503, detail="Meta credentials are not configured")

    app_response = httpx.get(
        f"https://graph.facebook.com/v26.0/{META_APP_ID}/subscriptions",
        params={"access_token": app_access_token},
        timeout=30,
    )
    waba_response = httpx.get(
        f"https://graph.facebook.com/v26.0/{META_WABA_ID}/subscribed_apps",
        headers={"Authorization": f"Bearer {whatsapp_token}"},
        timeout=30,
    )

    def safe_json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            return {"body": response.text[:500]}

    return {
        "app_subscriptions_status": app_response.status_code,
        "app_subscriptions": safe_json(app_response),
        "waba_subscriptions_status": waba_response.status_code,
        "waba_subscriptions": safe_json(waba_response),
        "expected_callback": META_CALLBACK_URL,
    }


@router.post("/diagnostic/repair")
def repair_meta_subscription(token: str = Query(...)):
    _require_diagnostic_token(token)
    settings = get_settings()
    whatsapp_token = os.getenv("DENTAL_PILOT_WHATSAPP_TOKEN", "")
    app_access_token = f"{META_APP_ID}|{settings.whatsapp_app_secret}"

    if not whatsapp_token or not settings.whatsapp_app_secret:
        raise HTTPException(status_code=503, detail="Meta credentials are not configured")

    app_response = httpx.post(
        f"https://graph.facebook.com/v26.0/{META_APP_ID}/subscriptions",
        data={
            "access_token": app_access_token,
            "object": "whatsapp_business_account",
            "callback_url": META_CALLBACK_URL,
            "fields": "messages",
            "verify_token": settings.whatsapp_verify_token,
        },
        timeout=30,
    )

    waba_response = httpx.post(
        f"https://graph.facebook.com/v26.0/{META_WABA_ID}/subscribed_apps",
        headers={"Authorization": f"Bearer {whatsapp_token}"},
        timeout=30,
    )

    def safe_json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            return {"body": response.text[:500]}

    return {
        "app_subscription_status": app_response.status_code,
        "app_subscription": safe_json(app_response),
        "waba_subscription_status": waba_response.status_code,
        "waba_subscription": safe_json(waba_response),
    }
