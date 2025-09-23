# Halloween 2025 — Repository Layout & Usage Guide

This document describes the folder structure for the Halloween 2025 installation, the intention behind each part, and how to run everything with Docker Compose—while keeping each **prop** truly self-contained.

---

## Goals

- **Single place for orchestration** (`infra/compose`).
- **Self-contained props** (plugin + backend + firmware + docs live under `props/<prop>`).
- **Generic server hosts** (dashboard + worker runner) that discover and load prop bundles at runtime.
- **Shared code** in `libs/` (Python libs for server/workers; MicroPython helpers for firmware).

---

## Folder Structure

```text
halloween-2025/
├─ README.md
├─ LICENSE
├─ .env.example
├─ .gitignore
├─ makefile
│
├─ infra/
│  └─ compose/
│     ├─ docker-compose.yml
│     ├─ docker-compose.dev.yml
│     └─ docker-compose.prod.yml
│
├─ server/
│  ├─ broker/
│  │  └─ mosquitto.conf               # MQTT broker config (Eclipse Mosquitto)
│  ├─ api/
│  │  ├─ app/
│  │  │  └─ main.py                    # FastAPI (REST/WebSocket), auth, facades
│  │  └─ Dockerfile
│  ├─ dashboard/
│  │  ├─ app.py                        # loads /opt/props/*/plugin at runtime
│  │  └─ Dockerfile
│  └─ worker_host/
│     ├─ runner.py                     # loads /opt/props/*/backend at runtime
│     └─ Dockerfile
│
├─ libs/
│  ├─ py/
│  │  ├─ halloween_common/
│  │  │  ├─ __init__.py
│  │  │  ├─ mqtt_topics.py             # canonical topic helpers
│  │  │  ├─ schemas.py                 # Pydantic models (Command/Status/Telemetry)
│  │  │  ├─ events.py                  # enums/constants for actions/events
│  │  │  ├─ mqtt_client.py             # thin client wrapper (LWT, retained, JSON)
│  │  │  └─ testing.py                 # fixtures and sample payloads
│  │  ├─ pyproject.toml
│  │  └─ tests/
│  └─ micropython/
│     ├─ mp_common/
│     │  ├─ __init__.py
│     │  ├─ wifi.py                    # connect/retry/backoff
│     │  ├─ mqtt.py                    # lightweight MQTT pub/sub
│     │  ├─ msgpack_json.py            # tiny (de)serialization helpers
│     │  └─ util.py                    # debounce, scheduler, safe reboot
│     └─ README.md
│
├─ props/
│  ├─ coffin_jumper/
│  │  ├─ firmware/
│  │  │  ├─ boot.py
│  │  │  ├─ main.py                    # uses libs/micropython/mp_common/*
│  │  │  └─ lib/                       # copy of mp_common at deploy time
│  │  ├─ plugin/
│  │  │  └─ page.py                    # dashboard plugin (UI)
│  │  ├─ backend/
│  │  │  └─ __init__.py                # exposes start(loop, services)
│  │  ├─ topics.md                     # MQTT contract for the prop
│  │  └─ pyproject.toml                # optional local imports
│  └─ tesla_hue_nest/
│     ├─ plugin/
│     │  └─ page.py
│     ├─ backend/
│     │  └─ __init__.py
│     ├─ app/                          # legacy terminal tool (optional)
│     ├─ topics.md
│     └─ pyproject.toml
│
└─ config/
   ├─ dashboard.env.example
   ├─ mqtt.yaml.example
   ├─ hue.yaml.example
   ├─ tesla.yaml.example
   └─ secrets/                         # git-ignored (real credentials)
```

---

## What Lives Where (and Why)

### `infra/compose/`
- **Single source of truth** for Docker Compose.
- `docker-compose.yml`: base stack (broker, api, dashboard, worker_host).
- `docker-compose.dev.yml`: dev overrides (bind-mount props and libs).
- `docker-compose.prod.yml`: prod overrides (resources, logging, baked libs).

### `server/`
- **Generic hosts**, no prop code here.
- `broker/`: MQTT config.
- `api/`: FastAPI façade for auth, REST/WebSocket, and safe access to broker/integrations.
- `dashboard/`: Plotly Dash host that **discovers** `/opt/props/*/plugin`.
- `worker_host/`: Async runner that **discovers** `/opt/props/*/backend`.

### `libs/`
- `libs/py`: Python packages shared by `api`, `dashboard`, `worker_host` (schemas, topics, client wrappers).
- `libs/micropython`: MicroPython helpers **copied** into each prop’s firmware.

### `props/<prop>/`
- **All prop-specific code**:
  - `firmware/`: ESP32 MicroPython.
  - `plugin/`: the dashboard UI for this prop.
  - `backend/`: headless logic (MQTT handlers, timers, rule glue, calls to integrations via API).
  - `topics.md`: documented topics & payload schemas.

---

## How Plugins & Backends Are Loaded

