from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import asyncio
import json
import logging
import os
import time

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
from tasks import AIR_HISTORY_DB, get_air_metrics_history, poll_air_sensor_task

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
AUTOMATION_LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "automation.log")
BOOST_DURATION_SECONDS = 20 * 60

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
    last_mode: str = "AUTO"
    speed: int = 3
    humidity: int = 3
    flux: str = "NONE"
    last_flux: str = "NORTH_SOUTH"
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
            if data.get("last_mode") not in ("AUTO", "SLEEP", "MANUAL"):
                current_mode = data.get("mode")
                data["last_mode"] = current_mode if current_mode in ("AUTO", "SLEEP", "MANUAL") else "AUTO"
            if data.get("last_flux") not in ("SOUTH_NORTH", "EXTRACT", "INTAKE", "NORTH_SOUTH"):
                current_flux = data.get("flux")
                data["last_flux"] = current_flux if current_flux in ("SOUTH_NORTH", "EXTRACT", "INTAKE", "NORTH_SOUTH") else "NORTH_SOUTH"
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
boost_task: asyncio.Task | None = None


def _boost_snapshot() -> dict:
    return {
        key: CURRENT_STATE.get(key)
        for key in (
            "mode",
            "speed",
            "humidity",
            "flux",
            "night",
            "automation_enabled",
        )
    }


def _restore_boost_state() -> None:
    snapshot = CURRENT_STATE.pop("boost_previous_state", None)
    if not isinstance(snapshot, dict):
        snapshot = {
            "mode": "AUTO",
            "speed": 1,
            "humidity": 3,
            "flux": "NONE",
            "night": False,
            "automation_enabled": True,
        }

    send_ir_button("BOOST")
    CURRENT_STATE.update(snapshot)
    CURRENT_STATE["boost"] = False
    CURRENT_STATE.pop("boost_expires_at", None)
    save_state(CURRENT_STATE)


async def _boost_timer(expires_at: float) -> None:
    await asyncio.sleep(max(0, expires_at - time.time()))
    if CURRENT_STATE.get("boost") and CURRENT_STATE.get("boost_expires_at") == expires_at:
        _restore_boost_state()


async def _start_boost() -> None:
    global boost_task

    snapshot = _boost_snapshot()
    expires_at = time.time() + BOOST_DURATION_SECONDS
    send_ir_button("BOOST")

    CURRENT_STATE["boost_previous_state"] = snapshot
    CURRENT_STATE["boost_expires_at"] = expires_at
    CURRENT_STATE["boost"] = True
    save_state(CURRENT_STATE)
    boost_task = asyncio.create_task(_boost_timer(expires_at))


async def _stop_boost() -> None:
    global boost_task

    if boost_task is not None:
        boost_task.cancel()
        boost_task = None
    if CURRENT_STATE.get("boost"):
        _restore_boost_state()

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
            air_history_db_path=AIR_HISTORY_DB,
        )
    )
    if CURRENT_STATE.get("boost") and CURRENT_STATE.get("boost_expires_at"):
        global boost_task
        boost_task = asyncio.create_task(_boost_timer(CURRENT_STATE["boost_expires_at"]))
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
        if result is None:
            logging.info("IR command %s", button_name)
            print(f"[IR SENT] {button_name}")
        else:
            logging.info("IR command %s: %s", button_name, result)
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

@app.get("/history")
async def get_history(limit: int = Query(default=1440, ge=1, le=1440)):
    return {
        "history": get_air_metrics_history(AIR_HISTORY_DB, limit),
    }

@app.get("/logs/automation")
async def get_automation_log(lines: int = Query(default=120, ge=1, le=500)):
    try:
        with open(AUTOMATION_LOG_FILE, "r", encoding="utf-8", errors="replace") as log_file:
            log_lines = log_file.readlines()
    except FileNotFoundError:
        return {"lines": [], "available": False}

    return {
        "lines": [line.rstrip("\n") for line in reversed(log_lines[-lines:])],
        "available": True,
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
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        current_speed = CURRENT_STATE.get("speed", 3)
        new_speed = 1 if current_speed >= 3 else current_speed + 1
        send_ir_button(f"SPEED_{new_speed}")
        CURRENT_STATE["speed"] = new_speed

    elif action == "HUMIDITY":
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        current_humidity = CURRENT_STATE.get("humidity", 3)
        new_humidity = 1 if current_humidity >= 3 else current_humidity + 1
        send_ir_button(f"HUMIDITY_{new_humidity}")
        CURRENT_STATE["humidity"] = new_humidity

    elif action == "MODE":
        modes = ["AUTO", "SLEEP", "MANUAL"]
        current_mode = CURRENT_STATE.get("mode", "AUTO")
        if current_mode == "NONE":
            remembered_mode = CURRENT_STATE.get("last_mode", "AUTO")
            new_mode = remembered_mode if remembered_mode in modes else "AUTO"
        else:
            idx = modes.index(current_mode) if current_mode in modes else -1
            new_mode = modes[(idx + 1) % len(modes)]
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        send_ir_button(f"MODE_{new_mode}")
        CURRENT_STATE["mode"] = new_mode
        CURRENT_STATE["last_mode"] = new_mode
        CURRENT_STATE["flux"] = "NONE"
        CURRENT_STATE["boost"] = False

    elif action == "FLUX":
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        fluxes = ["SOUTH_NORTH", "EXTRACT", "INTAKE", "NORTH_SOUTH"]
        current_flux = CURRENT_STATE.get("flux", "NONE")
        if current_flux == "NONE":
            remembered_flux = CURRENT_STATE.get("last_flux", "NORTH_SOUTH")
            new_flux = remembered_flux if remembered_flux in fluxes else "NORTH_SOUTH"
        else:
            idx = fluxes.index(current_flux) if current_flux in fluxes else -1
            new_flux = fluxes[(idx + 1) % len(fluxes)]
        send_ir_button(f"FLUX_{new_flux}")
        CURRENT_STATE["flux"] = new_flux
        CURRENT_STATE["last_flux"] = new_flux
        CURRENT_STATE["mode"] = "NONE"
        CURRENT_STATE["boost"] = False

    elif action == "NIGHT":
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        new_night = not CURRENT_STATE.get("night", False)
        send_ir_button("MODE_NIGHT")
        CURRENT_STATE["night"] = new_night
        if new_night:
            CURRENT_STATE["mode"] = "NONE"
            CURRENT_STATE["flux"] = "NONE"
            CURRENT_STATE["boost"] = False

    elif action == "BOOST":
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        else:
            await _start_boost()
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

    elif action == "TOGGLE_AUTO":
        if CURRENT_STATE.get("boost"):
            await _stop_boost()
        new_state = not CURRENT_STATE.get("automation_enabled", True)
        CURRENT_STATE["automation_enabled"] = new_state
        logging.info("Remote command TOGGLE_AUTO: %s", "enabled" if new_state else "disabled")
        if not new_state:
            # Inject an instant reset flag for the background task to catch
            CURRENT_STATE["reset_speed_lock"] = True

    elif action == "RESET":
        send_ir_button("RESET")

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