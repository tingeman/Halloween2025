"""Coffin jumper demo firmware helpers.

This module provides a small, test-oriented firmware helper for an ESP32
based prop. It implements Wi‑Fi connection, an SSD1306-driven OLED display
helper, and a lightweight MQTT client wrapper for publishing availability,
state and telemetry. It is intentionally small and synchronous to be easy to
run on constrained MicroPython builds.

Key behaviors covered:
- Connect to Wi‑Fi and optionally install missing libs via mip
- Render a small status display on an SSD1306 OLED
- Publish availability/state/telemetry to configured MQTT topics
- Configure an LWT and react to broker uptime messages

This file is intended for use in automated tests and local demos; it keeps
robustness simple (try/except and short reconnect paths) rather than providing
a full production-grade MQTT client.
"""

import time, json
try:
    # MicroPython-specific modules
    import network, machine, ubinascii  # type: ignore
    from machine import Pin, I2C  # type: ignore
    from umqtt.simple import MQTTClient  # type: ignore
    from dfplayer import DFPlayer  # type: ignore
    import secrets  # device secrets on the target
except Exception:
    # Provide fallbacks so the module can be imported on CPython for tests.
    network = None
    machine = None
    ubinascii = None
    Pin = object
    I2C = object
    MQTTClient = None
    try:
        import secrets  # may exist in repo for testing
    except Exception:
        secrets = None

FW_VERSION = "1.0.0"

# OLED dimensions (set to 32 if your display is 128x32)
OLED_W = 128
OLED_H = 64
OLED_ADDR = 0x3C

# ---- Pins ----
PIN_PIR       = 23      # PIR output (3.3V logic!)   (Not updated)
PIN_SOLENOID  = 18      # MOSFET gate                (Not updated)
UART_NUM      = 1       # DFPlayer UART (only relevant if you use DFPlayer here)
UART_TX       = 13      # ESP32 TX -> DF RX   (Updated per board)
UART_RX       = 12      # ESP32 RX <- DF TX   (Updated per board)
UART_BAUD     = 9600    # DFPlayer default
I2C_SDA       = 21
I2C_SCL       = 22

# ---- Topics ----
BASE = b"halloween/esp32-coffin-jumper-01"
T_AVAIL = BASE + b"/availability"
T_STATE = BASE + b"/state"
T_TEL   = BASE + b"/telemetry"
T_CMD   = BASE + b"/cmd"
T_BROKER_UP = b"halloween/broker/uptime"

# ---- Globals ----
_debug = secrets.DEBUG if hasattr(secrets, "DEBUG") else False
_state = "idle"
_blocked = False
_triggers = 0
_broker_uptime_str = "—"
client = None           # MQTT client instance
oled = None             # SSD1306 instance

# ---- Timezone (adjust when DST changes) ----
TZ_OFFSET_HOURS = 2     # Denmark: 1 (CET winter), 2 (CEST summer)
TZ_NAME = "CET/CEST"

# ----------------------------
# Utilities
# ----------------------------
def wifi_connect(ssid: str, psk: str, timeout: int = 20) -> object:
    """Connect the board to a Wi‑Fi access point.

    Args:
        ssid (str): SSID of the network to join.
        psk (str): Pre-shared key / password.
        timeout (int): Seconds to wait before raising RuntimeError.

    Returns:
        network.WLAN: The active WLAN interface object on success.

    Raises:
        RuntimeError: If the network cannot be joined within the timeout.
    """
    print("Wi-Fi: connecting to", ssid)
    wlan = network.WLAN(network.STA_IF)
    if not wlan.active():
        wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(ssid, psk)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout*1000:
                raise RuntimeError("Wi-Fi connect timeout")
            time.sleep(0.2)
    print("Wi-Fi: connected", wlan.ifconfig())
    return wlan

def ensure_lib(modname: str, mip_name: object = None) -> object:
    """Ensure a Python module is available, installing it via mip if needed.

    This helper attempts to import ``modname``. If the import fails it will
    try to install the module using ``mip`` (MicroPython package manager) and
    then re-import it. In a constrained device this keeps optional helpers
    installable at runtime.

    Args:
        modname (str): Module name to import.
        mip_name (str|None): Optional package name for mip if it differs.

    Returns:
        module: The imported module object.
    """
    try:
        mod = __import__(modname)
        print("Lib OK:", modname)
        return mod
    except ImportError:
        print("Installing:", mip_name or modname)
        import mip
        mip.install(mip_name or modname)
        mod = __import__(modname)
        print("Installed:", modname)
        return mod

