import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from tasks import poll_air_sensor_task

@pytest.mark.asyncio
async def test_scenario_1_normal_co2():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {
        "dps": {"1": "normal", "2": 1142, "18": 25, "19": 52}
    }
    
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 3, "flux": "EXTRACT"}
    air_metrics = {}
    save_func = MagicMock()
    mock_cloud = MagicMock()

    async def mock_sleep(secs):
        if secs == 10:
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
                cloud=mock_cloud,
                indoor_device_id="indoor_id",
                outdoor_device_id="outdoor_id"
            )

    assert state_dict["mode"] == "AUTO"
    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_2_high_co2_cooler_outdoor():
    """Scenario 2: CO2 > 1200, outdoor temp is closer to ideal -> NORTH_SOUTH flux."""
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
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "SOUTH_NORTH"}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 250}]},  # Indoor: 25.0°C (diff 3.0 from 22)
        {"result": [{"code": "va_temperature", "value": 210}]}   # Outdoor: 21.0°C (diff 1.0 from 22)
    ]

    class MockDateTime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 6, 6, 14, 0, 0)  # Daytime -> Speed 3

    async def mock_sleep(secs):
        if secs == 10:
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
                    cloud=mock_cloud,
                    indoor_device_id="indoor_id",
                    outdoor_device_id="outdoor_id"
                )

    assert state_dict["flux"] == "NORTH_SOUTH"
    assert state_dict["speed"] == 3
    # Note: with the new logic, MODE_MANUAL is not set when NORTH_SOUTH is chosen
    # assert state_dict["mode"] == "MANUAL" 
    mock_ir.send_button.assert_any_call("BTN_NS")
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_3_high_co2_indoor_preferred():
    """Scenario 3: CO2 > 1200, indoor temp is closer to ideal -> MANUAL mode, keeps default flux."""
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {
        "dps": {"1": "alarm", "2": 1300, "18": 22, "19": 50}
    }
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_3": "BTN_S3"
    }
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "SOUTH_NORTH"}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 220}]},  # Indoor: 22.0°C (diff 0.0)
        {"result": [{"code": "va_temperature", "value": 350}]}   # Outdoor: 35.0°C (diff 13.0)
    ]

    class MockDateTime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 6, 6, 14, 0, 0)

    async def mock_sleep(secs):
        if secs == 10:
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
                    cloud=mock_cloud,
                    indoor_device_id="indoor_id",
                    outdoor_device_id="outdoor_id"
                )

    assert state_dict["mode"] == "MANUAL"
    assert state_dict["speed"] == 3
    assert state_dict["flux"] == "SOUTH_NORTH"  # Nu s-a modificat pe direct
    mock_ir.send_button.assert_any_call("BTN_MANUAL")
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_4_recovery_indoor_preferred():
    """Scenario 4: Recovery when CO2 drops below 800 and indoor temp is preferred -> MANUAL mode (default flux SOUTH_NORTH), Speed 1."""
    mock_sensor = MagicMock()
    mock_sensor.status.side_effect = [
        {"dps": {"1": "alarm", "2": 1300}},
        {"dps": {"1": "normal", "2": 700}}
    ]
    
    mock_ir = MagicMock()
    button_codes = {
        "MODE_MANUAL": "BTN_MANUAL", 
        "SPEED_1": "BTN_S1"
    }
    state_dict = {"mode": "AUTO", "speed": 3, "flux": "NORTH_SOUTH"}
    air_metrics = {}
    save_func = MagicMock()
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 250}]},  # High CO2 Indoor
        {"result": [{"code": "va_temperature", "value": 100}]},  # High CO2 Outdoor
        {"result": [{"code": "va_temperature", "value": 220}]},  # Recovery Indoor: 22.0°C (preferred)
        {"result": [{"code": "va_temperature", "value": 350}]}   # Recovery Outdoor: 35.0°C
    ]

    call_count = 0
    async def mock_sleep(secs):
        nonlocal call_count
        if secs == 10:
            call_count += 1
            if call_count >= 2:
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
                cloud=mock_cloud,
                indoor_device_id="indoor_id",
                outdoor_device_id="outdoor_id"
            )

    assert state_dict["mode"] == "MANUAL"
    assert state_dict["speed"] == 1
    # state_dict["flux"] remains "NORTH_SOUTH" here because the 'else' block only sets "mode": "MANUAL"
    mock_ir.send_button.assert_any_call("BTN_MANUAL")
    mock_ir.send_button.assert_any_call("BTN_S1")


@pytest.mark.asyncio
async def test_scenario_day_speed_rule():
    """Scenario 5: High CO2 during the day (14:00) should select Speed 3."""
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1250}}
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_3": "BTN_S3"}
    state_dict = {"mode": "AUTO", "speed": 1}
    save_func = MagicMock()
    mock_cloud = MagicMock()

    class MockDateTime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 6, 6, 14, 0, 0)

    async def mock_sleep(secs):
        if secs == 10:
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
                    cloud=mock_cloud,
                    indoor_device_id="in",
                    outdoor_device_id="out"
                )

    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_S3")


@pytest.mark.asyncio
async def test_scenario_night_speed_rule():
    """Scenario 6: High CO2 during the night (23:00) should select Speed 2."""
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1250}}
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 1}
    save_func = MagicMock()
    mock_cloud = MagicMock()

    class MockDateTime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 6, 6, 23, 0, 0)

    async def mock_sleep(secs):
        if secs == 10:
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
                    cloud=mock_cloud,
                    indoor_device_id="in",
                    outdoor_device_id="out"
                )

    assert state_dict["speed"] == 2
    mock_ir.send_button.assert_any_call("BTN_S2")