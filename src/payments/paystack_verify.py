from __future__ import annotations

import hmac
import hashlib


def verify_paystack_signature(secret_key: str, raw_body: bytes, signature: str | None) -> bool:
    """
    Verify Paystack webhook signature using HMAC SHA512
    """

    if not signature:
        return False

    expected = hmac.new(
        secret_key.encode(),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)