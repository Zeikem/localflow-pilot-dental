import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Tenant
from app.services.intake import interpret_intake


def make_tenant():
    return Tenant(
        slug="pilot",
        name="Pilot",
        niche="dental",
        timezone="America/Mexico_City",
        whatsapp_phone_number_id="123",
        whatsapp_token_env="TOKEN",
        workflow_spec={
            "steps": [
                {"key": "nombre", "prompt": "Nombre"},
                {
                    "key": "servicio",
                    "prompt": "Servicio",
                    "kind": "choice",
                    "choices": ["Valoración", "Limpieza", "Ortodoncia"],
                },
                {
                    "key": "urgencia",
                    "prompt": "Urgencia",
                    "kind": "choice",
                    "choices": ["Sí, necesito atención hoy", "No, puedo agendar"],
                },
            ],
            "schedule": {
                "services": [
                    {"key": "valoracion", "label": "Valoración"},
                    {"key": "limpieza", "label": "Limpieza"},
                    {"key": "ortodoncia", "label": "Ortodoncia"},
                ]
            },
        },
    )


class IntakeTests(unittest.TestCase):
    def test_bare_hour_does_not_crash_or_assume_am_pm(self):
        self.assertIsNone(interpret_intake(make_tenant(), "Quiero cita mañana a las 4").requested_start)

    def test_morning_marker_is_not_tomorrow(self):
        now = datetime(2026, 9, 25, 12, tzinfo=ZoneInfo("America/Mexico_City"))
        start = interpret_intake(make_tenant(), "Quiero cita el lunes a las 9 de la mañana", now=now).requested_start
        self.assertEqual(start.date().isoformat(), "2026-09-28")
        self.assertEqual(start.hour, 9)

    def test_extracts_service_and_relative_datetime(self):
        tenant = make_tenant()
        now = datetime(2026, 9, 25, 22, 0, tzinfo=ZoneInfo("America/Mexico_City"))

        hints = interpret_intake(
            tenant,
            "Hola, quiero una limpieza mañana a las 4 pm",
            now=now,
        )

        self.assertEqual(hints.answers["servicio"], "Limpieza")
        self.assertEqual(hints.requested_start.date().isoformat(), "2026-09-26")
        self.assertEqual(hints.requested_start.hour, 16)

    def test_extracts_urgent_intent(self):
        tenant = make_tenant()
        hints = interpret_intake(tenant, "Tengo mucho dolor, es urgente")

        self.assertEqual(
            hints.answers["urgencia"],
            "Sí, necesito atención hoy",
        )

    def test_non_urgent_phrase_wins(self):
        tenant = make_tenant()
        hints = interpret_intake(tenant, "No es urgente, puedo agendar limpieza")

        self.assertEqual(hints.answers["servicio"], "Limpieza")
        self.assertEqual(hints.answers["urgencia"], "No, puedo agendar")

    def test_does_not_invent_missing_time(self):
        tenant = make_tenant()
        hints = interpret_intake(tenant, "Quiero valoración mañana")

        self.assertEqual(hints.answers["servicio"], "Valoración")
        self.assertIsNone(hints.requested_start)


if __name__ == "__main__":
    unittest.main()
