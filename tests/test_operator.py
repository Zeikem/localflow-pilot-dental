import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Lead, Tenant
from app.services.operator import reactivate_lead
from app.services.scheduling import confirm_appointment, reserve_hold


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.tenant = Tenant(
            slug="tenant",
            name="Tenant",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE-OP",
            whatsapp_token_env="TOKEN",
            workflow_spec={
                "steps": [{"key": "nombre", "prompt": "Nombre"}],
                "schedule": {
                    "provider": "internal",
                    "slot_minutes": 15,
                    "hold_minutes": 10,
                    "booking_horizon_days": 14,
                    "min_notice_minutes": 0,
                    "resources": [{"key": "r1", "name": "R1"}],
                    "services": [
                        {
                            "key": "s1",
                            "label": "S1",
                            "duration_minutes": 30,
                            "resource_keys": ["r1"],
                        }
                    ],
                    "weekly_hours": {str(i): [["09:00", "18:00"]] for i in range(7)},
                    "closed_dates": [],
                },
            },
        )
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_reactivate_handoff(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="1",
            status="human_handoff",
            answers={"nombre": "A"},
        )
        self.db.add(lead)
        self.db.commit()

        result = reactivate_lead(self.db, lead.id)
        self.assertEqual(result.status, "active")

    def test_reactivate_preserves_booked_state_when_confirmed_appointment_exists(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="2",
            status="human_handoff",
            answers={},
        )
        self.db.add(lead)
        self.db.commit()

        start = datetime.now(timezone.utc) + timedelta(days=1)
        appointment = reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="s1",
            resource_key="r1",
            start_at=start,
            idempotency_key="booked",
            now=datetime.now(timezone.utc),
        )
        confirm_appointment(
            self.db,
            appointment,
            now=datetime.now(timezone.utc),
        )
        lead.answers = {"_confirmed_appointment_id": appointment.id}
        lead.status = "human_handoff"
        self.db.commit()

        result = reactivate_lead(self.db, lead.id)
        self.assertEqual(result.status, "booked")

    def test_reset_flow_clears_transient_schedule_state(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="3",
            status="human_handoff",
            current_step="servicio",
            answers={
                "nombre": "A",
                "_schedule_offer": {"x": 1},
                "_pending_appointment_id": "pending",
            },
        )
        self.db.add(lead)
        self.db.commit()

        result = reactivate_lead(self.db, lead.id, reset_flow=True)
        self.assertEqual(result.status, "active")
        self.assertIsNone(result.current_step)
        self.assertNotIn("_schedule_offer", result.answers)
        self.assertNotIn("_pending_appointment_id", result.answers)
        self.assertEqual(result.answers["nombre"], "A")


if __name__ == "__main__":
    unittest.main()
