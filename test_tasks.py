import os
import sqlite3
import json

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from tasks import (
    _send_ir,
    get_air_metrics_history,
    get_phantom_state_history,
    get_phantom_state_runtime,
    poll_air_sensor_task,
    save_air_metrics_snapshot,
    save_phantom_state_snapshot,
)
from tasks import _should_use_direct_flow


def test_automation_ir_log_omits_none_response(caplog):
    mock_ir = MagicMock()
    mock_ir.send_button.return_value = None

    with caplog.at_level("INFO"):
        assert _send_ir(mock_ir, {"SPEED_1": "BTN_S1"}, "SPEED_1") is True

    assert "IR command SPEED_1" in caplog.messages
    assert not any("None" in message for message in caplog.messages)


def test_direct_flow_stops_when_indoor_temperature_is_closer_to_ideal():
    assert _should_use_direct_flow(22.9, 21.0, True) is False

@pytest.mark.asyncio
async def test_scenario_1_normal_co2():
    mock_sensor = MagicMock()
    # Low CO2 value (450) so that target_speed becomes 1
    mock_sensor.status.return_value = {
        "dps": {"1": "normal", "2": 450, "18": 25, "19": 52}
    }
    
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_1": "BTN_S1", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 3, "flux": "NONE", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(InterruptedError):
            await poll_air_sensor_task(
                co2_sensor=mock_sensor,
                ir_device=mock_ir,
                button_codes=button_codes,
                state_dict=state_dict,
                air_metrics_dict=air_metrics,
                save_state_func=save_func,
                gateway=mock_gateway,
            )

    assert state_dict["speed"] == 1
    mock_ir.send_button.assert_any_call("BTN_S1")


