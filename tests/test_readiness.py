"""Readiness checks cover configuration only and must never disclose secrets."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin import router as admin_router
from app.db import Base, get_db
from app.models import InboundEvent, OutboxMessage, Tenant
from app.services.readiness import check_readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.tenant = Tenant(
            slug="dental-pilot-leon",
            name="Prueba",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE-READY-TEST",
            whatsapp_token_env="TEST_WA_TOKEN",
            workflow_spec={
                "steps": [{"key": "nombre", "prompt": "Nombre"}],
                "schedule": {
                    "provider": "google_calendar",
                    "services": [{"key": "valoracion", "duration_minutes": 30}],
                    "resources": [{"key": "r1", "calendar_id_env": "TEST_CAL_ID"}],
                    "google": {"credentials_env": "TEST_GOOGLE_CREDS"},
                },
            },
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.mock_settings = SimpleNamespace(
            admin_api_token="readiness-test-only",
            whatsapp_app_secret="configured-secret-test-only",
            whatsapp_verify_token="configured-verify-test-only",
        )

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_missing_external_config_is_reported_without_values(self):
        with patch("app.services.readiness.get_settings", return_value=self.mock_settings):
            with patch.dict(os.environ, {
                "TEST_WA_TOKEN": "",
                "TEST_CAL_ID": "",
                "TEST_GOOGLE_CREDS": "",
            }):
                result = check_readiness(self.db, "dental-pilot-leon")
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["checks"]["whatsapp_access_token_present"])
        self.assertFalse(result["checks"]["calendar_credentials_present"])
        self.assertFalse(result["checks"]["calendar_ids_present"])
        self.assertFalse(result["external_integrations_verified"])
        self.assertNotIn("configured-secret-test-only", str(result))

    def test_config_presence_is_not_claimed_as_external_success(self):
        with patch("app.services.readiness.get_settings", return_value=self.mock_settings):
            with patch.dict(os.environ, {
                "TEST_WA_TOKEN": "fake-wa-token",
                "TEST_CAL_ID": "fake-calendar-id",
                "TEST_GOOGLE_CREDS": "fake-credentials",
            }):
                result = check_readiness(self.db, "dental-pilot-leon")
        self.assertEqual(result["status"], "configuration_complete")
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["external_integrations_verified"])
        self.assertFalse(result["worker_configuration_verified"])
        for token in ("fake-wa-token", "fake-calendar-id", "fake-credentials"):
            self.assertNotIn(token, str(result))

    def test_missing_tenant_does_not_claim_ready(self):
        with patch("app.services.readiness.get_settings", return_value=self.mock_settings):
            result = check_readiness(self.db, "nonexistent")
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["checks"]["tenant_active"])

    def test_activity_counts_do_not_expose_messages_or_contact_data(self):
        self.db.add(InboundEvent(
            tenant_id=self.tenant.id,
            wa_id="secret-test-phone",
            message_id="test-event-private",
            message_type="text",
            text="private-test-message",
            raw_payload={"private": "do-not-echo"},
        ))
        self.db.add(OutboxMessage(
            tenant_id=self.tenant.id,
            to_wa_id="secret-test-phone",
            body="private-test-message",
            status="delivery_unknown",
            last_error="private-provider-details",
        ))
        self.db.commit()
        with patch("app.services.readiness.get_settings", return_value=self.mock_settings):
            result = check_readiness(self.db, "dental-pilot-leon")
        self.assertEqual(result["activity"]["incoming_events"], 1)
        self.assertEqual(result["activity"]["outbox_delivery_unknown"], 1)
        self.assertEqual(result["activity"]["outbox_accepted"], 0)
        self.assertNotIn("secret-test-phone", str(result))
        self.assertNotIn("private-test-message", str(result))
        self.assertNotIn("private-provider-details", str(result))

    def test_admin_endpoint_rejects_unauthorized_and_exposes_no_secrets(self):
        app = FastAPI()
        app.include_router(admin_router)
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        with patch("app.api.admin.get_settings", return_value=self.mock_settings), \
             patch("app.services.readiness.get_settings", return_value=self.mock_settings):
            unauthorized = client.get("/admin/readiness")
            self.assertEqual(unauthorized.status_code, 401)
            authorized = client.get(
                "/admin/readiness",
                headers={"X-LocalFlow-Admin-Token": "readiness-test-only"},
            )
            self.assertEqual(authorized.status_code, 200)
            self.assertIn("checks", authorized.json())
            self.assertNotIn("configured-secret-test-only", authorized.text)


if __name__ == "__main__":
    unittest.main()
