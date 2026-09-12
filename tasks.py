import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import tinytuya
from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice
from gateway import TuyaGateway

CO2_HIGH_THRESHOLD = 1200
CO2_LOW_THRESHOLD = 800
IDEAL_TEMP = 22.0
NIGHT_START_HOUR = 21
NIGHT_END_HOUR = 8
SPEED_CHANGE_LOCK_MINUTES = 30
POLL_INTERVAL_SECONDS = 60
TEMP_HYSTERESIS_C = 0.5  # Prevents rapid toggling

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/automation.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def _get_now():
    return datetime.now(ZoneInfo("Europe/Bucharest"))

def _is_night() -> bool:
    hour = _get_now().hour
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR

def _get_target_speed(co2_ppm: float, night: bool) -> int:
    if co2_ppm > CO2_HIGH_THRESHOLD:
        return 2 if night else 3
    if co2_ppm > CO2_LOW_THRESHOLD:
        return 1 if night else 2
    return 1

def _should_use_direct_flow(indoor_temp: float, outdoor_temp: float | None, current_flow: bool) -> bool:
    if outdoor_temp is None:
        return False
    
    indoor_distance = abs(indoor_temp - IDEAL_TEMP)
    outdoor_distance = abs(outdoor_temp - IDEAL_TEMP)
    
    # If already running direct flow, apply hysteresis before turning OFF
    if current_flow:
        return outdoor_distance <= (indoor_distance + TEMP_HYSTERESIS_C)
    
    # Simple check for turning ON direct flow
    return outdoor_distance < indoor_distance

def _safe_float(val, divisor=1.0):
    if val is None:
        return None
    try:
        return float(val) / divisor
    except (ValueError, TypeError):
        return None

def fetch_co2_sensor_data(sensor):
    result = sensor.status()
    if not result or "dps" not in result:
        raise RuntimeError(f"Failed to read CO2 sensor: {result}")
    
    dps = result["dps"]
    return {
        "co2_state": dps.get("1"),
        "co2_ppm": _safe_float(dps.get("2")),
        "temperature_c": _safe_float(dps.get("18")), # Assumes 8-in-1 provides correct value directly
        "humidity_pct": _safe_float(dps.get("19")),
        "pm1_ugm3": _safe_float(_get_pm_value(dps, ("101", "23", "105"))),
        "pm25_ugm3": _safe_float(dps.get("20")),
        "pm10_ugm3": _safe_float(_get_pm_value(dps, ("102", "24", "106"))),
        "voc_mgm3": _safe_float(dps.get("21"), 1000.0),
        "ch2o_mgm3": _safe_float(dps.get("22"), 1000.0),
        "battery_pct": _safe_float(dps.get("15")),
    }

def _get_pm_value(dps: dict, keys: tuple[str, ...]):
    for key in keys:
        if dps.get(key) is not None:
            return dps[key]
    return None

def _apply_last_known_good(target: dict, source: dict):
    for key, value in source.items():
        if value is not None:
            target[key] = value

# IR commands must run synchronously but be awaited via executor
def _send_ir(ir_device, button_codes: dict, button_name: str):
    code = button_codes.get(button_name)
    if code is None:
        logging.warning(f"IR code not found: {button_name}")
        return False
    try:
        result = ir_device.send_button(code)
        logging.info(f"IR command {button_name}: {result}")
        return True
    except Exception as e:
        logging.error(f"IR command failed for {button_name}: {e}")
        return False

async def _async_send_ir(loop, ir_device, button_codes: dict, button_name: str):
    return await loop.run_in_executor(None, _send_ir, ir_device, button_codes, button_name)

async def _set_speed(loop, speed: int, ir_device, button_codes: dict):
    return await _async_send_ir(loop, ir_device, button_codes, f"SPEED_{speed}")

async def _set_mode(loop, mode: str, ir_device, button_codes: dict):
    if mode == "NONE":
        return True
    return await _async_send_ir(loop, ir_device, button_codes, f"MODE_{mode}")

