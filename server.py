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
from tasks import poll_air_sensor_task

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

# --- MODELS & CACHE ---
class PhantomState(BaseModel):
    mode: str = "AUTO"
    speed: int = 3
    humidity: int = 3
    flux: str = "SOUTH_NORTH"
    night: bool = False
    boost: bool = False

DEFAULT_STATE = PhantomState().model_dump()

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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(
        poll_air_sensor_task(
            co2_sensor=co2_sensor,
            ir_device=ir_device,
            button_codes=BUTTON_CODES,
            state_dict=CURRENT_STATE,
            air_metrics_dict=AIR_METRICS,
            save_state_func=save_state,
            cloud=cloud,
            indoor_device_id=os.getenv("INDOOR_SENSOR_DEVICE_ID"),
            outdoor_device_id=os.getenv("OUTDOOR_SENSOR_DEVICE_ID")
        )
    )

# --- TUYA CLOUD INIT ---
cloud = tinytuya.Cloud(
    apiRegion=os.getenv("TUYA_API_REGION", "eu"),
    apiKey=os.getenv("TUYA_API_CLIENT_ID"),
    apiSecret=os.getenv("TUYA_API_SECRET")
)

def get_zigbee_sensor_data(device_id: str):
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
        raw_hum = dps.get("va_humidity") or dps.get("humidity") or dps.get("humidity_value")
        battery = dps.get("battery_percentage") or dps.get("battery_state") or dps.get("battery")

        temp_c = None
        if raw_temp is not None:
            temp_c = raw_temp / 10.0 if raw_temp > 60 else float(raw_temp)

        hum_pct = None
        if raw_hum is not None:
            hum_pct = raw_hum / 10.0 if raw_hum > 100 else float(raw_hum)

        return {
            "temperature_c": temp_c,
            "humidity_pct": hum_pct,
            "battery": battery
        }
    except Exception as e:
        print(f"Error fetching Zigbee sensor {device_id}: {e}")
        return {"temperature_c": None, "humidity_pct": None, "battery": None}

# --- ENDPOINTS ---
@app.get("/state")
def get_state():
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS,
        "indoor": get_zigbee_sensor_data(os.getenv("INDOOR_SENSOR_DEVICE_ID")),
        "outdoor": get_zigbee_sensor_data(os.getenv("OUTDOOR_SENSOR_DEVICE_ID"))
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
        fluxes = ["SOUTH_NORTH", "EXTRACT", "INTAKE", "NORTH_SOUTH"]
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
    
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)