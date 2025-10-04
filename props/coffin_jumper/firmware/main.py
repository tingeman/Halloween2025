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
    import secrets  # device secrets on the target
    import dfplayer  # MANUAL INSTALL NEEDED! DOESN'T COME WITH MIP
    from pir_hcsr501 import PIRLatch
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

# ---- Constants ----
FW_VERSION = "1.0.0"

# OLED dimensions (set to 32 if your display is 128x32)
OLED_W = 128
OLED_H = 64
OLED_ADDR = 0x3C

# ---- Pins ----
PIN_PIR        = 4       # PIR output (3.3V logic!) 
PIR_LOCKOUT_MS = 5000    # Minimum ms between triggers
PIR_DEBOUNCE_MS= 300     # Debounce time for PIR edges (minimum time between edges)
PIR_WARMUP_MS  = 5000    # Ignore PIR edges for this long after boot
PIN_SOLENOID   = 18      # MOSFET gate                (Not updated)
UART_NUM       = 2       # DFPlayer UART
UART_TX        = 17      # ESP32 TX -> DF RX   (Updated per board)
UART_RX        = 16      # ESP32 RX <- DF TX   (Updated per board)
I2C_SDA        = 21
I2C_SCL        = 22


# ---- Topics ----
BASE = b"halloween/esp32-coffin-jumper-01"
T_AVAIL = BASE + b"/availability"
T_STATE = BASE + b"/state"
T_TEL   = BASE + b"/telemetry"
T_CMD   = BASE + b"/cmd"
T_BROKER_UP = b"halloween/broker/uptime"

# ---- Timezone (adjust when DST changes) ----
TZ_OFFSET_HOURS = 2     # Denmark: 1 (CET winter), 2 (CEST summer)
TZ_NAME = "CET/CEST"

# ----------------------------
# Utilities (stateless helpers)
# ----------------------------
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

