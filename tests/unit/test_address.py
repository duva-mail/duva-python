import pytest

from duva.address import format_address, unsubscribe_headers


def test_returns_the_bare_address_without_a_name() -> None:
    assert format_address("a@example.com") == "a@example.com"


def test_wraps_a_name_around_the_address() -> None:
    assert format_address("a@example.com", "Example") == "Example <a@example.com>"


def test_quotes_and_escapes_a_name_containing_a_comma_or_a_quote() -> None:
    assert format_address("a@example.com", 'Some, "Name"') == '"Some, \\"Name\\"" <a@example.com>'


def test_builds_both_headers_for_one_click_unsubscribe_by_default() -> None:
    assert unsubscribe_headers(https_url="https://example.com/u") == {
        "List-Unsubscribe": "<https://example.com/u>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_combines_an_https_link_and_a_mailto_without_one_click_when_asked() -> None:
    assert unsubscribe_headers(
        https_url="https://example.com/u", mailto="stop@example.com", one_click=False
    ) == {"List-Unsubscribe": "<https://example.com/u>, <mailto:stop@example.com>"}


def test_a_mailto_only_unsubscribe_never_gets_list_unsubscribe_post() -> None:
    assert unsubscribe_headers(mailto="stop@example.com") == {
        "List-Unsubscribe": "<mailto:stop@example.com>"
    }


def test_raises_without_any_destination() -> None:
    with pytest.raises(ValueError, match="needs https_url"):
        unsubscribe_headers()


def test_raises_if_https_url_is_not_https() -> None:
    with pytest.raises(ValueError, match="https://"):
        unsubscribe_headers(https_url="http://example.com/u")


def test_raises_asking_for_one_click_without_an_https_link() -> None:
    with pytest.raises(ValueError, match="needs https_url"):
        unsubscribe_headers(mailto="stop@example.com", one_click=True)
