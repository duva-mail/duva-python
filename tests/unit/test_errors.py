from duva.errors import (
    AuthenticationError,
    ConflictError,
    DuvaError,
    NotFoundError,
    PermissionError_,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    ValidationError,
    error_from_response,
)


def test_maps_each_documented_code_to_its_class() -> None:
    cases: list[tuple[str, int, type[DuvaError]]] = [
        ("unauthorized", 401, AuthenticationError),
        ("not_found", 404, NotFoundError),
        ("domain_not_verified", 403, PermissionError_),
        ("sending_not_allowed", 403, PermissionError_),
        ("idempotency_conflict", 409, ConflictError),
        ("limit_reached", 409, ConflictError),
        ("invalid_request", 422, ValidationError),
        ("internal_error", 500, ServerError),
    ]
    for code, status, cls in cases:
        error = error_from_response(status, {"error": {"code": code, "message": "x"}}, "{}", None)
        assert isinstance(error, cls)
        assert error.code == code
        assert error.status == status


def test_carries_retry_after_for_quota_exceeded_and_rate_limited_only() -> None:
    quota = error_from_response(
        429, {"error": {"code": "quota_exceeded", "message": "x"}}, "{}", "3600"
    )
    assert isinstance(quota, QuotaExceededError)
    assert quota.retry_after == 3600

    rate = error_from_response(429, {"error": {"code": "rate_limited", "message": "x"}}, "{}", "5")
    assert isinstance(rate, RateLimitError)
    assert rate.retry_after == 5


def test_carries_field_errors_on_invalid_request() -> None:
    error = error_from_response(
        422,
        {
            "error": {
                "code": "invalid_request",
                "message": "x",
                "fields": [{"field": "to[0]", "message": "bad"}],
            }
        },
        "{}",
        None,
    )
    assert isinstance(error, ValidationError)
    assert error.fields == [{"field": "to[0]", "message": "bad"}]


def test_never_crashes_on_a_body_that_is_not_the_documented_envelope() -> None:
    error = error_from_response(502, "<html>bad gateway</html>", "<html>bad gateway</html>", None)
    assert isinstance(error, ServerError)
    assert error.code == "http_error"


def test_bounds_the_raw_body_it_keeps() -> None:
    huge = "x" * 10_000
    error = error_from_response(500, None, huge, None)
    assert len(error.raw_body) <= 4096


def test_an_unknown_code_falls_back_to_server_error() -> None:
    error = error_from_response(
        599, {"error": {"code": "something_new", "message": "x"}}, "{}", None
    )
    assert isinstance(error, ServerError)
    assert error.code == "something_new"
