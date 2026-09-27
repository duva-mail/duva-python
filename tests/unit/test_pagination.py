from dataclasses import dataclass

import pytest

from duva.pagination import paginate, paginate_async


@dataclass(frozen=True, slots=True)
class _Page:
    data: list[int]
    next_cursor: str | None


def test_follows_next_cursor_until_none_without_an_extra_fetch() -> None:
    pages = [_Page([1, 2], "a"), _Page([3], "b"), _Page([4, 5], None)]
    seen_cursors: list[str | None] = []

    def fetch_page(cursor: str | None) -> _Page:
        seen_cursors.append(cursor)
        return pages[len(seen_cursors) - 1]

    items = list(paginate(fetch_page))
    assert items == [1, 2, 3, 4, 5]
    assert seen_cursors == [None, "a", "b"]


def test_a_single_empty_page_yields_nothing_and_fetches_only_once() -> None:
    calls = 0

    def fetch_page(_cursor: str | None) -> _Page:
        nonlocal calls
        calls += 1
        return _Page([], None)

    assert list(paginate(fetch_page)) == []
    assert calls == 1


def test_max_items_stops_early_without_fetching_pages_it_does_not_need() -> None:
    calls = 0

    def fetch_page(cursor: str | None) -> _Page:
        nonlocal calls
        calls += 1
        return _Page([1, 2, 3], None if cursor == "used" else "used")

    items = list(paginate(fetch_page, max_items=2))
    assert items == [1, 2]
    assert calls == 1  # the first page's third item is never needed


@pytest.mark.asyncio
async def test_async_follows_next_cursor_until_none() -> None:
    pages = [_Page([1, 2], "a"), _Page([3], "b"), _Page([4, 5], None)]
    seen_cursors: list[str | None] = []

    async def fetch_page(cursor: str | None) -> _Page:
        seen_cursors.append(cursor)
        return pages[len(seen_cursors) - 1]

    items = [item async for item in paginate_async(fetch_page)]
    assert items == [1, 2, 3, 4, 5]
    assert seen_cursors == [None, "a", "b"]


@pytest.mark.asyncio
async def test_async_max_items_stops_early() -> None:
    async def fetch_page(cursor: str | None) -> _Page:
        return _Page([1, 2, 3], None if cursor == "used" else "used")

    items = [item async for item in paginate_async(fetch_page, max_items=2)]
    assert items == [1, 2]
