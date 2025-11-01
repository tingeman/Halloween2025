# Halloween 2025

A modular, MQTT-based Halloween automation system with web dashboard, prop workers, and ESP32 firmware support.

## 🎃 Overview

This system orchestrates multiple Halloween props (animatronics, lights, sound effects) through:
- **MQTT Broker** (Mosquitto) for message passing
- **Web Dashboard** (Plotly Dash) for monitoring and control
- **Worker Host** for prop backend logic
- **ESP32 Firmware** (MicroPython) for physical prop control

Each prop is self-contained with its own firmware, backend logic, and dashboard plugin.

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- (Optional) Python 3.11+ for local development

### 1. Configure Secrets

Create the secrets directory and configuration files:

```bash
# Create secrets directory
mkdir -p config/secrets

# Copy example files
cp config/dashboard.env.example config/dashboard.env

# Create MQTT user credentials
cat > config/secrets/mqtt_users.env << EOF
MQTT_ADMIN_USER=admin
MQTT_ADMIN_PW=your_secure_password
MQTT_DASHBOARD_USER=dashboard
MQTT_DASHBOARD_PW=your_dashboard_password
MQTT_WORKER_USER=worker
MQTT_WORKER_PW=your_worker_password
EOF

# (Optional) Add Tesla credentials if using tesla_hue_nest prop
cat > config/secrets/tesla.env << EOF
TESLA_AUTH_TOKEN=your_tesla_token
VEHICLE_TAG=your_vehicle_name
EOF
```

### 2. Launch the System

#### Full Stack (All Services)
```bash
cd infra/compose
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               -f docker-compose.media.yml \
               up --build
```

#### Individual Services

**MQTT Broker Only:**
```bash
docker compose -f docker-compose.yml up --build
```

**Dashboard Only:**
```bash
docker compose -f docker-compose.yml \
               -f docker-compose.dashboard.yml \
               up --build
```

**Workers Only:**
```bash
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               up --build
```

### 3. Access the Dashboard

Open your browser to: **http://localhost:8050**

## 📁 Project Structure

```
halloween-2025/
├── config/                      # Configuration files
│   ├── dashboard.env            # Dashboard settings
│   ├── worker_host.env          # Worker settings
│   └── secrets/                 # Git-ignored credentials
│       ├── mqtt_users.env       # MQTT authentication
│       └── tesla.env            # Tesla API token (optional)
│
├── infra/compose/               # Docker Compose files
│   ├── docker-compose.yml       # Base: MQTT broker
│   ├── docker-compose.dashboard.yml  # Dashboard service
│   ├── docker-compose.workers.yml    # Worker host service
│   ├── docker-compose.media.yml      # Media server (optional)
│   ├── docker-compose.dev.yml        # Development overrides
│   └── docker-compose.prod.yml       # Production overrides
│
├── server/                      # Server components
│   ├── broker/                  # MQTT broker config
│   ├── dashboard/               # Web dashboard
│   └── worker_host/             # Worker runtime
│
├── props/                       # Individual props (self-contained)
│   ├── coffin_jumper/
│   │   ├── firmware/            # ESP32 MicroPython code
│   │   ├── plugin/              # Dashboard plugin
│   │   └── backend/             # Worker logic
│   ├── tesla_hue_nest/          # Tesla trunk + Hue lights + Nest speakers
│   ├── thriller_hue_nest/       # Hue lights + Nest speakers
│   └── example_prop/            # Template for new props
│
└── libs/                        # Shared libraries
    ├── py/                      # Python libs (server-side)
    │   └── halloween_common/    # MQTT topics, schemas
    └── micropython/             # MicroPython libs (ESP32)
        └── mp_common/           # WiFi, MQTT helpers
```

## 🎯 Available Props

### Currently Active
- **tesla_hue_nest** - Coordinates Tesla trunk, Hue lights, and Nest speakers
- **thriller_hue_nest** - Synchronizes Hue lights with Thriller audio on Nest speakers
- **coffin_jumper** - ESP32-based animatronic with PIR sensor and DFPlayer audio

### Enabling/Disabling Props

Edit `config/dashboard.env`:

```bash
# Option 1: Allow only specific props (recommended)
PLUGIN_PROPS_ALLOW=tesla_hue_nest,thriller_hue_nest,coffin_jumper

# Option 2: Disable specific props
PLUGIN_PROPS_DISABLE=example_prop

# Option 3: Disable all prop plugins
# PLUGIN_DISABLE_ALL_PROPS=1
```

## 🔧 Development

### Adding a New Prop

1. Create prop directory structure:
```bash
mkdir -p props/my_prop/{firmware,plugin,backend}
```

