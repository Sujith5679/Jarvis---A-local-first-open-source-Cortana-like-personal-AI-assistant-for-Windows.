from __future__ import annotations

import json

import pytest
from agent.graph import Agent
from llm.base import LLMResponse
from llm.manager import LLMManager
from storage.repositories import conversations as conv_repo
from storage.repositories import notes as notes_repo


class _ScriptedProvider:
    name = "scripted"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)

    async def generate(self, messages, tools=None):
        return self._responses.pop(0)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


@pytest.mark.asyncio
async def test_delete_note_pauses_for_confirmation_without_deleting(real_db):
    note_id = notes_repo.create_note(title="Keep me (for now)", content="content")

    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call("call_1", "delete_note", {"note_id": note_id})],
        ),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, f"Delete note {note_id}")

    assert state["requires_confirmation"] is True
    assert state["confirmation_request"]["tool"] == "delete_note"
    assert state["confirmation_request"]["arguments"] == {"note_id": note_id}
    assert state["response"] is None

    # Nothing was actually deleted, and no assistant message was persisted —
    # the turn is paused, not finished.
    assert notes_repo.get_note(note_id) is not None
    assert conv_repo.get_messages(conv_id) == [] or all(
        m["role"] != "assistant" for m in conv_repo.get_messages(conv_id)
    )


@pytest.mark.asyncio
async def test_confirm_and_execute_approved_deletes_note(real_db):
    note_id = notes_repo.create_note(title="Delete me", content="content")
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.confirm_and_execute(
        conv_id, "delete_note", {"note_id": note_id}, approved=True
    )

    assert state["error"] is None
    assert notes_repo.get_note(note_id) is None
    assert f"#{note_id}" in state["response"]

    persisted = conv_repo.get_messages(conv_id)
    assert len(persisted) == 1
    assert persisted[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_confirm_and_execute_denied_does_not_delete(real_db):
    note_id = notes_repo.create_note(title="Keep me", content="content")
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.confirm_and_execute(
        conv_id, "delete_note", {"note_id": note_id}, approved=False
    )

    assert notes_repo.get_note(note_id) is not None
    assert "won't run" in state["response"].lower()


@pytest.mark.asyncio
async def test_write_file_pauses_for_confirmation_without_writing(real_db, tmp_path):
    from storage.repositories import folders as folders_repo

    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))
    target = folder / "todo.txt"

    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[
                _tool_call(
                    "call_1", "write_file", {"path": str(target), "content": "buy milk"}
                )
            ],
        ),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "save this as todo.txt")

    assert state["requires_confirmation"] is True
    assert state["confirmation_request"]["tool"] == "write_file"
    assert not target.exists()  # nothing written yet


@pytest.mark.asyncio
async def test_confirm_and_execute_approved_writes_file(real_db, tmp_path):
    from storage.repositories import folders as folders_repo

    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))
    target = folder / "todo.txt"

    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.confirm_and_execute(
        conv_id, "write_file", {"path": str(target), "content": "buy milk"}, approved=True
    )

    assert state["error"] is None
    assert target.read_text(encoding="utf-8") == "buy milk"
    assert str(target) in state["response"]


@pytest.mark.asyncio
async def test_confirm_and_execute_denied_does_not_write_file(real_db, tmp_path):
    from storage.repositories import folders as folders_repo

    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))
    target = folder / "todo.txt"

    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    await agent.confirm_and_execute(
        conv_id, "write_file", {"path": str(target), "content": "buy milk"}, approved=False
    )

    assert not target.exists()


@pytest.mark.asyncio
async def test_launch_application_pauses_for_confirmation_without_launching(real_db, monkeypatch):
    from tools import windows

    def fail(*a, **kw):
        raise AssertionError("Popen should not be called before confirmation")

    monkeypatch.setattr(windows.subprocess, "Popen", fail)

    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call("call_1", "launch_application", {"application": "notepad"})],
        ),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "open notepad")

    assert state["requires_confirmation"] is True
    assert state["confirmation_request"]["tool"] == "launch_application"


@pytest.mark.asyncio
async def test_confirm_and_execute_approved_launches_application(real_db, monkeypatch):
    from tools import windows

    calls = []
    monkeypatch.setattr(windows.subprocess, "Popen", lambda args: calls.append(args))

    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.confirm_and_execute(
        conv_id, "launch_application", {"application": "notepad"}, approved=True
    )

    assert state["error"] is None
    assert calls == [["notepad.exe"]]


@pytest.mark.asyncio
async def test_confirm_and_execute_denied_does_not_launch_application(real_db, monkeypatch):
    from tools import windows

    def fail(*a, **kw):
        raise AssertionError("Popen should not be called when denied")

    monkeypatch.setattr(windows.subprocess, "Popen", fail)

    agent = Agent(llm_manager=LLMManager([_ScriptedProvider([])]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.confirm_and_execute(
        conv_id, "launch_application", {"application": "notepad"}, approved=False
    )

    assert "won't run" in state["response"].lower()


@pytest.mark.asyncio
async def test_lock_system_pauses_for_confirmation(real_db, monkeypatch):
    from tools import windows

    def fail():
        raise AssertionError("LockWorkStation should not be called before confirmation")

    monkeypatch.setattr(windows.ctypes.windll.user32, "LockWorkStation", fail, raising=False)

    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call("call_1", "lock_system", {})],
        ),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "lock my computer")

    assert state["requires_confirmation"] is True
    assert state["confirmation_request"]["tool"] == "lock_system"


@pytest.mark.asyncio
async def test_low_risk_tool_does_not_require_confirmation(real_db):
    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call("call_1", "create_note", {"content": "buy milk"})],
        ),
        LLMResponse(content="Noted!", provider="scripted", model="x"),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "remember to buy milk")

    assert state["requires_confirmation"] is False
    assert state["response"] == "Noted!"
    assert state["tool_results"][0]["result"]["content"] == "buy milk"
