import copy
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import select
from app.models import Appointment
from app.services.google_calendar import GoogleCalendarAPIError, BusyInterval
from tests import test_conversation_scheduling as helpers
from tests.test_google_calendar_provider import FakeGateway


class DirectBookingTests(unittest.TestCase):
    setUp_base = helpers.ConversationSchedulingTests.setUp
    tearDown = helpers.ConversationSchedulingTests.tearDown
    send = helpers.ConversationSchedulingTests.send
    lead = helpers.ConversationSchedulingTests.lead
    last_reply = helpers.ConversationSchedulingTests.last_reply

    def setUp(self):
        self.setUp_base()
        spec = copy.deepcopy(self.tenant.workflow_spec)
        spec['direct_booking'] = {'enabled': True, 'default_service_key': 'valoracion'}
        spec['schedule']['weekly_hours'] = {str(i): [['09:00', '19:00']] for i in range(7)}
        spec['schedule']['provider'] = 'google_calendar'
        spec['schedule']['google'] = {'credentials_env': 'TEST_CREDS'}
        spec['schedule']['resources'][0]['calendar_id_env'] = 'TEST_CALENDAR'
        self.tenant.workflow_spec = spec
        self.db.commit()
        self.gateway = FakeGateway()
        self.env_patch = patch.dict(os.environ, {'TEST_CALENDAR': 'test-calendar'})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.gateway_patch = patch('app.services.calendar_provider.GoogleCalendarProvider._gateway', return_value=self.gateway)
        self.gateway_patch.start()
        self.addCleanup(self.gateway_patch.stop)

    def test_books_exact_requested_time_and_deduplicates(self):
        self.send('Hola, quiero una cita mañana a las 4 pm', message_id='direct-1')
        self.assertEqual(self.lead().status, 'booked')
        appointment = self.db.scalar(select(Appointment))
        self.assertEqual(appointment.status, 'confirmed')
        self.assertTrue(appointment.external_event_id)
        self.assertEqual(appointment.start_at.hour, 22)  # 16:00 Mexico City = 22:00 UTC
        self.assertIn('16:00', self.last_reply())
        self.assertEqual(len(self.gateway.created), 1)
        self.assertFalse(self.send('Hola, quiero una cita mañana a las 4 pm', message_id='direct-1'))
        self.assertEqual(len(self.gateway.created), 1)

    def test_busy_time_never_books_a_different_slot(self):
        start = datetime.now(ZoneInfo('America/Mexico_City')).replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=1)
        self.gateway.busy_map = {'test-calendar': [BusyInterval(start, start + timedelta(hours=1))]}
        self.send('Quiero una cita mañana a las 4 pm')
        self.assertEqual(len(self.gateway.created), 0)
        self.assertIsNone(self.db.scalar(select(Appointment)))
        self.assertIn('no está disponible', self.last_reply())

    def test_google_failure_does_not_confirm(self):
        with patch.object(self.gateway, 'create_event', side_effect=GoogleCalendarAPIError('test')):
            self.send('Quiero una cita mañana a las 4 pm')
        self.assertEqual(self.lead().status, 'human_handoff')
        self.assertNotEqual(self.db.scalar(select(Appointment)).status, 'confirmed')
        self.assertNotIn('quedó confirmada', self.last_reply())

    def test_ambiguous_time_requests_clarification(self):
        self.send('Quiero una cita mañana a las 4')
        self.assertIn('am o pm', self.last_reply())
        self.assertIsNone(self.db.scalar(select(Appointment)))

    def test_negative_request_never_books(self):
        self.send('No quiero una cita mañana a las 4 pm')
        self.assertIsNone(self.db.scalar(select(Appointment)))

    def test_outside_hours_never_books(self):
        self.send('Quiero una cita mañana a las 10 pm')
        self.assertIsNone(self.db.scalar(select(Appointment)))

    def test_explicit_service_overrides_default(self):
        self.send('Quiero limpieza mañana a las 4 pm')
        self.assertEqual(self.db.scalar(select(Appointment)).service_key, 'limpieza')

    def test_required_fields_preserve_qualification(self):
        spec = copy.deepcopy(self.tenant.workflow_spec)
        spec['direct_booking']['required_fields'] = ['nombre']
        self.tenant.workflow_spec = spec
        self.send('Quiero una cita mañana a las 4 pm')
        self.assertIsNone(self.db.scalar(select(Appointment)))
        self.assertIn('nombre', self.last_reply())

    def test_urgency_wins_over_direct_booking(self):
        spec = copy.deepcopy(self.tenant.workflow_spec)
        spec['steps'].append({'key': 'urgencia', 'prompt': 'Urgencia', 'kind': 'choice', 'choices': ['Sí', 'No']})
        spec['handoff_rules'] = [{'field': 'urgencia', 'values': ['Sí'], 'message': 'Recepción continuará contigo.'}]
        self.tenant.workflow_spec = spec
        self.send('Quiero una cita mañana a las 4 pm, tengo mucho dolor')
        self.assertEqual(self.lead().status, 'human_handoff')
        self.assertIsNone(self.db.scalar(select(Appointment)))
