import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.google_calendar import GoogleCalendarGateway, GoogleCalendarAPIError


class AvailabilityResponseTests(unittest.TestCase):
    def test_incomplete_responses_are_rejected(self):
        for response in (None, {'calendars': None}, {}, {'calendars': {}}, {'calendars': {'calendar': {}}},
                         {'calendars': {'calendar': {'busy': None}}}):
            with self.subTest(response=response):
                gateway = GoogleCalendarGateway(credentials_env='UNUSED')
                gateway._service = MagicMock()
                gateway._service.freebusy.return_value.query.return_value.execute.return_value = response
                start = datetime.now(timezone.utc)
                with self.assertRaises(GoogleCalendarAPIError):
                    gateway.busy(calendar_ids=['calendar'], start=start, end=start + timedelta(hours=1))

    def test_explicit_empty_busy_list_is_available(self):
        gateway = GoogleCalendarGateway(credentials_env='UNUSED')
        gateway._service = MagicMock()
        gateway._service.freebusy.return_value.query.return_value.execute.return_value = {
            'calendars': {'calendar': {'busy': []}}}
        start = datetime.now(timezone.utc)
        self.assertEqual(gateway.busy(calendar_ids=['calendar'], start=start,
                                     end=start + timedelta(hours=1)), {'calendar': []})
