import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from tasks import poll_air_sensor_task

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