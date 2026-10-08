import os
import sqlite3

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from tasks import (
    _send_ir,
    get_air_metrics_history,
    get_phantom_consumption_summary,
    get_phantom_state_history,
    poll_air_sensor_task,
    save_air_metrics_snapshot,
    save_phantom_state_change,
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


def test_phantom_state_history_estimates_power_and_interval_energy(tmp_path):
    db_path = str(tmp_path / "air_history.sqlite3")
    start = datetime(2026, 1, 1, 10, 0, 0)
    save_air_metrics_snapshot({"co2_ppm": 650}, db_path, start)
    save_phantom_state_change(
        {"mode": "MANUAL", "speed": 1, "night": False}, "startup", db_path, start
    )
    save_phantom_state_change(
        {"mode": "MANUAL", "speed": 2, "night": False},
        "speed",
        db_path,
        start + timedelta(hours=1),
    )
    save_phantom_state_change(
        {"mode": "SLEEP", "flux": "NORTH_SOUTH", "speed": 2, "night": True},
        "night",
        db_path,
        start + timedelta(hours=2),
    )
    save_phantom_state_change(
        {"mode": "SLEEP", "flux": "NORTH_SOUTH", "speed": 2, "night": True, "boost": True},
        "boost",
        db_path,
        start + timedelta(hours=3),
    )

    history = get_phantom_state_history(db_path, now=start + timedelta(hours=4))

    assert [entry["estimated_power_w"] for entry in history] == [4.2, 5.5, 3.9, 6.7]
    assert [entry["estimated_energy_wh"] for entry in history] == [4.2, 5.5, 3.9, 6.7]
    assert history[2]["flux"] == "NORTH_SOUTH"
    assert history[3]["boost"] == 1
    assert history[3]["speed"] == 3
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT co2_ppm FROM air_metrics_history").fetchone() == (650.0,)


def test_phantom_consumption_summary_splits_hourly_and_daily_intervals(tmp_path):
    db_path = str(tmp_path / "consumption.sqlite3")
    now = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
    save_phantom_state_change(
        {"mode": "MANUAL", "speed": 1, "night": False},
        "startup",
        db_path,
        now - timedelta(hours=26),
    )
    save_phantom_state_change(
        {"mode": "MANUAL", "speed": 3, "night": False},
        "speed",
        db_path,
        now - timedelta(hours=1),
    )

    summary = get_phantom_consumption_summary(db_path, now)

    assert len(summary["hourly"]) == 24
    assert summary["hourly"][-2]["energy_wh"] == pytest.approx(4.2)
    assert summary["hourly"][-1]["energy_wh"] == pytest.approx(6.7)
    assert summary["hourly"][-1]["coverage_pct"] == pytest.approx(100)
    assert len(summary["daily"]) == 30
    assert summary["daily"][-2]["energy_wh"] == pytest.approx(58.8)
    assert summary["daily"][-2]["coverage_pct"] == pytest.approx(14 / 24 * 100)
    assert summary["daily"][-1]["energy_wh"] == pytest.approx(52.9)
    assert summary["daily"][-1]["coverage_pct"] == pytest.approx(100)


def test_phantom_consumption_summary_marks_unrecorded_periods_unknown(tmp_path):
    summary = get_phantom_consumption_summary(
        str(tmp_path / "missing.sqlite3"),
        datetime(2026, 1, 31, 12, tzinfo=timezone.utc),
    )

    assert len(summary["hourly"]) == 24
    assert len(summary["daily"]) == 30
    assert all(bucket["energy_wh"] is None for bucket in summary["hourly"])
    assert all(bucket["coverage_pct"] == 0 for bucket in summary["daily"])


def test_phantom_history_adds_flux_and_boost_to_existing_table(tmp_path):
    db_path = str(tmp_path / "existing.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE phantom_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                changed_at TEXT NOT NULL,
                change_type TEXT NOT NULL,
                mode TEXT,
                speed INTEGER,
                night INTEGER NOT NULL,
                estimated_power_w REAL
            )
            """
        )

    save_phantom_state_change(
        {"mode": "NONE", "flux": "EXTRACT", "speed": 2, "boost": True},
        "flux+boost",
        db_path,
    )

    history = get_phantom_state_history(db_path)
    assert history[0]["flux"] == "EXTRACT"
    assert history[0]["boost"] == 1
    assert history[0]["estimated_power_w"] == 6.7
    assert history[0]["speed"] == 3


@pytest.mark.asyncio
async def test_automation_records_night_mode_reset(tmp_path):
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "normal", "2": 450}}
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22, humidity=45, battery=90)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22, humidity=45, battery=90)
    state = {
        "mode": "AUTO",
        "speed": 1,
        "flux": "NORTH_SOUTH",
        "night": True,
        "boost": False,
        "automation_enabled": True,
    }
    db_path = str(tmp_path / "history.sqlite3")

    async def stop_after_poll(_seconds):
        raise InterruptedError

    with patch("tasks._is_night", return_value=False), patch(
        "asyncio.sleep", side_effect=stop_after_poll
    ):
        with pytest.raises(InterruptedError):
            await poll_air_sensor_task(
                co2_sensor=mock_sensor,
                ir_device=MagicMock(),
                button_codes={"MODE_MANUAL": "BTN_MANUAL"},
                state_dict=state,
                air_metrics_dict={},
                save_state_func=MagicMock(),
                gateway=mock_gateway,
                air_history_db_path=db_path,
            )

    history = get_phantom_state_history(db_path)
    assert history[-3]["change_type"] == "mode"
    assert history[-3]["night"] == 1
    assert history[-2]["change_type"] == "flux"
    assert history[-2]["flux"] == "NONE"
    assert history[-1]["change_type"] == "night"
    assert history[-1]["night"] == 0


@pytest.mark.parametrize(
    ("night", "expected_speed", "expected_power"),
    [(False, 2, 5.5), (True, 1, 3.9)],
)
@pytest.mark.asyncio
async def test_auto_mode_without_automation_records_schedule_profile(
    tmp_path, monkeypatch, night, expected_speed, expected_power
):
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "normal", "2": 700}}
    mock_gateway = MagicMock()
    mock_gateway.get_indoor.return_value = MagicMock(temperature=22, humidity=45, battery=90)
    mock_gateway.get_outdoor.return_value = MagicMock(temperature=22, humidity=45, battery=90)
    state = {
        "mode": "AUTO",
        "speed": 3,
        "flux": "NONE",
        "night": False,
        "boost": False,
        "automation_enabled": False,
    }
    db_path = str(tmp_path / f"history-{night}.sqlite3")
    ir_device = MagicMock()
    monkeypatch.setattr("tasks._is_night", lambda: night)

    async def stop_after_poll(_seconds):
        raise InterruptedError

    with patch("asyncio.sleep", side_effect=stop_after_poll):
        with pytest.raises(InterruptedError):
            await poll_air_sensor_task(
                co2_sensor=mock_sensor,
                ir_device=ir_device,
                button_codes={},
                state_dict=state,
                air_metrics_dict={},
                save_state_func=MagicMock(),
                gateway=mock_gateway,
                air_history_db_path=db_path,
            )

    event = get_phantom_state_history(db_path)[-1]
    assert event["change_type"] == "auto_schedule"
    assert event["mode"] == "AUTO"
    assert event["speed"] == expected_speed
    assert event["night"] == int(night)
    assert event["estimated_power_w"] == expected_power
    ir_device.send_button.assert_not_called()


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