def wrap(text: str, max_chars: int) -> list:
    """Simple word-wrap helper.

    Splits ``text`` into a list of lines where each line is at most
    ``max_chars`` characters. This is intended for rendering short strings
    on the OLED.

    Args:
        text (str): Input text to wrap.
        max_chars (int): Maximum characters per line.

    Returns:
        list[str]: Lines of wrapped text.
    """
    out, line = [], ""
    for w in text.split():
        if len(line) + (1 if line else 0) + len(w) <= max_chars:
            line = (line + " " + w) if line else w
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out

def draw_center(oled_obj: object, text: str, y: int) -> None:
    """Draw ``text`` centered horizontally at vertical position ``y``.

    Args:
        oled_obj: SSD1306-like object with a ``text`` method.
        text (str): Text to draw.
        y (int): Vertical pixel coordinate.
    """
    x = (OLED_W - len(text) * 6) // 2
    if x < 0:
        x = 0
    oled_obj.text(text, x, y)

# ----------------------------
# Display & MQTT helpers
# ----------------------------
def render_display() -> None:
    """Render the small status screen on the global OLED.

    The function reads module-level state variables such as ``_state``,
    ``_triggers``, ``_blocked`` and ``_broker_uptime`` and updates the OLED
    contents. If no OLED is available it is a no-op.
    """
    # Uses global 'oled'
    if oled is None:
        return
    oled.fill(0)
    oled.text("Coffin v{}".format(FW_VERSION), 0, 0)
    oled.text("State: {}".format(_state[:10]), 0, 8)
    oled.text("Trig: {}".format(_triggers), 0, 16)
    oled.text("Blk: {}".format("Y" if _blocked else "N"), 0, 24)
    up = _broker_uptime_str
    if len(up) > 18:
        up = up[:18]
    oled.text("Up: {}".format(up), 0, 32)
    oled.show()

def publish(mq: object, topic: object, payload: object, retain: bool = False) -> None:
    """Publish a payload to ``topic`` using ``mq`` with light normalization.

    The helper serializes dict/list payloads to JSON and ensures a bytes
    payload before publishing. Exceptions are swallowed because this helper
    is used in rendering/telemetry paths where strict error propagation would
    complicate a tiny demo.

    Args:
        mq: MQTT client-like object with a ``publish`` method.
        topic (bytes|str): Topic to publish to.
        payload (str|bytes|dict|list): Payload to publish.
        retain (bool): Whether to set the retain flag on the publish.
    """
    try:
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode()

        try:
            print("MQTT TX:", topic, payload)
        except Exception:
            pass

        mq.publish(topic, payload, retain=retain, qos=0)
    except Exception:
        pass

def set_state(mq: object, s: str) -> None:
    """Update the local state and publish it as a retained MQTT value.

    Args:
        mq: MQTT client used to publish the state.
        s (str): New state string.
    """
    global _state
    _state = s
    publish(mq, T_STATE, s, retain=True)
    render_display()

def birth(mq: object) -> None:
    """Mark this device as online and set the initial state.

    The function publishes an availability message (retained) and sets the
    internal state to "idle".
    """
    publish(mq, T_AVAIL, b"online", retain=True)
    set_state(mq, "idle")

def lwt_setup(mq: object) -> None:
    """Configure the MQTT Last Will and Testament (LWT).

    The LWT marks the device as offline (retained) if it disconnects
    unexpectedly.
    """
    mq.set_last_will(T_AVAIL, b"offline", retain=True, qos=0)

def telemetry(mq: object, wlan: object) -> None:
    """Publish a small telemetry JSON payload.

    Args:
        mq: MQTT client to use for publishing.
        wlan: WLAN interface, used to fetch RSSI if available.
    """
    tel = {
        "fw": FW_VERSION,
        "uptime_s": time.ticks_ms()//1000,
        "blocked": _blocked,
        "vol": dfp.volume,
        "rssi": wlan.status('rssi') if hasattr(wlan, "status") else None,
    }
    publish(mq, T_TEL, tel, retain=False)

