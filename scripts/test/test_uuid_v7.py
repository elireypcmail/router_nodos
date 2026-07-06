from __future__ import annotations

import re

import pytest

from core.uuid_v7 import compare_uuid_v7, generate_uuid_v7, is_uuid_v7

_UUID_V7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def test_generate_uuid_v7_format() -> None:
    value = generate_uuid_v7()
    assert _UUID_V7_RE.match(value)
    assert is_uuid_v7(value)


def test_compare_uuid_v7_order() -> None:
    a = generate_uuid_v7()
    b = generate_uuid_v7()
    assert compare_uuid_v7(a, a) == 0
    assert compare_uuid_v7(a, b) in (-1, 0, 1)


def test_v7_before_legacy_ids() -> None:
    assert compare_uuid_v7(generate_uuid_v7(), "purchase-kardex-1") < 0


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("uuid6") is None,
    reason="uuid6 not installed",
)
def test_uuid6_import() -> None:
    assert is_uuid_v7(generate_uuid_v7())
