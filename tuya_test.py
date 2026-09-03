import json
import os
import time
from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice
from config import IR_DEVICE_ID, IR_ADDRESS, IR_LOCAL_KEY

DEVICE_ID = IR_DEVICE_ID
IP = IR_ADDRESS
LOCAL_KEY = IR_LOCAL_KEY

OUTPUT = "phantom_ir.json"

ir = IRRemoteControlDevice(
    dev_id=DEVICE_ID,
    address=IP,
    local_key=LOCAL_KEY,
    version=3.3,
    control_type=1,  # DPS 201/202 for IR transmission
)

print("=" * 60)
print("PHANTOM IR TEST")
print("=" * 60)

# Check device status
print("\n1. Checking device status...")
status = ir.status()
print(f"   Status: {status}")

# Check if stuck in study mode
if status and '201' in status.get('dps', {}):
    control_val = status['dps']['201']
    if 'study' in control_val:
        print("   WARNING: Device is in STUDY MODE - trying to exit...")
        ir.study_end()
        time.sleep(1)
        status = ir.status()
        print(f"   After study_end: {status}")

# Load codes from JSON
print("\n2. Loading button codes...")
if os.path.exists(OUTPUT):
    with open(OUTPUT, "r") as f:
        codes = json.load(f)
    print(f"   OK: Loaded {len(codes)} codes: {list(codes.keys())}")
else:
    print(f"   ERROR: File not found: {OUTPUT}")
    exit(1)

# Send MODE command
print("\n3. Sending MODE command...")
if 'MODE' in codes:
    mode_code = codes['MODE']
    print(f"   Code length: {len(mode_code)}")
    print(f"   Sending...")
    result = ir.send_button(mode_code)
    print(f"   Result: {result}")
    print("   OK: Command sent - You should hear a BEEP from Phantom!")
else:
    print("   ERROR: MODE code not found in JSON")

# Verify by checking status again
time.sleep(0.5)
print("\n4. Final status check...")
final_status = ir.status()
print(f"   Status: {final_status}")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
