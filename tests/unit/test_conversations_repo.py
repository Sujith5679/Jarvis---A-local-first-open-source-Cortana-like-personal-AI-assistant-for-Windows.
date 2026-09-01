from __future__ import annotations

from storage.repositories import conversations as conv_repo


def test_create_conversation_and_add_messages(real_db):
    conv_id = conv_repo.create_conversation("Test chat")
    conv_repo.add_message(conv_id, "user", "hello")
    conv_repo.add_message(conv_id, "assistant", "hi there")

    messages = conv_repo.get_messages(conv_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert [m["content"] for m in messages] == ["hello", "hi there"]


def test_get_messages_respects_limit_and_order(real_db):
    conv_id = conv_repo.create_conversation()
    for i in range(5):
        conv_repo.add_message(conv_id, "user", f"msg {i}")

    limited = conv_repo.get_messages(conv_id, limit=2)
    assert [m["content"] for m in limited] == ["msg 3", "msg 4"]


def test_invalid_role_rejected(real_db):
    import pytest

    conv_id = conv_repo.create_conversation()
    with pytest.raises(ValueError):
        conv_repo.add_message(conv_id, "bogus", "x")


def test_to_llm_messages_excludes_tool_role(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "user", "hello")
    conv_repo.add_message(conv_id, "tool", "tool output")
    conv_repo.add_message(conv_id, "assistant", "hi")

    llm_messages = conv_repo.to_llm_messages(conv_repo.get_messages(conv_id))
    assert llm_messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_list_conversations_orders_by_updated_at_desc(real_db):
    first = conv_repo.create_conversation("first")
    second = conv_repo.create_conversation("second")
    conv_repo.add_message(first, "user", "bump updated_at")

    conversations = conv_repo.list_conversations()
    ids = [c["id"] for c in conversations]
    assert ids[0] == first  # most recently updated first
    assert second in ids


# --- Auto-titling (from the first user message) -----------------------------


def test_first_user_message_sets_title(real_db):
    conv_id = conv_repo.create_conversation()  # no title given
    conv_repo.add_message(conv_id, "user", "What's the capital of France?")

    conversation = conv_repo.get_conversation(conv_id)
    assert conversation["title"] == "What's the capital of France?"


def test_title_truncated_to_max_chars(real_db):
    from config.defaults import DEFAULT_CONVERSATION_TITLE_MAX_CHARS

    conv_id = conv_repo.create_conversation()
    long_message = "x" * (DEFAULT_CONVERSATION_TITLE_MAX_CHARS + 50)
    conv_repo.add_message(conv_id, "user", long_message)

    title = conv_repo.get_conversation(conv_id)["title"]
    assert len(title) == DEFAULT_CONVERSATION_TITLE_MAX_CHARS


def test_title_collapses_whitespace(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "user", "hello\n\nmultiline   message")

    title = conv_repo.get_conversation(conv_id)["title"]
    assert title == "hello multiline message"


def test_second_user_message_does_not_overwrite_title(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "user", "first message")
    conv_repo.add_message(conv_id, "user", "second message")

    assert conv_repo.get_conversation(conv_id)["title"] == "first message"


def test_explicit_title_is_not_overwritten_by_first_message(real_db):
    conv_id = conv_repo.create_conversation("My chosen title")
    conv_repo.add_message(conv_id, "user", "hello")

    assert conv_repo.get_conversation(conv_id)["title"] == "My chosen title"


def test_assistant_message_does_not_set_title(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "assistant", "How can I help?")

    assert conv_repo.get_conversation(conv_id)["title"] is None


def test_set_title_explicit_override(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "user", "original")
    conv_repo.set_title(conv_id, "Renamed")

    assert conv_repo.get_conversation(conv_id)["title"] == "Renamed"


# --- get_conversation / delete_conversation ---------------------------------


def test_get_conversation_missing_returns_none(real_db):
    assert conv_repo.get_conversation(999) is None


def test_delete_conversation_removes_it(real_db):
    conv_id = conv_repo.create_conversation()
    assert conv_repo.delete_conversation(conv_id) is True
    assert conv_repo.get_conversation(conv_id) is None


def test_delete_missing_conversation_returns_false(real_db):
    assert conv_repo.delete_conversation(999) is False


def test_delete_conversation_cascades_to_messages(real_db):
    conv_id = conv_repo.create_conversation()
    conv_repo.add_message(conv_id, "user", "hello")
    conv_repo.add_message(conv_id, "assistant", "hi")

    conv_repo.delete_conversation(conv_id)

    assert conv_repo.get_messages(conv_id) == []
