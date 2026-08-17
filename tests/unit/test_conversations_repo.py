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
    conv_id = conv_repo.create_conversation()
    try:
        conv_repo.add_message(conv_id, "bogus", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass


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