2. Implement components:
   - `plugin/page.py` - Dashboard UI (inherits from `BasePlugin`)
   - `backend/worker.py` - Server logic (inherits from `BaseWorker`)
   - `firmware/main.py` - ESP32 code (optional)

3. Document MQTT contract:
   - Create `props/my_prop/topics.md`

4. Restart services:
```bash
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               up --build
```

Often it is necessary to remove the old containers to trigger a complete rebuild:
```bash
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               rm

docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               up --build
```

The new prop will be auto-discovered and loaded!

## 📡 MQTT Topics

All communication follows this convention:

```
halloween/<prop_id>/cmd                    # Commands (JSON or text)
halloween/<prop_id>/state                  # Current state
halloween/<prop_id>/availability           # online/offline
halloween/<prop_id>/telemetry/<category>/<key>  # Sensor data, counters
```

### Example: Control a Prop

```bash
# Arm the tesla_hue_nest prop
mosquitto_pub -h localhost -t halloween/tesla_hue_nest/cmd -m 'arm'

# Play with JSON command
mosquitto_pub -h localhost -t halloween/tesla_hue_nest/cmd \
  -m '{"action": "play"}'

# Adjust volume
mosquitto_pub -h localhost -t halloween/tesla_hue_nest/cmd \
  -m '{"action": "chromecast", "args": {"volume": 0.7}}'
```

### Monitor Telemetry

```bash
# All telemetry
mosquitto_sub -h localhost -v -t 'halloween/+/telemetry/#'

# Specific prop
mosquitto_sub -h localhost -v -t 'halloween/tesla_hue_nest/#'
```

## 🐛 Troubleshooting

### Dashboard Not Loading Plugins

Check environment variables in `config/dashboard.env`:
```bash
docker compose -f docker-compose.dashboard.yml logs dashboard
```

Look for plugin discovery messages.

### Worker Not Starting

Check MQTT connection:
```bash
docker compose logs mqtt worker_host
```

Verify credentials in `config/secrets/mqtt_users.env`.

### Volume Controls Not Working

Ensure chromecast is connected:
1. Click "(Re)Connect" button in dashboard
2. Check worker logs for connection status
3. Verify network access to Nest speakers

### Rebuild Everything

```bash
# Stop all services
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               down -v

# Remove old images
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               rm

# Rebuild and start
docker compose -f docker-compose.yml \
               -f docker-compose.workers.yml \
               -f docker-compose.dashboard.yml \
               up --build
```

## 📚 Documentation

- **Dashboard Plugins**: `server/dashboard/README.md`
- **Workers**: `server/worker_host/WORKERS.md`
- **Architecture**: `halloween-2025-structure.md`
- **Individual Props**: See `props/<prop_name>/topics.md`

## 🧪 Running Integration Tests

The `docker-compose.dev.yml` file provides a test environment for running pytest integration tests, currently focused on MQTT broker setup validation:

```bash
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               up --build
```

This launches an `mqtt_test` service that:
- Installs test dependencies from `libs/py[test]`
- Runs integration tests in `libs/py/tests/integration/mqtt`
- Validates MQTT authentication and connectivity
- Exits after completion

The test results are displayed in the container logs.

## 🎬 2025 Experiences & Learnings

### What Worked Well
- ✅ Web dashboard was significantly better than terminal-based control
- ✅ Modular prop architecture made adding/removing features easy
- ✅ MQTT message bus enabled clean separation of concerns

### Issues Encountered
- ⚠️ Volume settings not persistent (props reset to default volume on each play)
- ⚠️ Stop button should reset cooldown timers for immediate re-arm
- ⚠️ Tesla trunk sometimes out of sync with Hue lights
- ⚠️ Trunk occasionally opened and closed quickly
- ⚠️ No direct "play" trigger (required arm + motion sensor)
- ⚠️ Doungeon soundscape not implemented

### TODO
- [ ] Implement dungeon soundscape based on thriller_hue_nest (we don't need hue operation, so simplify)
- [ ] Implement persistent volume settings across container restarts
- [ ] Move hue, chromecast and tesla integration apis to common folder and ensure import from there
- [ ] Add cooldown timer reset on stop command
- [ ] Add direct play mode (bypass motion sensors)
- [ ] Remote config editing from dashboard
- [ ] Prop removal/relaunching from dashboard
- [ ] Tesla state machine intensive testing and debugging
- [ ] Persistent Hue bridge key storage
- [ ] Fire counter and Tesla open counter (persistent)
- [ ] Mounted config volumes with reload capability

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

1. Create a new prop under `props/my_prop/`
2. Follow the self-contained structure (firmware/plugin/backend)
3. Document MQTT topics in `topics.md`
4. Test with development compose setup
5. Submit pull request

---

**Happy Haunting! 🎃👻**
