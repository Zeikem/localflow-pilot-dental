import asyncio
import unittest
from unittest.mock import patch

from app.config import get_settings
from app.services.n8n import notify_inbound_messages
from app.services.webhook_parser import InboundWhatsAppMessage


class N8nRelayTests(unittest.TestCase):
    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_disabled_without_endpoint(self):
        asyncio.run(notify_inbound_messages([]))

    def test_rejects_non_https_endpoint(self):
        with patch.dict("os.environ", {"N8N_INGRESS_URL": "http://localhost:5678"}):
            get_settings.cache_clear()
            event = InboundWhatsAppMessage("m1", "p1", "52", "1", "text", "hola")
            asyncio.run(notify_inbound_messages([event]))
