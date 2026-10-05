"""Synchronous (`Duva`) and asynchronous (`AsyncDuva`) clients, bound to one domain and its API
key. Both cover the same 13 operations; only the transport differs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from duva._generated import models
from duva._http import AsyncTransport, ClientConfig, RequestSpec, Transport
from duva.attachments import Attachment, assert_attachment_limits
from duva.pagination import paginate, paginate_async

EventType = Literal[
    "delivered", "bounced", "deferred", "expired", "complained", "opened", "clicked"
]
SuppressionReason = Literal["bounce", "unsubscribe", "complaint", "manual"]
Granularity = Literal["day", "hour"]


@dataclass(frozen=True, slots=True)
class SendMessageResult:
    id: str
    status: str
    #: `True` when this answer replays an earlier identical request (the `Idempotent-Replayed`
    #: response header).
    replayed: bool
    #: Address of the message (`GET /v1/{domain}/messages/{id}`), from the `Location` header.
    location: str | None


@dataclass(frozen=True, slots=True)
class EventPage:
    data: list[models.Event]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class SuppressionPage:
    data: list[models.Suppression]
    next_cursor: str | None


def _message_body(
    from_: str,
    to: list[str],
    subject: str,
    *,
    html: str | None = None,
    text: str | None = None,
    tags: list[str] | None = None,
    tracking: dict[str, bool] | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
    metadata: dict[str, str] | None = None,
    attachments: list[Attachment] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, object]:
    if attachments:
        assert_attachment_limits(attachments)
    body: dict[str, object] = {"from": from_, "to": to, "subject": subject}
    if cc is not None:
        body["cc"] = cc
    if bcc is not None:
        body["bcc"] = bcc
    if html is not None:
        body["html"] = html
    if text is not None:
        body["text"] = text
    if tags is not None:
        body["tags"] = tags
    if tracking is not None:
        body["tracking"] = {
            "opens": tracking.get("opens", False),
            "clicks": tracking.get("clicks", False),
        }
    if reply_to is not None:
        body["reply_to"] = reply_to
    if headers is not None:
        body["headers"] = headers
    if metadata is not None:
        body["metadata"] = metadata
    if attachments is not None:
        body["attachments"] = [dict(a.data) for a in attachments]
    return body


class Duva:
    """A synchronous Duva client.

    >>> duva = Duva(api_key="dv_...", domain="example.com")
    >>> message = duva.messages.send(
    ...     from_="Example <notifications@example.com>",
    ...     to=["client@example.org"],
    ...     subject="Your order",
    ...     text="Thank you for your order.",
    ... )
    """

    def __init__(
        self,
        api_key: str | None = None,
        domain: str | None = None,
        *,
        base_url: str = "https://api.duva.ca",
        timeout: float = 10.0,
        max_retries: int = 2,
        max_retry_wait_seconds: float = 30.0,
        language: Literal["en", "fr"] | None = None,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        config = ClientConfig.resolve(
            api_key, domain, base_url, timeout, max_retries, max_retry_wait_seconds,
            language, user_agent,
        )  # fmt: skip
        self._transport = Transport(config, http_client)
        self.messages = _Messages(self._transport, config)
        self.events = _Events(self._transport, config)
        self.suppressions = _Suppressions(self._transport, config)
        self.webhooks = _Webhooks(self._transport, config)
        self.stats = _Stats(self._transport, config)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> Duva:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def health(self) -> dict[str, str]:
        """`GET /health`, without authentication: `{"status": "ok"}` when the service works.
        Raises `ServerError` on a `503` (its database is unreachable)."""
        result = self._transport.request(RequestSpec("GET", "/health", safe_retry=True))
        return dict(result.data)


class _Messages:
    def __init__(self, transport: Transport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    def send(
        self, from_: str, to: list[str], subject: str, *, idempotency_key: str | None = None,
        **fields: object,
    ) -> SendMessageResult:  # fmt: skip
        """Accepts a message for delivery. Always asynchronous: `queued` never confirms a
        delivery, only that the message was validated. Read the outcome with `messages.get`,
        `events.list`, or a webhook.

        `idempotency_key`: unique per domain. A UUID is generated when omitted (see
        `docs/bibliotheques-clientes.md` section 3.3): a network-level retry of the SAME call can
        then never create a duplicate message, but two separate calls each get their own random
        key, so they are NOT deduplicated against each other; pass your own stable key for that
        (e.g. an order id).

        `to`, `cc` and `bcc` take addresses or `Name <address>`; they count together against the
        plan's recipient maximum. Every copy shows all the `to` and all the `cc`; a `bcc` address
        appears only on its own copy.
        """
        body = _message_body(from_, to, subject, **fields)  # type: ignore[arg-type]
        key = idempotency_key or str(uuid.uuid4())
        result = self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/messages", body=body,
                idempotency_key=key, safe_retry=True,
            )
        )  # fmt: skip
        accepted = models.MessageAccepted.model_validate(result.data)
        return SendMessageResult(
            id=accepted.id,
            status=accepted.status,
            replayed=result.headers.get("idempotent-replayed") == "true",
            location=result.headers.get("location"),
        )

    def get(self, id: str) -> models.Message:
        """The message's status and each recipient's status."""
        result = self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/messages/{id}", safe_retry=True)
        )
        return models.Message.model_validate(result.data)


class _Events:
    def __init__(self, transport: Transport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    def list(
        self,
        *,
        message_id: str | None = None,
        type: EventType | None = None,
        recipient: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> EventPage:
        """One page of delivery events, most recent first."""
        result = self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/events",
                query={
                    "message_id": message_id, "type": type, "recipient": recipient,
                    "since": since.isoformat() if since else None, "limit": limit, "cursor": cursor,
                },
                safe_retry=True,
            )
        )  # fmt: skip
        page = models.EventPage.model_validate(result.data)
        return EventPage(page.data, page.next_cursor)

    def list_all(
        self,
        *,
        message_id: str | None = None,
        type: EventType | None = None,
        recipient: str | None = None,
        since: datetime | None = None,
        max_items: int | None = None,
    ) -> Iterator[models.Event]:
        """Every delivery event, most recent first, following `next_cursor` automatically."""
        return paginate(
            lambda cursor: self.list(
                message_id=message_id, type=type, recipient=recipient, since=since, cursor=cursor
            ),
            max_items=max_items,
        )


class _Suppressions:
    def __init__(self, transport: Transport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    def list(
        self,
        *,
        reason: SuppressionReason | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> SuppressionPage:
        """One page of suppressed addresses, most recent first."""
        result = self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/suppressions",
                query={"reason": reason, "limit": limit, "cursor": cursor},
                safe_retry=True,
            )
        )  # fmt: skip
        page = models.SuppressionPage.model_validate(result.data)
        return SuppressionPage(page.data, page.next_cursor)

    def list_all(
        self, *, reason: SuppressionReason | None = None, max_items: int | None = None
    ) -> Iterator[models.Suppression]:
        """Every suppressed address, most recent first, following `next_cursor` automatically."""
        return paginate(lambda cursor: self.list(reason=reason, cursor=cursor), max_items=max_items)

    def add(self, email: str) -> models.Suppression:
        """Adds an address by hand (reason `manual`): it receives nothing more from this domain.
        Naturally idempotent: adding an already-suppressed address changes nothing."""
        result = self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/suppressions",
                body={"email": email}, safe_retry=False,
            )
        )  # fmt: skip
        return models.Suppression.model_validate(result.data)

    def remove(self, email: str) -> None:
        """Removes an address from the list: it may receive mail again. Raises `NotFoundError`
        if it was not on the list."""
        from urllib.parse import quote

        self._transport.request(
            RequestSpec(
                "DELETE", f"{self._config.domain_path}/suppressions/{quote(email, safe='')}",
                safe_retry=False,
            )
        )  # fmt: skip


class _Webhooks:
    def __init__(self, transport: Transport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    def create(self, url: str, events: list[EventType] | None = None) -> models.Webhook:
        """Registers an endpoint. The response carries the signing `secret` (`whsec_...`): shown
        ONCE, store it to verify signatures. Each call creates a DISTINCT endpoint, never retried
        automatically."""
        result = self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/webhooks",
                body={"url": url, "events": events or []}, safe_retry=False,
            )
        )  # fmt: skip
        return models.Webhook.model_validate(result.data)

    def list(self) -> Sequence[models.Webhook]:
        result = self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/webhooks", safe_retry=True)
        )
        return models.WebhookList.model_validate(result.data).data

    def get(self, id: str) -> models.Webhook:
        result = self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/webhooks/{id}", safe_retry=True)
        )
        return models.Webhook.model_validate(result.data)

    def delete(self, id: str) -> None:
        self._transport.request(
            RequestSpec("DELETE", f"{self._config.domain_path}/webhooks/{id}", safe_retry=False)
        )

    def deliveries(self, id: str, *, limit: int | None = None) -> Sequence[models.WebhookDelivery]:
        """The latest deliveries of this endpoint (`limit`: 1 to 100, 50 by default)."""
        result = self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/webhooks/{id}/deliveries",
                query={"limit": limit}, safe_retry=True,
            )
        )  # fmt: skip
        return models.WebhookDeliveryList.model_validate(result.data).data


class _Stats:
    def __init__(self, transport: Transport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    def get(
        self,
        *,
        granularity: Granularity | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> models.Stats:
        """Counters of the domain by period (UTC). Defaults to the last 30 days (or 24 hours, by
        hour). At most 366 days, or 7 days by hour."""
        result = self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/stats",
                query={
                    "granularity": granularity,
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                },
                safe_retry=True,
            )
        )  # fmt: skip
        return models.Stats.model_validate(result.data)


class AsyncDuva:
    """An asynchronous Duva client, mirroring :class:`Duva` operation for operation.

    >>> duva = AsyncDuva(api_key="dv_...", domain="example.com")
    >>> message = await duva.messages.send(
    ...     from_="Example <notifications@example.com>",
    ...     to=["client@example.org"],
    ...     subject="Your order",
    ...     text="Thank you for your order.",
    ... )
    """

    def __init__(
        self,
        api_key: str | None = None,
        domain: str | None = None,
        *,
        base_url: str = "https://api.duva.ca",
        timeout: float = 10.0,
        max_retries: int = 2,
        max_retry_wait_seconds: float = 30.0,
        language: Literal["en", "fr"] | None = None,
        user_agent: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        config = ClientConfig.resolve(
            api_key, domain, base_url, timeout, max_retries, max_retry_wait_seconds,
            language, user_agent,
        )  # fmt: skip
        self._transport = AsyncTransport(config, http_client)
        self.messages = _AsyncMessages(self._transport, config)
        self.events = _AsyncEvents(self._transport, config)
        self.suppressions = _AsyncSuppressions(self._transport, config)
        self.webhooks = _AsyncWebhooks(self._transport, config)
        self.stats = _AsyncStats(self._transport, config)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncDuva:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def health(self) -> dict[str, str]:
        """`GET /health`, without authentication: `{"status": "ok"}` when the service works.
        Raises `ServerError` on a `503` (its database is unreachable)."""
        result = await self._transport.request(RequestSpec("GET", "/health", safe_retry=True))
        return dict(result.data)


class _AsyncMessages:
    def __init__(self, transport: AsyncTransport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    async def send(
        self, from_: str, to: list[str], subject: str, *, idempotency_key: str | None = None,
        **fields: object,
    ) -> SendMessageResult:  # fmt: skip
        """See :meth:`_Messages.send`."""
        body = _message_body(from_, to, subject, **fields)  # type: ignore[arg-type]
        key = idempotency_key or str(uuid.uuid4())
        result = await self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/messages", body=body,
                idempotency_key=key, safe_retry=True,
            )
        )  # fmt: skip
        accepted = models.MessageAccepted.model_validate(result.data)
        return SendMessageResult(
            id=accepted.id,
            status=accepted.status,
            replayed=result.headers.get("idempotent-replayed") == "true",
            location=result.headers.get("location"),
        )

    async def get(self, id: str) -> models.Message:
        """The message's status and each recipient's status."""
        result = await self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/messages/{id}", safe_retry=True)
        )
        return models.Message.model_validate(result.data)


class _AsyncEvents:
    def __init__(self, transport: AsyncTransport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    async def list(
        self,
        *,
        message_id: str | None = None,
        type: EventType | None = None,
        recipient: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> EventPage:
        """One page of delivery events, most recent first."""
        result = await self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/events",
                query={
                    "message_id": message_id, "type": type, "recipient": recipient,
                    "since": since.isoformat() if since else None, "limit": limit, "cursor": cursor,
                },
                safe_retry=True,
            )
        )  # fmt: skip
        page = models.EventPage.model_validate(result.data)
        return EventPage(page.data, page.next_cursor)

    def list_all(
        self,
        *,
        message_id: str | None = None,
        type: EventType | None = None,
        recipient: str | None = None,
        since: datetime | None = None,
        max_items: int | None = None,
    ) -> AsyncIterator[models.Event]:
        """Every delivery event, most recent first, following `next_cursor` automatically."""
        return paginate_async(
            lambda cursor: self.list(
                message_id=message_id, type=type, recipient=recipient, since=since, cursor=cursor
            ),
            max_items=max_items,
        )


class _AsyncSuppressions:
    def __init__(self, transport: AsyncTransport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    async def list(
        self,
        *,
        reason: SuppressionReason | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> SuppressionPage:
        """One page of suppressed addresses, most recent first."""
        result = await self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/suppressions",
                query={"reason": reason, "limit": limit, "cursor": cursor},
                safe_retry=True,
            )
        )  # fmt: skip
        page = models.SuppressionPage.model_validate(result.data)
        return SuppressionPage(page.data, page.next_cursor)

    def list_all(
        self, *, reason: SuppressionReason | None = None, max_items: int | None = None
    ) -> AsyncIterator[models.Suppression]:
        """Every suppressed address, most recent first, following `next_cursor` automatically."""
        return paginate_async(
            lambda cursor: self.list(reason=reason, cursor=cursor), max_items=max_items
        )

    async def add(self, email: str) -> models.Suppression:
        """Adds an address by hand (reason `manual`): it receives nothing more from this domain.
        Naturally idempotent: adding an already-suppressed address changes nothing."""
        result = await self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/suppressions",
                body={"email": email}, safe_retry=False,
            )
        )  # fmt: skip
        return models.Suppression.model_validate(result.data)

    async def remove(self, email: str) -> None:
        """Removes an address from the list: it may receive mail again. Raises `NotFoundError`
        if it was not on the list."""
        from urllib.parse import quote

        await self._transport.request(
            RequestSpec(
                "DELETE", f"{self._config.domain_path}/suppressions/{quote(email, safe='')}",
                safe_retry=False,
            )
        )  # fmt: skip


class _AsyncWebhooks:
    def __init__(self, transport: AsyncTransport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    async def create(self, url: str, events: list[EventType] | None = None) -> models.Webhook:
        """Registers an endpoint. The response carries the signing `secret` (`whsec_...`): shown
        ONCE, store it to verify signatures. Each call creates a DISTINCT endpoint, never retried
        automatically."""
        result = await self._transport.request(
            RequestSpec(
                "POST", f"{self._config.domain_path}/webhooks",
                body={"url": url, "events": events or []}, safe_retry=False,
            )
        )  # fmt: skip
        return models.Webhook.model_validate(result.data)

    async def list(self) -> Sequence[models.Webhook]:
        result = await self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/webhooks", safe_retry=True)
        )
        return models.WebhookList.model_validate(result.data).data

    async def get(self, id: str) -> models.Webhook:
        result = await self._transport.request(
            RequestSpec("GET", f"{self._config.domain_path}/webhooks/{id}", safe_retry=True)
        )
        return models.Webhook.model_validate(result.data)

    async def delete(self, id: str) -> None:
        await self._transport.request(
            RequestSpec("DELETE", f"{self._config.domain_path}/webhooks/{id}", safe_retry=False)
        )

    async def deliveries(
        self, id: str, *, limit: int | None = None
    ) -> Sequence[models.WebhookDelivery]:
        """The latest deliveries of this endpoint (`limit`: 1 to 100, 50 by default)."""
        result = await self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/webhooks/{id}/deliveries",
                query={"limit": limit}, safe_retry=True,
            )
        )  # fmt: skip
        return models.WebhookDeliveryList.model_validate(result.data).data


class _AsyncStats:
    def __init__(self, transport: AsyncTransport, config: ClientConfig) -> None:
        self._transport, self._config = transport, config

    async def get(
        self,
        *,
        granularity: Granularity | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> models.Stats:
        """Counters of the domain by period (UTC). Defaults to the last 30 days (or 24 hours, by
        hour). At most 366 days, or 7 days by hour."""
        result = await self._transport.request(
            RequestSpec(
                "GET", f"{self._config.domain_path}/stats",
                query={
                    "granularity": granularity,
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                },
                safe_retry=True,
            )
        )  # fmt: skip
        return models.Stats.model_validate(result.data)
