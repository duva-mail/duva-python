"""Small formatting helpers matched to the API's own parsing rules (`docs/api.md`)."""

from __future__ import annotations

import re

_NEEDS_QUOTING = re.compile(r'[",]')


def format_address(email: str, name: str | None = None) -> str:
    """`Name <address>` (with `Name` quoted if it contains a `"` or `,`), or just `address`
    without a name."""
    if not name:
        return email
    escaped = name.replace(chr(34), chr(92) + chr(34))
    quoted = f'"{escaped}"' if _NEEDS_QUOTING.search(name) else name
    return f"{quoted} <{email}>"


def unsubscribe_headers(
    *,
    https_url: str | None = None,
    mailto: str | None = None,
    one_click: bool | None = None,
) -> dict[str, str]:
    """Builds `List-Unsubscribe` (and `List-Unsubscribe-Post` for one-click) exactly as the API
    validates them: at most 3 links, `https://` or `mailto:` only. Raises `ValueError` when
    neither `https_url` nor `mailto` is given.

    `one_click`: adds `List-Unsubscribe-Post` (RFC 8058). Defaults to `True` when `https_url` is
    given, `False` otherwise.
    """
    if not https_url and not mailto:
        raise ValueError("Duva: unsubscribe_headers needs https_url and/or mailto")
    if https_url and not https_url.startswith("https://"):
        raise ValueError("Duva: unsubscribe_headers.https_url must be an https:// link")
    resolved_one_click = one_click if one_click is not None else https_url is not None

    links = [f"<{link}>" for link in (https_url, f"mailto:{mailto}" if mailto else None) if link]
    headers = {"List-Unsubscribe": ", ".join(links)}
    if resolved_one_click:
        if not https_url:
            raise ValueError("Duva: one-click unsubscribe (List-Unsubscribe-Post) needs https_url")
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers
