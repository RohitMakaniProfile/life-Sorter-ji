"""
═══════════════════════════════════════════════════════════════
JUSPAY WEBHOOK SECURITY — HMAC-SHA256 Signature Verification
═══════════════════════════════════════════════════════════════
Implements JusPay's signed-response verification spec:
  1. Extract all key-value pairs (exclude signature & signature_algorithm)
  2. Percent-encode keys and values
  3. Sort alphabetically by encoded key (ASCII sort)
  4. Concatenate as key=value pairs joined by &
  5. Percent-encode the entire concatenated string
  6. HMAC-SHA256 with the Response Key
  7. Constant-time comparison against received signature
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import quote, unquote

import structlog

logger = structlog.get_logger()


def percent_encode(value: str) -> str:
    """
    RFC 3986 percent-encoding.
    Encodes all characters except unreserved chars (A-Z, a-z, 0-9, -, _, ., ~).
    """
    return quote(str(value), safe="")


def verify_juspay_signature(
    payload: dict,
    received_signature: str,
    response_key: str,
) -> bool:
    """
    Verify a JusPay webhook/return-URL signature using HMAC-SHA256.

    Args:
        payload: The full webhook payload as a dict (includes signature fields).
        received_signature: The 'signature' value from the payload (percent-encoded).
        response_key: Your JusPay Response Key from the dashboard.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        # Step 1: Remove signature fields from the payload
        filtered = {
            k: v
            for k, v in payload.items()
            if k not in ("signature", "signature_algorithm")
        }

        # Step 2: Percent-encode both keys and values
        encoded_pairs = [
            (percent_encode(k), percent_encode(str(v)))
            for k, v in filtered.items()
        ]

        # Step 3: Sort alphabetically by encoded key (ASCII sort)
        encoded_pairs.sort(key=lambda pair: pair[0])

        # Step 4: Concatenate as key=value pairs joined by &
        concatenated = "&".join(f"{k}={v}" for k, v in encoded_pairs)

        # Step 5: Percent-encode the entire concatenated string
        encoded_string = percent_encode(concatenated)

        # Step 6: Compute HMAC-SHA256
        computed_hmac = hmac.new(
            response_key.encode("utf-8"),
            encoded_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Step 7: Decode received signature (percent-decode once)
        decoded_signature = unquote(received_signature)

        # Step 8: Constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(computed_hmac, decoded_signature)

        if not is_valid:
            logger.warning(
                "JusPay signature verification failed",
                computed=computed_hmac[:16] + "...",
                received=decoded_signature[:16] + "...",
            )

        return is_valid

    except Exception as e:
        logger.error("JusPay signature verification error", error=str(e))
        return False
