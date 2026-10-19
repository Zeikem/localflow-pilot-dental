"""Safety tests: no external WhatsApp calls without an explicit enable flag."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.whatsapp import (
    WhatsAppClient, WhatsAppConfigurationError,
)


class OutboundSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(
            whatsapp_token_env="TEST_ONLY_WHATSAPP_ACCESS_TOKEN",
            whatsapp_phone_number_id="FAKE-ID-NOT-IN-META",
        )

    def test_text_and_template_are_blocked_by_default(self):
        with patch("app.services.whatsapp.get_settings",
                   return_value=SimpleNamespace(whatsapp_outbound_enabled=False)):
            client = WhatsAppClient()
        with patch("app.services.whatsapp.httpx.Client") as transport:
            with self.assertRaises(WhatsAppConfigurationError):
                client.send_text(self.tenant, "0000000000000", "Mensaje de prueba")
            with self.assertRaises(WhatsAppConfigurationError):
                client.send_template(
                    self.tenant, "0000000000000", template_name="demo",
                    language_code="es_MX",
                )
            transport.assert_not_called()

    def test_enabled_flag_needs_configured_token_and_mocked_transport(self):
        with patch("app.services.whatsapp.get_settings",
                   return_value=SimpleNamespace(
                       whatsapp_outbound_enabled=True,
                       meta_graph_api_version="v26.0",
                   )):
            client = WhatsAppClient()
        with patch.dict(os.environ, {"TEST_ONLY_WHATSAPP_ACCESS_TOKEN": ""}):
            with patch("app.services.whatsapp.httpx.Client") as transport:
                with self.assertRaises(WhatsAppConfigurationError):
                    client.send_text(self.tenant, "0000000000000", "Hola")
                transport.assert_not_called()

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"messages": [{"id": "wamid.FAKE"}]}
        instance = MagicMock()
        instance.__enter__.return_value.post.return_value = response
        with patch.dict(os.environ, {"TEST_ONLY_WHATSAPP_ACCESS_TOKEN": "fake-not-real"}):
            with patch("app.services.whatsapp.httpx.Client", return_value=instance):
                self.assertEqual(
                    client.send_text(self.tenant, "0000000000000", "Hola"),
                    "wamid.FAKE",
                )
        self.assertIn("FAKE-ID-NOT-IN-META", instance.__enter__.return_value.post.call_args.args[0])

    def test_review_only_cannot_send_even_when_global_outbound_enabled(self):
        self.tenant.workflow_spec = {"inbound_mode": "review_only"}
        with patch("app.services.whatsapp.get_settings",
                   return_value=SimpleNamespace(whatsapp_outbound_enabled=True)):
            client = WhatsAppClient()
        with patch("app.services.whatsapp.httpx.Client") as transport:
            with self.assertRaises(WhatsAppConfigurationError):
                client.send_text(self.tenant, "0000000000000", "No enviar")
            with self.assertRaises(WhatsAppConfigurationError):
                client.send_template(
                    self.tenant, "0000000000000",
                    template_name="demo", language_code="es_MX",
                )
            transport.assert_not_called()

    def test_worker_blocks_preexisting_outbox_for_review_only_tenant(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db import Base
        from app.models import Tenant, OutboxMessage
        from app.workers.outbox import deliver

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with session() as db:
                tenant = Tenant(
                    slug="review-only-demo", name="Clínica simulada", niche="dental",
                    timezone="America/Mexico_City",
                    whatsapp_phone_number_id="FAKE-NOT-META",
                    whatsapp_token_env="NOT_SET",
                    workflow_spec={"inbound_mode": "review_only"},
                )
                db.add(tenant)
                db.flush()
                old_message = OutboxMessage(
                    tenant_id=tenant.id, to_wa_id="0000000000000",
                    body="Previously queued and never sent", status="sending",
                )
                db.add(old_message)
                db.commit()
                message_id = old_message.id
            fake_client = MagicMock()
            with patch("app.workers.outbox.SessionLocal", session):
                deliver(message_id, fake_client)
            fake_client.send_text.assert_not_called()
            fake_client.send_template.assert_not_called()
            with session() as db:
                item = db.get(OutboxMessage, message_id)
                self.assertEqual(item.status, "blocked")
                self.assertIsNone(item.locked_at)
        finally:
            engine.dispose()

    def test_worker_does_not_claim_queue_when_disabled(self):
        class EndLoop(Exception):
            pass

        with (
            patch("app.workers.outbox.get_settings",
                  return_value=SimpleNamespace(whatsapp_outbound_enabled=False)),
            patch("app.workers.outbox.WhatsAppClient"),
            patch("app.workers.outbox.requeue_stale") as requeue,
            patch("app.workers.outbox.claim_batch") as claim,
            patch("app.workers.outbox.time.sleep", side_effect=EndLoop),
        ):
            from app.workers.outbox import main
            with self.assertRaises(EndLoop):
                main()
            claim.assert_not_called()
            requeue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
