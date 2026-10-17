import hashlib
import hmac
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.core.security import verify_meta_signature
from app.models import Tenant
from app.services.whatsapp import WhatsAppClient, WhatsAppSendError


class SignatureTests(unittest.TestCase):
    def test_valid_signature(self):
        secret = "top-secret"
        body = b'{"hello":"world"}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        header = f"sha256={digest}"
        self.assertTrue(verify_meta_signature(body, header, secret))

    def test_invalid_signature(self):
        self.assertFalse(
            verify_meta_signature(b"payload", "sha256=deadbeef", "top-secret")
        )



class WhatsAppAcknowledgementTests(unittest.TestCase):
    """Check actual WhatsApp client responses without contacting Meta."""

    def setUp(self):
        self.tenant = Tenant(
            slug="security-wa",
            name="Security WA",
            niche="dental",
            whatsapp_phone_number_id="TEST-PHONE",
            whatsapp_token_env="SECURITY_TEST_WA_TOKEN",
            workflow_spec={},
        )
        self.client = WhatsAppClient()
        self.client.settings = SimpleNamespace(meta_graph_api_version="v26.0")
        self.client_cls = httpx.Client
        self.env_patch = patch.dict(os.environ, {"SECURITY_TEST_WA_TOKEN": "only-test-token"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _stub_meta(self, response):
        transport = httpx.MockTransport(lambda request: response)
        return patch(
            "app.services.whatsapp.httpx.Client",
            side_effect=lambda timeout: self.client_cls(
                transport=transport, timeout=timeout
            ),
        )

    def test_text_sent_only_after_provider_returns_message_id(self):
        with self._stub_meta(httpx.Response(200, json={"messages": [{"id": "wamid.test"}]})):
            self.assertEqual(self.client.send_text(self.tenant, "5210000000000", "Hola"), "wamid.test")

    def test_template_sent_only_after_provider_returns_message_id(self):
        with self._stub_meta(httpx.Response(200, json={"messages": [{"id": "wamid.tpl"}]})):
            self.assertEqual(
                self.client.send_template(
                    self.tenant, "5210000000000",
                    template_name="test_template",
                    language_code="es_MX",
                ),
                "wamid.tpl",
            )

    def test_http_200_without_message_id_does_not_mark_text_as_sent(self):
        with self._stub_meta(httpx.Response(200, json={"messages": []})):
            with self.assertRaises(WhatsAppSendError):
                self.client.send_text(self.tenant, "5210000000000", "Hola")

    def test_http_200_without_message_id_does_not_mark_template_as_sent(self):
        with self._stub_meta(httpx.Response(200, json={})):
            with self.assertRaises(WhatsAppSendError):
                self.client.send_template(
                    self.tenant, "5210000000000",
                    template_name="test_template", language_code="es_MX",
                )

    def test_malformed_provider_response_is_rejected(self):
        with self._stub_meta(httpx.Response(200, text="not JSON")):
            with self.assertRaises(WhatsAppSendError):
                self.client.send_text(self.tenant, "5210000000000", "Hola")

    def test_provider_error_does_not_expose_response_body(self):
        with self._stub_meta(httpx.Response(403, text="sensitive-provider-data")):
            with self.assertRaises(WhatsAppSendError) as raised:
                self.client.send_text(self.tenant, "5210000000000", "Hola")
        self.assertIn("403", str(raised.exception))
        self.assertNotIn("sensitive-provider-data", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
