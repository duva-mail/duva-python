import base64

import pytest

from duva.attachments import Attachment, assert_attachment_limits


def test_base64_encodes_the_bytes_and_defaults_content_type_and_id_to_none() -> None:
    attachment = Attachment.from_bytes("a.txt", b"hi")
    assert attachment.data == {
        "filename": "a.txt",
        "content": base64.b64encode(b"hi").decode(),
        "content_type": None,
        "content_id": None,
    }


def test_carries_an_explicit_content_type_and_inline_content_id() -> None:
    attachment = Attachment.from_bytes(
        "logo.png", bytes([1, 2, 3]), content_type="image/png", content_id="logo"
    )
    assert attachment.data["content_type"] == "image/png"
    assert attachment.data["content_id"] == "logo"


def test_refuses_a_filename_with_a_path() -> None:
    with pytest.raises(ValueError, match="path"):
        Attachment.from_bytes("../a.txt", b"")


def test_refuses_an_executable_extension() -> None:
    with pytest.raises(ValueError, match="executable"):
        Attachment.from_bytes("virus.exe", b"")


def test_accepts_a_message_within_the_limits() -> None:
    attachments = [Attachment.from_bytes("a.txt", b"hi")]
    assert_attachment_limits(attachments)  # does not raise


def test_refuses_more_than_10_attachments() -> None:
    attachments = [Attachment.from_bytes(f"a{i}.txt", b"") for i in range(11)]
    with pytest.raises(ValueError, match="at most 10"):
        assert_attachment_limits(attachments)


def test_refuses_more_than_5mb_decoded_in_total() -> None:
    big = Attachment.from_bytes("big.bin", b"\x00" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="limit"):
        assert_attachment_limits([big])
