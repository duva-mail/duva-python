"""Official Duva client library. See `README.md` for usage; `docs/api.md` (in the `duva`
repository) for the API this wraps.
"""

from __future__ import annotations

from duva._generated.models import (
    Event,
    Message,
    MessageAccepted,
    Recipient,
    Stats,
    StatsPeriod,
    Suppression,
    Tracking,
    Webhook,
    WebhookDelivery,
    WebhookDeliveryList,
    WebhookList,
)
from duva.address import format_address, unsubscribe_headers
from duva.attachments import Attachment, AttachmentInput
from duva.client import (
    AsyncDuva,
    Duva,
    EventPage,
    Granularity,
    SendMessageResult,
    SuppressionPage,
)
from duva.errors import (
    AuthenticationError,
    ConflictError,
    DuvaConnectionError,
    DuvaError,
    DuvaTimeoutError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionError_,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    ValidationError,
    WebhookSignatureError,
)
from duva.webhooks import (
    WebhookEvent,
    construct_event,
    sign_webhook_request,
    verify_webhook_signature,
)

__version__ = "0.1.0"

__all__ = [
    "AsyncDuva",
    "Attachment",
    "AttachmentInput",
    "AuthenticationError",
    "ConflictError",
    "Duva",
    "DuvaConnectionError",
    "DuvaError",
    "DuvaTimeoutError",
    "Event",
    "EventPage",
    "Granularity",
    "Message",
    "MessageAccepted",
    "NotFoundError",
    "PayloadTooLargeError",
    "PermissionError_",
    "QuotaExceededError",
    "RateLimitError",
    "Recipient",
    "SendMessageResult",
    "ServerError",
    "Stats",
    "StatsPeriod",
    "Suppression",
    "SuppressionPage",
    "Tracking",
    "ValidationError",
    "Webhook",
    "WebhookDelivery",
    "WebhookDeliveryList",
    "WebhookEvent",
    "WebhookList",
    "WebhookSignatureError",
    "__version__",
    "construct_event",
    "format_address",
    "sign_webhook_request",
    "unsubscribe_headers",
    "verify_webhook_signature",
]
