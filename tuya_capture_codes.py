import json
import os
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
    control_type=1,
)

# List of all absolute states to capture
TARGET_STATES = [
    # "SPEED_1", "SPEED_2", "SPEED_3",
    # "HUMIDITY_1", "HUMIDITY_2", "HUMIDITY_3",
    "BOOST"
    # "MODE_AUTO", "MODE_SLEEP", "MODE_MANUAL", "MODE_NIGHT",
    # "FLUX_INTAKE", "FLUX_NORTH_SOUTH", "FLUX_SOUTH_NORTH", "FLUX_EXTRACT",
    # "BOOST", "RESET"
]

if os.path.exists(OUTPUT):
    with open(OUTPUT, "r") as f:
        codes = json.load(f)
else:
    codes = {}

print("\n=== PHANTOM ABSOLUTE IR CAPTURE ===")
print("Blaster:", IP)
print("Output:", OUTPUT)

try:
    for state in TARGET_STATES:
        print("\n" + "=" * 55)
        print(f"TARGET STATE: {state}")
        print("=" * 55)

        if state in codes:
            print(f"A code for {state} is already saved.")
            choice = input("Press ENTER to overwrite it, or 's' followed by ENTER to skip: ")
            if choice.lower() == 's':
                continue

        print(f"\n1. Set the physical remote to the target state '{state}'.")
        print(f"2. Point the remote at the Tuya blaster.")
        input(f"3. Press ENTER here, then press the remote button to switch to '{state}'...")

        print("\nStarting learning...")
        # Enter listening mode
        ir.study_start()

        print(f">>> TRANSMIT {state} FROM THE REMOTE NOW <<<")
        
        # Wait for the signal for 15 seconds
        code = ir.receive_button(timeout=15)
        
        # Exit listening mode immediately
        ir.study_end()

        if not code:
            print("!!! No code received. Make sure the remote is pointed correctly.")
            continue

        print("CAPTURE OK")
        print(f"Raw code (fragment): {code[:20]}...")

        codes[state] = code

        with open(OUTPUT, "w") as f:
            json.dump(codes, f, indent=2)

        print(f"Saved to {OUTPUT}")

    print("\n=== COMPLETED SUCCESSFULLY ===")
    print(f"{OUTPUT} now contains {len(codes)} codes.")

except KeyboardInterrupt:
    print("\n\n!!! Interrupted by user !!!")
except Exception as e:
    print(f"\n\n!!! Error: {e} !!!")
finally:
    print("\nSafely exiting learning mode...")
    try:
        ir.study_end()
    except:
        pass
    print("Device reset. IR transmission restored.")