async def _set_flux(loop, flux: str, ir_device, button_codes: dict):
    if flux == "NONE":
        return True
    return await _async_send_ir(loop, ir_device, button_codes, f"FLUX_{flux}")


async def poll_air_sensor_task(
    co2_sensor,
    ir_device,
    button_codes,
    state_dict,
    air_metrics_dict,
    save_state_func,
    gateway: TuyaGateway,
):
    print("[STARTUP] Starting air sensor automation...")
    logging.info("Air sensor automation started.")

    loop = asyncio.get_running_loop()
    last_speed_change = None
    was_night = _is_night()

    while True:
        try:
            # Check for instant UI reset signals from server.py
            if state_dict.pop("reset_speed_lock", False):
                last_speed_change = None

            # 1. Read main air-quality sensor
            try:
                co2_data = await loop.run_in_executor(None, fetch_co2_sensor_data, co2_sensor)
                _apply_last_known_good(air_metrics_dict, co2_data)
                air_metrics_dict["online"] = True
            except Exception as e:
                logging.error(f"CO2 SENSOR FETCH ERROR: {e}")
                air_metrics_dict["online"] = False

            # 2. Read local Zigbee sensors
            try:
                indoor_data = await loop.run_in_executor(None, gateway.get_indoor)
                outdoor_data = await loop.run_in_executor(None, gateway.get_outdoor)

                _apply_last_known_good(air_metrics_dict, {
                    "indoor_temperature_c": indoor_data.temperature,
                    "indoor_humidity_pct": indoor_data.humidity,
                    "indoor_battery": indoor_data.battery,
                    "outdoor_temperature_c": getattr(outdoor_data, 'temperature', None),
                    "outdoor_humidity_pct": getattr(outdoor_data, 'humidity', None),
                    "outdoor_battery": getattr(outdoor_data, 'battery', None)
                })
                air_metrics_dict["zigbee_online"] = True
            except Exception as e:
                logging.error(f"LOCAL ZIGBEE FETCH ERROR: {e}")
                air_metrics_dict["zigbee_online"] = False

            # 3. Automation decision
            if not state_dict.get("automation_enabled", True):
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            co2_ppm = air_metrics_dict.get("co2_ppm", 400.0)
            night = _is_night()

            # 4. Thermal airflow logic
            indoor_temp = air_metrics_dict.get("indoor_temperature_c", IDEAL_TEMP)
            outdoor_temp = air_metrics_dict.get("outdoor_temperature_c")

            currently_direct = state_dict.get("flux") == "NORTH_SOUTH"
            direct_flow = _should_use_direct_flow(indoor_temp, outdoor_temp, currently_direct)

            target_mode = "NONE" if direct_flow else "MANUAL"
            target_flux = "NORTH_SOUTH" if direct_flow else "NONE"
            target_speed = _get_target_speed(co2_ppm, night)

            state_changed = False

            # 5. Apply Mode & Flux asynchronously
            if state_dict.get("mode") != target_mode:
                if await _set_mode(loop, target_mode, ir_device, button_codes):
                    state_dict["mode"] = target_mode
                    state_changed = True

            if state_dict.get("flux") != target_flux:
                if await _set_flux(loop, target_flux, ir_device, button_codes):
                    state_dict["flux"] = target_flux
                    state_changed = True

            # 6. Speed lock with Night Transition Override
            now = _get_now()
            night_transition = (night and not was_night)

            can_change_speed = (
                last_speed_change is None
                or night_transition  # Bypass lock to drop speed when sleeping
                or (now - last_speed_change) >= timedelta(minutes=SPEED_CHANGE_LOCK_MINUTES)
            )

            if can_change_speed and state_dict.get("speed") != target_speed:
                if await _set_speed(loop, target_speed, ir_device, button_codes):
                    state_dict["speed"] = target_speed
                    last_speed_change = now
                    state_changed = True

            # 7. Persist & cleanup
            was_night = night
            if state_changed:
                state_dict["boost"] = False
                state_dict["night"] = False
                save_state_func(state_dict)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logging.info("Automation task cancelled.")
            raise
        except Exception as e:
            logging.exception(f"Unexpected automation error: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)