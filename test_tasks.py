import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from tasks import poll_air_sensor_task

@pytest.mark.asyncio
async def test_scenario_1_normal_co2():
    mock_sensor = MagicMock()
    # CO2 is 1142 (below 1200). Under continuous logic, clean air targets Speed 1.
    mock_sensor.status.return_value = {
        "dps": {"1": "normal", "2": 1142, "18": 25, "19": 52}
    }
    
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_1": "BTN_S1"}
    # Initialize speed at 3; automation should correct it to 1 because CO2 is < 1200
    state_dict = {"mode": "AUTO", "speed": 3, "flux": "NONE", "boost": False, "automation_enabled": True}
    air_metrics = {}
    save_func = MagicMock()
    mock_cloud = MagicMock()
    
    mock_cloud.getstatus.return_value = {"result": [{"code": "va_temperature", "value": 220}]}

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
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 250}]},  
        {"result": [{"code": "va_temperature", "value": 210}]}   
    ]

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
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
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 220}]}, 
        {"result": [{"code": "va_temperature", "value": 350}]}   
    ]

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
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
    
    mock_cloud = MagicMock()
    mock_cloud.getstatus.side_effect = [
        {"result": [{"code": "va_temperature", "value": 250}]}, 
        {"result": [{"code": "va_temperature", "value": 100}]},  
        {"result": [{"code": "va_temperature", "value": 220}]},  
        {"result": [{"code": "va_temperature", "value": 350}]}   
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
    mock_cloud = MagicMock()
    mock_cloud.getstatus.return_value = {"result": [{"code": "va_temperature", "value": 220}]}

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
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
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1250}}
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_2": "BTN_S2"}
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": True}
    save_func = MagicMock()
    mock_cloud = MagicMock()
    mock_cloud.getstatus.return_value = {"result": [{"code": "va_temperature", "value": 220}]}

    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
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


@pytest.mark.asyncio
async def test_scenario_automation_disabled():
    mock_sensor = MagicMock()
    mock_sensor.status.return_value = {"dps": {"1": "alarm", "2": 1500}} 
    mock_ir = MagicMock()
    button_codes = {"MODE_MANUAL": "BTN_MANUAL", "SPEED_3": "BTN_S3"}
    state_dict = {"mode": "AUTO", "speed": 1, "flux": "NONE", "boost": False, "automation_enabled": False}
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
    assert state_dict["speed"] == 1
    mock_ir.send_button.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_deadzone_morning_shift():
    mock_sensor = MagicMock()
    mock_sensor.status.side_effect = [
        {"dps": {"1": "alarm", "2": 1250}},
        {"dps": {"1": "alarm", "2": 1100}} 
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
    mock_cloud = MagicMock()
    mock_cloud.getstatus.return_value = {"result": [{"code": "va_temperature", "value": 220}]}

    mock_times = [
        datetime(2026, 6, 6, 7, 59, 0),
        datetime(2026, 6, 6, 8, 1, 0)
    ]
    
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return mock_times.pop(0)

    call_count = 0
    async def mock_sleep(secs):
        nonlocal call_count
        if secs == 10:
            call_count += 1
            if call_count >= 2:
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

    assert state_dict["speed"] == 3
    mock_ir.send_button.assert_any_call("BTN_S2") 
    mock_ir.send_button.assert_any_call("BTN_S3")