- **Dashboard host** scans `/opt/props/*/plugin/page.py`.
  - Each plugin exposes:
    - `name: str`, `path: str` (for routing/navigation),
    - `layout() -> Component`,
    - `register_callbacks(app, services) -> None`.

- **Worker host** scans `/opt/props/*/backend/__init__.py`.
  - Each backend exposes:
    - `async def start(loop, services) -> None` to subscribe to MQTT topics, schedule tasks, etc.

Both hosts receive a `services` dict (e.g., API client, MQTT client, Redis), so plugins/backends don’t manage their own core connections.

---

## How to Mount Prop Folders (Compose)

### Development (bind-mount live code)

`infra/compose/docker-compose.dev.yml`:
```yaml
services:
  dashboard:
    volumes:
      - ../../props:/opt/props:ro        # mount ALL props (read-only)
      - ../../libs/py:/opt/libs/py:ro    # shared python libs
    environment:
      - PYTHONPATH=/opt/libs/py

  worker_host:
    volumes:
      - ../../props:/opt/props:ro
      - ../../libs/py:/opt/libs/py:ro
    environment:
      - PYTHONPATH=/opt/libs/py

  api:
    volumes:
      - ../../libs/py:/opt/libs/py:ro
    environment:
      - PYTHONPATH=/opt/libs/py
```

### Production (bake selected props)

Option A — still mount (simplest):
```yaml
# docker-compose.prod.yml
services:
  dashboard:
    volumes:
      - ../../props:/opt/props:ro
  worker_host:
    volumes:
      - ../../props:/opt/props:ro
```

Option B — **vendor only the props you want** into the images at build time:
- Add a build arg `PROPS_ENABLED="coffin_jumper tesla_hue_nest"`.
- Copy those folders in the Dockerfile:
```dockerfile
# server/dashboard/Dockerfile (excerpt)
ARG PROPS_ENABLED
RUN mkdir -p /opt/props
# simple example: copy all; for selective copy, use a build script
COPY /props /opt/props
```
- Install `libs/py` as a wheel in each image (no bind-mounts in prod).

---

## Running the Stack

```bash
# 1) Create and fill .env files from the examples
cp .env.example .env
cp config/dashboard.env.example config/dashboard.env
# ...and place real secrets in config/secrets/ (git-ignored)

# 2) Dev up (with live mounts)
docker compose -f infra/compose/docker-compose.yml                -f infra/compose/docker-compose.dev.yml up --build

# 3) Prod up (baked images or prod mounts)
docker compose -f infra/compose/docker-compose.yml                -f infra/compose/docker-compose.prod.yml up -d
```

---

## Prop Anatomy & Contracts

Each prop should document **topics** and **payloads** in `props/<prop>/topics.md`. A common convention (enforced by `libs/py/halloween_common`):

- `halloween/<prop>/status` (retained) — high-level state machine.
- `halloween/<prop>/telemetry` — counters, timings, sensor data.
- `halloween/<prop>/cmd` — commands (`action`, `params`, `correlation_id`).

Backends and plugins import shared models:
```python
from halloween_common.schemas import Command, Status, Telemetry
from halloween_common.mqtt_topics import prop_cmd_topic, prop_status_topic
```

---

## Firmware Reuse (MicroPython)

- Copy `libs/micropython/mp_common/*` into `props/<prop>/firmware/lib/` before uploading:
```bash
cp -r libs/micropython/mp_common/* props/coffin_jumper/firmware/lib/
python -m mpremote connect COM12 cp props/coffin_jumper/firmware/* :
```
- Keep modules tiny (RAM-friendly, no heavy deps).

---

## Secrets & Configuration

- Keep real secrets in `config/secrets/` (git-ignored).
- Provide `*.example` files in `config/` and root `.env.example`.
- Map secrets into containers via `env_file:`, `environment:`, or Docker secrets (prod).

---

## Typical Developer Workflow

1. **Add a new prop**
   - `props/new_prop/{firmware,plugin,backend}` + `topics.md`.
   - Implement plugin and backend using `libs/py/halloween_common` schemas.
2. **Run locally**
   - `docker compose -f .../docker-compose.yml -f .../docker-compose.dev.yml up`.
   - Dashboard auto-loads `props/new_prop/plugin/page.py`.
   - Worker host auto-loads `props/new_prop/backend/__init__.py`.
3. **Iterate**
   - Update schemas in `libs/py`. All services import the same models.
4. **Deploy**
   - Use prod compose. Either mount `/opt/props` or bake props into images.

---

## FAQ

**Q: Why not put plugins directly under `server/dashboard/plugins`?**  
A: Portability. With self-contained props, each prop “carries” its own UI. The dashboard just **discovers** them.

**Q: Can I run a prop’s backend in its own container?**  
A: Yes. You can add a dedicated service that builds `props/<prop>/backend` directly. The default pattern reduces container sprawl by using a **single worker host** that loads many backends.

**Q: Where do integrations (Tesla/Hue/Nest) live?**  
A: Keep vendor-specific logic inside the prop’s backend or as shared client code in `libs/py` if multiple props will reuse it. Access tokens/secrets stay in `config/`.
