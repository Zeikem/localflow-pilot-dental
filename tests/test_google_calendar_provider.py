import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Appointment, CalendarSyncTask, Lead, Tenant
from app.services.calendar_provider import GoogleCalendarProvider
from app.services.google_calendar import BusyInterval
from app.services.scheduling import SlotUnavailable


def workflow_spec():
    return {
        "steps": [
            {"key": "nombre", "prompt": "Nombre"},
            {
                "key": "servicio",
                "prompt": "Servicio",
                "kind": "choice",
                "choices": ["Valoración"],
            },
        ],
        "schedule": {
            "provider": "google_calendar",
            "google": {"credentials_env": "GC_CREDS"},
            "slot_minutes": 15,
            "hold_minutes": 10,
            "booking_horizon_days": 14,
            "min_notice_minutes": 0,
            "resources": [
                {
                    "key": "chair-1",
                    "name": "Consultorio",
                    "calendar_id_env": "CALENDAR_A",
                }
            ],
            "services": [
                {
                    "key": "valoracion",
                    "label": "Valoración",
                    "duration_minutes": 45,
                    "resource_keys": ["chair-1"],
                }
            ],
            "weekly_hours": {
                "0": [["09:00", "19:00"]],
                "1": [["09:00", "19:00"]],
                "2": [["09:00", "19:00"]],
                "3": [["09:00", "19:00"]],
                "4": [["09:00", "19:00"]],
                "5": [],
                "6": [],
            },
            "closed_dates": [],
        },
    }


class FakeGateway:
    def __init__(self):
        self.busy_map = {}
        self.created = []
        self.deleted = []
        self.existing_event_id = None

    def busy(self, *, calendar_ids, start, end):
        return {
            calendar_id: list(self.busy_map.get(calendar_id, []))
            for calendar_id in calendar_ids
        }

    def find_event_id_by_idempotency(
        self, *, calendar_id, idempotency_key, start, end
    ):
        return self.existing_event_id

    def create_event(self, **kwargs):
        self.created.append(kwargs)
        return "evt-new"

    def delete_event(self, *, calendar_id, event_id):
        self.deleted.append((calendar_id, event_id))


class GoogleCalendarProviderTests(unittest.TestCase):
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
            slug="google-demo",
            name="Google Demo",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE-G",
            whatsapp_token_env="TOKEN_G",
            workflow_spec=workflow_spec(),
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.provider = GoogleCalendarProvider()
        self.gateway = FakeGateway()
        self.gateway_patch = patch.object(
            self.provider,
            "_gateway",
            return_value=self.gateway,
        )
        self.gateway_patch.start()
        self.env_patch = patch.dict(
            "os.environ",
            {"CALENDAR_A": "calendar-a@example.com"},
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.gateway_patch.stop()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_external_busy_slots_are_filtered_and_later_slots_survive(self):
        self.gateway.busy_map["calendar-a@example.com"] = [
            BusyInterval(
                start=datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc),
                end=datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc),
            )
        ]
        slots = self.provider.list_available_slots(
            self.db,
            self.tenant,
            "valoracion",
            start_date=datetime(2026, 9, 23).date(),
            days=1,
            limit=3,
            now=datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(slots), 3)
        self.assertGreaterEqual(
            slots[0].start_at,
            datetime(2026, 9, 23, 17, 0, tzinfo=timezone.utc),
        )

    def test_confirm_creates_google_event_and_marks_internal_confirmed(self):
        lead = Lead(tenant_id=self.tenant.id, wa_id="1", answers={"nombre": "Adrián"})
        self.db.add(lead)
        self.db.commit()

        start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=lead.id,
            service_key="valoracion",
            resource_key="chair-1",
            start_at=start,
            idempotency_key="confirm-google",
            now=start - timedelta(hours=1),
        )

        confirmed = self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=start - timedelta(minutes=55),
        )
        self.db.commit()

        self.assertEqual(confirmed.status, "confirmed")
        self.assertEqual(confirmed.external_provider, "google_calendar")
        self.assertEqual(confirmed.external_event_id, "evt-new")
        self.assertEqual(len(self.gateway.created), 1)

    def test_retry_recovers_existing_google_event_without_duplicate_create(self):
        self.gateway.existing_event_id = "evt-existing"
        start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=None,
            service_key="valoracion",
            resource_key="chair-1",
            start_at=start,
            idempotency_key="recover-google",
            now=start - timedelta(hours=1),
        )

        confirmed = self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=start - timedelta(minutes=55),
        )

        self.assertEqual(confirmed.external_event_id, "evt-existing")
        self.assertEqual(self.gateway.created, [])

    def test_external_collision_prevents_confirmation(self):
        start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=None,
            service_key="valoracion",
            resource_key="chair-1",
            start_at=start,
            idempotency_key="collision-google",
            now=start - timedelta(hours=1),
        )
        self.gateway.busy_map["calendar-a@example.com"] = [
            BusyInterval(start=start, end=start + timedelta(minutes=45))
        ]

        with self.assertRaises(SlotUnavailable):
            self.provider.confirm(
                self.db,
                self.tenant,
                hold,
                now=start - timedelta(minutes=55),
            )

        self.assertEqual(hold.status, "cancelled")
        self.assertEqual(self.gateway.created, [])

    def test_cancel_queues_external_delete_with_retry_worker(self):
        start = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
        hold = self.provider.reserve_hold(
            self.db,
            self.tenant,
            lead_id=None,
            service_key="valoracion",
            resource_key="chair-1",
            start_at=start,
            idempotency_key="cancel-google",
            now=start - timedelta(hours=1),
        )
        confirmed = self.provider.confirm(
            self.db,
            self.tenant,
            hold,
            now=start - timedelta(minutes=55),
        )
        self.provider.cancel(self.db, self.tenant, confirmed)
        self.db.commit()

        task = self.db.scalar(
            select(CalendarSyncTask).where(
                CalendarSyncTask.appointment_id == confirmed.id
            )
        )
        self.assertIsNotNone(task)
        self.assertEqual(task.action, "delete_event")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.payload["event_id"], "evt-new")


if __name__ == "__main__":
    unittest.main()
