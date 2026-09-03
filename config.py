import os
from pathlib import Path


def _load_env_file() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file()

IR_DEVICE_ID = os.environ["IR_DEVICE_ID"]
IR_ADDRESS = os.environ["IR_ADDRESS"]
IR_LOCAL_KEY = os.environ["IR_LOCAL_KEY"]
SENSOR_DEVICE_ID = os.environ["SENSOR_DEVICE_ID"]
SENSOR_ADDRESS = os.environ["SENSOR_ADDRESS"]
SENSOR_LOCAL_KEY = os.environ["SENSOR_LOCAL_KEY"]
