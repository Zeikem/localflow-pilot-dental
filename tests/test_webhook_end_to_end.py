"""Signed Meta webhook -> database -> automated reply -> internal appointment.

Uses only an in-memory SQLite database and synthetic WhatsApp identifiers.
No external network calls, Meta credentials, or live messages are involved.
"""
import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.whatsapp import router as whatsapp_router
from app.db import Base, get_db
from app.models import Appointment, InboundEvent, Lead, OutboxMessage, Tenant
from tests.test_conversation_scheduling import tenant_spec


class SignedWebhookFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.tenant = Tenant(
            slug="dental-webhook-test",
            name="Clínica de prueba",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE-INTEGRATION-TEST",
            whatsapp_token_env="SYNTHETIC_WHATSAPP_ACCESS_TOKEN",
            workflow_spec=tenant_spec(),
        )
        self.db.add(self.tenant)
        self.db.commit()
        app = FastAPI()
        app.include_router(whatsapp_router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.settings = SimpleNamespace(
            whatsapp_verify_token="synthetic-verify-token",
            whatsapp_app_secret="synthetic-signature-secret",
        )
        self.settings_patch = patch("app.api.whatsapp.get_settings", return_value=self.settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def tearDown(self):
        self.client.close()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _post_message(self, body: str, message_id: str, *, phone_id=None, secret=None):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": phone_id or self.tenant.whatsapp_phone_number_id},
                        "contacts": [{"wa_id": "5210000000000"}],
                        "messages": [{
                            "id": message_id,
                            "from": "5210000000000",
                            "type": "text",
                            "text": {"body": body},
                        }],
                    },
                }],
            }],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        digest = hmac.new(
            (secret or self.settings.whatsapp_app_secret).encode("utf-8"),
            raw, hashlib.sha256,
        ).hexdigest()
        return self.client.post(
            "/webhooks/whatsapp",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={digest}",
            },
        )

    def test_meta_verification_requires_matching_token(self):
        good = self.client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.settings.whatsapp_verify_token,
                "hub.challenge": "synthetic-challenge-123",
            },
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.text, "synthetic-challenge-123")
        bad = self.client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "incorrect-token",
                "hub.challenge": "synthetic-challenge-123",
            },
        )
        self.assertEqual(bad.status_code, 403)

    def test_invalid_signature_rejected_without_database_write(self):
        result = self._post_message("Hola", "signed-rejected-1", secret="wrong-secret")
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(InboundEvent)), 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(OutboxMessage)), 0)

    def test_unknown_phone_is_not_routed_to_another_tenant(self):
        result = self._post_message(
            "Hola", "unknown-tenant-1", phone_id="UNCONFIGURED-PHONE",
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["processed"], 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(InboundEvent)), 0)

    def test_signed_webhook_books_once_and_enqueues_replies(self):
        steps = [
            ("Hola", "webhook-demo-1"),
            ("Sofia", "webhook-demo-2"),
            ("1", "webhook-demo-3"),
            ("1", "webhook-demo-4"),
            ("CONFIRMAR", "webhook-demo-5"),
        ]
        for body, message_id in steps:
            response = self._post_message(body, message_id)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["messages_found"], 1)
            self.assertEqual(response.json()["processed"], 1)

        lead = self.db.scalar(select(Lead).where(Lead.wa_id == "5210000000000"))
        self.assertIsNotNone(lead)
        self.assertEqual(lead.status, "booked")
        appointment = self.db.scalar(select(Appointment))
        self.assertIsNotNone(appointment)
        self.assertEqual(appointment.status, "confirmed")
        self.assertEqual(lead.answers["_confirmed_appointment_id"], appointment.id)
        outbox = self.db.scalars(select(OutboxMessage)).all()
        self.assertEqual(len(outbox), 5)
        self.assertIn("confirmada", outbox[-1].body.casefold())

        replay = self._post_message("CONFIRMAR", "webhook-demo-5")
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["processed"], 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(InboundEvent)), 5)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(OutboxMessage)), 5)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Appointment)), 1)


if __name__ == "__main__":
    unittest.main()
