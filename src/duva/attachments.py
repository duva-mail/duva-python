"""Attachment helpers. The server remains the authority on the limits below (they can change):
these are a courtesy, so a mistake fails locally instead of after an upload.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

# Mirrors `services/messages.py` in the `duva` repository at the time of writing: 10 attachments,
# 5 MB decoded in total, these extensions refused. Re-check against `docs/api.md` if this drifts.
MAX_ATTACHMENTS = 10
MAX_TOTAL_BYTES = 5 * 1024 * 1024
_FORBIDDEN_EXTENSIONS = frozenset(
    {".exe", ".bat", ".cmd", ".com", ".js", ".vbs", ".vbe", ".scr", ".msi", ".msp", ".ps1", ".jar"}
)


class AttachmentInput(TypedDict):
    filename: str
    content: str  # base64
    content_type: str | None
    content_id: str | None


def _assert_allowed_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename:
        raise ValueError(f"Duva: attachment filename must not contain a path: {filename}")
    if Path(filename).suffix.lower() in _FORBIDDEN_EXTENSIONS:
        raise ValueError(f"Duva: executable attachments are refused: {filename}")


@dataclass(frozen=True, slots=True)
class Attachment:
    data: AttachmentInput = field(repr=False)

    @staticmethod
    def from_bytes(
        filename: str,
        content: bytes,
        *,
        content_type: str | None = None,
        content_id: str | None = None,
    ) -> Attachment:
        """From raw bytes already in memory."""
        _assert_allowed_filename(filename)
        return Attachment(
            {
                "filename": filename,
                "content": base64.b64encode(content).decode(),
                "content_type": content_type,
                "content_id": content_id,
            }
        )

    @staticmethod
    def from_file(
        path: str | os.PathLike[str],
        *,
        content_type: str | None = None,
        content_id: str | None = None,
        filename: str | None = None,
    ) -> Attachment:
        """Reads a file from disk."""
        file_path = Path(path)
        return Attachment.from_bytes(
            filename or file_path.name,
            file_path.read_bytes(),
            content_type=content_type,
            content_id=content_id,
        )


def assert_attachment_limits(attachments: list[Attachment]) -> None:
    """Local, courtesy-only checks: at most :data:`MAX_ATTACHMENTS` attachments, at most
    :data:`MAX_TOTAL_BYTES` decoded in total. Raises `ValueError` when exceeded; the server
    re-checks regardless."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise ValueError(f"Duva: at most {MAX_ATTACHMENTS} attachments per message")
    total_bytes = sum(_decoded_length(a.data["content"]) for a in attachments)
    if total_bytes > MAX_TOTAL_BYTES:
        raise ValueError(
            f"Duva: attachments are {total_bytes} bytes decoded, over the {MAX_TOTAL_BYTES} limit"
        )


def _decoded_length(b64: str) -> int:
    padding = b64.count("=", -2)
    return (len(b64) * 3) // 4 - padding
