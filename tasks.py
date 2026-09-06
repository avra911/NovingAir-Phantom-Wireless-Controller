import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

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
    current_hour = datetime.now(ZoneInfo("Europe/Bucharest")).hour
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
                
                # Update local metrics
                if "1" in dps: air_metrics_dict["co2_state"] = dps["1"]
                if "2" in dps: air_metrics_dict["co2_ppm"] = dps["2"]
                if "18" in dps: air_metrics_dict["temperature_c"] = dps["18"]
                if "19" in dps: air_metrics_dict["humidity_pct"] = dps["19"]
                
                pm1 = dps.get("101") or dps.get("23") or dps.get("105")
                if pm1 is not None: air_metrics_dict["pm1_ugm3"] = pm1
                if "20" in dps: air_metrics_dict["pm25_ugm3"] = dps["20"]
                pm10 = dps.get("102") or dps.get("24") or dps.get("106")
                if pm10 is not None: air_metrics_dict["pm10_ugm3"] = pm10
                
                if "21" in dps: air_metrics_dict["voc_mgm3"] = round(dps["21"] / 1000.0, 3)
                if "22" in dps: air_metrics_dict["ch2o_mgm3"] = round(dps["22"] / 1000.0, 3)
                if "15" in dps: air_metrics_dict["battery_pct"] = dps["15"]
                
                air_metrics_dict["online"] = True

                # ==========================================
                # CONTINUOUS ADAPTIVE AUTOMATION LOGIC
                # ==========================================
                if not state_dict.get("automation_enabled", True):
                    co2_override_active = False
                else:
                    co2 = air_metrics_dict.get("co2_ppm")
                    if co2 is None:
                        co2 = 400 # Failsafe to prevent crashes if sensor glitch occurs
                        
                    # 1. Determine Target Speed (Clean air = 1, Bad air = 2 or 3)
                    if co2 > CO2_HIGH_THRESHOLD or (co2_override_active and co2 >= CO2_LOW_THRESHOLD):
                        co2_override_active = True
                        target_speed = _get_target_speed()
                    else:
                        co2_override_active = False
                        target_speed = 1
                        
                    # 2. Fetch Temps (using executor so Tuya Cloud doesn't block FastAPI)
                    indoor_temp_raw = await loop.run_in_executor(None, fetch_zigbee_temp, cloud, indoor_device_id)
                    outdoor_temp = await loop.run_in_executor(None, fetch_zigbee_temp, cloud, outdoor_device_id)
                    
                    indoor_temp = indoor_temp_raw if indoor_temp_raw is not None else air_metrics_dict.get("temperature_c", IDEAL_TEMP)

                    # 3. Determine Target Mode/Flux based on Temps
                    if _should_use_direct_flow(indoor_temp, outdoor_temp):
                        target_mode = "NONE"
                        target_flux = "NORTH_SOUTH"
                    else:
                        target_mode = "MANUAL"
                        target_flux = "NONE"
                        
                    target_boost = False
                    state_changed = False
                    
                    # 4. Compare Actual State vs Target State and Fire IR Commands
                    if state_dict.get("mode") != target_mode or state_dict.get("flux") != target_flux:
                        logging.info(f"Thermal decision changed: Mode -> {target_mode}, Flux -> {target_flux} (In: {indoor_temp}, Out: {outdoor_temp})")
                        state_dict["mode"] = target_mode
                        state_dict["flux"] = target_flux
                        state_dict["boost"] = target_boost
                        
                        ir_key = "FLUX_NORTH_SOUTH" if target_flux == "NORTH_SOUTH" else "MODE_MANUAL"
                        if ir_key in button_codes:
                            # Using executor so IR blaster networking doesn't block loop
                            await loop.run_in_executor(None, ir_device.send_button, button_codes[ir_key])
                        
                        state_changed = True
                        await asyncio.sleep(1.5) # Protect IR unit from command spam
                    
                    if state_dict.get("speed") != target_speed:
                        logging.info(f"Speed changed -> {target_speed} (CO2: {co2}, Active: {co2_override_active})")
                        state_dict["speed"] = target_speed
                        speed_key = f"SPEED_{target_speed}"
                        
                        if speed_key in button_codes:
                            await loop.run_in_executor(None, ir_device.send_button, button_codes[speed_key])
                            
                        state_changed = True
                        
                    # 5. Persist if state shifted
                    if state_changed:
                        save_state_func(state_dict)

        except Exception as e:
            logging.error(f"SENSOR POLLING ERROR: {e}")
            air_metrics_dict["online"] = False

        await asyncio.sleep(10)