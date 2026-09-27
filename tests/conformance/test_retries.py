"""Verified against `duva-mail/duva-conformance` (fetched by `scripts/fetch_conformance.py`,
never committed: see `.gitignore`). Run `uv run --extra dev python scripts/fetch_conformance.py`
first if `conformance/retries.json` is missing.
"""

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pydantic
import pytest

from duva.client import Duva
from duva.errors import DuvaConnectionError, DuvaError

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "conformance" / "retries.json"
pytestmark = pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="conformance/retries.json missing: run scripts/fetch_conformance.py",
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


def _cases() -> list[dict[str, Any]]:
    # Guards against `pytest.mark.parametrize` evaluating this at collection time, before the
    # module-level `skipif` above has a chance to apply.
    return _fixture()["cases"] if FIXTURE_PATH.exists() else []


CALL: dict[str, Callable[[Duva], object]] = {
    "sendMessage": lambda duva: duva.messages.send(
        from_="a@example.com", to=["b@example.org"], subject="s", text="t"
    ),
    "getMessage": lambda duva: duva.messages.get("msg_" + "a" * 32),
    "addSuppression": lambda duva: duva.suppressions.add("b@example.org"),
    "listEvents": lambda duva: duva.events.list(),
}


def _scripted_client(sequence: list[dict[str, Any]]) -> tuple[httpx.Client, list[int]]:
    """Serves the scripted `response_sequence` in order, one per call; `status: None` simulates a
    network failure (no response at all). `attempts[0]` counts how many attempts were actually
    made."""
    attempts = [0]

    def handler(_request: httpx.Request) -> httpx.Response:
        scripted = sequence[attempts[0]]
        attempts[0] += 1
        if scripted["status"] is None:
            raise httpx.ConnectError("simulated network failure")
        return httpx.Response(
            scripted["status"],
            headers=scripted.get("headers", {}),
            json=scripted.get("body"),
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), attempts


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_case(case: dict[str, Any]) -> None:
    http_client, attempts = _scripted_client(case["response_sequence"])
    duva = Duva(
        api_key="dv_test",
        domain="example.com",
        base_url="https://api.example.com",
        max_retries=case["max_retries"],
        max_retry_wait_seconds=case["max_retry_wait_seconds"],
        http_client=http_client,
    )
    call = CALL[case["operation_id"]]

    if case["expected_outcome"] == "success":
        # retries.json's success bodies are the same generic placeholder across every operation
        # (only the transport-level retry/error behavior is under test here, not response shape):
        # a real `listEvents` call returns a proper `EventPage`, this fixture's body just doesn't
        # shape-match it -- expected, not a failure.
        with contextlib.suppress(pydantic.ValidationError):
            call(duva)
    else:
        _, code = case["expected_outcome"].split(":")
        try:
            call(duva)
        except Exception as exc:  # noqa: BLE001 (re-raised as an assertion failure below)
            error: Exception | None = exc
        else:
            error = None
        assert error is not None, "expected a failure"
        if code == "server":
            assert isinstance(error, DuvaError | DuvaConnectionError)
        else:
            assert isinstance(error, DuvaError)
            assert error.code == code

    assert attempts[0] == case["expected_attempts"]
