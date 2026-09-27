"""Verified against `duva-mail/duva-conformance` (fetched by `scripts/fetch_conformance.py`,
never committed: see `.gitignore`). Run `uv run --extra dev python scripts/fetch_conformance.py`
first if `conformance/webhooks.json` is missing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from duva.webhooks import verify_webhook_signature

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "conformance" / "webhooks.json"
pytestmark = pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="conformance/webhooks.json missing: run scripts/fetch_conformance.py",
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


def _now(fixture: dict[str, Any]) -> float:
    # A webhook signature expires by design (replay protection): it can only be replayed by
    # freezing the clock at the fixture's `reference_now`, never at the real wall-clock time.
    return datetime.fromisoformat(fixture["reference_now"]).astimezone(timezone.utc).timestamp()


def _non_rotation_cases(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in fixture["cases"] if c["category"] != "rotation"]


def _collected_non_rotation_cases() -> list[dict[str, Any]]:
    # Guards against `pytest.mark.parametrize` evaluating this at collection time, before the
    # module-level `skipif` above has a chance to apply.
    return _non_rotation_cases(_fixture()) if FIXTURE_PATH.exists() else []


@pytest.mark.parametrize("case", _collected_non_rotation_cases(), ids=lambda c: c["name"])
def test_case(case: dict[str, Any]) -> None:
    fixture = _fixture()
    # Always its OWN secret (the fixture's canonical one); `signed_with` is informational only:
    # it's exactly what a `wrong_secret` case distinguishes.
    got = verify_webhook_signature(
        fixture["secret"],
        case["headers"],
        case["body"],
        tolerance_seconds=fixture["tolerance_seconds"],
        now=_now(fixture),
    )
    assert got is case["expect"]


def test_covers_every_non_rotation_case() -> None:
    fixture = _fixture()
    assert len(_non_rotation_cases(fixture)) == len(fixture["cases"]) - 1


def test_a_rotation_vector_verifies_against_a_list_of_active_secrets() -> None:
    fixture = _fixture()
    [rotation] = [c for c in fixture["cases"] if c["category"] == "rotation"]
    # The active set during rotation: the current secret (`other_valid_secret`, == the top-level
    # `secret`) AND the older one that actually signed this webhook (`signed_with`).
    secrets = [rotation["other_valid_secret"], rotation["signed_with"]]
    got = verify_webhook_signature(
        secrets,
        rotation["headers"],
        rotation["body"],
        tolerance_seconds=fixture["tolerance_seconds"],
        now=_now(fixture),
    )
    assert got is rotation["expect"]


def test_the_current_secret_alone_is_not_enough() -> None:
    """Proof the rotation case truly needs the older secret too."""
    fixture = _fixture()
    [rotation] = [c for c in fixture["cases"] if c["category"] == "rotation"]
    now = _now(fixture)
    with_current_only = verify_webhook_signature(
        rotation["other_valid_secret"], rotation["headers"], rotation["body"], now=now
    )
    assert with_current_only is False
    # The point: a verifier must try the signer alone too, it doesn't know which one signed.
    with_the_signer_alone = verify_webhook_signature(
        rotation["signed_with"], rotation["headers"], rotation["body"], now=now
    )
    assert with_the_signer_alone is True
