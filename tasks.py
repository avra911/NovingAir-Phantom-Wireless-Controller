import asyncio
from bisect import bisect_right
from contextlib import closing
import json
import logging
import os
import sqlite3
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
AIR_HISTORY_DB = os.environ.get("AIR_HISTORY_DB", "data/air_history.sqlite3")

AIR_HISTORY_FIELDS = (
    "co2_ppm",
    "co2_state",
    "temperature_c",
    "humidity_pct",
    "pm1_ugm3",
    "pm25_ugm3",
    "pm10_ugm3",
    "voc_mgm3",
    "ch2o_mgm3",
    "battery_pct",
    "online",
    "indoor_temperature_c",
    "indoor_humidity_pct",
    "indoor_battery",
    "outdoor_temperature_c",
    "outdoor_humidity_pct",
    "outdoor_battery",
    "zigbee_online",
)
SPEED_POWER_WATTS = {1: 4.2, 2: 5.5, 3: 6.7}
NIGHT_POWER_WATTS = 3.9

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

    return abs(outdoor_temp - IDEAL_TEMP) < abs(indoor_temp - IDEAL_TEMP)

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

def _create_air_history_schema(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE air_metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL,
            co2_ppm REAL,
            co2_state TEXT,
            temperature_c REAL,
            humidity_pct REAL,
            pm1_ugm3 REAL,
            pm25_ugm3 REAL,
            pm10_ugm3 REAL,
            voc_mgm3 REAL,
            ch2o_mgm3 REAL,
            battery_pct REAL,
            online INTEGER NOT NULL,
            indoor_temperature_c REAL,
            indoor_humidity_pct REAL,
            indoor_battery REAL,
            outdoor_temperature_c REAL,
            outdoor_humidity_pct REAL,
            outdoor_battery REAL,
            zigbee_online INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )

def save_air_metrics_snapshot(metrics: dict, db_path: str, fetched_at: datetime | None = None):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    timestamp = (fetched_at or _get_now()).isoformat()
    snapshot = {field: metrics.get(field) for field in AIR_HISTORY_FIELDS}

    with closing(sqlite3.connect(db_path)) as conn, conn:
        has_air_history_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'air_metrics_history'"
        ).fetchone()
        if not has_air_history_table:
            _create_air_history_schema(conn)

        conn.execute(
            """
            INSERT INTO air_metrics_history (
                fetched_at,
                co2_ppm,
                co2_state,
                temperature_c,
                humidity_pct,
                pm1_ugm3,
                pm25_ugm3,
                pm10_ugm3,
                voc_mgm3,
                ch2o_mgm3,
                battery_pct,
                online,
                indoor_temperature_c,
                indoor_humidity_pct,
                indoor_battery,
                outdoor_temperature_c,
                outdoor_humidity_pct,
                outdoor_battery,
                zigbee_online,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                snapshot["co2_ppm"],
                snapshot["co2_state"],
                snapshot["temperature_c"],
                snapshot["humidity_pct"],
                snapshot["pm1_ugm3"],
                snapshot["pm25_ugm3"],
                snapshot["pm10_ugm3"],
                snapshot["voc_mgm3"],
                snapshot["ch2o_mgm3"],
                snapshot["battery_pct"],
                int(bool(snapshot["online"])),
                snapshot["indoor_temperature_c"],
                snapshot["indoor_humidity_pct"],
                snapshot["indoor_battery"],
                snapshot["outdoor_temperature_c"],
                snapshot["outdoor_humidity_pct"],
                snapshot["outdoor_battery"],
                int(bool(snapshot["zigbee_online"])),
                json.dumps(snapshot),
            ),
        )

def get_air_metrics_history(db_path: str, limit: int = 180) -> list[dict]:
    if not os.path.exists(db_path):
        return []

    safe_limit = max(1, min(limit, 1440))

    try:
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    fetched_at,
                    co2_ppm,
                    temperature_c,
                    humidity_pct,
                    pm1_ugm3,
                    pm25_ugm3,
                    pm10_ugm3,
                    voc_mgm3,
                    ch2o_mgm3,
                    indoor_temperature_c,
                    indoor_humidity_pct,
                    outdoor_temperature_c,
                    outdoor_humidity_pct,
                    online,
                    zigbee_online
                FROM air_metrics_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    return [dict(row) for row in reversed(rows)]

def _create_phantom_history_schema(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS phantom_state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            changed_at TEXT NOT NULL,
            change_type TEXT NOT NULL,
            mode TEXT,
            flux TEXT,
            speed INTEGER,
            night INTEGER NOT NULL,
            boost INTEGER NOT NULL DEFAULT 0,
            estimated_power_w REAL
        )
        """
    )

    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(phantom_state_history)").fetchall()
    }
    if "flux" not in columns:
        conn.execute("ALTER TABLE phantom_state_history ADD COLUMN flux TEXT")
    if "boost" not in columns:
        conn.execute(
            "ALTER TABLE phantom_state_history ADD COLUMN boost INTEGER NOT NULL DEFAULT 0"
        )

