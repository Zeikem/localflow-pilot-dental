"""Full synthetic, signed WhatsApp workflow -> Core DB -> protected bridge.

No network, Meta token, actual phone number, Railway data or outbound worker.
Uses the same FastAPI endpoints, DB models and conversation engine as Core.
"""
import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Appointment, InboundEvent, Lead, OutboxMessage, Tenant
from tests.test_conversation_scheduling import tenant_spec


class SignedWhatsAppToBridgeTests(unittest.TestCase):
    SECRET = "fake-hmac-secret-for-local-test"
    BRIDGE_SECRET = "fake-bridge-token-only-for-unit-test-123456"
    PHONE_ID = "FAKE-PHONE-ID-NOT-META"
    WA_ID = "0000000000000"

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.db.add(Tenant(
            slug="dental-laboratorio", name="Clínica ficticia",
            niche="dental", timezone="America/Mexico_City",
            whatsapp_phone_number_id=self.PHONE_ID,
            whatsapp_token_env="UNSET_FAKE_TOKEN",
            workflow_spec=tenant_spec(),
        ))
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.stack = [
            patch("app.api.whatsapp.get_settings", return_value=SimpleNamespace(
                whatsapp_app_secret=self.SECRET,
            )),
            patch("app.api.bridge.get_settings", return_value=SimpleNamespace(
                localflow_bridge_read_token=self.BRIDGE_SECRET,
                localflow_bridge_tenant_slug="dental-laboratorio",
            )),
            patch("app.services.whatsapp.WhatsAppClient.send_text"),
            patch("app.services.whatsapp.WhatsAppClient.send_template"),
        ]
        self.mocks = [item.start() for item in self.stack]
        self.client = TestClient(app)
        self.sequence = 0

    def tearDown(self):
        self.client.close()
        for item in reversed(self.stack):
            item.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _body(self, text, message_id):
        return json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "FAKE-WABA",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": self.PHONE_ID},
                        "contacts": [{"wa_id": self.WA_ID, "profile": {"name": "Demo"}}],
                        "messages": [{
                            "from": self.WA_ID,
                            "id": message_id,
                            "type": "text",
                            "text": {"body": text},
                        }],
                    },
                }],
            }],
        }, ensure_ascii=False).encode("utf-8")

    def _send(self, text, message_id=None):
        self.sequence += 1
        body = self._body(text, message_id or f"wamid.FAKE-{self.sequence}")
        signature = hmac.new(self.SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={signature}",
            },
        )

    def _events(self):
        return self.client.get(
            "/admin/bridge/events",
            params={"tenant_slug": "dental-laboratorio"},
            headers={"X-LocalFlow-Bridge-Token": self.BRIDGE_SECRET},
        )

    def _appointments(self):
        return self.client.get(
            "/admin/bridge/appointments",
            params={"tenant_slug": "dental-laboratorio"},
            headers={"X-LocalFlow-Bridge-Token": self.BRIDGE_SECRET},
        )

    def test_signed_conversation_books_and_exports_only_metadata(self):
        # Actual webhook endpoints, signature, parser, state machine and DB.
        for phrase in ("Hola", "Paciente de laboratorio", "1", "1", "CONFIRMAR"):
            reply = self._send(phrase)
            self.assertEqual(reply.status_code, 200, reply.text)
            self.assertEqual(reply.json()["processed"], 1)

        lead = self.db.scalar(select(Lead))
        self.assertEqual(lead.status, "booked")
        appointment = self.db.scalar(select(Appointment))
        self.assertEqual(appointment.status, "confirmed")

        inbound_count = len(self.db.scalars(select(InboundEvent)).all())
        pending_outbox = self.db.scalars(select(OutboxMessage)).all()
        self.assertEqual(inbound_count, 5)
        self.assertEqual(len(pending_outbox), 5)
        self.assertTrue(all(msg.status == "pending" for msg in pending_outbox))
        self.mocks[2].assert_not_called()
        self.mocks[3].assert_not_called()

        ev = self._events()
        self.assertEqual(ev.status_code, 200, ev.text)
        self.assertEqual(len(ev.json()["events"]), 5)
        apt = self._appointments()
        self.assertEqual(apt.status_code, 200, apt.text)
        self.assertEqual(len(apt.json()["appointments"]), 1)
        self.assertEqual(apt.json()["appointments"][0]["status"], "confirmed")

        public = ev.text + apt.text
        for forbidden in (
            self.WA_ID, self.PHONE_ID, "Paciente de laboratorio",
            "Hola", "wamid.FAKE-",
        ):
            self.assertNotIn(forbidden, public)

        # Same webhook event must be deduplicated and never queue a second reply.
        self.assertEqual(self._send("Hola", "wamid.FAKE-1").json()["processed"], 0)
        self.assertEqual(len(self.db.scalars(select(InboundEvent)).all()), 5)
        self.assertEqual(len(self.db.scalars(select(OutboxMessage)).all()), 5)

    def test_unsigned_or_corrupted_signature_is_rejected(self):
        body = self._body("Hola", "wamid.FAKE-INVALID")
        for header in ({}, {"X-Hub-Signature-256": "sha256=bad"}):
            reply = self.client.post(
                "/webhooks/whatsapp", content=body, headers=header
            )
            self.assertEqual(reply.status_code, 401)
        self.assertEqual(len(self.db.scalars(select(InboundEvent)).all()), 0)

    def test_tenant_isolation_and_missing_bridge_key(self):
        self.assertEqual(
            self.client.get(
                "/admin/bridge/events", params={"tenant_slug": "dental-laboratorio"}
            ).status_code, 401
        )
        self.assertEqual(
            self.client.get(
                "/admin/bridge/events",
                params={"tenant_slug": "otra-clinica"},
                headers={"X-LocalFlow-Bridge-Token": self.BRIDGE_SECRET},
            ).status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
