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

# Lista tuturor stărilor absolute pe care vrem să le captăm
TARGET_STATES = [
    "SPEED_1", "SPEED_2", "SPEED_3",
    "HUMIDITY_1", "HUMIDITY_2", "HUMIDITY_3",
    "MODE_AUTO", "MODE_SLEEP", "MODE_MANUAL", "MODE_NIGHT",
    "FLUX_INTAKE", "FLUX_EXTRACT", "FLUX_RECOVERY", "FLUX_SLAVE_MASTER",
    "BOOST", "RESET"
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
        print(f"STARE ȚINTĂ: {state}")
        print("=" * 55)

        if state in codes:
            print(f"Ai deja un cod salvat pentru {state}.")
            alegere = input("Apasa ENTER pentru a-l suprascrie, sau 's' urmat de ENTER pentru a-l sari: ")
            if alegere.lower() == 's':
                continue

        print(f"\n1. Asigura-te ca telecomanda fizica este la un pas distanta de starea '{state}'.")
        print(f"2. Indreapta telecomanda spre blasterul Tuya.")
        input(f"3. Apasa ENTER aici in consola, apoi apasa butonul pe telecomanda pentru a trece in '{state}'...")

        print("\nPornesc learning...")
        # Intra in modul de ascultare
        ir.study_start()

        print(f">>> TRANSMITE {state} DE PE TELECOMANDA ACUM <<<")
        
        # Asteapta semnalul 15 secunde
        code = ir.receive_button(timeout=15)
        
        # Iese imediat din modul de ascultare
        ir.study_end()

        if not code:
            print("!!! Nu am primit niciun cod. Asigura-te ca ai indreptat telecomanda corect.")
            continue

        print("CAPTURE OK")
        print(f"Cod Raw (fragment): {code[:20]}...")

        codes[state] = code

        with open(OUTPUT, "w") as f:
            json.dump(codes, f, indent=2)

        print(f"Salvat in {OUTPUT}")

    print("\n=== TERMINAT CU SUCCES ===")
    print(f"Fisierul {OUTPUT} contine acum {len(codes)} coduri.")

except KeyboardInterrupt:
    print("\n\n!!! Intrerupt de utilizator !!!")
except Exception as e:
    print(f"\n\n!!! Eroare: {e} !!!")
finally:
    print("\nIesire de siguranta din learning mode...")
    try:
        ir.study_end()
    except:
        pass
    print("Device reset. IR transmission restored.")