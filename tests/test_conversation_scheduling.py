import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Appointment, Lead, OutboxMessage, Tenant
from app.services.conversation import process_inbound_message
from app.services.webhook_parser import InboundWhatsAppMessage


def tenant_spec():
    return {
        "handoff_message": "Recepción continuará contigo.",
        "steps": [
            {"key": "nombre", "prompt": "¿Cuál es tu nombre?"},
            {
                "key": "servicio",
                "prompt": "¿Qué servicio te interesa?",
                "kind": "choice",
                "choices": ["Valoración", "Limpieza", "Otro"],
            },
        ],
        "schedule": {
            "provider": "internal",
            "slot_minutes": 15,
            "hold_minutes": 10,
            "booking_horizon_days": 14,
            "min_notice_minutes": 0,
            "resources": [{"key": "recurso-1", "name": "Agenda"}],
            "services": [
                {
                    "key": "valoracion",
                    "label": "Valoración",
                    "duration_minutes": 45,
                    "resource_keys": ["recurso-1"],
                },
                {
                    "key": "limpieza",
                    "label": "Limpieza",
                    "duration_minutes": 60,
                    "resource_keys": ["recurso-1"],
                },
            ],
            "weekly_hours": {
                "0": [["09:00", "19:00"]],
                "1": [["09:00", "19:00"]],
                "2": [["09:00", "19:00"]],
                "3": [["09:00", "19:00"]],
                "4": [["09:00", "19:00"]],
                "5": [["09:00", "14:00"]],
                "6": [],
            },
            "closed_dates": [],
        },
    }


