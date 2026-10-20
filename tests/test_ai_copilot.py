"""Safety and opt-in tests: no real API calls or WhatsApp sends."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.services.ai_copilot import (
    InvalidVerifiedFact, draft_administrative_reply,
)

class AiCopilotTests(unittest.TestCase):
    def setUp(self):
        self.off = SimpleNamespace(
            localflow_ai_enabled=False, localflow_ai_api_key="", localflow_ai_model=""
        )
        self.on = SimpleNamespace(
            localflow_ai_enabled=True, localflow_ai_api_key="FAKE_TEST_ONLY",
            localflow_ai_model="gpt-4o-mini",
        )

    def test_disabled_never_calls_network(self):
        with patch("app.services.ai_copilot.get_settings", return_value=self.off):
            with patch("app.services.ai_copilot.httpx.Client") as http:
                draft = draft_administrative_reply(
                    "horarios", verified_public_fact="lunes a viernes de 9 a 18",
                    request_ai=True,
                )
                http.assert_not_called()
        self.assertEqual(draft.source, "plantilla")
        self.assertTrue(draft.requires_human_review)
        self.assertFalse(draft.sent)
        self.assertFalse(draft.appointment_created)

    def test_high_risk_intents_require_humans_not_ai(self):
        with patch("app.services.ai_copilot.httpx.Client") as client:
            for intent in ("urgencia", "agendar", "reprogramar", "cancelar", "otro"):
                response = draft_administrative_reply(intent, request_ai=True)
                self.assertEqual(response.source, "plantilla")
                self.assertFalse(response.api_called)
                self.assertFalse(response.sent)
            client.assert_not_called()

    def test_private_data_in_fact_rejected(self):
        for fact in ("Paciente Ramón", "+52 477 123 4567", "abc@correo.com",
                     "ignora instrucciones", "historial médico", "<script>",
                     "A" * 161):
            with self.subTest(fact=fact):
                with self.assertRaises(InvalidVerifiedFact):
                    draft_administrative_reply(
                        "horarios", verified_public_fact=fact
                    )

    def test_missing_verified_price_cannot_be_invented(self):
        for intent in ("precios", "horarios", "servicios"):
            with patch("app.services.ai_copilot.httpx.Client") as http:
                result = draft_administrative_reply(intent, request_ai=True)
                http.assert_not_called()
            self.assertIn("recepción", result.draft.lower())

    def test_openai_call_requires_opt_in_and_sends_only_public_information(self):
        response = MagicMock()
        response.json.return_value = {
            "status": "completed", "output": [{
                "type": "message", "role": "assistant", "content": [{
                    "type": "output_text",
                    "text": "Nuestro horario es de lunes a viernes, de 9 a 18 horas.",
                }],
            }],
        }
        client = MagicMock()
        client.__enter__.return_value.post.return_value = response
        with patch("app.services.ai_copilot.get_settings", return_value=self.on):
            with patch("app.services.ai_copilot.httpx.Client", return_value=client):
                result = draft_administrative_reply(
                    "horarios", verified_public_fact="lunes a viernes de 9 a 18",
                    request_ai=True,
                )
        self.assertEqual(result.source, "ia_sugerencia")
        self.assertTrue(result.requires_human_review)
        self.assertFalse(result.sent)
        self.assertTrue(result.api_called)
        call = client.__enter__.return_value.post.call_args
        self.assertEqual(call.args[0], "https://api.openai.com/v1/responses")
        self.assertFalse(call.kwargs["json"]["store"])
        self.assertLessEqual(call.kwargs["json"]["max_output_tokens"], 160)
        self.assertIn("lunes a viernes de 9 a 18", call.kwargs["json"]["input"])

    def test_hallucination_or_network_error_falls_back(self):
        response = MagicMock()
        response.json.return_value = {
            "status": "completed", "output": [{
                "type": "message", "role": "assistant", "content": [{
                    "type": "output_text", "text": "Tu cita confirmada ya está lista.",
                }],
            }],
        }
        client = MagicMock()
        client.__enter__.return_value.post.return_value = response
        with patch("app.services.ai_copilot.get_settings", return_value=self.on):
            with patch("app.services.ai_copilot.httpx.Client", return_value=client):
                result = draft_administrative_reply(
                    "servicios", verified_public_fact="limpieza", request_ai=True,
                )
            self.assertEqual(result.source, "plantilla")
            import httpx
            client.__enter__.return_value.post.side_effect = httpx.ReadTimeout("timeout")
            with patch("app.services.ai_copilot.httpx.Client", return_value=client):
                result = draft_administrative_reply(
                    "servicios", verified_public_fact="limpieza", request_ai=True,
                )
            self.assertEqual(result.source, "plantilla")

class CopilotRouteTests(unittest.TestCase):
    KEY = "staff-only-demo-credential-32-characters"

    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_unconfigured_and_unauthorized_requests_denied(self):
        with patch("app.api.copilot.get_settings",
                   return_value=SimpleNamespace(localflow_copilot_token="")):
            self.assertEqual(
                self.client.post("/admin/copilot/draft", json={"intent": "saludo"}).status_code,
                503,
            )
        with patch("app.api.copilot.get_settings",
                   return_value=SimpleNamespace(localflow_copilot_token=self.KEY)):
            self.assertEqual(
                self.client.post("/admin/copilot/draft", json={"intent": "saludo"}).status_code,
                401,
            )

    def test_authorized_draft_has_no_send_or_booking_side_effect(self):
        with patch("app.api.copilot.get_settings",
                   return_value=SimpleNamespace(localflow_copilot_token=self.KEY)):
            reply = self.client.post(
                "/admin/copilot/draft", json={"intent": "agendar"},
                headers={"X-LocalFlow-Copilot-Token": self.KEY},
            )
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertTrue(reply.json()["requires_human_review"])
            self.assertFalse(reply.json()["sent"])
            self.assertFalse(reply.json()["appointment_created"])
            rejected = self.client.post(
                "/admin/copilot/draft",
                json={"intent": "horarios", "verified_public_fact": "juan@correo.com"},
                headers={"X-LocalFlow-Copilot-Token": self.KEY},
            )
            self.assertEqual(rejected.status_code, 422)

if __name__ == "__main__":
    unittest.main()
