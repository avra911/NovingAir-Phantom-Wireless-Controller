from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import json
import os
import asyncio
import tinytuya
from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice
from config import (
    IR_DEVICE_ID,
    IR_ADDRESS,
    IR_LOCAL_KEY,
    SENSOR_DEVICE_ID,
    SENSOR_ADDRESS,
    SENSOR_LOCAL_KEY,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DEVICE CONFIGURATION ---
STATE_FILE = "state.json"
BUTTON_CODES_FILE = "phantom_ir.json"

# --- TUYA DEVICE INITIALIZATION ---
ir_device = IRRemoteControlDevice(
    dev_id=IR_DEVICE_ID,
    address=IR_ADDRESS,
    local_key=IR_LOCAL_KEY,
    version=3.3,
    control_type=1
)

# 8-in-1 Sensor (Protocol 3.5)
co2_sensor = tinytuya.Device(
    dev_id=SENSOR_DEVICE_ID,
    address=SENSOR_ADDRESS,
    local_key=SENSOR_LOCAL_KEY,
    version=3.5
)
co2_sensor.set_socketTimeout(3)

co2_override_active = False

# --- MODELS & CACHE ---
class PhantomState(BaseModel):
    mode: str = "AUTO"
    speed: int = 3
    humidity: int = 3
    flux: str = "RECOVERY"
    night: bool = False
    boost: bool = False

DEFAULT_STATE = PhantomState().model_dump()

# Expanded to 8 metrics + battery status
AIR_METRICS = {
    "co2_ppm": 0,
    "co2_state": "normal",
    "temperature_c": 0,
    "humidity_pct": 0,
    "pm1_ugm3": 0,
    "pm25_ugm3": 0,
    "pm10_ugm3": 0,
    "voc_mgm3": 0.0,
    "ch2o_mgm3": 0.0,
    "battery_pct": 100,
    "online": False
}

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_STATE.copy()

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_button_codes() -> dict:
    if os.path.exists(BUTTON_CODES_FILE):
        with open(BUTTON_CODES_FILE, "r") as f:
            return json.load(f)
    print(f"Warning: {BUTTON_CODES_FILE} not found!")
    return {}

CURRENT_STATE = load_state()
BUTTON_CODES = load_button_codes()

# --- BACKGROUND SENSOR POLLING ---
async def poll_air_sensor_task():
    """Polls the 8-in-1 sensor every 10 seconds and automates the HRV based on CO2."""
    global AIR_METRICS, CURRENT_STATE, co2_override_active
    
    while True:
        try:
            loop = asyncio.get_event_loop()
            status = await loop.run_in_executor(None, co2_sensor.status)
            
            if status and 'dps' in status:
                dps = status['dps']
                
                # Update Metrics
                AIR_METRICS.update({
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

                co2 = AIR_METRICS["co2_ppm"]

                # ==========================================
                # AUTOMATION LOGIC
                # ==========================================

                """
                HEALTH THRESHOLDS FOR AIR QUALITY METRICS
                
                Metric      | Good          | Moderate      | Unhealthy
                ============|===============|===============|===============
                CO2         | <800 ppm      | 800-1200      | >1200
                Temp        | 18-24°C       | 15-28°C       | <15 or >28
                Humidity    | 30-50%        | 25-60%        | <25 or >60%
                PM1.0       | <12 µg/m³     | 12-35         | 35-55 | >55
                PM2.5       | <12 µg/m³     | 12-35         | 35-55 | >55
                PM10        | <12 µg/m³     | 12-35         | 35-55 | >55
                TVOC        | <0.3 mg/m³    | 0.3-1.0       | >1.0
                HCHO        | <0.05 mg/m³   | 0.05-0.1      | >0.1
                
                Color coding:
                Cyan (#00ffcc) = Good/Healthy
                Orange (#f39c12) = Moderate/Caution
                Red (#e74c3c) = Unhealthy/Poor
                """
                
                # TRIGGER OVERRIDE: CO2 > 1200 (Unhealthy CO2)
                if co2 > 1200 and not co2_override_active:
                    print(f"[AUTOMATION] CO2 high ({co2} ppm). Forcing quiet MANUAL Speed 2.")
                    co2_override_active = True
                    
                    # 1. Switch to MANUAL
                    CURRENT_STATE["mode"] = "MANUAL"
                    if "MODE_MANUAL" in BUTTON_CODES:
                        ir_device.send_button(BUTTON_CODES["MODE_MANUAL"])
                        
                    await asyncio.sleep(1.5)
                    
                    # 2. Switch to SPEED 2 (Balanced noise and airflow)
                    CURRENT_STATE["speed"] = 2
                    if "SPEED_2" in BUTTON_CODES:
                        ir_device.send_button(BUTTON_CODES["SPEED_2"])
                        
                    save_state(CURRENT_STATE)

                # RECOVER OVERRIDE: CO2 < 800 (Good CO2)
                elif co2 < 800 and co2_override_active:
                    print(f"[AUTOMATION] CO2 normalized ({co2} ppm). Restoring AUTO mode.")
                    co2_override_active = False
                    
                    # 1. Switch to MANUAL
                    CURRENT_STATE["mode"] = "MANUAL"
                    if "MODE_MANUAL" in BUTTON_CODES:
                        ir_device.send_button(BUTTON_CODES["MODE_MANUAL"])
                        
                    await asyncio.sleep(1.5)
                    
                    # 2. Switch to SPEED 1 (Balanced noise and airflow)
                    CURRENT_STATE["speed"] = 1
                    if "SPEED_1" in BUTTON_CODES:
                        ir_device.send_button(BUTTON_CODES["SPEED_1"])
                        
                    save_state(CURRENT_STATE)


        except Exception as e:
            print(f"[SENSOR POLLING ERROR] {e}")
            AIR_METRICS["online"] = False

        await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_air_sensor_task())

# --- ENDPOINTS ---
@app.get("/state")
def get_state():
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS
    }

@app.post("/command/{action}")
def handle_command(action: str, payload: Optional[dict] = Body(None)):
    global CURRENT_STATE
    btn_key = action.upper()
    target_ir_key = None

    if btn_key == "SPEED":
        CURRENT_STATE["speed"] = 1 if CURRENT_STATE["speed"] >= 3 else CURRENT_STATE["speed"] + 1
        target_ir_key = f"SPEED_{CURRENT_STATE['speed']}"
        
    elif btn_key == "HUMIDITY":
        CURRENT_STATE["humidity"] = 1 if CURRENT_STATE["humidity"] >= 3 else CURRENT_STATE["humidity"] + 1
        target_ir_key = f"HUMIDITY_{CURRENT_STATE['humidity']}"
        
    elif btn_key == "MODE":
        modes = ["AUTO", "SLEEP", "MANUAL"]
        idx = modes.index(CURRENT_STATE["mode"]) if CURRENT_STATE["mode"] in modes else 0
        CURRENT_STATE["mode"] = modes[(idx + 1) % len(modes)]
        target_ir_key = f"MODE_{CURRENT_STATE['mode']}"
        
    elif btn_key == "FLUX":
        fluxes = ["RECOVERY", "SLAVE_MASTER", "INTAKE", "EXTRACT"]
        idx = fluxes.index(CURRENT_STATE["flux"]) if CURRENT_STATE["flux"] in fluxes else 0
        CURRENT_STATE["flux"] = fluxes[(idx + 1) % len(fluxes)]
        target_ir_key = f"FLUX_{CURRENT_STATE['flux']}"
        
    elif btn_key == "NIGHT":
        CURRENT_STATE["night"] = not CURRENT_STATE["night"]
        target_ir_key = "MODE_NIGHT"
        
    elif btn_key == "BOOST":
        CURRENT_STATE["boost"] = not CURRENT_STATE["boost"]
        target_ir_key = "BOOST"
        
    elif btn_key == "RESET":
        target_ir_key = "RESET"

    # Transmit IR command
    if target_ir_key and target_ir_key in BUTTON_CODES:
        code = BUTTON_CODES[target_ir_key]
        try:
            result = ir_device.send_button(code)
            print(f"[IR SENT] Target State: {target_ir_key} | Result: {result}")
        except Exception as e:
            print(f"[IR ERROR] Failed to send {target_ir_key}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        print(f"[WARNING] Key '{target_ir_key}' not mapped in {BUTTON_CODES_FILE}")

    save_state(CURRENT_STATE)
    
    # Return the combined updated state
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)