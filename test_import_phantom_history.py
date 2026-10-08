import json
from datetime import datetime
from zoneinfo import ZoneInfo

from import_phantom_history import import_events, replay_log
from tasks import get_phantom_state_history, save_phantom_state_change


def test_import_converts_utc_and_merges_history_chronologically(tmp_path):
    log_path = tmp_path / "automation.log"
    log_path.write_text(
        "2026-10-02 10:00:00 [INFO] Remote command TOGGLE_AUTO: disabled\n"
        "2026-10-02 10:00:01 [INFO] IR command MODE_AUTO\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "mode": "AUTO",
                "flux": "NONE",
                "speed": 2,
                "night": False,
                "boost": False,
                "automation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    events, _ = replay_log(log_path, state_path)
    assert [event[1] for event in events] == [
        "reconstructed:mode+flux",
        "reconstructed:auto_schedule",
    ]
    assert events[0][0] == "2026-10-02T13:00:01+03:00"

    db_path = tmp_path / "air_history.sqlite3"
    save_phantom_state_change(
        {"mode": "MANUAL", "flux": "NONE", "speed": 1, "night": False},
        "startup",
        str(db_path),
        datetime(2026, 10, 3, 13, tzinfo=ZoneInfo("Europe/Bucharest")),
    )

    assert import_events(db_path, events, apply=True) == (2, 0)
    assert import_events(db_path, events, apply=True) == (0, 2)

    history = get_phantom_state_history(
        str(db_path),
        now=datetime(2026, 10, 3, 14, tzinfo=ZoneInfo("Europe/Bucharest")),
    )
    assert [entry["change_type"] for entry in history] == [
        "reconstructed:mode+flux",
        "reconstructed:auto_schedule",
        "startup",
    ]