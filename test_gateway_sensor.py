import tinytuya
from dataclasses import dataclass
from typing import Optional

from config import (
    GATEWAY_IP,
    GATEWAY_ID,
    TUYA_VERSION,
    TUYA_CHILD_KEY,
    INDOOR_ID,
    INDOOR_CID,
    OUTDOOR_ID,
    OUTDOOR_CID,
)

# If your config has a separate GATEWAY_LOCAL_KEY, import it here:
try:
    from config import GATEWAY_LOCAL_KEY
except ImportError:
    GATEWAY_LOCAL_KEY = TUYA_CHILD_KEY


@dataclass
class SensorData:
    temperature: Optional[float]
    humidity: Optional[float]
    battery: object = None


class TuyaGateway:
    """
    Local Tuya Zigbee gateway access.

    The CDT03 gateway accepts the Zigbee child local key for the
    child-device status requests used here.
    """

    def __init__(self):
        # Initialize primary Gateway connection
        self.gateway = tinytuya.Device(
            dev_id=GATEWAY_ID,
            address=GATEWAY_IP,
            local_key=GATEWAY_LOCAL_KEY,
            version=TUYA_VERSION,
        )
        self.gateway.set_socketTimeout(3)

        # Child device definitions
        self.indoor = tinytuya.Device(
            dev_id=INDOOR_ID,
            cid=INDOOR_CID,
            parent=self.gateway,
            address=GATEWAY_IP,
            local_key=TUYA_CHILD_KEY,
            version=TUYA_VERSION,
        )
        self.indoor.set_socketTimeout(3)

        self.outdoor = tinytuya.Device(
            dev_id=OUTDOOR_ID,
            cid=OUTDOOR_CID,
            parent=self.gateway,
            address=GATEWAY_IP,
            local_key=TUYA_CHILD_KEY,
            version=TUYA_VERSION,
        )
        self.outdoor.set_socketTimeout(3)

    @staticmethod
    def _parse_indoor(result: dict) -> SensorData:
        dps = result.get("dps", {})

        temperature = dps.get("1")
        humidity = dps.get("2")
        battery = dps.get("3")

        return SensorData(
            temperature=round(temperature / 10.0, 1) if isinstance(temperature, (int, float)) else None,
            humidity=float(humidity) if isinstance(humidity, (int, float)) else None,
            battery=battery,
        )

    @staticmethod
    def _parse_outdoor(result: dict) -> SensorData:
        dps = result.get("dps", {})

        temperature = dps.get("1")
        humidity = dps.get("2")
        battery = dps.get("4")

        return SensorData(
            temperature=round(temperature / 10.0, 1) if isinstance(temperature, (int, float)) else None,
            humidity=round(humidity / 10.0, 1) if isinstance(humidity, (int, float)) else None,
            battery=battery,
        )

    def _query_device(self, device: tinytuya.Device) -> dict:
        """
        Attempts standard status query, falling back to updatedps() 
        if status returns empty/None (common for Zigbee sensors).
        """
        result = device.status()
        if not result or "dps" not in result:
            result = device.updatedps()
        return result or {}

    def get_indoor(self) -> SensorData:
        result = self._query_device(self.indoor)

        if not result or "dps" not in result:
            raise RuntimeError(
                f"Failed to read indoor sensor: {result}"
            )

        return self._parse_indoor(result)

    def get_outdoor(self) -> SensorData:
        result = self._query_device(self.outdoor)

        if not result or "dps" not in result:
            raise RuntimeError(
                f"Failed to read outdoor sensor: {result}"
            )

        return self._parse_outdoor(result)

    def get_all(self):
        return {
            "indoor": self.get_indoor(),
            "outdoor": self.get_outdoor(),
        }


if __name__ == "__main__":
    print(f"Polling Tuya Gateway ({GATEWAY_ID})...\n")

    try:
        # Initialize the gateway wrapper
        hub = TuyaGateway()

        # Fetch both indoor and outdoor data
        data = hub.get_all()
        indoor = data["indoor"]
        outdoor = data["outdoor"]

        print("=== ZIGBEE SUB-DEVICE READINGS ===")
        print("--- INDOOR SENSOR ---")
        if indoor.temperature is not None:
            print(f"Temperature : {indoor.temperature} °C")
            print(f"Humidity    : {indoor.humidity} %")
            print(f"Battery     : {indoor.battery}")
        else:
            print("Data unavailable.")

        print("\n--- OUTDOOR SENSOR ---")
        if outdoor.temperature is not None:
            print(f"Temperature : {outdoor.temperature} °C")
            print(f"Humidity    : {outdoor.humidity} %")
            print(f"Battery     : {outdoor.battery}")
        else:
            print("Data unavailable.")
        print("==================================")

    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {e}")