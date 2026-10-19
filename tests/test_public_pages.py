"""Public legal notice URLs required by the Meta app configuration."""
import unittest
from fastapi.testclient import TestClient
from app.main import app

class LegalPagesTests(unittest.TestCase):
    def test_pages_are_public_and_linked(self):
        with TestClient(app) as client:
            for path in ("/privacy", "/data-deletion", "/terms"):
                result = client.get(path)
                self.assertEqual(result.status_code, 200, (path, result.status_code))
                self.assertIn("text/html", result.headers["content-type"])
                self.assertIn("LocalFlow", result.text)
                self.assertIn("rthojalateriaypintura@gmail.com", result.text)
                self.assertIn('href="/data-deletion"', result.text)
                self.assertNotIn("WHATSAPP_APP_SECRET", result.text)
                self.assertNotIn("LOCALFLOW_BRIDGE_READ_TOKEN", result.text)

    def test_privacy_describes_current_scope(self):
        with TestClient(app) as client:
            page = client.get("/privacy").text
            for fragment in ("solo recepción", "seudónim", "Meta", "Railway",
                             "eliminación", "19 de octubre de 2026"):
                self.assertIn(fragment, page)
