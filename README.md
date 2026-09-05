# NovingAir

Local air-quality monitoring and Phantom HRV remote control.

The project has two parts:

- `server.py`: FastAPI backend that reads the Tuya air sensor, sends IR commands to the Phantom unit, persists UI state, and exposes sensor metrics.
- `PhantomRemote/`: Expo React Native app for the control panel and air-quality dashboard.

## Requirements

- Python 3.10+
- A Python virtual environment with `tinytuya`, `fastapi`, and `uvicorn`
- Node.js, npm, and global `serve` package (`sudo npm install -g serve`)
- The Tuya IR blaster and air-quality sensor reachable on the local network

## Configuration

Copy the templates and fill in local values:

```bash
cp .env.example .env
cp PhantomRemote/.env.example PhantomRemote/.env
```

The backend `.env` contains the Tuya device IDs, IP addresses, and local keys:

```dotenv
IR_DEVICE_ID=
IR_ADDRESS=
IR_LOCAL_KEY=
SENSOR_DEVICE_ID=
SENSOR_ADDRESS=
SENSOR_LOCAL_KEY=
```

`PhantomRemote/.env` contains the address used by the app to reach the backend:

```dotenv
EXPO_PUBLIC_API_URL=http://YOUR_BACKEND_IP:8000
```

Never commit either `.env` file. They are ignored by Git.

## Run the backend (Development)

From the repository root:

```bash
source .venv/bin/activate
python3 server.py
```

The API listens on `http://0.0.0.0:8000`.

Useful endpoints:

- `GET /state` returns Phantom state and current sensor metrics.
- `POST /command/SPEED` cycles the stored speed state and sends the corresponding IR code.
- `POST /command/MODE` cycles `AUTO -> SLEEP -> MANUAL`.
- `POST /command/HUMIDITY`, `/FLUX`, `/NIGHT`, `/BOOST`, and `/RESET` control the remaining functions.

## Run the mobile app (Development)

In another terminal:

```bash
cd PhantomRemote
npm install
npx expo start
```

Use Expo Go, an emulator, or the web option. The phone and backend machine must be able to reach each other over the local network.

## Production Setup (Systemd Deployment)

For persistent background execution on a local server (e.g., Linux NUC / Raspberry Pi), run both backend and web frontend as persistent systemd services.

### 1. Build Frontend Static Bundle

Environment variables are statically baked into the Expo web bundle at build time. Clean cache and build against your server's local IP:

```bash
cd PhantomRemote
npm install
EXPO_PUBLIC_API_URL=http://YOUR_SERVER_IP:8000 npx expo export -p web --clear
```

### 2. Configure Firewall (UFW)

Ensure incoming traffic to both the FastAPI backend and web frontend ports is permitted:

```bash
sudo ufw allow 8000/tcp
sudo ufw allow 3000/tcp
sudo ufw reload
```

### 3. Create Systemd Service Configurations

#### Backend Service (`/etc/systemd/system/phantom-backend.service`)
```ini
[Unit]
Description=NovingAir Phantom Backend Service
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/Projects/NovingAir
ExecStart=/home/YOUR_USER/Projects/NovingAir/.venv/bin/python3 server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Frontend Service (`/etc/systemd/system/phantom-frontend.service`)
```ini
[Unit]
Description=NovingAir Phantom React Frontend
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/Projects/NovingAir/PhantomRemote
ExecStart=/usr/bin/serve -s dist -l 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4. Enable and Launch Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now phantom-backend.service
sudo systemctl enable --now phantom-frontend.service
```

Access the control interface from any local browser at `http://YOUR_SERVER_IP:3000`.

## IR code capture

`tuya_capture_codes.py` captures the absolute IR commands expected by the backend, including entries such as:

```text
SPEED_1, SPEED_2, SPEED_3
HUMIDITY_1, HUMIDITY_2, HUMIDITY_3
MODE_AUTO, MODE_SLEEP, MODE_MANUAL
FLUX_INTAKE, FLUX_NORTH_SOUTH, FLUX_SOUTH_NORTH
BOOST, RESET
```

Run it from the repository root:

```bash
source .venv/bin/activate
python3 tuya_capture_codes.py
```

The captured values are stored in `phantom_ir.json` as Base64-encoded IR payloads. The file is required by the backend but contains no Tuya local keys.

## Sensor-only test

```bash
source .venv/bin/activate
python3 co2_sensor.py
```

To test IR communication independently:

```bash
python3 tuya_test.py
```

## Notes

- The Phantom controller is an IR transmitter, so its local Tuya status does not reliably report the actual HRV operating mode.
- `state.json` is local runtime state and may differ from the physical remote if commands are sent elsewhere.
- Keep the IR blaster and sensor on stable IP addresses or update `.env` when their addresses change.