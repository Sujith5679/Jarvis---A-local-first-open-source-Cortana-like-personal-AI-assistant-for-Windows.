from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from llm.base import parse_retry_after_header


def test_none_returns_none():
    assert parse_retry_after_header(None) is None


def test_empty_string_returns_none():
    assert parse_retry_after_header("") is None


def test_plain_integer_seconds():
    assert parse_retry_after_header("30") == 30.0


def test_plain_float_seconds():
    assert parse_retry_after_header("2.5") == 2.5


def test_negative_value_clamped_to_zero():
    assert parse_retry_after_header("-5") == 0.0


def test_http_date_in_future():
    future = datetime.now(UTC) + timedelta(seconds=60)
    header = format_datetime(future, usegmt=True)
    result = parse_retry_after_header(header)
    assert result is not None
    assert 55 <= result <= 65  # allow a little slack for test execution time


def test_http_date_in_past_clamped_to_zero():
    past = datetime.now(UTC) - timedelta(seconds=60)
    header = format_datetime(past, usegmt=True)
    assert parse_retry_after_header(header) == 0.0


def test_garbage_value_returns_none():
    assert parse_retry_after_header("not a valid value at all") is None
