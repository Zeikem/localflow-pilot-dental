import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Appointment, AppointmentSlot, Lead, Tenant
from app.services.scheduling import (
    AppointmentStateError,
    SlotUnavailable,
    cancel_appointment,
    cleanup_expired_holds,
    confirm_appointment,
    list_available_slots,
    reserve_hold,
    validate_schedule_spec,
)


def schedule():
    return {
        "provider": "internal",
        "slot_minutes": 15,
        "hold_minutes": 10,
        "booking_horizon_days": 14,
        "min_notice_minutes": 0,
        "resources": [{"key": "chair-1", "name": "Chair 1"}],
        "services": [
            {
                "key": "valoracion",
                "label": "Valoración",
                "duration_minutes": 45,
                "resource_keys": ["chair-1"],
            }
        ],
        "weekly_hours": {
            "0": [["09:00", "12:00"]],
            "1": [["09:00", "12:00"]],
            "2": [["09:00", "12:00"]],
            "3": [["09:00", "12:00"]],
            "4": [["09:00", "12:00"]],
            "5": [],
            "6": [],
        },
        "closed_dates": [],
    }


def make_tenant(slug="tenant-a", phone="phone-a"):
    return Tenant(
        slug=slug,
        name=slug,
        niche="dental",
        timezone="America/Mexico_City",
        whatsapp_phone_number_id=phone,
        whatsapp_token_env="TOKEN",
        workflow_spec={
            "steps": [{"key": "nombre", "prompt": "Nombre"}],
            "schedule": schedule(),
        },
    )


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_config_is_valid(self):
        validate_schedule_spec(schedule())

    def test_available_slots_respect_service_duration(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            # Miércoles 23/09/2026 a las 08:00 en CDMX = 14:00 UTC.
            now = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)
            slots = list_available_slots(
                db,
                tenant,
                "valoracion",
                start_date=datetime(2026, 9, 23).date(),
                days=1,
                limit=20,
                now=now,
            )
            self.assertTrue(slots)
            # 09:00-09:45 es el primer bloque local de 45 minutos.
            self.assertEqual(slots[0].start_at.hour, 15)  # UTC
            self.assertEqual(
                int((slots[0].end_at - slots[0].start_at).total_seconds() / 60),
                45,
            )

    def test_double_booking_is_blocked(self):
        with self.Session() as db:
            tenant = make_tenant()
            lead1 = Lead(tenant_id="placeholder", wa_id="1", answers={})
            db.add(tenant)
            db.flush()
            lead1.tenant_id = tenant.id
            lead2 = Lead(tenant_id=tenant.id, wa_id="2", answers={})
            db.add_all([lead1, lead2])
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            first = reserve_hold(
                db,
                tenant,
                lead_id=lead1.id,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="first",
                now=start - timedelta(hours=1),
            )
            db.flush()
            self.assertEqual(first.status, "held")

            with self.assertRaises(SlotUnavailable):
                reserve_hold(
                    db,
                    tenant,
                    lead_id=lead2.id,
                    service_key="valoracion",
                    resource_key="chair-1",
                    start_at=start,
                    idempotency_key="second",
                    now=start - timedelta(hours=1),
                )

    def test_idempotent_retry_returns_same_hold(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            first = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="same-request",
                now=start - timedelta(hours=1),
            )
            second = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="same-request",
                now=start - timedelta(hours=1),
            )
            self.assertEqual(first.id, second.id)

    def test_expired_hold_releases_slots(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            created_at = start - timedelta(hours=2)
            hold = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="expires",
                now=created_at,
            )
            db.commit()

            expired = cleanup_expired_holds(
                db,
                tenant.id,
                now=created_at + timedelta(minutes=11),
            )
            db.commit()
            self.assertEqual(expired, 1)
            self.assertEqual(hold.status, "expired")
            self.assertEqual(
                db.scalar(
                    select(AppointmentSlot).where(
                        AppointmentSlot.appointment_id == hold.id
                    )
                ),
                None,
            )

            replacement = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="replacement",
                now=created_at + timedelta(minutes=11),
            )
            self.assertEqual(replacement.status, "held")

    def test_confirmation_after_expiration_fails(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            now = start - timedelta(hours=2)
            hold = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="late-confirm",
                now=now,
            )
            with self.assertRaises(AppointmentStateError):
                confirm_appointment(db, hold, now=now + timedelta(minutes=11))
            self.assertEqual(hold.status, "expired")

    def test_cancellation_releases_slots(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            hold = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="cancel-me",
                now=start - timedelta(hours=1),
            )
            confirm_appointment(db, hold, now=start - timedelta(minutes=55))
            cancel_appointment(db, hold)
            db.commit()
            self.assertEqual(hold.status, "cancelled")

            replacement = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="after-cancel",
                now=start - timedelta(minutes=40),
            )
            self.assertEqual(replacement.status, "held")

    def test_reschedule_keeps_old_until_new_is_confirmed(self):
        with self.Session() as db:
            tenant = make_tenant()
            db.add(tenant)
            db.commit()

            old_start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            new_start = datetime(2026, 9, 24, 16, 0, tzinfo=timezone.utc)
            now = old_start - timedelta(hours=1)

            old = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=old_start,
                idempotency_key="old",
                now=now,
            )
            confirm_appointment(db, old, now=now + timedelta(minutes=1))
            db.commit()

            new = reserve_hold(
                db,
                tenant,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=new_start,
                idempotency_key="new",
                supersedes_appointment_id=old.id,
                now=now + timedelta(minutes=2),
            )
            db.flush()
            self.assertEqual(old.status, "confirmed")
            self.assertEqual(new.status, "held")

            confirm_appointment(db, new, now=now + timedelta(minutes=3))
            db.commit()
            self.assertEqual(old.status, "cancelled")
            self.assertEqual(new.status, "confirmed")

    def test_tenants_can_use_same_resource_name_and_time(self):
        with self.Session() as db:
            tenant_a = make_tenant("tenant-a", "phone-a")
            tenant_b = make_tenant("tenant-b", "phone-b")
            db.add_all([tenant_a, tenant_b])
            db.commit()

            start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
            a = reserve_hold(
                db,
                tenant_a,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="a",
                now=start - timedelta(hours=1),
            )
            b = reserve_hold(
                db,
                tenant_b,
                lead_id=None,
                service_key="valoracion",
                resource_key="chair-1",
                start_at=start,
                idempotency_key="b",
                now=start - timedelta(hours=1),
            )
            self.assertNotEqual(a.tenant_id, b.tenant_id)


if __name__ == "__main__":
    unittest.main()
