import argparse
from collections import Counter
import json
import re
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
BUCHAREST = ZoneInfo("Europe/Bucharest")
LINE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[INFO\] (.*)$")
SPEED_POWER_WATTS = {1: 4.2, 2: 5.5, 3: 6.7}


def _append_event(events, state, when, change_type):
    boost = state["boost"]
    speed = 3 if boost else state["speed"]
    if boost:
        power_w = SPEED_POWER_WATTS[3]
    elif state["night"]:
        power_w = 3.9
    else:
        power_w = SPEED_POWER_WATTS.get(speed)

    events.append(
        (
            when.isoformat(),
            f"reconstructed:{change_type}",
            state["mode"],
            state["flux"],
            speed,
            int(state["night"]),
            int(boost),
            power_w,
        )
    )


def _apply_auto_profile(events, state, when):
    if state["automation_enabled"] is not False or state["mode"] != "AUTO" or state["boost"]:
        return

    night = when.hour >= 21 or when.hour < 8
    speed = 1 if night else 2
    if (state["speed"], state["night"]) != (speed, night):
        state["speed"], state["night"] = speed, night
        _append_event(events, state, when, "auto_schedule")


def _advance_auto_schedule(events, state, start, end):
    if (
        start is None
        or end <= start
        or state["automation_enabled"] is not False
        or state["mode"] != "AUTO"
        or state["boost"]
    ):
        return

    cursor = start
    while True:
        candidates = []
        for day_offset in (0, 1):
            day = (cursor + timedelta(days=day_offset)).date()
            for hour in (8, 21):
                boundary = datetime.combine(day, time(hour), tzinfo=BUCHAREST)
                if cursor < boundary <= end:
                    candidates.append(boundary)
        if not candidates:
            return
        boundary = min(candidates)
        _apply_auto_profile(events, state, boundary)
        cursor = boundary


def replay_log(log_path: Path, state_path: Path):
    state = {
        "mode": None,
        "flux": None,
        "speed": None,
        "night": False,
        "boost": False,
        "automation_enabled": None,
    }
    events = []
    last_timestamp = None

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE_PATTERN.match(line)
        if not match:
            continue

        timestamp = datetime.strptime(
            match.group(1), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc).astimezone(BUCHAREST)
        _advance_auto_schedule(events, state, last_timestamp, timestamp)
        message = match.group(2)
        before = (
            state["mode"], state["flux"], state["speed"], state["night"], state["boost"]
        )
        change_type = None

        automation_match = re.search(
            r"Remote command TOGGLE_AUTO: (enabled|disabled)", message
        )
        if automation_match:
            state["automation_enabled"] = automation_match.group(1) == "enabled"
        elif message == "IR command BOOST":
            state["boost"] = not state["boost"]
            change_type = "boost"
        else:
            command_match = re.search(
                r"IR command (SPEED_[123]|MODE_(?:AUTO|SLEEP|MANUAL|NIGHT)|"
                r"FLUX_(?:NORTH_SOUTH|SOUTH_NORTH|INTAKE|EXTRACT))",
                message,
            )
            if command_match:
                button = command_match.group(1)
                if button.startswith("SPEED_"):
                    state["speed"] = int(button[-1])
                    change_type = "speed"
                elif button == "MODE_NIGHT":
                    state["night"] = not state["night"]
                    if state["night"]:
                        state["mode"], state["flux"] = "NONE", "NONE"
                    change_type = "night"
                elif button.startswith("MODE_"):
                    state["mode"], state["flux"] = button[5:], "NONE"
                    change_type = "mode+flux"
                elif button.startswith("FLUX_"):
                    state["mode"], state["flux"] = "NONE", button[5:]
                    change_type = "mode+flux"

        after = (
            state["mode"], state["flux"], state["speed"], state["night"], state["boost"]
        )
        if change_type and before != after:
            _append_event(events, state, timestamp, change_type)
        _apply_auto_profile(events, state, timestamp)
        last_timestamp = timestamp

    current_state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_state = {
        "mode": current_state.get("mode"),
        "flux": current_state.get("flux"),
        "speed": current_state.get("speed"),
        "night": bool(current_state.get("night", False)),
        "boost": bool(current_state.get("boost", False)),
        "automation_enabled": bool(current_state.get("automation_enabled", True)),
    }
    if state != expected_state:
        raise RuntimeError(
            f"Replayed log state does not match state.json: {state!r} != {expected_state!r}"
        )
    if not events:
        raise RuntimeError("No reconstructable state events found")
    return events, state


def _ensure_schema(conn):
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
        row[1] for row in conn.execute("PRAGMA table_info(phantom_state_history)")
    }
    if "flux" not in columns:
        conn.execute("ALTER TABLE phantom_state_history ADD COLUMN flux TEXT")
    if "boost" not in columns:
        conn.execute(
            "ALTER TABLE phantom_state_history ADD COLUMN boost INTEGER NOT NULL DEFAULT 0"
        )


def _event_identity(changed_at, mode, flux, speed, night, boost):
    timestamp = datetime.fromisoformat(changed_at)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (
        int(timestamp.timestamp()),
        mode,
        flux,
        speed,
        int(night),
        int(boost),
    )


def import_events(db_path: Path, events, apply=False):
    if apply:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30)
    elif db_path.exists():
        conn = sqlite3.connect(db_path)
    else:
        return len(events), 0

    try:
        if apply:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_schema(conn)
        try:
            rows = conn.execute(
                "SELECT changed_at, mode, flux, speed, night, boost "
                "FROM phantom_state_history"
            )
            identities = {_event_identity(*row) for row in rows.fetchall()}
        except sqlite3.OperationalError:
            identities = set()

        pending = []
        duplicates = 0
        for event in events:
            identity = _event_identity(
                event[0], event[2], event[3], event[4], event[5], event[6]
            )
            if identity in identities:
                duplicates += 1
                continue
            identities.add(identity)
            pending.append(event)

        if apply and pending:
            conn.executemany(
                """
                INSERT INTO phantom_state_history (
                    changed_at, change_type, mode, flux, speed, night, boost,
                    estimated_power_w
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pending,
            )
        if apply:
            conn.commit()
        return len(pending), duplicates
    except Exception:
        if apply:
            conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Import Phantom state history reconstructed from UTC automation logs."
    )
    parser.add_argument("--log", type=Path, default=ROOT / "logs/automation.log")
    parser.add_argument("--state", type=Path, default=ROOT / "state.json")
    parser.add_argument("--db", type=Path, default=ROOT / "data/air_history.sqlite3")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write missing events (default is a read-only preview)",
    )
    args = parser.parse_args()

    try:
        events, state = replay_log(args.log, args.state)
        inserted, duplicates = import_events(args.db, events, apply=args.apply)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
        parser.error(str(error))

    counts = Counter(event[1] for event in events)
    action = "Inserted" if args.apply else "Would insert"
    print(f"Replayed {len(events)} events: {dict(counts)}")
    print(f"{action} {inserted}; already present: {duplicates}")
    print(f"Log range (Bucharest): {events[0][0]} through {events[-1][0]}")
    print(f"Final replay state matches state.json: {state}")
    if not args.apply:
        print("Preview only. Pass --apply to write the missing events.")


if __name__ == "__main__":
    main()