def estimate_phantom_power_watts(
    speed: int | None,
    night: bool,
    boost: bool = False,
) -> float | None:
    if boost:
        return SPEED_POWER_WATTS[3]
    if night:
        return NIGHT_POWER_WATTS
    return SPEED_POWER_WATTS.get(speed)

def save_phantom_state_change(
    state: dict,
    change_type: str,
    db_path: str,
    changed_at: datetime | None = None,
):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    timestamp = (changed_at or _get_now()).isoformat()
    boost = bool(state.get("boost", False))
    speed = 3 if boost else state.get("speed")
    flux = state.get("flux")
    night = bool(state.get("night", False))
    estimated_power = estimate_phantom_power_watts(speed, night, boost)

    with closing(sqlite3.connect(db_path)) as conn, conn:
        _create_phantom_history_schema(conn)
        conn.execute(
            """
            INSERT INTO phantom_state_history (
                changed_at, change_type, mode, flux, speed, night, boost, estimated_power_w
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                change_type,
                state.get("mode"),
                flux,
                speed,
                int(night),
                int(boost),
                estimated_power,
            ),
        )

def get_phantom_state_history(
    db_path: str,
    limit: int = 1440,
    now: datetime | None = None,
) -> list[dict]:
    if not os.path.exists(db_path):
        return []

    safe_limit = max(1, min(limit, 1440))
    try:
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT changed_at, change_type, mode, flux, speed, night, boost, estimated_power_w
                FROM phantom_state_history
                ORDER BY julianday(changed_at) DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    history = [dict(row) for row in reversed(rows)]
    current_time = now or _get_now()
    for index, entry in enumerate(history):
        interval_end = (
            datetime.fromisoformat(history[index + 1]["changed_at"])
            if index + 1 < len(history)
            else current_time
        )
        interval_start = datetime.fromisoformat(entry["changed_at"])
        duration_seconds = max(0.0, (interval_end - interval_start).total_seconds())
        power_w = entry["estimated_power_w"]
        entry["estimated_energy_wh"] = (
            power_w * duration_seconds / 3600 if power_w is not None else None
        )

    return history

def _create_phantom_consumption_buckets(now: datetime) -> tuple[list[dict], list[dict]]:
    now_timestamp = now.timestamp()
    hourly = []
    hourly_start = now_timestamp - 24 * 60 * 60
    for index in range(24):
        start_timestamp = hourly_start + index * 60 * 60
        hourly.append(
            {
                "bucket_start": datetime.fromtimestamp(
                    start_timestamp, tz=now.tzinfo
                ).isoformat(),
                "start_timestamp": start_timestamp,
                "end_timestamp": start_timestamp + 60 * 60,
            }
        )

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily = []
    for days_ago in reversed(range(30)):
        start = today_start - timedelta(days=days_ago)
        end = min(start + timedelta(days=1), now)
        daily.append(
            {
                "bucket_start": start.date().isoformat(),
                "start_timestamp": start.timestamp(),
                "end_timestamp": end.timestamp(),
            }
        )

    return hourly, daily

def _integrate_phantom_energy_buckets(
    events: list[tuple[float, float | None]],
    buckets: list[dict],
    now_timestamp: float,
) -> list[dict]:
    if not buckets:
        return []

    bucket_starts = [bucket["start_timestamp"] for bucket in buckets]
    bucket_energy = [0.0] * len(buckets)
    bucket_known_seconds = [0.0] * len(buckets)
    range_start = buckets[0]["start_timestamp"]

    for index, (event_start, power_w) in enumerate(events):
        interval_end = events[index + 1][0] if index + 1 < len(events) else now_timestamp
        clipped_start = max(event_start, range_start)
        if interval_end <= clipped_start:
            continue

        bucket_index = max(0, bisect_right(bucket_starts, clipped_start) - 1)
        while bucket_index < len(buckets):
            bucket = buckets[bucket_index]
            overlap_seconds = min(interval_end, bucket["end_timestamp"]) - max(
                clipped_start, bucket["start_timestamp"]
            )
            if overlap_seconds > 0 and power_w is not None:
                bucket_energy[bucket_index] += power_w * overlap_seconds / 3600
                bucket_known_seconds[bucket_index] += overlap_seconds
            if bucket["end_timestamp"] >= interval_end:
                break
            bucket_index += 1

    result = []
    for index, bucket in enumerate(buckets):
        duration = max(0.0, bucket["end_timestamp"] - bucket["start_timestamp"])
        known_seconds = bucket_known_seconds[index]
        result.append(
            {
                "bucket_start": bucket["bucket_start"],
                "duration_seconds": duration,
                "energy_wh": bucket_energy[index] if known_seconds > 0 else None,
                "coverage_pct": (
                    min(100.0, known_seconds / duration * 100) if duration > 0 else 0.0
                ),
            }
        )
    return result

def get_phantom_consumption_summary(db_path: str, now: datetime | None = None) -> dict:
    current_time = now or _get_now()
    hourly_buckets, daily_buckets = _create_phantom_consumption_buckets(current_time)
    range_start = min(
        hourly_buckets[0]["start_timestamp"],
        daily_buckets[0]["start_timestamp"],
    )
    start_iso = datetime.fromtimestamp(range_start, tz=current_time.tzinfo).isoformat()
    end_iso = current_time.isoformat()
    events = []

    if os.path.exists(db_path):
        try:
            with closing(sqlite3.connect(db_path)) as conn, conn:
                previous = conn.execute(
                    """
                    SELECT id, changed_at, estimated_power_w
                    FROM phantom_state_history
                    WHERE julianday(changed_at) < julianday(?)
                    ORDER BY julianday(changed_at) DESC, id DESC
                    LIMIT 1
                    """,
                    (start_iso,),
                ).fetchall()
                rows = conn.execute(
                    """
                    SELECT id, changed_at, estimated_power_w
                    FROM phantom_state_history
                    WHERE julianday(changed_at) >= julianday(?)
                      AND julianday(changed_at) <= julianday(?)
                    ORDER BY julianday(changed_at), id
                    """,
                    (start_iso, end_iso),
                ).fetchall()
            for row in [*previous, *rows]:
                events.append(
                    (datetime.fromisoformat(row[1]).timestamp(), row[2])
                )
            events.sort(key=lambda event: event[0])
        except sqlite3.OperationalError:
            events = []

    return {
        "hourly": _integrate_phantom_energy_buckets(
            events, hourly_buckets, current_time.timestamp()
        ),
        "daily": _integrate_phantom_energy_buckets(
            events, daily_buckets, current_time.timestamp()
        ),
    }

# IR commands must run synchronously but be awaited via executor
def _send_ir(ir_device, button_codes: dict, button_name: str):
    code = button_codes.get(button_name)
    if code is None:
        logging.warning(f"IR code not found: {button_name}")
        return False
    try:
        result = ir_device.send_button(code)
        if result is None:
            logging.info("IR command %s", button_name)
        else:
            logging.info("IR command %s: %s", button_name, result)
        return True
    except Exception as e:
        logging.error(f"IR command failed for {button_name}: {e}")
        return False

async def _async_send_ir(loop, ir_device, button_codes: dict, button_name: str):
    return await loop.run_in_executor(None, _send_ir, ir_device, button_codes, button_name)

async def _async_save_phantom_state_change(loop, state: dict, change_type: str, db_path: str):
    try:
        await loop.run_in_executor(
            None,
            save_phantom_state_change,
            state.copy(),
            change_type,
            db_path,
        )
    except Exception as e:
        logging.error(f"PHANTOM HISTORY SAVE ERROR: {e}")

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
    air_history_db_path: str | None = None,
):
    print("[STARTUP] Starting air sensor automation...")
    logging.info("Air sensor automation started.")

    loop = asyncio.get_running_loop()
    last_speed_change = None
    last_auto_profile = None
    was_night = _is_night()

    if air_history_db_path:
        await _async_save_phantom_state_change(
            loop, state_dict, "startup", air_history_db_path
        )

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

            if air_history_db_path:
                try:
                    await loop.run_in_executor(
                        None,
                        save_air_metrics_snapshot,
                        air_metrics_dict.copy(),
                        air_history_db_path,
                    )
                except Exception as e:
                    logging.error(f"AIR HISTORY SAVE ERROR: {e}")

            # 3. Automation decision
            if not state_dict.get("automation_enabled", True):
                if state_dict.get("mode") == "AUTO" and not state_dict.get("boost", False):
                    profile_night = _is_night()
                    profile_speed = 1 if profile_night else 2
                    profile = (profile_night, profile_speed)
                    if profile != last_auto_profile and air_history_db_path:
                        estimated_state = state_dict.copy()
                        estimated_state["speed"] = profile_speed
                        estimated_state["night"] = profile_night
                        await _async_save_phantom_state_change(
                            loop, estimated_state, "auto_schedule", air_history_db_path
                        )
                    last_auto_profile = profile
                else:
                    last_auto_profile = None
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            last_auto_profile = None
            if state_dict.get("boost", False):
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
                    if air_history_db_path:
                        await _async_save_phantom_state_change(
                            loop, state_dict, "mode", air_history_db_path
                        )

            if state_dict.get("flux") != target_flux:
                if await _set_flux(loop, target_flux, ir_device, button_codes):
                    state_dict["flux"] = target_flux
                    state_changed = True
                    if air_history_db_path:
                        await _async_save_phantom_state_change(
                            loop, state_dict, "flux", air_history_db_path
                        )

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
                    if air_history_db_path:
                        await _async_save_phantom_state_change(
                            loop, state_dict, "speed", air_history_db_path
                        )

            # 7. Persist & cleanup
            was_night = night
            if state_changed:
                night_was_enabled = state_dict.get("night", False)
                state_dict["night"] = False
                if night_was_enabled and air_history_db_path:
                    await _async_save_phantom_state_change(
                        loop, state_dict, "night", air_history_db_path
                    )
                save_state_func(state_dict)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logging.info("Automation task cancelled.")
            raise
        except Exception as e:
            logging.exception(f"Unexpected automation error: {e}")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)