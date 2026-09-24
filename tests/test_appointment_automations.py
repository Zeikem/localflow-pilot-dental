import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Lead, OutboxMessage, Tenant
from app.services.appointment_automations import schedule_appointment_messages
from app.services.calendar_provider import InternalCalendarProvider


class AppointmentAutomationTests(unittest.TestCase):
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
            slug="auto",
            name="Dental Auto",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE-AUTO",
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
                    "services": [{
                        "key": "valoracion",
                        "label": "Valoración",
                        "duration_minutes": 45,
                        "resource_keys": ["r1"],
                    }],
                    "weekly_hours": {str(i): [["09:00", "18:00"]] for i in range(7)},
                    "closed_dates": [],
                },
                "automations": {
                    "google_review_url": "https://example.com/review",
                    "appointment_reminder": {
                        "enabled": True,
                        "before_minutes": 1440,
                        "template_name": "recordatorio_cita",
                        "language": "es_MX",
                    },
                    "review_request": {
                        "enabled": True,
                        "after_minutes": 120,
                        "template_name": "solicitud_resena",
                        "language": "es_MX",
                    },
                },
            },
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.provider = InternalCalendarProvider()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_confirmation_schedules_reminder_and_review_templates(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="521000000000",
            answers={"nombre": "Adrián"},
        )
        self.db.add(lead)
        self.db.commit()

        start = datetime.now(timezone.utc) + timedelta(days=3)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="r1",
            start_at=start,
            idempotency_key="automation-confirm",
            now=datetime.now(timezone.utc),
        )
        self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=datetime.now(timezone.utc),
        )
        self.db.commit()

        rows = self.db.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.appointment_id == hold.id)
            .order_by(OutboxMessage.next_attempt_at)
        ).all()

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.message_kind == "template" for row in rows))
        self.assertEqual(rows[0].template_name, "recordatorio_cita")
        self.assertEqual(rows[1].template_name, "solicitud_resena")
        self.assertIn("Adrián", rows[0].template_params)
        self.assertIn("https://example.com/review", rows[1].template_params)

    def test_cancellation_cancels_pending_appointment_templates(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="521000000001",
            answers={"nombre": "A"},
        )
        self.db.add(lead)
        self.db.commit()

        start = datetime.now(timezone.utc) + timedelta(days=3)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="r1",
            start_at=start,
            idempotency_key="automation-cancel",
            now=datetime.now(timezone.utc),
        )
        self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=datetime.now(timezone.utc),
        )
        self.provider.cancel(self.db, self.tenant, hold)
        self.db.commit()

        rows = self.db.scalars(
            select(OutboxMessage).where(OutboxMessage.appointment_id == hold.id)
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.status == "cancelled" for row in rows))

    def test_reschedule_cancels_old_templates_and_schedules_new(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="521000000002",
            answers={"nombre": "Adrián"},
        )
        self.db.add(lead)
        self.db.commit()

        now = datetime.now(timezone.utc)
        old_start = now + timedelta(days=3)
        new_start = now + timedelta(days=4)

        old = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="r1",
            start_at=old_start,
            idempotency_key="automation-old",
            now=now,
        )
        self.provider.confirm(self.db, self.tenant, old, now=now)
        self.db.commit()

        new = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="r1",
            start_at=new_start,
            idempotency_key="automation-new",
            supersedes_appointment_id=old.id,
            now=now + timedelta(minutes=1),
        )
        self.provider.confirm(
            self.db,
            self.tenant,
            new,
            now=now + timedelta(minutes=2),
        )
        self.db.commit()

        old_rows = self.db.scalars(
            select(OutboxMessage).where(OutboxMessage.appointment_id == old.id)
        ).all()
        new_rows = self.db.scalars(
            select(OutboxMessage).where(OutboxMessage.appointment_id == new.id)
        ).all()

        self.assertEqual(len(old_rows), 2)
        self.assertTrue(all(row.status == "cancelled" for row in old_rows))
        self.assertEqual(len(new_rows), 2)
        self.assertTrue(all(row.status == "pending" for row in new_rows))

    def test_reminder_params_use_human_label_and_local_time(self):
        lead = Lead(
            tenant_id=self.tenant.id,
            wa_id="521000000003",
            answers={"nombre": "Adrián"},
        )
        self.db.add(lead)
        self.db.commit()

        start = datetime(2026, 9, 26, 16, 0, tzinfo=timezone.utc)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="r1",
            start_at=start,
            idempotency_key="automation-local-time",
            now=start - timedelta(days=2),
        )
        self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=start - timedelta(days=2),
        )
        self.db.commit()

        row = self.db.scalar(
            select(OutboxMessage).where(
                OutboxMessage.appointment_id == hold.id,
                OutboxMessage.template_name == "recordatorio_cita",
            )
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.template_params[1], "Valoración")
        self.assertEqual(row.template_params[2], "26/09/2026 10:00")


if __name__ == "__main__":
    unittest.main()
