import asyncio
import logging
import os
from datetime import datetime

# --- CONFIGURATION CONSTANTS ---
CO2_HIGH_THRESHOLD = 1200
CO2_LOW_THRESHOLD = 800
IDEAL_TEMP = 22.0
NIGHT_START_HOUR = 21
NIGHT_END_HOUR = 8

# Configure file logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/automation.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def fetch_zigbee_temp(cloud, device_id: str) -> float | None:
    try:
        status = cloud.getstatus(device_id)
        dps = {}
        if isinstance(status, dict):
            result = status.get("result", [])
            if isinstance(result, list):
                dps = {item.get('code'): item.get('value') for item in result if isinstance(item, dict) and 'code' in item}
            elif isinstance(result, dict):
                dps = result
            elif 'dps' in status:
                dps = status['dps']
        elif isinstance(status, list):
            dps = {item.get('code'): item.get('value') for item in status if isinstance(item, dict) and 'code' in item}

        raw_temp = dps.get("va_temperature") or dps.get("temp_current") or dps.get("temperature")
        if raw_temp is not None:
            return raw_temp / 10.0 if raw_temp > 60 else float(raw_temp)
    except Exception as e:
        logging.error(f"ZIGBEE FETCH ERROR [{device_id}]: {e}")
    return None

def _get_target_speed() -> int:
    current_hour = datetime.now().hour
    is_night = current_hour >= NIGHT_START_HOUR or current_hour < NIGHT_END_HOUR
    return 2 if is_night else 3

def _should_use_direct_flow(indoor_temp: float, outdoor_temp: float | None) -> bool:
    if outdoor_temp is None:
        return False
    return abs(outdoor_temp - IDEAL_TEMP) < abs(indoor_temp - IDEAL_TEMP)

async def poll_air_sensor_task(
    co2_sensor, 
    ir_device, 
    button_codes: dict, 
    state_dict: dict, 
    air_metrics_dict: dict, 
    save_state_func,
    cloud,
    indoor_device_id: str,
    outdoor_device_id: str
):
    logging.info("Air sensor automation task started successfully.")
    co2_override_active = False
    
    while True:
        try:
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(None, co2_sensor.status)
            
            if status and 'dps' in status:
                dps = status['dps']
                
                air_metrics_dict.update({
                    "co2_state": dps.get("1", "normal"),
                    "co2_ppm": dps.get("2", 0),
                    "temperature_c": dps.get("18", 0),
                    "humidity_pct": dps.get("19", 0),
                    "pm1_ugm3": dps.get("101", dps.get("23", dps.get("105", 0))),
                    "pm25_ugm3": dps.get("20", 0),
                    "pm10_ugm3": dps.get("102", dps.get("24", dps.get("106", 0))),
                    "voc_mgm3": round(dps.get("21", 0) / 1000.0, 3),
                    "ch2o_mgm3": round(dps.get("22", 0) / 1000.0, 3),
                    "battery_pct": dps.get("15", 100),
                    "online": True
                })

                co2 = air_metrics_dict["co2_ppm"]

                # Handle high CO2 threshold override
                if co2 > CO2_HIGH_THRESHOLD and not co2_override_active:
                    logging.info(f"CO2 high threshold reached ({co2} ppm). Evaluating time and thermal conditions.")
                    co2_override_active = True
                    
                    target_speed = _get_target_speed()
                    indoor_temp = fetch_zigbee_temp(cloud, indoor_device_id) or air_metrics_dict.get("temperature_c", IDEAL_TEMP)
                    outdoor_temp = fetch_zigbee_temp(cloud, outdoor_device_id)
                    
                    if _should_use_direct_flow(indoor_temp, outdoor_temp):
                        logging.info(f"Thermal decision: Outdoor temp ({outdoor_temp}°C) closer to ideal than indoor ({indoor_temp}°C). Activating directional flux (NORTH_SOUTH).")
                        state_dict["flux"] = "NORTH_SOUTH"
                        if "FLUX_NORTH_SOUTH" in button_codes:
                            ir_device.send_button(button_codes["FLUX_NORTH_SOUTH"])
                        await asyncio.sleep(1.5)
                    else:
                        logging.info(f"Thermal decision: Indoor temp ({indoor_temp}°C) preferred over outdoor ({outdoor_temp}°C). Switching to MANUAL mode for temperature conservation.")
                        state_dict["mode"] = "MANUAL"
                        if "MODE_MANUAL" in button_codes:
                            ir_device.send_button(button_codes["MODE_MANUAL"])
                        await asyncio.sleep(1.5)

                    state_dict["speed"] = target_speed
                    speed_key = f"SPEED_{target_speed}"
                    if speed_key in button_codes:
                        logging.info(f"Setting ventilation speed to {target_speed}.")
                        ir_device.send_button(button_codes[speed_key])
                        
                    save_state_func(state_dict)

                # Handle normalization recovery
                elif co2 < CO2_LOW_THRESHOLD and co2_override_active:
                    logging.info(f"CO2 normalized ({co2} ppm). Evaluating thermal conditions for recovery state.")
                    co2_override_active = False
                    
                    indoor_temp = fetch_zigbee_temp(cloud, indoor_device_id) or air_metrics_dict.get("temperature_c", IDEAL_TEMP)
                    outdoor_temp = fetch_zigbee_temp(cloud, outdoor_device_id)

                    if _should_use_direct_flow(indoor_temp, outdoor_temp):
                        logging.info(f"Thermal recovery decision: Outdoor temp ({outdoor_temp}°C) closer to ideal than indoor ({indoor_temp}°C). Setting flux to NORTH_SOUTH at Speed 1.")
                        state_dict["flux"] = "NORTH_SOUTH"
                        if "FLUX_NORTH_SOUTH" in button_codes:
                            ir_device.send_button(button_codes["FLUX_NORTH_SOUTH"])
                        await asyncio.sleep(1.5)
                    else:
                        logging.info(f"Thermal recovery decision: Indoor temp ({indoor_temp}°C) preferred over outdoor ({outdoor_temp}°C). Setting default flux SOUTH_NORTH at Speed 1.")
                        state_dict["mode"] = "MANUAL"
                        if "MODE_MANUAL" in button_codes:
                            ir_device.send_button(button_codes["MODE_MANUAL"])
                        await asyncio.sleep(1.5)
                    
                    state_dict["speed"] = 1
                    if "SPEED_1" in button_codes:
                        ir_device.send_button(button_codes["SPEED_1"])

                    save_state_func(state_dict)

        except Exception as e:
            logging.error(f"SENSOR POLLING ERROR: {e}")
            air_metrics_dict["online"] = False

        await asyncio.sleep(10)