@pytest.mark.asyncio
async def test_poll_persists_air_metrics_snapshot(tmp_path):
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {
        "dps": {"1": "normal", "2": 650, "18": 23.5, "19": 48, "20": 7, "21": 250, "22": 30}
    }

    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_1": "BTN_S1"}
    state_dict = {"mode": "MANUAL", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": False}
    air_metrics = {}
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=45, battery=91)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=12.0, humidity=60, battery=88)
    db_path = tmp_path / "air_history.sqlite3"

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(InterruptedError):
            await poll_air_sensor_task(
                co2_sensor=mock_sensor,
                ir_device=mock_ir,
                button_codes=button_codes,
                state_dict=state_dict,
                air_metrics_dict=air_metrics,
                save_state_func=MagicMock(),
                gateway=mock_gateway,
                air_history_db_path=str(db_path),
            )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT co2_ppm, temperature_c, humidity_pct, voc_mgm3,
                   ch2o_mgm3, online, indoor_temperature_c,
                   outdoor_temperature_c, zigbee_online
            FROM air_metrics_history
            """
        ).fetchone()

    assert row == (650.0, 23.5, 48.0, 0.25, 0.03, 1, 22.0, 12.0, 1)


def test_existing_air_history_db_does_not_recreate_schema(tmp_path):
    db_path = tmp_path / "air_history.sqlite3"
    metrics = {"co2_ppm": 650, "online": True, "zigbee_online": True}

    save_air_metrics_snapshot(metrics, str(db_path))

    with patch("tasks._create_air_history_schema") as create_schema:
        save_air_metrics_snapshot(metrics, str(db_path))

    with sqlite3.connect(db_path) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM air_metrics_history").fetchone()[0]

    create_schema.assert_not_called()
    assert row_count == 2


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="requires Linux procfs")
def test_air_history_connections_are_closed(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    metrics = {"co2_ppm": 650, "online": True, "zigbee_online": True}
    initial_fd_count = len(os.listdir("/proc/self/fd"))

    for _ in range(20):
        save_air_metrics_snapshot(metrics, db_path)
        get_air_metrics_history(db_path)

    assert len(os.listdir("/proc/self/fd")) <= initial_fd_count + 1


def test_get_air_metrics_history_returns_oldest_to_newest_limited_rows(tmp_path):
    db_path = tmp_path / "air_history.sqlite3"

    save_air_metrics_snapshot(
        {"co2_ppm": 500, "temperature_c": 22, "online": True, "zigbee_online": True},
        str(db_path),
        datetime(2026, 1, 1, 10, 0, 0),
    )
    save_air_metrics_snapshot(
        {"co2_ppm": 650, "temperature_c": 23, "online": True, "zigbee_online": True},
        str(db_path),
        datetime(2026, 1, 1, 10, 1, 0),
    )
    save_air_metrics_snapshot(
        {"co2_ppm": 700, "temperature_c": 24, "online": True, "zigbee_online": True},
        str(db_path),
        datetime(2026, 1, 1, 10, 2, 0),
    )

    history = get_air_metrics_history(str(db_path), limit=2)

    assert [row["co2_ppm"] for row in history] == [650.0, 700.0]
    assert history[0]["fetched_at"] == "2026-01-01T10:01:00"


def test_get_air_metrics_history_missing_db_returns_empty_list(tmp_path):
    assert get_air_metrics_history(str(tmp_path / "missing.sqlite3")) == []


def test_phantom_state_history_returns_requested_page_newest_first(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    states = [
        {"mode": "AUTO", "speed": 1},
        {"mode": "MANUAL", "speed": 2},
        {"mode": "SLEEP", "speed": 3},
    ]
    for index, state in enumerate(states):
        save_phantom_state_snapshot(state, db_path, datetime(2026, 1, 1, 10, index, 0))

    result = get_phantom_state_history(db_path, page=2, page_size=1)

    assert result["total"] == 3
    assert result["page"] == 2
    assert result["page_size"] == 1
    assert result["history"][0]["changed_at"] == "2026-01-01T10:01:00"
    assert result["history"][0]["state"] == states[1]


def test_sensor_history_schema_is_created_when_state_history_created_db_first(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    save_phantom_state_snapshot({"mode": "AUTO"}, db_path)

    save_air_metrics_snapshot({"co2_ppm": 650, "online": True, "zigbee_online": True}, db_path)

    with sqlite3.connect(db_path) as conn:
        sensor_rows = conn.execute("SELECT COUNT(*) FROM air_metrics_history").fetchone()[0]
        state_rows = conn.execute("SELECT COUNT(*) FROM phantom_state_history").fetchone()[0]

    assert sensor_rows == 1
    assert state_rows == 1


def test_get_phantom_state_history_without_table_returns_empty_list(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    save_air_metrics_snapshot({"co2_ppm": 650, "online": True, "zigbee_online": True}, db_path)

    assert get_phantom_state_history(db_path) == {
        "history": [],
        "total": 0,
        "page": 1,
        "page_size": 25,
    }


def test_phantom_state_history_pagination_reaches_past_500_rows(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    first_state = {"mode": "AUTO", "speed": 1}
    save_phantom_state_snapshot(first_state, db_path, datetime(2026, 1, 1, 10, 0, 0))

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO phantom_state_history (changed_at, state_json) VALUES (?, ?)",
            ((f"test-{index}", json.dumps({"mode": "MANUAL", "speed": index})) for index in range(500)),
        )

    final_page = get_phantom_state_history(db_path, page=21, page_size=25)

    assert final_page["total"] == 501
    assert len(final_page["history"]) == 1
    assert final_page["history"][0]["state"] == first_state


def test_phantom_state_runtime_splits_night_and_counts_boost_as_speed_three(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    transitions = [
        (datetime(2026, 1, 1, 10, 0), {"speed": 1}),
        (datetime(2026, 1, 1, 10, 10), {"speed": 1, "boost": True}),
        (datetime(2026, 1, 1, 10, 25), {"speed": 2, "night": True}),
        (datetime(2026, 1, 1, 10, 35), {"speed": 3}),
        (datetime(2026, 1, 1, 10, 50), {"speed": 2}),
    ]
    for changed_at, state in transitions:
        save_phantom_state_snapshot(state, db_path, changed_at)

    runtime = get_phantom_state_runtime(db_path, datetime(2026, 1, 1, 11, 0))

    assert runtime["durations_seconds"] == {
        "night": 600,
        "speed_1": 600,
        "speed_2": 600,
        "speed_3": 1800,
    }
    assert runtime["total_seconds"] == 3600
    assert runtime["started_at"] == "2026-01-01T10:00:00+02:00"


@pytest.mark.asyncio
async def test_scenario_2_high_co2_cooler_outdoor():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {
        "dps": {"1": "alarm", "2": 1250, "18": 25, "19": 50}
    }
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_3": "BTN_S3", 
        "FLUX_NORTH_SOUTH": "BTN_NS"
    }
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=25.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=21.0, humidity=50, battery=100)

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 6, 14, 0, 0)

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("tasks.datetime", MockDateTime):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict=air_metrics,
                    save_state_func=save_func,
                    gateway=mock_gateway,
                )

    assert state_dict["flux"] == "NORTH_SOUTH"
    assert state_dict["mode"] == "NONE"
    assert state_dict["boost"] is False
    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_NS")
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_3_high_co2_indoor_preferred():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {
        "dps": {"1": "alarm", "2": 1300, "18": 22, "19": 50}
    }
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_3": "BTN_S3"
    }
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=35.0, humidity=50, battery=100)

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 6, 14, 0, 0)

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("tasks.datetime", MockDateTime):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict=air_metrics,
                    save_state_func=save_func,
                    gateway=mock_gateway,
                )

    assert state_dict["mode"] == "MANUAL"
    assert state_dict["flux"] == "NONE"
    assert state_dict["boost"] is False
    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_MANUAL")
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_4_recovery_indoor_preferred():
    mock_sensor = MagicMock()
    mock_sensor.status.side_effect = [
        {"dps": {"1": "alarm", "2": 1300}},
        {"dps": {"1": "normal", "2": 700}}
    ]
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_1": "BTN_S1",
        "SPEED_3": "BTN_S3",
        "FLUX_NORTH_SOUTH": "BTN_NS"
    }
    state_dict = {"mode": "NONE", "speed": 1, "flux": "NORTH_SOUTH", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.side_effect = [
        MagicMock(temperature=25.0, humidity=50, battery=100),
        MagicMock(temperature=22.0, humidity=50, battery=100)
    ]
    mock_gateway.get_outdoor.side_effect = [
        MagicMock(temperature=10.0, humidity=50, battery=100),
        MagicMock(temperature=35.0, humidity=50, battery=100)
    ]

    time_states = [
        datetime(2026, 6, 6, 12, 0, 0),
        datetime(2026, 6, 6, 13, 0, 0)
    ]
    time_idx = 0

    def mock_get_now():
        nonlocal time_idx
        return time_states[min(time_idx, len(time_states) - 1)]

    call_count = 0
    async def mock_sleep(secs):
        nonlocal call_count, time_idx
        if secs == 60:
            call_count += 1
            time_idx += 1
            if call_count >= 2:
                raise InterruptedError

    with patch("tasks._get_now", side_effect=mock_get_now):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict=air_metrics,
                    save_state_func=save_func,
                    gateway=mock_gateway,
                )

    assert state_dict["mode"] == "MANUAL"
    assert state_dict["flux"] == "NONE"
    assert state_dict["boost"] is False
    assert state_dict["speed"] == 1
    mock_ir.send_button.assert_any_call("BTN_MANUAL")
    mock_ir.send_button.assert_any_call("BTN_S1")


@pytest.mark.asyncio
async def test_scenario_day_speed_rule():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1250}}
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_3": "BTN_S3"}
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 6, 14, 0, 0)

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("tasks.datetime", MockDateTime):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict={},
                    save_state_func=save_func,
                    gateway=mock_gateway,
                )

    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_night_speed_rule():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1250}}
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 6, 23, 0, 0)

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("tasks.datetime", MockDateTime):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict={},
                    save_state_func=save_func,
                    gateway=mock_gateway,
                )

    assert state_dict["speed"] == 2
    mock_ir.send_button.assert_any_call("BTN_S2")


@pytest.mark.asyncio
async def test_scenario_automation_disabled():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1500}} 
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_3": "BTN_S3"}
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": False}
    air_metrics = {}
    save_func = MagicMock()
    mock_gateway = MagicMock()

    async def mock_sleep(secs):
        if secs == 60:
            raise InterruptedError

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(InterruptedError):
            await poll_air_sensor_task(
                co2_sensor=mock_sensor,
                ir_device=mock_ir,
                button_codes=button_codes,
                state_dict=state_dict,
                air_metrics_dict=air_metrics,
                save_state_func=save_func,
                gateway=mock_gateway,
            )

    assert state_dict["mode"] == "AUTO"
    assert state_dict["speed"] == 1
    mock_ir.send_button.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_deadzone_morning_shift():
    mock_sensor = MagicMock()
    # High CO2 level in both iterations (1350) to reach speed threshold 3
    mock_sensor.status.side_effect = [
        {"dps": {"1": "alarm", "2": 1350}},
        {"dps": {"1": "alarm", "2": 1350}} 
    ]
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_2": "BTN_S2",
        "SPEED_3": "BTN_S3"
    }
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)

    mock_times = [
        datetime(2026, 6, 6, 7, 59, 0),
        datetime(2026, 6, 6, 9, 1, 0)
    ]
    time_idx = 0

    def mock_get_now():
        return mock_times[min(time_idx, len(mock_times) - 1)]

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return mock_get_now()

    call_count = 0
    async def mock_sleep(secs):
        nonlocal call_count, time_idx
        if secs == 60:
            call_count += 1
            time_idx += 1
            if call_count >= 2:
                raise InterruptedError

    with patch("tasks._get_now", side_effect=mock_get_now):
        with patch("tasks.datetime", MockDateTime):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                with pytest.raises(InterruptedError):
                    await poll_air_sensor_task(
                        co2_sensor=mock_sensor,
                        ir_device=mock_ir,
                        button_codes=button_codes,
                        state_dict=state_dict,
                        air_metrics_dict=air_metrics,
                        save_state_func=save_func,
                        gateway=mock_gateway,
                    )

    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_S2") 
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_medium_co2_day_and_night():
    # Verify rule: 800-1200 ppm -> 2 day and 1 night
    mock_sensor = MagicMock()
    mock_sensor.status.side_effect = [
        {"dps": {"1": "alarm", "2": 1000}}, # Iteration 1: 1000 ppm (Day) -> Speed 2
        {"dps": {"1": "alarm", "2": 1000}}  # Iteration 2: 1000 ppm (Night) -> Speed 1
    ]
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_1": "BTN_S1", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 3, "flux": "NONE", "boost": False, "automation_enabled": True}
    
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22.0, humidity=50, battery=100)

    mock_times = [
        datetime(2026, 6, 6, 14, 0, 0),  # Day
        datetime(2026, 6, 6, 23, 0, 0)   # Night
    ]
    time_idx = 0

    def mock_get_now():
        return mock_times[min(time_idx, len(mock_times) - 1)]

    call_count = 0
    async def mock_sleep(secs):
        nonlocal call_count, time_idx
        if secs == 60:
            call_count += 1
            time_idx += 1
            if call_count >= 2:
                raise InterruptedError

    with patch("tasks._get_now", side_effect=mock_get_now):
        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(InterruptedError):
                await poll_air_sensor_task(
                    co2_sensor=mock_sensor,
                    ir_device=mock_ir,
                    button_codes=button_codes,
                    state_dict=state_dict,
                    air_metrics_dict={},
                    save_state_func=MagicMock(),
                    gateway=mock_gateway,
                )

    # At the end of the second iteration (night), speed must be 1
    assert state_dict["speed"] == 1
    mock_ir.send_button.assert_any_call("BTN_S1")