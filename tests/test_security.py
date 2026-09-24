import hashlib
import hmac
import unittest

from app.core.security import verify_meta_signature


class SignatureTests(unittest.TestCase):
    def test_valid_signature(self):
        secret = "top-secret"
        body = b'{"hello":"world"}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        header = f"sha256={digest}"
        self.assertTrue(verify_meta_signature(body, header, secret))

    def test_invalid_signature(self):
        self.assertFalse(
            verify_meta_signature(b"payload", "sha256=deadbeef", "top-secret")
        )


if __name__ == "__main__":
    unittest.main()
