"""Best-effort event relay for an operator-controlled n8n workflow."""

import logging

import httpx

from app.config import get_settings
from app.services.webhook_parser import InboundWhatsAppMessage


logger = logging.getLogger("impulvera.n8n")


async def notify_inbound_messages(messages: list[InboundWhatsAppMessage]) -> None:
    """Send normalized inbound events to n8n when the relay is configured."""
    settings = get_settings()
    endpoint = settings.n8n_ingress_url.strip()
    if not endpoint or not messages:
        return
    if not endpoint.startswith("https://"):
        logger.error("n8n_relay_skipped reason=non_https_endpoint")
        return

    payload = {
        "source": "impulvera.whatsapp",
        "events": [
            {
                "message_id": item.message_id,
                "phone_number_id": item.phone_number_id,
                "from": item.from_number,
                "timestamp": item.timestamp,
                "type": item.message_type,
                "text": item.text,
                "media_id": item.media_id,
            }
            for item in messages
        ],
    }
    headers = {"X-Impulvera-Source": "whatsapp"}
    if settings.n8n_shared_secret:
        headers["X-Impulvera-Signature"] = settings.n8n_shared_secret

    try:
        async with httpx.AsyncClient(timeout=4.5) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("n8n_relay_failed error=%s", type(exc).__name__)
