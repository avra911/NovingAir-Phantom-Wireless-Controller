import asyncio

import pytest

import server


def _state():
    return {
        "mode": "SLEEP",
        "speed": 1,
        "humidity": 2,
        "flux": "SOUTH_NORTH",
        "night": True,
        "boost": False,
        "automation_enabled": True,
    }


def _snapshot(state):
    return {
        key: state[key]
        for key in (
            "mode",
            "speed",
            "humidity",
            "flux",
            "night",
            "automation_enabled",
        )
    }


@pytest.mark.asyncio
async def test_start_boost_only_changes_boost_state(monkeypatch):
    state = _state()
    sent_commands = []

    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", sent_commands.append)
    monkeypatch.setattr(server, "save_state", lambda ignored_state: None)
    monkeypatch.setattr(server, "boost_task", None)

    await server._start_boost()

    assert sent_commands == ["BOOST"]
    assert state["boost"] is True
    assert state["mode"] == "SLEEP"
    assert state["speed"] == 1
    assert state["humidity"] == 2
    assert state["flux"] == "SOUTH_NORTH"
    assert state["night"] is True
    assert state["automation_enabled"] is True
    assert state["boost_previous_state"] == _snapshot(state)
    assert state["boost_expires_at"] > 0

    server.boost_task.cancel()
    await asyncio.gather(server.boost_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_boost_timer_restores_previous_state_after_expiry(monkeypatch):
    previous_state = _snapshot(_state())
    state = {**previous_state, "boost": True}
    state["boost_previous_state"] = previous_state
    state["boost_expires_at"] = 1200.0
    sent_commands = []

    async def skip_sleep(seconds):
        assert seconds == 1200.0

    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", sent_commands.append)
    monkeypatch.setattr(server, "save_state", lambda ignored_state: None)
    monkeypatch.setattr(server.time, "time", lambda: 0.0)
    monkeypatch.setattr(server.asyncio, "sleep", skip_sleep)

    await server._boost_timer(1200.0)

    assert sent_commands == ["BOOST"]
    assert state == {**previous_state, "boost": False}
    assert state["boost"] is False