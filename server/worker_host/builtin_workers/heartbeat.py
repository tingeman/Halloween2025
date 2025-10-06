# server/worker_host/builtin_workers/heartbeat.py
from __future__ import annotations
import asyncio, json
from worker_host.base import BaseWorker

PROP_ID = "builtin_heartbeat"

class Worker(BaseWorker):
    """
    Built-in demo worker.
    - Publishes telemetry ticks.
    - Responds to commands on halloween/<prop_id>/cmd
      Payload may be:
        - plain text: "ping", "set_mode armed", "fire 750"
        - JSON: {"action": "set_mode", "args": "armed"}
    """
    NAME = "builtin:heartbeat"

    async def start(self) -> None:
        await super().start()
        self.spawn(self._ticker())

    async def _ticker(self):
        """Publish a counter every few seconds."""
        i = 0
        interval = int(self.config.get("tick_interval", 5))
        try:
          while True:
              self.telemetry("tick", i)
              i += 1
              await asyncio.sleep(interval)
        except asyncio.CancelledError:
          # Optional: cleanup hardware, close files, etc.
          raise

    # --- Actions ---
    async def do_ping(self, arg: str | None):
        self.telemetry("pong", arg or "ok")

    async def do_set_mode(self, arg: str | None):
        mode = (arg or "").strip() or "idle"
        if mode not in {"idle", "armed", "firing"}:
            self.status("error", f"invalid mode '{mode}'")
            return
        self.telemetry("mode", mode, qos=1)

    async def do_fire(self, arg: str | None):
        try:
            ms = int((arg or "500").strip())
        except ValueError:
            ms = 500
        self.telemetry("event", f"fire start {ms}ms")
        await asyncio.sleep(ms / 1000)
        self.telemetry("event", "fire end")
