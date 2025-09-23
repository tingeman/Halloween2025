# MQTT Broker Testing Guide

This document describes how to **automatically test the MQTT broker** in
the Halloween project.\
The tests are self-contained and require only the broker service to be
running.

------------------------------------------------------------------------

## 📂 Location of this document

This file lives alongside the broker configuration:

    server/broker/README.testing.md

From the project root, you will also find references in the main
`README.md` pointing here.

------------------------------------------------------------------------

## 🧪 Location of Tests

All test cases are located under:

    libs/py/tests/integration/mqtt/

Example files: - `test_broker_basics.py`\
- `test_auth_anonymous.py`\
- `test_lwt_ws_health.py`

These validate connectivity, ACL enforcement, LWT/offline behavior,
WebSocket support, and the broker's uptime topic.

------------------------------------------------------------------------

## 📦 Dependencies

Tests require: - [pytest](https://docs.pytest.org/)\
- [paho-mqtt](https://www.eclipse.org/paho/)

Declared in `libs/py/pyproject.toml` as an optional `test` dependency:

``` toml
[project.optional-dependencies]
test = ["pytest>=8", "paho-mqtt>=2.1"]
```

------------------------------------------------------------------------

## 🔑 Environment Variables

The tests are configured through environment variables provided to the
test container:

    MQTT_HOST=mqtt
    MQTT_PORT=1883
    MQTT_WS_PORT=9001
    MQTT_ADMIN_USER=admin
    MQTT_ADMIN_PW=...
    MQTT_DEVICE_USER=device
    MQTT_DEVICE_PW=...

Passwords are managed in `config/secrets/mqtt_users.env` and injected by
Compose.

------------------------------------------------------------------------

## 🐳 Compose Integration

An ephemeral **`mqtt_test`** service is defined in:

    infra/compose/docker-compose.dev.yml

It depends on the broker and runs pytest automatically.

``` yaml
services:
  mqtt_test:
    image: python:3.12-slim
    depends_on:
      - mqtt
    working_dir: /work
    volumes:
      - ../../libs/py:/work/libs/py:ro
    environment:
      - PYTHONPATH=/work/libs/py
      - MQTT_HOST=mqtt
      - MQTT_PORT=1883
      - MQTT_WS_PORT=9001
      - MQTT_ADMIN_USER=admin
      - MQTT_ADMIN_PW=${ADMIN_PW:?set in config/secrets/mqtt_users.env}
      - MQTT_DEVICE_USER=device
      - MQTT_DEVICE_PW=${DEVICE_PW:?set in config/secrets/mqtt_users.env}
    entrypoint: ["/bin/sh","-lc"]
    command: >
      "python -m pip install -q /work/libs/py[test] &&
       pytest -q /work/libs/py/tests/integration/mqtt"
```

------------------------------------------------------------------------

## ▶️ Running the Tests

Bring up the broker and run tests in one command:

``` bash
docker compose   -f infra/compose/docker-compose.yml   -f infra/compose/docker-compose.dev.yml   up --build --exit-code-from mqtt_test mqtt_test
```

-   Broker starts.\
-   Test container installs dependencies.\
-   `pytest` runs and exits with pass/fail code.

------------------------------------------------------------------------

## ✅ What is Tested?

-   **Authentication**
    -   Admin connects successfully.
    -   Anonymous clients are rejected.
-   **ACL enforcement**
    -   Device users (shared account + clientid) can only
        publish/subscribe within their own namespace.
-   **LWT / offline behavior**
    -   Unexpected disconnect triggers Last Will (`status=offline`),
        retained on the status topic.
-   **WebSocket listener**
    -   Admin can connect on port 9001 and exchange messages.
-   **Health / uptime topic**
    -   Broker publishes JSON on `halloween/broker/uptime` every 5s.
    -   Tests verify reception and monotonic increase of `uptime_s`.

------------------------------------------------------------------------

## 🔧 Extending Tests

-   Add new scenarios under `libs/py/tests/integration/mqtt/`.\
-   Ensure environment variables are passed in the `mqtt_test` service.\
-   For end-to-end testing with other services (worker, dashboard),
    create additional suites under `libs/py/tests/integration/`.

------------------------------------------------------------------------

## 📚 Related Files

-   Broker config: [`mosquitto.conf`](./mosquitto.conf)\
-   ACL rules: [`acl`](./acl)\
-   Entrypoint with hot-reload + uptime publisher:
    [`mqtt_entrypoint.sh`](./mqtt_entrypoint.sh)\
-   Automated password builder: [`build_passwd.sh`](./build_passwd.sh)

------------------------------------------------------------------------