# ----------------------------
# Main Prop Class
# ----------------------------
class CoffinProp:
    """A class to encapsulate the coffin prop's state and logic."""

    def __init__(self, debug=False):
        """Initialize the prop, its state, and component placeholders."""
        self._debug = debug
        
        # State
        self.state = "booting"
        self.is_blocked = False
        self.triggers = 0
        self.volume = 20
        self.broker_uptime_str = "—"

        # Components
        self.wlan = None
        self.mqtt = None
        self.oled = None
        self.pir_latch = None
        self.dfp = None

    # ----------------------------
    # Initialization
    # ----------------------------
    def _init_wifi(self) -> bool:
        """Connect the board to a Wi‑Fi access point.
        
        Returns:
            bool: True on success, False on failure.
        """
        if not secrets:
            print("Wi-Fi: secrets.py not found, cannot connect.")
            return False
        
        print("Wi-Fi: connecting to", secrets.WIFI_SSID)
        self.wlan = network.WLAN(network.STA_IF)
        if not self.wlan.active():
            self.wlan.active(True)
        
        if not self.wlan.isconnected():
            self.wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
            t0 = time.ticks_ms()
            while not self.wlan.isconnected():
                if time.ticks_diff(time.ticks_ms(), t0) > 20 * 1000:
                    print("Wi-Fi: connect timeout")
                    self.wlan = None
                    return False
                time.sleep(0.2)
        
        print("Wi-Fi: connected", self.wlan.ifconfig())
        return True

    def _init_peripherals(self):
        """Initialize hardware peripherals (OLED, PIR, DFPlayer)."""
        # PIR Latch
        try:
            self.pir_latch = PIRLatch(
                PIN_PIR, 
                hold_ms=PIR_LOCKOUT_MS, 
                debounce_ms=PIR_DEBOUNCE_MS, 
                warmup_ms=PIR_WARMUP_MS
            )
            print("PIR: Initialized")
        except Exception as e:
            print("PIR: Failed to initialize:", e)

        # OLED Display
        try:
            ssd1306 = ensure_lib("ssd1306")
            try:
                i2c = I2C(0, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=400_000)
            except TypeError:
                i2c = I2C(1, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=400_000)
            self.oled = ssd1306.SSD1306_I2C(OLED_W, OLED_H, i2c, addr=OLED_ADDR)
            print("OLED: Initialized")
        except Exception as e:
            print("OLED: Failed to initialize:", e)

        # DFPlayer
        try:
            self.dfp = dfplayer.DFPlayer(uart_id=UART_NUM, tx_pin_id=UART_TX, rx_pin_id=UART_RX)
            self.dfp.volume(self.volume)
            print("DFPlayer: Initialized")
        except Exception as e:
            print("DFPlayer: Failed to initialize:", e)

    def _init_mqtt(self):
        """Create and connect the MQTT client."""
        if not self.wlan or not self.wlan.isconnected() or not secrets:
            print("MQTT: No Wi-Fi or secrets, skipping connection.")
            return

        try:
            self.mqtt = MQTTClient(
                client_id=secrets.CLIENT_ID,
                server=secrets.MQTT_HOST,
                port=secrets.MQTT_PORT,
                user=secrets.MQTT_USER,
                password=secrets.MQTT_PASSWORD,
                keepalive=30,
            )
            self.mqtt.set_last_will(T_AVAIL, b"offline", retain=True, qos=0)
            self.mqtt.set_callback(self._on_mqtt_message)
            self.mqtt.connect()
            self.mqtt.subscribe(T_CMD)
            self.mqtt.subscribe(T_BROKER_UP)
            self._birth()
            self.set_state("armed" if not self.is_blocked else "blocked")
            print("MQTT: Connected and configured")
        except Exception as e:
            print("MQTT: Failed to connect:", e)
            self.mqtt = None

    # ----------------------------
    # Core Logic & State
    # ----------------------------
    def set_state(self, new_state: str):
        """Update the local state and publish it via MQTT if connected."""
        self.state = new_state
        if self.mqtt:
            self._publish(T_STATE, new_state, retain=True)
        self.render_display()

    def _birth(self):
        """Mark this device as online and set the initial state."""
        if self.mqtt:
            self._publish(T_AVAIL, b"online", retain=True)
            self.set_state("idle")

    def _start_action(self):
        """Perform the pre-programmed action."""
        print("ACTION: Starting...")
        self.play_track(folder=0, track=1)
        self.set_state("action")

    # ----------------------------
    # Display & MQTT Helpers
    # ----------------------------
    def render_display(self):
        """Render the status screen on the OLED, if available."""
        if not self.oled:
            return
        
        self.oled.fill(0)
        self.oled.text("Coffin v{}".format(FW_VERSION), 0, 0)
        self.oled.text("State: {}".format(self.state[:10]), 0, 8)
        self.oled.text("Trig: {}".format(self.triggers), 0, 16)
        
        pir_status = "---"
        if self.pir_latch:
            pir_status = "Motion!" if self.pir_latch.active() else "---"
        self.oled.text("PIR: {}".format(pir_status), 0, 24)
        
        self.oled.text("Blk: {}".format("Y" if self.is_blocked else "N"), 0, 32)
        
        up = self.broker_uptime_str
        if len(up) > 18:
            up = up[:18]
        self.oled.text("Up: {}".format(up), 0, 40)
        
        self.oled.show()

    def _publish(self, topic: bytes, payload, retain: bool = False):
        """Publish a payload to a topic with light normalization."""
        if not self.mqtt:
            return
        
        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            if isinstance(payload, str):
                payload = payload.encode()

            if self._debug:
                try:
                    print("MQTT TX:", topic, payload)
                except Exception:
                    pass
            
            self.mqtt.publish(topic, payload, retain=retain, qos=0)
        except Exception as e:
            print("MQTT: Publish failed:", e)

    def _telemetry(self):
        """Publish a small telemetry JSON payload."""
        tel = {
            "fw": FW_VERSION,
            "uptime_s": time.ticks_ms() // 1000,
            "triggers": self.triggers,
            "pir": "---",
            "blocked": self.is_blocked,
            "vol": self.volume,
            "rssi": None,
        }
        if self.pir_latch:
            tel["pir"] = "Motion!" if self.pir_latch.active() else "---"
        if self.wlan and hasattr(self.wlan, "status"):
            tel["rssi"] = self.wlan.status('rssi')
        
        self._publish(T_TEL, tel, retain=False)

    # ----------------------------
    # MQTT Message Handlers
    # ----------------------------
    def _on_mqtt_message(self, topic: bytes, msg: bytes):
        """Callback for incoming MQTT messages."""
        try:
            t = topic.decode()
        except:
            t = str(topic)

        if self._debug:
            try:
                print("MQTT RX:", t, msg)
            except Exception:
                pass

        if t == T_CMD.decode():
            self._on_cmd(msg)
        elif t == T_BROKER_UP.decode():
            self._on_broker_uptime(msg)

    def _on_broker_uptime(self, msg: bytes):
        """Handle incoming broker uptime messages."""
        try:
            msg_json = json.loads(msg.decode())
            if self._debug:
                print("Broker uptime payload JSON:", msg_json)

            raw = msg_json.get('uptime_s')
            broker_uptime_seconds = int(float(raw)) if raw is not None else 0
            self.broker_uptime_str = format_uptime(broker_uptime_seconds)

            if self._debug:
                print("Broker uptime str:", self.broker_uptime_str)
        except Exception as e:
            print("Failed to parse broker uptime payload:", msg, "Error:", e)
            self.broker_uptime_str = str(msg)
        
        self.render_display()

    def _on_cmd(self, msg: bytes):
        """Handle incoming command messages."""
        try:
            s = msg.decode()
        except:
            s = str(msg)

        action, params = None, {}
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                action = obj.get("action")
                params = obj.get("params", {})
            except Exception:
                pass
        else:
            action = s.strip().lower()

        print("Command action:", action)

        if action == "block":
            self.is_blocked = True
            self.set_state("blocked")
        elif action == "unblock":
            self.is_blocked = False
            self.set_state("armed")
        elif action == "reset":
            self.triggers = 0
            self.is_blocked = False
            self.set_state("armed")
        elif action == "arm":
            if not self.is_blocked:
                self.set_state("armed")
        elif action == "trigger":
            if not self.is_blocked and self.state in ("armed", "idle"):
                self._start_action()
        elif action == "play_music":
            vol = params.get("volume")
            if vol is not None:
                self.set_volume(vol)
            track = params.get("track", 1)
            self.play_track(folder=0, track=track)
        elif action == "pause_music":
            self.pause()
        elif action == "resume_music":
            self.resume()
        elif action == "stop_music":
            self.stop()

    # ----------------------------
    # DFPlayer Methods
    # ----------------------------
    def set_volume(self, vol: int):
        """Set the DFPlayer volume with bounds checking."""
        if not self.dfp: return
        try:
            if 0 <= vol <= 30:
                self.volume = vol
                self.dfp.volume(self.volume)
            else:
                print("Volume out of range (0-30):", vol)
        except Exception as e:
            print("Error setting volume:", e)

    def play_track(self, folder: int = 0, track: int = 1):
        """Play a specific track on the DFPlayer."""
        if not self.dfp: return
        try:
            if track >= 1:
                self.dfp.send_cmd(3, folder, track)
                self.set_state("playing")
            else:
                print("Track number must be >= 1:", track)
        except Exception as e:
            print("Error playing track:", e)

    def pause(self):
        """Pause playback on the DFPlayer."""
        if not self.dfp: return
        try:
            self.dfp.send_cmd(int('0E', 16))
        except Exception as e:
            print("Error pausing track:", e)

    def resume(self):
        """Resume playback on the DFPlayer."""
        if not self.dfp: return
        try:
            self.dfp.send_cmd(int('0D', 16))
            self.set_state("playing")
        except Exception as e:
            print("Error resuming track:", e)

    def stop(self):
        """Stop playback on the DFPlayer."""
        if not self.dfp: return
        try:
            self.dfp.send_cmd(int('16', 16))
            self.set_state("armed" if not self.is_blocked else "blocked")
        except Exception as e:
            print("Error stopping track:", e)

    # ----------------------------
    # Main Loop
    # ----------------------------
    def run(self):
        """Main entrypoint for the device firmware."""
        # 1. Initialize peripherals
        self._init_peripherals()

        # 2. Splash screen
        if self.oled:
            self.oled.fill(0)
            self.oled.text("ESP32 + Coffin", 0, 0)
            self.oled.text("Connecting...", 0, 16)
            self.oled.show()

        # 3. Connect to Wi-Fi
        self._init_wifi()
        if self.oled:
            ip = self.wlan.ifconfig()[0] if self.wlan else "Offline"
            self.oled.fill(0)
            self.oled.text("ESP32 + Coffin", 0, 0)
            self.oled.text("IP: " + ip, 0, 8)
            self.oled.show()

        # 4. Sync NTP if online
        if self.wlan:
            try:
                import ntptime
                ntptime.settime()
                print("NTP: synced")
            except Exception as e:
                print("NTP error:", e)

        # 5. Connect to MQTT if online
        self._init_mqtt()
        self.set_state("armed" if not self.is_blocked else "blocked")

        # 6. Main loop
        last_tel = 0
        while True:
            # Pump MQTT if connected
            if self.mqtt:
                try:
                    self.mqtt.check_msg()
                except Exception:
                    print("MQTT: Reconnecting...")
                    try: self.mqtt.disconnect() 
                    except: pass
                    time.sleep(1)
                    self._init_mqtt()

            # Check DFPlayer playback status
            if self.dfp and self.state in ("playing", "action"):
                try:
                    if not self.dfp.is_playing():
                        self.set_state("armed" if not self.is_blocked else "blocked")
                except Exception as e:
                    print("Error checking playback status:", e)
                    self.set_state("IO Error")

            # Check PIR sensor
            if self.pir_latch and self.pir_latch.pending():
                if not self.is_blocked and self.state in ("armed", "idle"):
                    self.triggers += 1
                    self._start_action()
                else:
                    print("PIR triggered but blocked")

            # Periodic telemetry
            now = time.ticks_ms()
            if self.mqtt and time.ticks_diff(now, last_tel) > 5000:
                self._telemetry()
                last_tel = now

            self.render_display()
            time.sleep(0.1)

# ----------------------------
# Entrypoint
# ----------------------------
def main():
    """Instantiates and runs the prop."""
    debug = secrets.DEBUG if hasattr(secrets, "DEBUG") else False
    prop = CoffinProp(debug=debug)
    prop.run()

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

        # _publish() serialisation test
        class DummyMQ:
            def __init__(self):
                self.publ = []
            def publish(self, topic, payload, retain=False, qos=0):
                self.publ.append((topic, payload, retain, qos))

        prop = CoffinProp(debug=False)
        prop.mqtt = DummyMQ()
        prop._publish(b'topic', {'a': 1}, retain=True)
        assert prop.mqtt.publ, "_publish did not invoke underlying publish()"
        payload = prop.mqtt.publ[0][1]
        assert isinstance(payload, (bytes, bytearray)) and payload.startswith(b'{') and b'"a"' in payload

        # ensure_lib should at least import stdlib json on CPython
        mod = ensure_lib('json')
        import json as _json
        assert mod is _json

        print("All helper checks passed.")
