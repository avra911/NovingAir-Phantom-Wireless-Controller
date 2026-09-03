import tinytuya
import json
from config import SENSOR_DEVICE_ID, SENSOR_ADDRESS, SENSOR_LOCAL_KEY

# Device Configuration
DEVICE_ID = SENSOR_DEVICE_ID
LOCAL_KEY = SENSOR_LOCAL_KEY
IP_ADDRESS = SENSOR_ADDRESS

# Initialize device with Protocol 3.5
sensor = tinytuya.Device(
    dev_id=DEVICE_ID,
    address=IP_ADDRESS,
    local_key=LOCAL_KEY,
    version=3.5
)
sensor.set_socketTimeout(3)

def read_air_detector():
    status = sensor.status()
    
    if not status or 'dps' not in status:
        print("[ERROR] Failed to fetch data from AIR_DETECTOR. Check Local Key/IP.")
        return None

    dps = status['dps']
    
    # Print raw payload once so you can verify exact DP key mappings for PM1.0 and PM10
    print(f"DEBUG Raw DPS: {dps}\n")
    
    # Map all 8 metrics from Tuya schema (with fallbacks for common Tuya PM1/PM10 DP keys)
    parsed_data = {
        "co2_state": dps.get("1", "unknown"),
        "co2_ppm": dps.get("2", 0),
        "temperature_c": dps.get("18", 0),
        "humidity_pct": dps.get("19", 0),
        "pm1_ugm3": dps.get("101", dps.get("23", dps.get("105", 0))),
        "pm25_ugm3": dps.get("20", 0),
        "pm10_ugm3": dps.get("102", dps.get("24", dps.get("106", 0))),
        "voc_mgm3": round(dps.get("21", 0) / 1000.0, 3),
        "ch2o_mgm3": round(dps.get("22", 0) / 1000.0, 3),
        "battery_pct": dps.get("15", 0)
    }

    return parsed_data

if __name__ == "__main__":
    print(f"Polling AIR_DETECTOR ({DEVICE_ID})...\n")
    data = read_air_detector()
    
    if data:
        print("=== 8-IN-1 AIR DETECTOR READINGS ===")
        print(f"1. CO2 Level       : {data['co2_ppm']} ppm ({data['co2_state']})")
        print(f"2. Temperature     : {data['temperature_c']} °C")
        print(f"3. Humidity        : {data['humidity_pct']} %")
        print(f"4. PM1.0           : {data['pm1_ugm3']} µg/m³")
        print(f"5. PM2.5           : {data['pm25_ugm3']} µg/m³")
        print(f"6. PM10            : {data['pm10_ugm3']} µg/m³")
        print(f"7. TVOC            : {data['voc_mgm3']} mg/m³")
        print(f"8. Formaldehyde    : {data['ch2o_mgm3']} mg/m³")
        print("-----------------------------------")
        print(f"   Battery         : {data['battery_pct']} %")