def format_uptime(seconds: int) -> str:
    """Format an uptime in seconds to a human-readable string.

    Args:
        seconds (int): Uptime in seconds.

    Returns:
        str: Formatted uptime string, e.g. "1h 23m 45s".
    """
    hours = seconds // 3600
    rem = seconds % 3600
    mins = rem // 60
    secs = rem % 60
    return f"{hours}h {mins}m {secs}s"


def on_mqtt_message(mq: object, topic: object, msg: object) -> None:
    """MQTT callback invoked for incoming messages.

    This wrapper decodes the topic and dispatches to specific handlers
    (commands and broker uptime messages).

    Args:
        mq: The MQTT client instance.
        topic (bytes|str): Topic of the incoming message.
        msg (bytes|str): Payload of the incoming message.
    """
    global _broker_uptime_str
    try:
        t = topic.decode() if isinstance(topic, (bytes, bytearray)) else str(topic)
    except:
        t = str(topic)
    # Debug: log incoming messages to the serial console so we can see
    # whether the uptime topic is being received and what its payload is.
    try:
        print("MQTT RX:", t, msg)
    except Exception:
        pass
    if t == T_CMD.decode():
        on_cmd(mq, topic, msg)
        return

    if t == T_BROKER_UP.decode():
        on_broker_uptime(mq, topic, msg)
        return

def on_broker_uptime(mq: object, topic: object, msg: object) -> None:
    """Handle incoming broker uptime messages.

    The function expects the payload to be a JSON object with an "uptime_s"
    field containing the broker uptime in seconds. It updates the global
    ``_broker_uptime_str`` variable used for display.

    Args:
        mq: The MQTT client instance.
        topic (bytes|str): Topic of the incoming message.
        msg (bytes|str): Payload of the incoming message.
    """
    global _broker_uptime_str
    try:
        msg_json = json.loads(msg.decode()) if isinstance(msg, (bytes, bytearray)) else json.loads(str(msg))
        # Debug: show the parsed JSON so we can see which key the broker uses
        if _debug:
            try:
                print("Broker uptime payload JSON:", msg_json)
            except Exception:
                pass

        raw = msg_json.get('uptime_s')

        try:
            broker_uptime_seconds = int(float(raw)) if raw is not None else 0
        except Exception:
            broker_uptime_seconds = 0

        _broker_uptime_str = format_uptime(broker_uptime_seconds)

        if _debug:
            try:
                print("Broker uptime str:", _broker_uptime_str)
            except Exception:
                pass
    except:
        # On parse failure, fall back to a simple string representation
        # and log the parse error for diagnostics.
        try:
            print("Failed to parse broker uptime payload:", msg)
        except Exception:
            pass
        _broker_uptime_str = str(msg)

    render_display()

def on_cmd(mq: object, topic: object, msg: object) -> None:
    """Handle incoming command messages.

    The command payload can be a simple string (e.g. "arm", "block") or a
    JSON object with an "action" field. Only a small set of actions is
    supported in this demo: block, unblock, reset and arm.

    Args:
        mq: MQTT client instance (unused except for state publishing).
        topic: Topic the command arrived on.
        msg: Payload (bytes or str).
    """
    global _blocked, _triggers
    try:
        s = msg.decode() if isinstance(msg, (bytes, bytearray)) else str(msg)
    except:
        s = str(msg)

    action = None
    value  = None
    track  = None

    if s.startswith("{"):
        try:
            obj = json.loads(s)
            action = obj.get("action")
            value = obj.get("value")
            track = obj.get("track")
        except Exception:
            pass

    if action is None:
        action = s.strip().lower()

    if action == "block":
        _blocked = True
        set_state(mq, "blocked")
    elif action == "unblock":
        _blocked = False
        set_state(mq, "armed")
    elif action == "reset":
        _triggers = 0
    elif action == "arm":
        if not _blocked:
            set_state(mq, "armed")
    # 'trigger' and 'volume' left out intentionally in this trimmed demo

def make_client() -> object:
    """Create and return a configured MQTTClient instance.

    The function configures the LWT and sets the message callback to the
    module-level ``on_mqtt_message`` handler.

    Returns:
        MQTTClient: Configured client (not connected).
    """
    c = MQTTClient(
        client_id=secrets.CLIENT_ID,
        server=secrets.MQTT_HOST,
        port=secrets.MQTT_PORT,
        user=secrets.MQTT_USER,
        password=secrets.MQTT_PASSWORD,
        keepalive=30,
    )
    lwt_setup(c)
    c.set_callback(lambda t, m: on_mqtt_message(c, t, m))
    return c