class ConversationSchedulingTests(unittest.TestCase):
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
            slug="dental",
            name="Dental",
            niche="dental",
            timezone="America/Mexico_City",
            whatsapp_phone_number_id="PHONE",
            whatsapp_token_env="TOKEN",
            workflow_spec=tenant_spec(),
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.counter = 0

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def send(self, text, wa_id="5210000000000", message_id=None):
        self.counter += 1
        msg = InboundWhatsAppMessage(
            message_id=message_id or f"wamid-{self.counter}",
            phone_number_id="PHONE",
            wa_id=wa_id,
            message_type="text",
            text=text,
            raw={"test": True},
        )
        previous_ids = set(self.db.scalars(select(OutboxMessage.id)).all())
        processed = process_inbound_message(self.db, msg)
        for reply in self.db.scalars(select(OutboxMessage)).all():
            if reply.id not in previous_ids:
                self._last_reply = reply.body
        return processed

    def last_reply(self):
        return self._last_reply

    def lead(self):
        return self.db.scalar(select(Lead).where(Lead.wa_id == "5210000000000"))

    def reach_slot_offer(self):
        self.assertTrue(self.send("Hola"))
        self.assertIn("nombre", self.last_reply().lower())
        self.assertTrue(self.send("Adrián"))
        self.assertIn("servicio", self.last_reply().lower())
        self.assertTrue(self.send("1"))
        self.assertIn("horarios disponibles", self.last_reply().lower())
        self.assertEqual(self.lead().status, "awaiting_slot")

    def test_full_booking_flow(self):
        self.reach_slot_offer()

        self.assertTrue(self.send("1"))
        self.assertIn("reservé temporalmente", self.last_reply().lower())
        self.assertEqual(self.lead().status, "awaiting_confirmation")

        self.assertTrue(self.send("CONFIRMAR"))
        self.assertIn("cita quedó confirmada", self.last_reply().lower())
        self.assertEqual(self.lead().status, "booked")

        appointment_id = self.lead().answers["_confirmed_appointment_id"]
        appointment = self.db.get(Appointment, appointment_id)
        self.assertEqual(appointment.status, "confirmed")

    def test_other_service_escalates_to_human(self):
        self.send("Hola")
        self.send("Adrián")
        self.send("3")
        self.assertEqual(self.lead().status, "human_handoff")
        self.assertIn("persona", self.last_reply().lower())

    def test_cancel_pending_hold_releases_it(self):
        self.reach_slot_offer()
        self.send("1")
        pending_id = self.lead().answers["_pending_appointment_id"]

        self.send("CANCELAR")
        pending = self.db.get(Appointment, pending_id)
        self.assertEqual(pending.status, "cancelled")
        self.assertEqual(self.lead().status, "active")

    def test_reschedule_cancel_keeps_original(self):
        self.reach_slot_offer()
        self.send("1")
        self.send("CONFIRMAR")
        original_id = self.lead().answers["_confirmed_appointment_id"]
        original = self.db.get(Appointment, original_id)
        self.assertEqual(original.status, "confirmed")

        self.send("REPROGRAMAR")
        self.assertEqual(self.lead().status, "awaiting_slot")
        self.send("1")
        self.assertEqual(self.lead().status, "awaiting_confirmation")
        new_id = self.lead().answers["_pending_appointment_id"]

        self.send("CANCELAR")
        new = self.db.get(Appointment, new_id)
        self.assertEqual(new.status, "cancelled")
        self.assertEqual(original.status, "confirmed")
        self.assertEqual(self.lead().status, "booked")
        self.assertIn("cita original sigue confirmada", self.last_reply().lower())

    def test_reschedule_confirmation_replaces_original(self):
        self.reach_slot_offer()
        self.send("1")
        self.send("CONFIRMAR")
        original_id = self.lead().answers["_confirmed_appointment_id"]

        self.send("REPROGRAMAR")
        self.send("1")
        new_id = self.lead().answers["_pending_appointment_id"]
        self.send("CONFIRMAR")

        original = self.db.get(Appointment, original_id)
        new = self.db.get(Appointment, new_id)
        self.assertEqual(original.status, "cancelled")
        self.assertEqual(new.status, "confirmed")
        self.assertEqual(self.lead().answers["_confirmed_appointment_id"], new.id)

    def test_duplicate_message_is_ignored(self):
        msg_id = "same-id"
        self.assertTrue(self.send("Hola", message_id=msg_id))
        count_before = len(self.db.scalars(select(OutboxMessage)).all())
        self.assertFalse(self.send("Hola de nuevo", message_id=msg_id))
        count_after = len(self.db.scalars(select(OutboxMessage)).all())
        self.assertEqual(count_before, count_after)

    def test_expired_pending_hold_reoffers_availability(self):
        self.reach_slot_offer()
        self.send("1")
        pending_id = self.lead().answers["_pending_appointment_id"]
        pending = self.db.get(Appointment, pending_id)
        pending.hold_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()

        self.send("CONFIRMAR")
        self.assertEqual(pending.status, "expired")
        self.assertEqual(self.lead().status, "awaiting_slot")
        self.assertIn("horarios disponibles", self.last_reply().lower())

    def test_human_handoff_does_not_restart_bot(self):
        self.send("Hola")
        self.send("ASESOR")
        self.assertEqual(self.lead().status, "human_handoff")
        count_before = len(self.db.scalars(select(OutboxMessage)).all())

        self.send("Hola, sigo aquí")
        count_after = len(self.db.scalars(select(OutboxMessage)).all())

        self.assertEqual(self.lead().status, "human_handoff")
        self.assertEqual(count_before, count_after)

    def test_completed_handoff_rule_escalates_urgent_request(self):
        spec = self.tenant.workflow_spec
        spec["steps"].append({
            "key": "urgencia",
            "prompt": "¿Necesitas atención hoy?",
            "kind": "choice",
            "choices": ["Sí, necesito atención hoy", "No, puedo agendar"],
        })
        spec["handoff_rules"] = [{
            "field": "urgencia",
            "values": ["Sí, necesito atención hoy"],
            "message": "Recepción continuará contigo por tratarse de una solicitud urgente.",
        }]
        self.tenant.workflow_spec = dict(spec)
        self.db.commit()

        self.send("Hola")
        self.send("Adrián")
        self.send("1")
        self.send("1")

        self.assertEqual(self.lead().status, "human_handoff")
        self.assertIn("urgente", self.last_reply().lower())


if __name__ == "__main__":
    unittest.main()
