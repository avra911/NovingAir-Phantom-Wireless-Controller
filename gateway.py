from dataclasses import dataclass
from typing import Optional

import tinytuya

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
        self.gateway = tinytuya.Device(
            dev_id=GATEWAY_ID,
            address=GATEWAY_IP,
            local_key=TUYA_CHILD_KEY,
            version=TUYA_VERSION,
        )

        self.indoor = tinytuya.Device(
            dev_id=INDOOR_ID,
            cid=INDOOR_CID,
            parent=self.gateway,
            address=GATEWAY_IP,
            local_key=TUYA_CHILD_KEY,
            version=TUYA_VERSION,
        )

        self.outdoor = tinytuya.Device(
            dev_id=OUTDOOR_ID,
            cid=OUTDOOR_CID,
            parent=self.gateway,
            address=GATEWAY_IP,
            local_key=TUYA_CHILD_KEY,
            version=TUYA_VERSION,
        )

    @staticmethod
    def _parse_indoor(result: dict) -> SensorData:
        dps = result.get("dps", {})

        temperature = dps.get("1")
        humidity = dps.get("2")
        battery = dps.get("3")

        return SensorData(
            temperature=temperature / 10 if temperature is not None else None,
            humidity=float(humidity) if humidity is not None else None,
            battery=battery,
        )

    @staticmethod
    def _parse_outdoor(result: dict) -> SensorData:
        dps = result.get("dps", {})

        temperature = dps.get("1")
        humidity = dps.get("2")
        battery = dps.get("4")

        return SensorData(
            temperature=temperature / 10 if temperature is not None else None,
            humidity=humidity / 10 if humidity is not None else None,
            battery=battery,
        )

    def get_indoor(self) -> SensorData:
        result = self.indoor.status()

        if not result or "dps" not in result:
            raise RuntimeError(
                f"Failed to read indoor sensor: {result}"
            )

        return self._parse_indoor(result)

    def get_outdoor(self) -> SensorData:
        result = self.outdoor.status()

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