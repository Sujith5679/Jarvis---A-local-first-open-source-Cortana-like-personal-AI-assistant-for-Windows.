from __future__ import annotations

from security.secrets import mask, scrub_secrets


def test_mask_none_and_empty():
    assert mask(None) == "<unset>"
    assert mask("") == "<empty>"


def test_mask_short_value_fully_hidden():
    assert mask("abc") == "***"


def test_mask_long_value_shows_partial():
    masked = mask("gsk_abcdef123456")
    assert masked.startswith("gsk_")
    assert masked.endswith("56")
    assert "abcdef" not in masked


def test_scrub_secrets_replaces_occurrences():
    text = "Request failed: Authorization Bearer gsk_supersecretkey123 was rejected"
    scrubbed = scrub_secrets(text, ["gsk_supersecretkey123"])
    assert "gsk_supersecretkey123" not in scrubbed
    assert "rejected" in scrubbed


def test_scrub_secrets_ignores_none_entries():
    text = "no secrets here"
    assert scrub_secrets(text, [None, ""]) == text


