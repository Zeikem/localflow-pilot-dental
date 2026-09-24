import os

import httpx

from app.config import get_settings
from app.models import Tenant


class WhatsAppConfigurationError(RuntimeError):
    pass


class WhatsAppSendError(RuntimeError):
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

        if response.status_code >= 400:
            raise WhatsAppSendError(
                f"Meta devolvió HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        messages = data.get("messages") or []
        if messages and isinstance(messages[0], dict):
            return messages[0].get("id")
        return None


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

        if response.status_code >= 400:
            raise WhatsAppSendError(
                f"Meta devolvió HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        messages = data.get("messages") or []
        if messages and isinstance(messages[0], dict):
            return messages[0].get("id")
        return None
