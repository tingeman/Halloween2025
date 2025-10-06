from __future__ import annotations
import asyncio
import json
import os
import signal
import time
from pathlib import Path
from typing import Dict

from .base import BaseWorker, MqttMessage
from .loader import discover_workers, WorkerDesc
from .mqtt import ThreadedMqtt

PROPS_ROOT = Path("/app/props")  # bind-mounted repo
BUILTIN_ROOT = Path("/app/server/worker_host/builtin_workers")  # optional
WORKER_LWT = "halloween/worker_host/availability"
UPTIME_TOPIC = "halloween/worker_host/uptime"

def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and (val is None or val == ""):
        raise SystemExit(f"Missing required env var: {name}")
    return val or ""

def _load_config(desc: WorkerDesc) -> dict:
    if not desc.config_path:
        return {}
    try:
        if desc.config_path.suffix.lower() == ".json":
            return json.loads(desc.config_path.read_text(encoding="utf-8"))
        # Lazy YAML support only if user adds pyyaml to deps
        if desc.config_path.suffix.lower() in (".yaml", ".yml"):
            import yaml  # type: ignore
            return yaml.safe_load(desc.config_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[worker_host] Failed to parse {desc.config_path}: {e}")
    return {}

async def run():
    # MQTT
    host = env("MQTT_HOST", "broker")
    port = int(env("MQTT_PORT", "1883"))
    user = env("MQTT_USERNAME", "")
    pw   = env("MQTT_PASSWORD", "")
    client_id = env("MQTT_CLIENT_ID", "halloween_worker_host")

    mqtt = ThreadedMqtt(
        host=host,
        port=port,
        username=user or None,
        password=pw or None,
        client_id=client_id,
        lwt_topic=WORKER_LWT,
    )
    mqtt.connect_and_loop()

    # Discover workers (class-only contract)
    discovered = discover_workers(PROPS_ROOT, BUILTIN_ROOT if BUILTIN_ROOT.exists() else None)
    if not discovered:
        mqtt.publish("halloween/worker_host/status/warn", "No workers discovered", qos=0)

    # Fan-out setup
    loop = asyncio.get_running_loop()
    msg_queue: asyncio.Queue[MqttMessage] = asyncio.Queue()

    def on_any_message(msg: MqttMessage) -> None:
        loop.call_soon_threadsafe(msg_queue.put_nowait, msg)

    mqtt.add_message_handler(on_any_message)

    # Instantiate & start each worker
    instances: Dict[str, BaseWorker] = {}
    for desc in discovered:
        cfg = _load_config(desc)
        w = desc.cls(desc.prop_id, mqtt, cfg)
        await w.start()
        instances[desc.prop_id] = w

    # One subscription for all control topics; workers filter locally
    mqtt.subscribe("halloween/+/cmd", qos=1)

    # Heartbeat
    async def heartbeat():
        start = time.time()
        while True:
            mqtt.publish(UPTIME_TOPIC, str(int(time.time() - start)), qos=0)
            await asyncio.sleep(10)
    hb_task = asyncio.create_task(heartbeat())

    # Dispatcher
    async def dispatcher():
        while True:
            msg = await msg_queue.get()
            parts = msg.topic.split("/", 3)
            if len(parts) >= 3 and parts[0] == "halloween":
                prop_id = parts[1]
                w = instances.get(prop_id)
                if w:
                    await w.on_message(msg)
    disp_task = asyncio.create_task(dispatcher())

    # Graceful shutdown
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

    hb_task.cancel()
    disp_task.cancel()
    for w in instances.values():
        try:
            await w.stop()
        except Exception:
            pass

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
