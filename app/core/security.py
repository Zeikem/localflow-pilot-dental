import hashlib
import hmac


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not app_secret or not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    expected = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    supplied = signature_header[len(prefix):]
    return hmac.compare_digest(expected, supplied)
