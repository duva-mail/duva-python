"""Verified against `duva-mail/duva-conformance` (fetched by `scripts/fetch_conformance.py`,
never committed: see `.gitignore`). Run `uv run --extra dev python scripts/fetch_conformance.py`
first if `conformance/requests.json` is missing.
"""

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from duva.client import Duva

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "conformance" / "requests.json"
pytestmark = pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="conformance/requests.json missing: run scripts/fetch_conformance.py",
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


CALL: dict[str, Callable[[Duva, dict[str, Any]], object]] = {
    "sendMessage": lambda duva, i: duva.messages.send(
        from_=i["from_"],
        to=i["to"],
        subject=i["subject"],
        text=i.get("text"),
        tags=i.get("tags"),
        metadata=i.get("metadata"),
        idempotency_key=i.get("idempotency_key"),
    ),
    "addSuppression": lambda duva, i: duva.suppressions.add(i["email"]),
    "createWebhook": lambda duva, i: duva.webhooks.create(i["url"], i.get("events")),
    "getMessage": lambda duva, i: duva.messages.get(i["id"]),
    "removeSuppression": lambda duva, i: duva.suppressions.remove(i["email"]),
}


def _capturing_client() -> tuple[httpx.Client, list[httpx.Request]]:
    """Captures the single outgoing request instead of hitting the network. The response only
    needs to be well-formed enough for the call to run to completion; the ASSERTION is on what
    was SENT, so a downstream model-validation failure on this fake body is not the test's
    concern (see the broad `except` around each call, below)."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "x", "status": "queued", "data": []})

    return httpx.Client(transport=httpx.MockTransport(handler)), captured


def _cases() -> list[dict[str, Any]]:
    # Guards against `pytest.mark.parametrize` evaluating this at collection time, before the
    # module-level `skipif` above has a chance to apply.
    return _fixture()["cases"] if FIXTURE_PATH.exists() else []


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["operation_id"])
def test_case(case: dict[str, Any]) -> None:
    http_client, captured = _capturing_client()
    duva = Duva(
        api_key=case["input"]["api_key"],
        domain=case["input"]["domain"],
        base_url="https://api.example.com",
        http_client=http_client,
    )
    # See _capturing_client's docstring: only the request that was SENT matters here.
    with contextlib.suppress(Exception):
        CALL[case["operation_id"]](duva, case["input"])

    [request] = captured
    expected = case["expected_request"]
    assert request.method == expected["method"]
    # `.path` decodes percent-escapes (httpx normalizes it); `.raw_path` is what actually went on
    # the wire, which is what `expected_request.path` (itself percent-encoded) documents.
    assert request.url.raw_path.decode() == expected["path"]
    for name, value in expected["headers"].items():
        assert request.headers.get(name) == value
    if expected["body"] is None:
        assert request.content == b""
    else:
        assert json.loads(request.content) == expected["body"]


def test_covers_every_operation_the_generator_declares() -> None:
    fixture = _fixture()
    missing = [c["operation_id"] for c in fixture["cases"] if c["operation_id"] not in CALL]
    assert missing == []
