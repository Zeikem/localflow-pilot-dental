import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Appointment, InboundEvent, Lead, Tenant


class BridgeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.tenants = []
        for i in range(2):
            t = Tenant(
                slug=f"clinic-{i}", name=f"Clínica Ficticia {i}",
                niche="dental", timezone="America/Mexico_City",
                whatsapp_phone_number_id=f"fake-{i}",
                whatsapp_token_env="TOKEN_NOT_USED",
                workflow_spec={},
            )
            self.session.add(t)
            self.tenants.append(t)
        self.session.flush()
        self.lead = Lead(
            tenant_id=self.tenants[0].id,
            wa_id="5214771234000",
            status="human_handoff",
            answers={"medical_private": "very confidential"},
        )
        self.session.add(self.lead)
        self.session.flush()
        for index in range(3):
            self.session.add(InboundEvent(
                message_id=f"wamid.test-{index}",
                tenant_id=self.tenants[0].id,
                lead_id=self.lead.id,
                wa_id="5214771234000",
                message_type="text",
                text="Información médica privada que no se debe exportar",
                raw_payload={"data": "privada", "phone": "5214771234000"},
                created_at=datetime.now(timezone.utc) + timedelta(seconds=index),
            ))
        self.session.add(InboundEvent(
            message_id="wamid.other-tenant",
            tenant_id=self.tenants[1].id,
            wa_id="5214779999999",
            message_type="text",
            text="otro negocio confidencial",
            raw_payload={"sensitive": True},
        ))
        self.session.add(Appointment(
            tenant_id=self.tenants[0].id,
            lead_id=self.lead.id,
            service_key="limpieza",
            resource_key="sillon-1",
            start_at=datetime.now(timezone.utc) + timedelta(days=2),
            end_at=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
            status="confirmed",
            idempotency_key="ficticia-test",
        ))
        self.session.commit()
        app.dependency_overrides[get_db] = lambda: self.session
        self.patcher = patch(
            "app.api.bridge.get_settings",
            return_value=SimpleNamespace(localflow_bridge_read_token="bridge-exclusive-read-only-secret-2026"),
        )
        self.patcher.start()
        self.client = TestClient(app, raise_server_exceptions=True)
        self.header = {"X-LocalFlow-Bridge-Token": "bridge-exclusive-read-only-secret-2026"}

    def tearDown(self):
        self.client.close()
        self.patcher.stop()
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def test_requires_authentication(self):
        for suffix in ("events", "appointments"):
            path = f"/admin/bridge/{suffix}?tenant_slug=clinic-0"
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(
                path, headers={"X-LocalFlow-Bridge-Token": "incorrect"}
            ).status_code, 401)

    def test_tenant_isolation_and_minimization(self):
        reply = self.client.get(
            "/admin/bridge/events?tenant_slug=clinic-0", headers=self.header
        )
        self.assertEqual(reply.status_code, 200)
        payload = reply.json()
        self.assertEqual(len(payload["events"]), 3)
        response_text = reply.text.lower()
        for forbidden in (
            "5214771234000", "información médica", "privada",
            "wamid.test-", "medical_private", "otro negocio",
        ):
            self.assertNotIn(forbidden, response_text)
        self.assertEqual(payload["events"][0]["category"], "Requiere recepción")
        self.assertEqual(
            self.client.get(
                "/admin/bridge/events?tenant_slug=clinic-1",
                headers=self.header,
            ).json()["events"].__len__(), 1,
        )
        self.assertEqual(self.client.get(
            "/admin/bridge/events?tenant_slug=absent", headers=self.header
        ).status_code, 404)

    def test_cursor_pagination_no_repeats(self):
        seen = []
        cursor = None
        while True:
            params = {"tenant_slug": "clinic-0", "limit": 1}
            if cursor:
                params["cursor"] = cursor
            response = self.client.get(
                "/admin/bridge/events", headers=self.header, params=params
            )
            self.assertEqual(response.status_code, 200, response.text)
            doc = response.json()
            seen += [e["event_digest"] for e in doc["events"]]
            cursor = doc["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(set(seen)), 3)
        self.assertEqual(self.client.get(
            "/admin/bridge/events", headers=self.header,
            params={"tenant_slug": "clinic-0", "cursor": "bad"},
        ).status_code, 400)

    def test_appointments_read_only_and_scoped(self):
        response = self.client.get(
            "/admin/bridge/appointments?tenant_slug=clinic-0",
            headers=self.header,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["appointments"]), 1)
        self.assertNotIn("5214771234000", response.text)
        self.assertEqual(self.client.get(
            "/admin/bridge/appointments?tenant_slug=clinic-1",
            headers=self.header,
        ).json()["appointments"], [])


if __name__ == "__main__":
    unittest.main()
