"""Cursor pagination, shared by `events.list_all` and `suppressions.list_all`: follows
`next_cursor` until it is `None`, without ever loading every page into memory at once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine, Iterator
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class Page(Protocol[T]):
    #: Read-only members (not plain attributes): a frozen dataclass's fields, which never allow
    #: assignment, still satisfy this — a mutable-attribute Protocol member would not.
    @property
    def data(self) -> list[T]: ...

    @property
    def next_cursor(self) -> str | None: ...


def paginate(
    fetch_page: Callable[[str | None], Page[T]], *, max_items: int | None = None
) -> Iterator[T]:
    cursor: str | None = None
    yielded = 0
    while True:
        page = fetch_page(cursor)
        for item in page.data:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return
        if page.next_cursor is None:
            return
        cursor = page.next_cursor


async def paginate_async(
    fetch_page: Callable[[str | None], Coroutine[Any, Any, Page[T]]],
    *,
    max_items: int | None = None,
) -> AsyncIterator[T]:
    cursor: str | None = None
    yielded = 0
    while True:
        page = await fetch_page(cursor)
        for item in page.data:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return
        if page.next_cursor is None:
            return
        cursor = page.next_cursor
