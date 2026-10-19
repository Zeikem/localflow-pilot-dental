"""Signed Meta webhook: isolated inbox-only mode without personal data or outbound."""
import hashlib
import hmac
import json
import re
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


class ReviewOnlyPilotTests(unittest.TestCase):
    HMAC_KEY = "a-fake-only-for-tests-meta-app-secret"
    PRIVACY_KEY = "a-different-and-strong-fake-pseudonym-secret"
    WA = "5214771234567"
    PHONE = "FAKE_META_PHONE_ID_NEVER_LINKED"

    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.tenant = Tenant(
            slug="laboratorio-dental", name="Clínica inexistente",
            niche="dental", timezone="America/Mexico_City",
            whatsapp_phone_number_id=self.PHONE,
            whatsapp_token_env="NEVER_CONFIGURED",
            workflow_spec={"inbound_mode": "review_only", "steps": []},
        )
        self.db.add(self.tenant)
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.settings = SimpleNamespace(whatsapp_app_secret=self.HMAC_KEY)
        self.key_settings = SimpleNamespace(
            localflow_inbound_pseudonym_key=self.PRIVACY_KEY,
        )
        self.meta_patch = patch(
            "app.api.whatsapp.get_settings", return_value=self.settings
        )
        self.key_patch = patch(
            "app.services.review_only.get_settings", return_value=self.key_settings
        )
        self.meta_patch.start()
        self.key_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.key_patch.stop()
        self.meta_patch.stop()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def _send(self, text="Dolor fuerte, necesito atención", *, msgid="wamid.sensitive-id",
              phone=None, kind="text", valid=True):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": phone or self.PHONE},
                    "messages": [{
                        "id": msgid, "from": self.WA, "type": kind,
                        "text": {"body": text}, "image": {"caption": "private photo"},
                    }],
                    "contacts": [{"wa_id": self.WA, "profile": {"name": "Private"}}],
                },
            }]}],
        }
        raw = json.dumps(payload).encode()
        digest = hmac.new(self.HMAC_KEY.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(
            "/webhooks/whatsapp", content=raw,
            headers={"X-Hub-Signature-256": "sha256=" + (digest if valid else "bad")},
        )

    def test_signed_message_creates_only_anonymous_review_signal(self):
        result = self._send()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["processed"], 1)
        lead = self.db.scalar(select(Lead))
        record = self.db.scalar(select(InboundEvent))
        self.assertIsNotNone(lead)
        self.assertIsNotNone(record)
        self.assertEqual(lead.status, "human_handoff")
        self.assertEqual(lead.answers, {})
        self.assertIsNone(lead.current_step)
        self.assertRegex(lead.wa_id, r"^[0-9a-f]{40}$")
        self.assertEqual(record.wa_id, lead.wa_id)
        self.assertRegex(record.message_id, r"^[0-9a-f]{64}$")
        self.assertIsNone(record.text)
        self.assertEqual(record.raw_payload, {})
        self.assertNotIn(self.WA, str(lead.__dict__) + str(record.__dict__))
        self.assertNotIn("Dolor fuerte", str(record.__dict__))
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)
        self.assertEqual(self.db.query(Appointment).count(), 0)

    def test_duplicate_and_multiple_messages_share_review_contact(self):
        self.assertEqual(self._send().json()["processed"], 1)
        self.assertEqual(self._send().json()["processed"], 0)
        self.assertEqual(self._send("¿Me apoyan?", msgid="wamid.another").json()["processed"], 1)
        self.assertEqual(self.db.query(Lead).count(), 1)
        self.assertEqual(self.db.query(InboundEvent).count(), 2)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)

    def test_message_that_would_confirm_a_booking_stays_in_review_only(self):
        result = self._send("CONFIRMAR", msgid="wamid.confirmation")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["processed"], 1)
        self.assertEqual(self.db.query(Appointment).count(), 0)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)
        self.assertEqual(self.db.scalar(select(Lead)).status, "human_handoff")

    def test_bridge_exposes_only_review_category_without_personal_content(self):
        self.assertEqual(self._send().status_code, 200)
        with patch("app.api.bridge.get_settings", return_value=SimpleNamespace(
            localflow_bridge_read_token="test-read-only-secret-for-bridge-2026",
            localflow_bridge_tenant_slug=self.tenant.slug,
        )):
            response = self.client.get(
                "/admin/bridge/events",
                params={"tenant_slug": self.tenant.slug},
                headers={"X-LocalFlow-Bridge-Token": "test-read-only-secret-for-bridge-2026"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["events"]), 1)
        self.assertEqual(response.json()["events"][0]["category"], "Requiere recepción")
        for secret in (self.WA, self.PHONE, "Dolor fuerte", "wamid.sensitive-id"):
            self.assertNotIn(secret, response.text)

    def test_oversized_webhook_is_rejected_before_processing(self):
        response = self.client.post(
            "/webhooks/whatsapp",
            content=b"x" * 131073,
            headers={"X-Hub-Signature-256": "sha256=untrusted"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.db.query(InboundEvent).count(), 0)

    def test_non_text_media_does_not_save_photo_metadata(self):
        reply = self._send(kind="image", msgid="wamid.image")
        self.assertEqual(reply.status_code, 200)
        event = self.db.scalar(select(InboundEvent))
        self.assertEqual(event.message_type, "image")
        self.assertIsNone(event.text)
        self.assertEqual(event.raw_payload, {})

    def test_one_transient_unique_conflict_retries_without_duplicate(self):
        from sqlalchemy.exc import IntegrityError

        from app.services.review_only import record_review_only
        from app.services.webhook_parser import InboundWhatsAppMessage
        message = InboundWhatsAppMessage(
            message_id='wamid.transient-race', phone_number_id=self.PHONE,
            wa_id=self.WA, message_type='text', text='No conservar', raw={},
        )
        actual_flush = self.db.flush
        attempts = {"count": 0}

        def maybe_conflict(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise IntegrityError("synthetic unique race", (), None)
            return actual_flush(*args, **kwargs)

        with patch.object(self.db, "flush", side_effect=maybe_conflict):
            self.assertTrue(record_review_only(self.db, self.tenant, message))
        self.assertEqual(self.db.query(Lead).count(), 1)
        self.assertEqual(self.db.query(InboundEvent).count(), 1)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)

    def test_two_unique_conflicts_fail_without_storing_or_sending(self):
        from sqlalchemy.exc import IntegrityError

        from app.services.review_only import (
            InboundReviewStorageError, record_review_only,
        )
        from app.services.webhook_parser import InboundWhatsAppMessage
        message = InboundWhatsAppMessage(
            message_id='wamid.persistent-race', phone_number_id=self.PHONE,
            wa_id=self.WA, message_type='text', text='No conservar', raw={},
        )
        with patch.object(
            self.db, "flush",
            side_effect=IntegrityError("synthetic duplicate", (), None),
        ):
            with self.assertRaises(InboundReviewStorageError):
                record_review_only(self.db, self.tenant, message)
        self.assertEqual(self.db.query(Lead).count(), 0)
        self.assertEqual(self.db.query(InboundEvent).count(), 0)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)

    def test_storage_failure_makes_webhook_return_503_for_meta_retry(self):
        from app.services.review_only import InboundReviewStorageError
        with patch(
            'app.services.conversation.record_review_only',
            side_effect=InboundReviewStorageError('synthetic failure'),
        ):
            response = self._send(msgid='wamid.synthetic-storage-failure')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.db.query(InboundEvent).count(), 0)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)

    def test_untrusted_message_type_is_normalized(self):
        self.assertEqual(
            self._send(kind="medical_sensitive_<script>", msgid="wamid.bad-type").status_code,
            200,
        )
        self.assertEqual(self.db.scalar(select(InboundEvent)).message_type, "unknown")

    def test_missing_privacy_secret_fails_closed_and_retries(self):
        self.key_settings.localflow_inbound_pseudonym_key = ""
        reply = self._send()
        self.assertEqual(reply.status_code, 503)
        self.assertEqual(self.db.query(Lead).count(), 0)
        self.assertEqual(self.db.query(InboundEvent).count(), 0)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)

    def test_wrong_phone_or_bad_signature_cannot_insert_anything(self):
        result = self._send(phone="other-unconfigured-phone")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["processed"], 0)
        result = self._send(valid=False)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.db.query(Lead).count(), 0)
        self.assertEqual(self.db.query(InboundEvent).count(), 0)
        self.assertEqual(self.db.query(OutboxMessage).count(), 0)


if __name__ == "__main__":
    unittest.main()
