import argparse
from contextlib import closing
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def phantom_state_category(state: dict) -> str | None:
    if state.get("night"):
        return "night"
    if state.get("boost"):
        return "speed_3"
    if state.get("speed") in (1, 2, 3):
        return f"speed_{state['speed']}"
    return None


def normalize_phantom_timestamp(value: datetime) -> datetime:
    bucharest = ZoneInfo("Europe/Bucharest")
    if value.tzinfo is None:
        value = value.replace(tzinfo=bucharest)
    return value.astimezone(bucharest)


def parse_phantom_timestamp(value: str) -> datetime:
    return normalize_phantom_timestamp(datetime.fromisoformat(value))


def ensure_phantom_state_history_schema(conn: sqlite3.Connection) -> dict:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(phantom_state_history)").fetchall()
    }
    renamed_created_at = False
    if "changed_at" in columns and "created_at" not in columns:
        conn.execute(
            "ALTER TABLE phantom_state_history RENAME COLUMN changed_at TO created_at"
        )
        columns.remove("changed_at")
        columns.add("created_at")
        renamed_created_at = True

    added_category = "category" not in columns
    added_duration = "duration_seconds" not in columns
    if added_category:
        conn.execute("ALTER TABLE phantom_state_history ADD COLUMN category TEXT")
    if added_duration:
        conn.execute("ALTER TABLE phantom_state_history ADD COLUMN duration_seconds INTEGER")

    backfilled_rows = 0
    if renamed_created_at or added_category or added_duration:
        rows = conn.execute(
            "SELECT id, created_at, state_json FROM phantom_state_history ORDER BY id"
        ).fetchall()
        timestamps = []
        states = []
        for _, created_at, state_json in rows:
            try:
                timestamps.append(parse_phantom_timestamp(created_at))
            except (TypeError, ValueError):
                timestamps.append(None)
            try:
                state = json.loads(state_json)
                states.append(state if isinstance(state, dict) else {})
            except (TypeError, ValueError, json.JSONDecodeError):
                states.append({})

        for index, (row_id, _, _) in enumerate(rows):
            updates = []
            values = []
            timestamp = timestamps[index]
            if timestamp is not None:
                updates.append("created_at = ?")
                values.append(timestamp.isoformat())
            if added_category:
                updates.append("category = ?")
                values.append(phantom_state_category(states[index]))
            if added_duration and index + 1 < len(rows):
                next_timestamp = timestamps[index + 1]
                duration = 0
                if timestamp is not None and next_timestamp is not None:
                    duration = max(0, int((next_timestamp - timestamp).total_seconds()))
                updates.append("duration_seconds = ?")
                values.append(duration)
            if updates:
                values.append(row_id)
                conn.execute(
                    f"UPDATE phantom_state_history SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                backfilled_rows += 1

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phantom_state_runtime "
        "ON phantom_state_history(category, duration_seconds, created_at)"
    )
    return {
        "renamed_created_at": renamed_created_at,
        "added_category": added_category,
        "added_duration": added_duration,
        "backfilled_rows": backfilled_rows,
    }


def migrate_phantom_state_history(db_path: str) -> dict:
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    with closing(sqlite3.connect(db_path)) as conn, conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'phantom_state_history'"
        ).fetchone()
        if table_exists is None:
            raise RuntimeError("Database does not contain phantom_state_history")
        migration = ensure_phantom_state_history_schema(conn)
        migration["rows"] = conn.execute(
            "SELECT COUNT(*) FROM phantom_state_history"
        ).fetchone()[0]
        return migration


def _default_db_path() -> str:
    configured = os.environ.get("AIR_HISTORY_DB")
    if configured:
        return configured

    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "AIR_HISTORY_DB":
                return value.strip().strip("\"'")

    return "data/air_history.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Phantom state history columns and backfill intervals.")
    parser.add_argument(
        "db_path",
        nargs="?",
        default=_default_db_path(),
        help="SQLite file (defaults to AIR_HISTORY_DB or data/air_history.sqlite3)",
    )
    args = parser.parse_args()
    result = migrate_phantom_state_history(args.db_path)
    print(f"Migrated {result['rows']} Phantom state rows in {args.db_path}")
    print(
        "Changes: "
        f"created_at renamed={result['renamed_created_at']}, "
        f"category added={result['added_category']}, "
        f"duration_seconds added={result['added_duration']}, "
        f"rows backfilled={result['backfilled_rows']}"
    )


if __name__ == "__main__":
    main()