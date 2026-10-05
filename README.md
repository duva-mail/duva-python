# Duva for Python

The official [Duva](https://duva.ca) client library for Python. Duva is a transactional email
API hosted in Canada.

```bash
pip install duva-mail
# or: uv add duva-mail
```

Requires Python 3.10 or later. Fully typed (`py.typed`); both a synchronous and an asynchronous
client are provided.

## Sending a message

```python
from duva import Duva

duva = Duva(api_key="dv_...", domain="example.com")  # or DUVA_API_KEY / DUVA_DOMAIN

message = duva.messages.send(
    from_="Example <notifications@example.com>",
    to=["client@example.org"],
    subject="Your order",
    text="Thank you for your order.",
)
print(message.id, message.status)  # "queued": always asynchronous
```

The same call, asynchronously:

```python
from duva import AsyncDuva

async with AsyncDuva(api_key="dv_...", domain="example.com") as duva:
    message = await duva.messages.send(
        from_="Example <notifications@example.com>",
        to=["client@example.org"],
        subject="Your order",
        text="Thank you for your order.",
    )
```

### To, Cc and Bcc

`to`, `cc` and `bcc` take addresses or `Name <address>`. Every copy shows all the `to` and all the
`cc`; a `bcc` address appears only on its own copy. The three lists together count against your
plan's recipient maximum.

```python
duva.messages.send(
    from_="Example <notifications@example.com>",
    to=["Jean Tremblay <jean@example.org>"],
    cc=["accounting@example.org"],
    bcc=["archive@example.com"],
    subject="Your order",
    text="Thank you for your order.",
)
```

## Reading events and pagination

```python
for event in duva.events.list_all(type="bounced"):
    print(event.type, event.detail.get("recipient"))
```

`events.list()` and `suppressions.list()` return one page (`.data`, `.next_cursor`);
`events.list_all()` and `suppressions.list_all()` are generators that follow `next_cursor` for
you, optionally bounded with `max_items=`. `AsyncDuva`'s equivalents (`list_all`) are async
generators (`async for`).

## Verifying a webhook

```python
from duva import WebhookSignatureError, construct_event

try:
    event = construct_event(secret, request.headers, raw_body)
    print(event.type, event.data.get("message_id"))
except WebhookSignatureError:
    # respond 400
    ...
```

`raw_body` must be the **exact bytes** Duva sent (your framework's raw-body option, not a
re-serialized parsed body): re-encoding it changes the bytes and invalidates the signature.
Rotating your webhook secret? Pass a list — `construct_event([old_secret, new_secret], ...)` —
while both are active.

## Errors

Every error Duva answers with is a `DuvaError` subclass; rely on `.code` (the contract), never on
the exception message (its wording can change):

```python
from duva import NotFoundError, QuotaExceededError, ValidationError

try:
    duva.messages.send(...)
except ValidationError as error:
    print(error.fields)  # [{"field": "to[0]", "message": "..."}]
except QuotaExceededError as error:
    print(f"retry in {error.retry_after}s")
except NotFoundError:
    ...  # the API key, domain or resource could not be found
```

Network failures and timeouts raise `DuvaConnectionError` / `DuvaTimeoutError` instead (no HTTP
response was ever received). Reads and `messages.send` (idempotency-key protected) are retried
automatically on a transient failure; `suppressions.add`/`remove` and `webhooks.create`/`delete`
are not, because the outcome of a timed-out first attempt is unknown. A `429 quota_exceeded` is
never retried automatically (its `retry_after` can be hours); a `429 rate_limited` is, as long as
the wait fits within `max_retry_wait_seconds` (30s by default).

## Attachments

```python
from duva import Attachment

attachment = Attachment.from_file("./invoice.pdf")
duva.messages.send(..., attachments=[attachment])
```

`Attachment.from_bytes(filename, content, content_type=None, content_id=None)` works from data
already in memory; `content_id` turns the attachment into an inline image the HTML references
with `cid:`.

## Configuration

| Argument | Default | |
|---|---|---|
| `api_key` | `DUVA_API_KEY` | Required. |
| `domain` | `DUVA_DOMAIN` | Required: the domain this key was created for. |
| `base_url` | `https://api.duva.ca` | |
| `timeout` | `10` (seconds) | |
| `max_retries` | `2` | Network failures / `5xx` on a safe-to-retry call. |
| `max_retry_wait_seconds` | `30` | A `429 rate_limited` with a longer wait is not retried. |
| `language` | unset | `"en"` or `"fr"`: the language of `error.message`. |
| `http_client` | a new `httpx.Client`/`AsyncClient` | Inject your own (proxying, tests). |

## Full reference

The complete API surface and the OpenAPI specification this library is generated from:
<https://duva.ca/en/docs> and <https://duva.ca/openapi.json>.

## Development

```bash
uv sync --extra dev
uv run --extra dev python scripts/generate.py --local  # regenerate _generated/models.py from a local ../duva checkout
uv run mypy
uv run pytest                                           # unit tests
uv run --extra dev python scripts/fetch_conformance.py && uv run pytest tests/conformance
uv build
```

This library's request/response models are generated from Duva's OpenAPI specification
(`src/duva/_generated/`, never edited by hand); the client itself (retries, pagination, errors,
webhooks) is hand-written and checked against the shared fixtures published in
[`duva-mail/duva-conformance`](https://github.com/duva-mail/duva-conformance).

## License

MIT, see [LICENSE](./LICENSE).
