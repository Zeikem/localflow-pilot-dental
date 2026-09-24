import unittest

from app.services.webhook_parser import extract_inbound_messages


class WebhookParserTests(unittest.TestCase):
    def test_extracts_text_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "12345"},
                        "contacts": [{"wa_id": "5214770000000"}],
                        "messages": [{
                            "id": "wamid.TEST",
                            "from": "5214770000000",
                            "type": "text",
                            "text": {"body": "Hola"},
                        }],
                    }
                }]
            }]
        }

        messages = extract_inbound_messages(payload)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].phone_number_id, "12345")
        self.assertEqual(messages[0].text, "Hola")

    def test_ignores_status_only_payload(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "12345"},
                        "statuses": [{"id": "wamid.TEST", "status": "delivered"}],
                    }
                }]
            }]
        }
        self.assertEqual(extract_inbound_messages(payload), [])


if __name__ == "__main__":
    unittest.main()