# ----------------------------
# Main
# ----------------------------
def main() -> None:
    """Main entrypoint for the device firmware.

    Connects to Wi‑Fi, initializes the display, connects to MQTT and enters a
    small loop that processes incoming MQTT messages and periodically emits
    telemetry. The function catches MQTT errors and performs a simple
    automatic reconnect sequence.
    """
    global client, oled, dfp

    # 1) Wi-Fi first (needed if ensure_lib uses mip)
    wlan = wifi_connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)

    # 2) Ensure OLED driver present, init I2C + OLED ONCE (global)
    ssd1306 = ensure_lib("ssd1306")
    try:
        i2c = I2C(0, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=400_000)
    except TypeError:
        i2c = I2C(1, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=400_000)
    oled = ssd1306.SSD1306_I2C(OLED_W, OLED_H, i2c, addr=OLED_ADDR)

    uart = machine.UART(UART_NUM, baudrate=UART_BAUD, tx=machine.Pin(UART_TX), rx=machine.Pin(UART_RX))
    dfp = DFPlayer(uart)
    dfp.set_volume(20)  # reasonable default; override via MQTT

    # Splash
    ip = wlan.ifconfig()[0]
    oled.fill(0)
    oled.text("ESP32 + Coffin", 0, 0)
    oled.text("IP: " + ip, 0, 8)
    oled.text("Syncing NTP...", 0, 24)
    oled.show()

    # 3) NTP (optional)
    try:
        import ntptime
        ntptime.settime()
        print("NTP: synced")
    except Exception as e:
        print("NTP error:", e)

    # 4) MQTT connect + subscribe
    if client is None:
        client = make_client()
        client.connect()
        client.subscribe(T_CMD)
        client.subscribe(T_BROKER_UP)
        birth(client)
        set_state(client, "armed" if not _blocked else "blocked")

    # 5) Main loop
    last_tel = 0
    while True:
        # pump MQTT to receive messages (like broker uptime)
        try:
            client.check_msg()
        except Exception:
            # quick auto-recover
            try:
                client.disconnect()
            except:
                pass
            client = None
            time.sleep(1)
            client = make_client()
            client.connect()
            client.subscribe(T_CMD)
            client.subscribe(T_BROKER_UP)
            birth(client)
            set_state(client, "armed" if not _blocked else "blocked")

        # periodic telemetry
        now = time.ticks_ms()
        if time.ticks_diff(now, last_tel) > 5000:
            telemetry(client, wlan)
            last_tel = now

        render_display()
        time.sleep(0.1)

# Entry
if __name__ == "__main__":
    # Run real firmware loop on MicroPython; otherwise execute lightweight
    # helper checks suitable for CPython host environments.
    import sys
    impl = getattr(sys, "implementation", None)
    name = getattr(impl, "name", "") if impl is not None else ""
    if name == "micropython":
        main()
    else:
        # CPython-only quick unit-style checks for pure helpers.
        print("Running helper checks (host CPython)...")

        # wrap() behavior
        assert wrap("hello world test", 6) == ["hello", "world", "test"]

        # draw_center() with a dummy OLED
        class DummyOLED:
            def __init__(self):
                self.calls = []
            def text(self, text, x, y):
                self.calls.append((text, x, y))
            def fill(self, v):
                pass
            def show(self):
                pass

        d = DummyOLED()
        draw_center(d, "OK", 10)
        assert any(c[0] == "OK" for c in d.calls), "draw_center did not call text()"

        # publish() serialisation test
        class DummyMQ:
            def __init__(self):
                self.publ = []
            def publish(self, topic, payload, retain=False, qos=0):
                self.publ.append((topic, payload, retain, qos))

        dm = DummyMQ()
        publish(dm, b'topic', {'a': 1}, retain=True)
        assert dm.publ, "publish did not invoke underlying publish()"
        payload = dm.publ[0][1]
        assert isinstance(payload, (bytes, bytearray)) and payload.startswith(b'{') and b'"a"' in payload

        # ensure_lib should at least import stdlib json on CPython
        mod = ensure_lib('json')
        import json as _json
        assert mod is _json

        print("All helper checks passed.")
