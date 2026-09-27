"""Error hierarchy, mapped from `error.code` (the contract) rather than from the HTTP status or
the wording of `error.message`, which can change between languages and over time.

See `docs/bibliotheques-clientes.md` section 3.6 in the `duva` repository for the source table.
"""

from __future__ import annotations

from typing import Any


class DuvaError(Exception):
    """Base of every error raised for a request Duva actually answered (as opposed to a network
    failure: see :class:`DuvaConnectionError` and :class:`DuvaTimeoutError`)."""

    #: The HTTP status Duva answered with.
    status: int
    #: `error.code`: the contract. Rely on this, never on the exception message.
    code: str
    #: `error.fields`, when the error is a validation error (`code == "invalid_request"`).
    fields: list[dict[str, str]] | None
    #: The raw response body, bounded to 4 KB: never includes your API key.
    raw_body: str

    def __init__(self, status: int, code: str, message: str, raw_body: str,
                 fields: list[dict[str, str]] | None = None) -> None:  # fmt: skip
        super().__init__(message)
        self.status = status
        self.code = code
        self.fields = fields
        self.raw_body = raw_body[:4096]


class AuthenticationError(DuvaError):
    pass


class NotFoundError(DuvaError):
    pass


class PermissionError_(DuvaError):
    """`domain_not_verified` or `sending_not_allowed`. Named with a trailing underscore:
    `PermissionError` is a Python builtin, and shadowing it would confuse a `try/except`
    alongside the real one."""


class ConflictError(DuvaError):
    """`idempotency_conflict` or `limit_reached`."""


class PayloadTooLargeError(DuvaError):
    pass


class ValidationError(DuvaError):
    fields: list[dict[str, str]]

    def __init__(self, status: int, code: str, message: str, raw_body: str,
                 fields: list[dict[str, str]] | None = None) -> None:  # fmt: skip
        super().__init__(status, code, message, raw_body, fields)
        self.fields = fields or []


class QuotaExceededError(DuvaError):
    """A `429` on YOUR ACCOUNT quota (daily or monthly). `retry_after` can be hours: never retried
    automatically, by design (see `docs/bibliotheques-clientes.md` section 3.5)."""

    retry_after: int

    def __init__(self, status: int, code: str, message: str, raw_body: str,
                 fields: list[dict[str, str]] | None, retry_after: int) -> None:  # fmt: skip
        super().__init__(status, code, message, raw_body, fields)
        self.retry_after = retry_after


class RateLimitError(DuvaError):
    """A `429` from the per-key rate limit (unrelated to your sending quota). Retried automatically
    when `retry_after` fits within `max_retry_wait_seconds`."""

    retry_after: int

    def __init__(self, status: int, code: str, message: str, raw_body: str,
                 fields: list[dict[str, str]] | None, retry_after: int) -> None:  # fmt: skip
        super().__init__(status, code, message, raw_body, fields)
        self.retry_after = retry_after


class ServerError(DuvaError):
    """A `5xx`, or a response whose body was not the documented error envelope."""


class DuvaConnectionError(Exception):
    """No response was received at all (DNS, TLS, connection refused, connection reset...)."""


class DuvaTimeoutError(Exception):
    """The request exceeded `timeout` before any response arrived."""


class WebhookSignatureError(Exception):
    """A webhook signature failed to verify: never carries the secret or the raw body."""


_CODES: dict[str, type[DuvaError]] = {
    "unauthorized": AuthenticationError,
    "not_found": NotFoundError,
    "domain_not_verified": PermissionError_,
    "sending_not_allowed": PermissionError_,
    "idempotency_conflict": ConflictError,
    "limit_reached": ConflictError,
    "payload_too_large": PayloadTooLargeError,
    "invalid_request": ValidationError,
    "internal_error": ServerError,
    "method_not_allowed": ServerError,
    "http_error": ServerError,
}


def error_from_response(
    status: int, parsed_body: Any, raw_body: str, retry_after_header: str | None
) -> DuvaError:
    """Builds the right :class:`DuvaError` subclass from a parsed response body, or a generic
    :class:`ServerError` when the body does not match the documented envelope (a proxy error page,
    for instance): never raises itself."""
    code, message, fields = _as_error_body(parsed_body)
    retry_after = int(retry_after_header) if retry_after_header else 0
    if code == "quota_exceeded":
        return QuotaExceededError(status, code, message, raw_body, fields, retry_after)
    if code == "rate_limited":
        return RateLimitError(status, code, message, raw_body, fields, retry_after)
    error_class = _CODES.get(code, ServerError)
    return error_class(status, code, message, raw_body, fields)


def _as_error_body(value: Any) -> tuple[str, str, list[dict[str, str]] | None]:
    if (
        isinstance(value, dict)
        and isinstance(value.get("error"), dict)
        and isinstance(value["error"].get("code"), str)
    ):
        error = value["error"]
        return error["code"], error.get("message", ""), error.get("fields")
    return "http_error", "Duva answered with an unexpected body.", None
