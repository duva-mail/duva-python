"""HTTP transport: builds requests, applies the retry policy of
`docs/bibliotheques-clientes.md` section 3.5 (in the `duva` repository) exactly, and turns a Duva
error response into the right :class:`DuvaError` subclass. Sync and async share every pure piece
of logic (building the request, deciding whether to retry); only the actual I/O differs.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from duva.errors import (
    DuvaConnectionError,
    DuvaError,
    DuvaTimeoutError,
    RateLimitError,
    ServerError,
    error_from_response,
)

_PACKAGE_VERSION = "0.1.0"
_DEFAULT_BASE_URL = "https://api.duva.ca"


@dataclass(frozen=True, slots=True)
class ClientConfig:
    api_key: str
    domain: str
    base_url: str = _DEFAULT_BASE_URL
    timeout: float = 10.0
    max_retries: int = 2
    max_retry_wait_seconds: float = 30.0
    language: Literal["en", "fr"] | None = None
    user_agent: str | None = None

    @staticmethod
    def resolve(
        api_key: str | None = None,
        domain: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 2,
        max_retry_wait_seconds: float = 30.0,
        language: Literal["en", "fr"] | None = None,
        user_agent: str | None = None,
    ) -> ClientConfig:
        resolved_key = api_key or os.environ.get("DUVA_API_KEY")
        resolved_domain = domain or os.environ.get("DUVA_DOMAIN")
        if not resolved_key:
            raise TypeError("Duva: an API key is required (api_key= or DUVA_API_KEY)")
        if not resolved_domain:
            raise TypeError("Duva: a domain is required (domain= or DUVA_DOMAIN)")
        clean_base_url = base_url.rstrip("/")
        if not clean_base_url.startswith("https://") and "localhost" not in clean_base_url:
            raise TypeError(
                "Duva: base_url must be https:// (http://localhost is allowed for tests)"
            )
        return ClientConfig(
            resolved_key,
            resolved_domain,
            clean_base_url,
            timeout,
            max_retries,
            max_retry_wait_seconds,
            language,
            user_agent,
        )

    @property
    def domain_path(self) -> str:
        """The path prefix for this client's domain (`/v1/<domain>`)."""
        from urllib.parse import quote

        return f"/v1/{quote(self.domain, safe='')}"

    def user_agent_header(self) -> str:
        extra = f" {self.user_agent}" if self.user_agent else ""
        return f"duva-python/{_PACKAGE_VERSION}{extra}"


@dataclass(frozen=True, slots=True)
class RequestSpec:
    method: Literal["GET", "POST", "DELETE"]
    path: str
    query: dict[str, str | int | None] | None = None
    body: Any = None
    idempotency_key: str | None = None
    #: Whether the WHOLE call may be retried after a network failure or a `5xx` (distinct from the
    #: per-error-code `Retry-After` policy, which always applies): `False` for a write whose
    #: outcome, after a timeout, is unknown (see `docs/bibliotheques-clientes.md` section 3.5).
    safe_retry: bool = False


@dataclass(frozen=True, slots=True)
class RawResponse:
    data: Any
    headers: httpx.Headers


def build_httpx_request(config: ClientConfig, spec: RequestSpec) -> dict[str, Any]:
    """The keyword arguments for `httpx.Client.request` / `httpx.AsyncClient.request`."""
    headers = {
        "authorization": f"Bearer {config.api_key}",
        "user-agent": config.user_agent_header(),
    }
    if config.language:
        headers["accept-language"] = config.language
    if spec.idempotency_key:
        headers["idempotency-key"] = spec.idempotency_key
    kwargs: dict[str, Any] = {
        "method": spec.method,
        "url": config.base_url + spec.path,
        "headers": headers,
        "params": {k: v for k, v in (spec.query or {}).items() if v is not None},
    }
    if spec.body is not None:
        headers["content-type"] = "application/json"
        kwargs["content"] = json.dumps(spec.body).encode()
    return kwargs


def parse_response(response: httpx.Response) -> RawResponse:
    """Returns the parsed body, or raises the right :class:`DuvaError`."""
    if response.status_code == 204:
        return RawResponse(None, response.headers)
    if 200 <= response.status_code < 300:
        return RawResponse(None if not response.content else response.json(), response.headers)
    try:
        parsed = response.json() if response.content else None
    except ValueError:
        parsed = None
    raise error_from_response(
        response.status_code, parsed, response.text, response.headers.get("retry-after")
    )


def retry_delay_seconds(
    error: BaseException, spec: RequestSpec, attempt: int, config: ClientConfig
) -> float | None:
    """`None` = do not retry (re-raise); a number = wait this many seconds, then retry."""
    if isinstance(error, RateLimitError):
        if error.retry_after > config.max_retry_wait_seconds:
            return None
        return float(error.retry_after)
    if isinstance(error, DuvaError) and not isinstance(error, ServerError):
        return None  # a QuotaExceededError (has retry_after too) is never retried automatically
    is_transient = isinstance(error, DuvaConnectionError | DuvaTimeoutError | ServerError)
    if not is_transient or not spec.safe_retry or attempt >= config.max_retries:
        return None
    return _backoff_seconds(attempt)


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter, capped: never a fixed delay, never unbounded."""
    base = min(0.5 * 2.0**attempt, 8.0)  # 2.0, not 2: int.__pow__'s overloads make `int**int`
    # resolve to `Any` in mypy strict mode unless the exponent is a literal.
    return base / 2 + random.random() * (base / 2)  # noqa: S311 (jitter, not cryptographic)


def wrap_transport_error(exc: httpx.TimeoutException | httpx.TransportError) -> Exception:
    if isinstance(exc, httpx.TimeoutException):
        return DuvaTimeoutError(f"Duva: request timed out: {exc}")
    return DuvaConnectionError(f"Duva: the request could not be sent: {exc}")


class Transport:
    """Synchronous transport, backed by one `httpx.Client` reused across calls."""

    def __init__(self, config: ClientConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=config.timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def request(self, spec: RequestSpec) -> RawResponse:
        attempt = 0
        while True:
            try:
                response = self._client.request(**build_httpx_request(self._config, spec))
                return parse_response(response)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error: Exception = wrap_transport_error(exc)
            except DuvaError as exc:
                error = exc
            wait = retry_delay_seconds(error, spec, attempt, self._config)
            if wait is None:
                raise error
            attempt += 1
            time.sleep(wait)


class AsyncTransport:
    """Asynchronous transport, backed by one `httpx.AsyncClient` reused across calls."""

    def __init__(self, config: ClientConfig, client: httpx.AsyncClient | None = None) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def request(self, spec: RequestSpec) -> RawResponse:
        import asyncio

        attempt = 0
        while True:
            try:
                response = await self._client.request(**build_httpx_request(self._config, spec))
                return parse_response(response)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error: Exception = wrap_transport_error(exc)
            except DuvaError as exc:
                error = exc
            wait = retry_delay_seconds(error, spec, attempt, self._config)
            if wait is None:
                raise error
            attempt += 1
            await asyncio.sleep(wait)
