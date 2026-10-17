"""Prueba automática de la demostración comercial sin integraciones externas."""
import unittest

from app.demo import SCRIPT, run_demo


class DemoTests(unittest.TestCase):
    def test_internal_booking_demo_is_reproducible(self):
        result = run_demo()
        self.assertEqual(result["mode"], "offline_synthetic_demonstration")
        self.assertEqual(result["calendar_provider"], "internal")
        self.assertEqual(result["appointment_status"], "confirmed")
        self.assertEqual(result["confirmed_appointments"], 1)
        self.assertEqual(result["meta_messages_sent"], 0)
        self.assertEqual(result["openai_api_calls"], 0)
        self.assertFalse(result["external_integrations_tested"])
        self.assertFalse(result["production_modified"])
        self.assertEqual(len(result["transcript"]), len(SCRIPT))
        self.assertTrue(
            all(row["localflow"].strip() for row in result["transcript"])
        )
        self.assertIn(
            "confirmada",
            result["transcript"][-1]["localflow"].casefold(),
        )


if __name__ == "__main__":
    unittest.main()
