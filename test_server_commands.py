import json
import os
from unittest.mock import MagicMock

import pytest

for key, value in {
    "IR_DEVICE_ID": "test-ir",
    "IR_ADDRESS": "127.0.0.1",
    "IR_LOCAL_KEY": "test-key",
    "SENSOR_DEVICE_ID": "test-sensor",
    "SENSOR_ADDRESS": "127.0.0.1",
    "SENSOR_LOCAL_KEY": "test-key",
    "GATEWAY_IP": "127.0.0.1",
    "GATEWAY_ID": "test-gateway",
    "TUYA_VERSION": "3.3",
    "INDOOR_ID": "test-indoor",
    "INDOOR_CID": "test-indoor-cid",
    "OUTDOOR_ID": "test-outdoor",
    "OUTDOOR_CID": "test-outdoor-cid",
    "TUYA_CHILD_KEY": "test-child-key",
}.items():
    os.environ.setdefault(key, value)

import server


def test_manual_ir_command_is_logged_without_empty_result(monkeypatch, caplog):
    ir_device = MagicMock()
    ir_device.send_button.return_value = None
    monkeypatch.setattr(server, "BUTTON_CODES", {"SPEED_1": "BTN_S1"})
    monkeypatch.setattr(server, "ir_device", ir_device)

    with caplog.at_level("INFO"):
        server.send_ir_button("SPEED_1")

    assert "IR command SPEED_1" in caplog.messages
    assert not any("None" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_mode_is_restored_after_switching_to_flux(monkeypatch):
    state = {
        "mode": "MANUAL",
        "last_mode": "MANUAL",
        "speed": 2,
        "humidity": 3,
        "flux": "NONE",
        "last_flux": "SOUTH_NORTH",
        "night": False,
        "boost": False,
        "automation_enabled": False,
    }
    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", lambda _button: None)
    monkeypatch.setattr(server, "save_state", lambda _state: None)

    await server.command("FLUX")
    assert state["mode"] == "NONE"
    assert state["flux"] == "SOUTH_NORTH"

    await server.command("MODE")
    assert state["mode"] == "MANUAL"
    assert state["flux"] == "NONE"
    assert state["speed"] == 2


@pytest.mark.asyncio
async def test_flux_is_restored_after_switching_to_mode(monkeypatch):
    state = {
        "mode": "NONE",
        "last_mode": "MANUAL",
        "speed": 2,
        "humidity": 3,
        "flux": "EXTRACT",
        "last_flux": "EXTRACT",
        "night": False,
        "boost": False,
        "automation_enabled": False,
    }
    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", lambda _button: None)
    monkeypatch.setattr(server, "save_state", lambda _state: None)

    await server.command("MODE")
    assert state["mode"] == "MANUAL"
    assert state["flux"] == "NONE"

    await server.command("FLUX")
    assert state["mode"] == "NONE"
    assert state["flux"] == "EXTRACT"


@pytest.mark.asyncio
async def test_missing_previous_selection_uses_default(monkeypatch):
    state = {
        "mode": "NONE",
        "speed": 2,
        "humidity": 3,
        "flux": "NONE",
        "night": False,
        "boost": False,
        "automation_enabled": False,
    }
    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", lambda _button: None)
    monkeypatch.setattr(server, "save_state", lambda _state: None)

    await server.command("MODE")
    assert state["mode"] == "AUTO"

    state["mode"] = "NONE"
    await server.command("FLUX")
    assert state["flux"] == "NORTH_SOUTH"


def test_load_state_remembers_legacy_active_selections(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"mode": "MANUAL", "flux": "EXTRACT"}))
    monkeypatch.setattr(server, "STATE_FILE", str(state_file))

    state = server.load_state()

    assert state["last_mode"] == "MANUAL"
    assert state["last_flux"] == "EXTRACT"


@pytest.mark.asyncio
async def test_automation_toggle_is_logged(monkeypatch, caplog):
    state = {"automation_enabled": True, "boost": False}
    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "save_state", lambda _state: None)

    with caplog.at_level("INFO"):
        await server.command("TOGGLE_AUTO")

    assert "Remote command TOGGLE_AUTO: disabled" in caplog.messages


@pytest.mark.asyncio
async def test_toggle_auto_restores_physical_state_after_boost(monkeypatch):
    previous_state = {
        "mode": "AUTO",
        "last_mode": "AUTO",
        "speed": 1,
        "humidity": 3,
        "flux": "NONE",
        "night": False,
        "automation_enabled": False,
    }
    state = {
        **previous_state,
        "boost": True,
        "boost_previous_state": previous_state,
        "boost_expires_at": 1200.0,
    }
    sent_commands = []

    monkeypatch.setattr(server, "CURRENT_STATE", state)
    monkeypatch.setattr(server, "send_ir_button", sent_commands.append)
    monkeypatch.setattr(server, "save_state", lambda _state: None)
    monkeypatch.setattr(server, "boost_task", None)

    await server.command("TOGGLE_AUTO")

    assert sent_commands == ["MODE_AUTO", "SPEED_1", "HUMIDITY_3"]
    assert state["boost"] is False
    assert state["automation_enabled"] is True


def test_save_state_records_only_actual_state_changes(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    db_path = tmp_path / "air_history.sqlite3"
    monkeypatch.setattr(server, "STATE_FILE", str(state_path))
    monkeypatch.setattr(server, "AIR_HISTORY_DB", str(db_path))
    first_state = {"mode": "AUTO", "speed": 1}
    changed_state = {"mode": "MANUAL", "speed": 2}

    server.save_state(first_state)
    server.save_state(first_state.copy())
    server.save_state(changed_state)

    history = server.get_phantom_state_history(str(db_path))["history"]
    assert [entry["state"] for entry in history] == [changed_state, first_state]


@pytest.mark.asyncio
async def test_phantom_history_endpoint_returns_bounded_history(monkeypatch):
    expected_response = {
        "history": [{"id": 3, "changed_at": "2026-01-01T10:00:00", "state": {"mode": "AUTO"}}],
        "total": 41,
        "page": 2,
        "page_size": 25,
    }
    monkeypatch.setattr(server, "AIR_HISTORY_DB", "history.sqlite3")
    monkeypatch.setattr(server, "get_phantom_state_history", lambda db_path, page, page_size: expected_response)

    response = await server.get_phantom_history(page=2, page_size=25)

    assert response == expected_response


@pytest.mark.asyncio
async def test_phantom_runtime_endpoint_returns_duration_summary(monkeypatch):
    expected_summary = {
        "durations_seconds": {"night": 60, "speed_1": 120, "speed_2": 180, "speed_3": 240},
        "total_seconds": 600,
        "started_at": "2026-01-01T10:00:00+02:00",
        "as_of": "2026-01-01T10:10:00+02:00",
    }
    monkeypatch.setattr(server, "AIR_HISTORY_DB", "history.sqlite3")
    monkeypatch.setattr(server, "get_phantom_state_runtime", lambda db_path: expected_summary)

    response = await server.get_phantom_runtime()

    assert response == expected_summary
