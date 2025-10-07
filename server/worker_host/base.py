from __future__ import annotations
import asyncio, json
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, Iterable

@dataclass
class MqttMessage:
    topic: str
    payload: bytes
    qos: int
    retain: bool

class MqttClientProto(Protocol):
    def publish(self, topic: str, payload: str | bytes, qos: int = 0, retain: bool = False) -> None: ...
    def subscribe(self, topic: str, qos: int = 0) -> None: ...
    def add_message_handler(self, handler: Callable[[MqttMessage], None]) -> None: ...

class BaseWorker:
    """
    Class-based contract for prop backends.
    Control topic: halloween/<prop_id>/cmd   (action comes from payload)
    Telemetry:     halloween/<prop_id>/telemetry/<key>
    Status:        halloween/<prop_id>/status/<key>
    Availability:  halloween/<prop_id>/status/availability
    """
    def __init__(self, prop_id: str, mqtt: MqttClientProto, config: dict[str, Any] | None = None):
        self.prop_id = prop_id
        self.mqtt = mqtt
        self.config = config or {}
        self._tasks: list[asyncio.Task] = []

    # --- Lifecycle ---
    async def start(self) -> None:
        self.mqtt.subscribe(f"halloween/{self.prop_id}/cmd", qos=1)
        self.mqtt.publish(f"halloween/{self.prop_id}/status/availability", "online", qos=1, retain=True)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self.mqtt.publish(f"halloween/{self.prop_id}/status/availability", "offline", qos=1, retain=True)

    # --- Message dispatch (parse action from payload) ---
    async def on_message(self, msg: MqttMessage) -> None:
        if msg.topic != f"halloween/{self.prop_id}/cmd":
            return
        action, arg = self._parse_cmd_payload(msg.payload)
        if not action:
            self.status("warn", "Empty/invalid command payload")
            return
        handler_name = f"do_{action.replace('/', '_')}"
        if hasattr(self, handler_name):
            try:
                await asyncio.coroutine(getattr(self, handler_name))(arg)
            except Exception as e:
                self.status("error", f"{type(e).__name__}: {e}")
        else:
            self.status("warn", f"Unknown action: {action}")

    # --- Helpers for workers ---
    def spawn(self, coro) -> None:
        self._tasks.append(asyncio.create_task(coro))

    def telemetry(self, key: str, value: Any, qos: int = 0) -> None:
        self.mqtt.publish(f"halloween/{self.prop_id}/telemetry/{key}", str(value), qos=qos)
        print(f"telemetry: halloween/{self.prop_id}/telemetry/{key}={value}")

    def status(self, key: str, value: Any, qos: int = 0, retain: bool = False) -> None:
        self.mqtt.publish(f"halloween/{self.prop_id}/status/{key}", str(value), qos=qos, retain=retain)

    def command(self, target_prop: str, action: str, args: Any | None = None, *, qos: int = 1):
        """
        Send a command to another worker/prop firmware:
        topic: halloween/<target_prop>/cmd
        payload: JSON {"action": ..., "args": ...}
        """
        payload = json.dumps({"action": action, "args": args})
        self.mqtt.publish(f"halloween/{target_prop}/cmd", payload, qos=qos)

    def broadcast(self, targets: Iterable[str], action: str, args: Any | None = None, *, qos: int = 1):
        """Send the same command to many props."""
        for t in targets:
            self.command(t, action, args, qos=qos)


    @staticmethod
    def _parse_cmd_payload(payload: bytes) -> tuple[Optional[str], Optional[str]]:
        """Accept either JSON {'action': 'x', 'args': 'y'} or plain text 'x y...'."""
        if not payload:
            return None, None
        p = payload.decode("utf-8", errors="ignore").strip()
        if not p:
            return None, None
        # Try JSON first
        try:
            obj = json.loads(p)
            if isinstance(obj, dict) and "action" in obj:
                action = str(obj["action"]).strip()
                arg = obj.get("args")
                if isinstance(arg, (dict, list)):
                    arg = json.dumps(arg)
                elif arg is not None:
                    arg = str(arg)
                return action, arg
        except Exception:
            pass
        # Plain text: "action arg..."
        if " " in p:
            action, arg = p.split(" ", 1)
            return action.strip(), arg.strip()
        return p, None
