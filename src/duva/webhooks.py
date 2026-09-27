"""Webhook signature verification, "Standard Webhooks" format (see `docs/api.md` "Webhooks" in the
`duva` repository). Duva SENDS webhooks; this module is for VERIFYING them on your side.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from duva.errors import WebhookSignatureError

_SECRET_PREFIX = "whsec_"
_DEFAULT_TOLERANCE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """The JSON body Duva sends to your webhook URL, already parsed."""

    id: str
    type: str
    domain: str
    data: dict[str, Any]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive lookup: whatever your framework hands you (a plain `dict`, an
    `httpx.Headers`-like mapping...) is not guaranteed to have lower-case keys."""
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _decode_secret(secret: str) -> bytes:
    if not secret.startswith(_SECRET_PREFIX):
        raise WebhookSignatureError("a Duva webhook secret starts with whsec_")
    return base64.b64decode(secret[len(_SECRET_PREFIX) :])


def _expected_signature(secret: str, event_id: str, timestamp: str, raw_body: bytes) -> str:
    signed = f"{event_id}.{timestamp}.".encode() + raw_body
    digest = hmac.new(_decode_secret(secret), signed, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_webhook_signature(
    secrets: str | Sequence[str],
    headers: Mapping[str, str],
    raw_body: bytes | str,
    *,
    tolerance_seconds: int = _DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    """Verifies a webhook request. Accepts one secret or several at once (for key rotation: while
    both the old and the new secret are active, a webhook signed with either must verify).

    The raw, EXACT body Duva sent must be passed as-is: re-encoding a parsed-then-re-serialized
    JSON body changes its bytes and invalidates every signature (see your framework's raw-body
    option, documented per-framework in `docs/api.md`).

    `now`: the current instant as a Unix timestamp in seconds. Defaults to `time.time()`; override
    only in your OWN tests (see `sign_webhook_request` and the fixtures of
    `duva-mail/duva-conformance`, which document the exact instant each vector was signed at).
    """
    event_id = _header(headers, "webhook-id")
    timestamp = _header(headers, "webhook-timestamp")
    signature_header = _header(headers, "webhook-signature")
    if not event_id or not timestamp or not signature_header:
        return False

    try:
        at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - at) > tolerance_seconds:
        return False

    body = raw_body.encode() if isinstance(raw_body, str) else raw_body
    secret_list = [secrets] if isinstance(secrets, str) else list(secrets)
    try:
        expected = [
            _expected_signature(secret, event_id, timestamp, body) for secret in secret_list
        ]
    except WebhookSignatureError:
        return False

    # `webhook-signature` may carry several space-separated `v1,<signature>` entries (Duva sends
    # one; a sender that itself rotates its OWN signing key mid-flight could send more): any match
    # against any of your active secrets is accepted.
    for part in signature_header.split(" "):
        version, _, signature = part.partition(",")
        if version != "v1" or not signature:
            continue
        for candidate in expected:
            if hmac.compare_digest(signature, candidate):
                return True
    return False


def construct_event(
    secrets: str | Sequence[str],
    headers: Mapping[str, str],
    raw_body: bytes | str,
    *,
    tolerance_seconds: int = _DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> WebhookEvent:
    """:func:`verify_webhook_signature`, then parses the body: raises
    :class:`WebhookSignatureError` on a bad signature rather than returning a boolean, for call
    sites that want to raise on failure. Never includes the secret or the raw body in the error."""
    if not verify_webhook_signature(
        secrets, headers, raw_body, tolerance_seconds=tolerance_seconds, now=now
    ):
        raise WebhookSignatureError("webhook signature verification failed")
    text = raw_body.decode() if isinstance(raw_body, bytes) else raw_body
    parsed = json.loads(text)
    return WebhookEvent(
        id=parsed["id"], type=parsed["type"], domain=parsed["domain"], data=parsed["data"]
    )


def sign_webhook_request(
    secret: str, event_id: str, body: str, timestamp: int | None = None
) -> dict[str, str]:
    """Builds a validly signed request FOR YOUR OWN TESTS: the headers a real Duva webhook
    delivery would carry for `body`, signed with `secret` as of `timestamp` (Unix seconds;
    defaults to now). Never used by the library itself to send anything: Duva is the only real
    sender."""
    at = timestamp if timestamp is not None else int(time.time())
    ts = str(at)
    signature = _expected_signature(secret, event_id, ts, body.encode())
    return {
        "content-type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{signature}",
    }
