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

def _should_use_direct_flow(indoor_temp: float, outdoor_temp: float | None) -> bool:
    if outdoor_temp is None:
        return False
    indoor_distance = abs(indoor_temp - IDEAL_TEMP)
    outdoor_distance = abs(outdoor_temp - IDEAL_TEMP)
    return outdoor_distance < indoor_distance

def fetch_co2_sensor_data(sensor):
    result = sensor.status()
    if not result or "dps" not in result:
        raise RuntimeError(f"Failed to read CO2 sensor: {result}")
    dps = result["dps"]
    return {
        "co2_state": dps.get("1"),
        "co2_ppm": dps.get("2"),
        "temperature_c": dps["18"] / 10 if dps.get("18") is not None else None,
        "humidity_pct": dps["19"] if dps.get("19") is not None else None,
        "pm1_ugm3": _get_pm_value(dps, ("101", "23", "105")),
        "pm25_ugm3": dps["20"] if dps.get("20") is not None else None,
        "pm10_ugm3": _get_pm_value(dps, ("102", "24", "106")),
        "voc_mgm3": dps["21"] / 1000 if dps.get("21") is not None else None,
        "ch2o_mgm3": dps["22"] / 1000 if dps.get("22") is not None else None,
        "battery_pct": dps.get("15"),
    }

def _get_pm_value(dps: dict, keys: tuple[str, ...]):
    for key in keys:
        value = dps.get(key)
        if value is not None:
            return value
    return None

def _apply_last_known_good(target: dict, source: dict):
    for key, value in source.items():
        if value is not None:
            target[key] = value

# Metoda originala: send_button
def _send_ir(ir_device, button_codes: dict, button_name: str):
    code = button_codes.get(button_name)
    if code is None:
        logging.warning(f"IR code not found for button: {button_name}")
        return False
    try:
        result = ir_device.send_button(code)
        logging.info(f"IR command {button_name}: {result}")
        return True
    except Exception as e:
        logging.error(f"IR command failed for {button_name}: {e}")
        return False

def _set_speed(speed: int, ir_device, button_codes: dict):
    return _send_ir(ir_device, button_codes, f"SPEED_{speed}")

def _set_mode(mode: str, ir_device, button_codes: dict):
    if mode == "NONE":
        return True
    return _send_ir(ir_device, button_codes, f"MODE_{mode}")

def _set_flux(flux: str, ir_device, button_codes: dict):
    if flux == "NONE":
        return True
    return _send_ir(ir_device, button_codes, f"FLUX_{flux}")


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

    while True:
        try:
            # 1. Read main air-quality sensor
            try:
                co2_data = await loop.run_in_executor(None, fetch_co2_sensor_data, co2_sensor)
                _apply_last_known_good(air_metrics_dict, co2_data)
                air_metrics_dict["online"] = True
            except Exception as e:
                logging.error(f"CO2 SENSOR FETCH ERROR: {e}")
                air_metrics_dict["online"] = False

            # 2. Read local Zigbee sensors through Gateway
            try:
                indoor_data = await loop.run_in_executor(None, gateway.get_indoor)
                outdoor_data = await loop.run_in_executor(None, gateway.get_outdoor)

                if indoor_data.temperature is not None:
                    air_metrics_dict["indoor_temperature_c"] = indoor_data.temperature
                if indoor_data.humidity is not None:
                    air_metrics_dict["indoor_humidity_pct"] = indoor_data.humidity
                if indoor_data.battery is not None:
                    air_metrics_dict["indoor_battery"] = indoor_data.battery

                if outdoor_data.temperature is not None:
                    air_metrics_dict["outdoor_temperature_c"] = outdoor_data.temperature
                if outdoor_data.humidity is not None:
                    air_metrics_dict["outdoor_humidity_pct"] = outdoor_data.humidity
                if outdoor_data.battery is not None:
                    air_metrics_dict["outdoor_battery"] = outdoor_data.battery

                air_metrics_dict["zigbee_online"] = True

                logging.info(
                    "Zigbee sensors: "
                    f"indoor={indoor_data.temperature}°C/{indoor_data.humidity}%/{indoor_data.battery}, "
                    f"outdoor={outdoor_data.temperature}°C/{outdoor_data.humidity}%/{outdoor_data.battery}"
                )
            except Exception as e:
                logging.error(f"LOCAL ZIGBEE FETCH ERROR: {e}")
                air_metrics_dict["zigbee_online"] = False

            # 3. Automation decision
            if not state_dict.get("automation_enabled", True):
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            co2_ppm = air_metrics_dict.get("co2_ppm")
            if co2_ppm is None:
                co2_ppm = 400

            try:
                co2_ppm = float(co2_ppm)
            except (TypeError, ValueError):
                logging.warning(f"Invalid CO2 value: {co2_ppm}")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            night = _is_night()
            state_dict["night"] = night

            # 4. CO2 automation
            if co2_ppm >= CO2_LOW_THRESHOLD:
                state_dict["boost"] = True
            else:
                state_dict["boost"] = False

            target_speed = _get_target_speed(co2_ppm, night)

            # 5. Thermal airflow logic
            indoor_temp = air_metrics_dict.get("indoor_temperature_c")
            outdoor_temp = air_metrics_dict.get("outdoor_temperature_c")

            if indoor_temp is None:
                indoor_temp = IDEAL_TEMP

            direct_flow = _should_use_direct_flow(indoor_temp, outdoor_temp)

            if direct_flow:
                target_mode = "NONE"
                target_flux = "NORTH_SOUTH"
            else:
                target_mode = "MANUAL"
                target_flux = "NONE"

            state_changed = False

            # 6. Mode / flux
            if state_dict.get("mode") != target_mode:
                if _set_mode(target_mode, ir_device, button_codes):
                    state_dict["mode"] = target_mode
                    state_changed = True

            if state_dict.get("flux") != target_flux:
                if _set_flux(target_flux, ir_device, button_codes):
                    state_dict["flux"] = target_flux
                    state_changed = True

            # 7. Speed lock
            now = _get_now()
            can_change_speed = (
                last_speed_change is None
                or now - last_speed_change >= timedelta(minutes=SPEED_CHANGE_LOCK_MINUTES)
            )

            if can_change_speed and state_dict.get("speed") != target_speed:
                if _set_speed(target_speed, ir_device, button_codes):
                    state_dict["speed"] = target_speed
                    last_speed_change = now
                    state_changed = True

            # 8. Persist
            if state_changed:
                save_state_func(state_dict)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logging.info("Air sensor automation task cancelled.")
            raise
        except InterruptedError:
            raise
        except Exception as e:
            logging.exception(f"Unexpected automation error: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)