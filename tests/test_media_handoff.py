from sqlalchemy import select
from app.models import InboundEvent, OutboxMessage
from app.services.conversation import process_inbound_message
from app.services.webhook_parser import InboundWhatsAppMessage
import unittest
from tests import test_conversation_scheduling as helpers


class MediaHandoffTests(unittest.TestCase):
    setUp = helpers.ConversationSchedulingTests.setUp
    tearDown = helpers.ConversationSchedulingTests.tearDown
    send = helpers.ConversationSchedulingTests.send
    lead = helpers.ConversationSchedulingTests.lead
    def test_media_during_handoff_is_recorded_without_reply(self):
        self.send('ASESOR')
        before = len(self.db.scalars(select(OutboxMessage)).all())
        for kind in ('audio', 'image', 'sticker'):
            with self.subTest(kind=kind):
                message = InboundWhatsAppMessage(
                    message_id='media-' + kind, phone_number_id='PHONE',
                    wa_id='5210000000000', message_type=kind, text=None, raw={})
                self.assertTrue(process_inbound_message(self.db, message))
                self.assertIsNotNone(self.db.scalar(select(InboundEvent).where(
                    InboundEvent.message_id == message.message_id)))
                self.assertEqual(self.lead().status, 'human_handoff')
                self.assertIsNotNone(self.lead().last_user_message_at)
                self.assertEqual(len(self.db.scalars(select(OutboxMessage)).all()), before)
