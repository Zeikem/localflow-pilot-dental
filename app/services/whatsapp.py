import os

import httpx

from app.config import get_settings
from app.models import Tenant


class WhatsAppConfigurationError(RuntimeError):
    pass


class WhatsAppSendError(RuntimeError):
    pass


class WhatsAppAcknowledgementError(WhatsAppSendError):
    """Meta returned success without a usable message id; automatic retries risk duplicates."""
    pass


class WhatsAppClient:
    def __init__(self, timeout_seconds: float = 15.0):
        self.settings = get_settings()
        self.timeout_seconds = timeout_seconds

    def _token_for(self, tenant: Tenant) -> str:
        token = os.getenv(tenant.whatsapp_token_env, "").strip()
        if not token:
            raise WhatsAppConfigurationError(
                f"Falta la variable de entorno {tenant.whatsapp_token_env}"
            )
        return token

    @staticmethod
    def _accepted_message_id(response: httpx.Response) -> str:
        # Meta acknowledging an HTTP request is not evidence of delivery.
        # A provider message ID is required before the outbox can mark it sent.
        if response.status_code >= 400:
            raise WhatsAppSendError(f"Meta rechazó el envío (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WhatsAppAcknowledgementError("Meta devolvió una respuesta no JSON.") from exc
        messages = payload.get("messages") if isinstance(payload, dict) else None
        first = messages[0] if isinstance(messages, list) and messages else None
        message_id = str(first.get("id", "")).strip() if isinstance(first, dict) else ""
        if not message_id:
            raise WhatsAppAcknowledgementError("Meta no devolvió un identificador de mensaje.")
        return message_id

    def send_text(self, tenant: Tenant, to_wa_id: str, body: str) -> str | None:
        token = self._token_for(tenant)
        url = (
            f"https://graph.facebook.com/"
            f"{self.settings.meta_graph_api_version}/"
            f"{tenant.whatsapp_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        return self._accepted_message_id(response)


    def send_template(
        self,
        tenant: Tenant,
        to_wa_id: str,
        *,
        template_name: str,
        language_code: str,
        params: list[str] | None = None,
    ) -> str | None:
        token = self._token_for(tenant)
        url = (
            f"https://graph.facebook.com/"
            f"{self.settings.meta_graph_api_version}/"
            f"{tenant.whatsapp_phone_number_id}/messages"
        )

        components = []
        if params:
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(value)}
                        for value in params
                    ],
                }
            ]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        return self._accepted_message_id(response)
