from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import asyncio
import json
import os

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

from gateway import TuyaGateway
from tasks import poll_air_sensor_task

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE_FILE = "state.json"
BUTTON_CODES_FILE = "phantom_ir.json"

# ---------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------
ir_device = IRRemoteControlDevice(
    dev_id=IR_DEVICE_ID,
    address=IR_ADDRESS,
    local_key=IR_LOCAL_KEY,
    version=3.3,
    control_type=1,
)

co2_sensor = tinytuya.Device(
    dev_id=SENSOR_DEVICE_ID,
    address=SENSOR_ADDRESS,
    local_key=SENSOR_LOCAL_KEY,
    version=3.5,
)
co2_sensor.set_socketTimeout(3)

# Integrarea locala Zigbee (inlocuieste Tuya Cloud)
gateway = TuyaGateway()

# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------
class PhantomState(BaseModel):
    mode: str = "AUTO"
    speed: int = 3
    humidity: int = 3
    flux: str = "SOUTH_NORTH"
    night: bool = False
    boost: bool = False
    automation_enabled: bool = True

DEFAULT_STATE = PhantomState().model_dump()

AIR_METRICS = {
    # Main air-quality sensor
    "co2_ppm": None,
    "co2_state": None,
    "temperature_c": None,
    "humidity_pct": None,
    "pm1_ugm3": None,
    "pm25_ugm3": None,
    "pm10_ugm3": None,
    "voc_mgm3": None,
    "ch2o_mgm3": None,
    "battery_pct": None,
    "online": False,

    # Local Zigbee sensors
    "indoor_temperature_c": None,
    "indoor_humidity_pct": None,
    "indoor_battery": None,

    "outdoor_temperature_c": None,
    "outdoor_humidity_pct": None,
    "outdoor_battery": None,

    "zigbee_online": False,
}

# ---------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            for key, value in DEFAULT_STATE.items():
                if key not in data:
                    data[key] = value
            return data
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

# ---------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    print("[STARTUP] Starting air sensor automation...")
    asyncio.create_task(
        poll_air_sensor_task(
            co2_sensor=co2_sensor,
            ir_device=ir_device,
            button_codes=BUTTON_CODES,
            state_dict=CURRENT_STATE,
            air_metrics_dict=AIR_METRICS,
            save_state_func=save_state,
            gateway=gateway,
        )
    )
    print("[STARTUP] Air sensor automation started.")

# ---------------------------------------------------------------------
# IR helper (Metoda originala: send_button)
# ---------------------------------------------------------------------
def send_ir_button(button_name: str):
    code = BUTTON_CODES.get(button_name)
    if code is None:
        raise HTTPException(
            status_code=404,
            detail=f"IR button not found: {button_name}",
        )
    try:
        result = ir_device.send_button(code)
        print(f"[IR SENT] {button_name} | Result: {result}")
        return result
    except Exception as e:
        print(f"[IR ERROR] Failed to send {button_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"IR command failed: {e}",
        )

# ---------------------------------------------------------------------
# API
# ---------------------------------------------------------------------
@app.get("/state")
async def get_state():
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS,
        "indoor": {
            "temperature_c": AIR_METRICS.get("indoor_temperature_c"),
            "humidity_pct": AIR_METRICS.get("indoor_humidity_pct"),
            "battery": AIR_METRICS.get("indoor_battery"),
        },
        "outdoor": {
            "temperature_c": AIR_METRICS.get("outdoor_temperature_c"),
            "humidity_pct": AIR_METRICS.get("outdoor_humidity_pct"),
            "battery": AIR_METRICS.get("outdoor_battery"),
        },
    }

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "NovingAIR local hub",
    }

# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------
@app.post("/command/{action}")
async def command(action: str):
    action = action.upper()

    if action == "SPEED":
        current_speed = CURRENT_STATE.get("speed", 3)
        new_speed = 1 if current_speed >= 3 else current_speed + 1
        send_ir_button(f"SPEED_{new_speed}")
        CURRENT_STATE["speed"] = new_speed

    elif action == "HUMIDITY":
        current_humidity = CURRENT_STATE.get("humidity", 3)
        new_humidity = 1 if current_humidity >= 3 else current_humidity + 1
        send_ir_button(f"HUMIDITY_{new_humidity}")
        CURRENT_STATE["humidity"] = new_humidity

    elif action == "MODE":
        modes = ["AUTO", "SLEEP", "MANUAL"]
        current_mode = CURRENT_STATE.get("mode", "AUTO")
        idx = modes.index(current_mode) if current_mode in modes else -1
        new_mode = modes[(idx + 1) % len(modes)]
        send_ir_button(f"MODE_{new_mode}")
        CURRENT_STATE["mode"] = new_mode
        CURRENT_STATE["flux"] = "NONE"
        CURRENT_STATE["boost"] = False

    elif action == "FLUX":
        fluxes = ["SOUTH_NORTH", "EXTRACT", "INTAKE", "NORTH_SOUTH"]
        current_flux = CURRENT_STATE.get("flux", "SOUTH_NORTH")
        idx = fluxes.index(current_flux) if current_flux in fluxes else -1
        new_flux = fluxes[(idx + 1) % len(fluxes)]
        send_ir_button(f"FLUX_{new_flux}")
        CURRENT_STATE["flux"] = new_flux
        CURRENT_STATE["mode"] = "NONE"
        CURRENT_STATE["boost"] = False

    elif action == "NIGHT":
        new_night = not CURRENT_STATE.get("night", False)
        send_ir_button("MODE_NIGHT")
        CURRENT_STATE["night"] = new_night

    elif action == "BOOST":
        new_boost = not CURRENT_STATE.get("boost", False)
        send_ir_button("BOOST")
        CURRENT_STATE["boost"] = new_boost
        if new_boost:
            CURRENT_STATE["mode"] = "NONE"
            CURRENT_STATE["flux"] = "NONE"

    elif action == "TOGGLE_AUTO":
        CURRENT_STATE["automation_enabled"] = not CURRENT_STATE.get("automation_enabled", True)

    elif action == "RESET":
        send_ir_button("RESET")
        CURRENT_STATE.clear()
        CURRENT_STATE.update(DEFAULT_STATE.copy())

    else:
        raise HTTPException(status_code=400, detail=f"Unknown command: {action}")

    save_state(CURRENT_STATE)
    return {
        "phantom": CURRENT_STATE,
        "sensor": AIR_METRICS,
        "indoor": {
            "temperature_c": AIR_METRICS.get("indoor_temperature_c"),
            "humidity_pct": AIR_METRICS.get("indoor_humidity_pct"),
            "battery": AIR_METRICS.get("indoor_battery"),
        },
        "outdoor": {
            "temperature_c": AIR_METRICS.get("outdoor_temperature_c"),
            "humidity_pct": AIR_METRICS.get("outdoor_humidity_pct"),
            "battery": AIR_METRICS.get("outdoor_battery"),
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)