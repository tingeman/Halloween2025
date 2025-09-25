# server/dashboard/app.py
import os
from dash import Dash, html, dcc
import dash_bootstrap_components as dbc
from mqtt_service import MQTTService
from plugin_loader import discover_plugins
import os
import socket

# Env
MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "dashboard")
# Safe fallback: allow MQTT_PW or MQTT_DASHBOARD_PW to be present in the container
MQTT_PW   = os.getenv("MQTT_PW") or os.getenv("MQTT_DASHBOARD_PW", "")
PORT      = int(os.getenv("DASHBOARD_PORT", "8050"))

client_id = f"dashboard-{socket.gethostname()}-{os.getpid()}"

# Services
mqtt = MQTTService(
    host=MQTT_HOST,
    port=MQTT_PORT,
    username=MQTT_USER,
    password=MQTT_PW,
    client_id=client_id,
    # will=WillConfig(topic="halloween/dashboard/status", payload="offline", qos=1, retain=True),
)
mqtt.connect()
CACHE = {}  # shared dict for plugins

# Discover: builtins + external props
PLUGINS = discover_plugins("/opt/props", "/app/builtin_plugins")

# Dash app
external_stylesheets = [dbc.themes.BOOTSTRAP]
app = Dash(__name__, external_stylesheets=external_stylesheets)
app.config.suppress_callback_exceptions = True 
server = app.server

# Separate zones
topbar_items = [p["layout"]() for p in PLUGINS if p["zone"] == "topbar"]
card_items   = [
    dbc.Card(dbc.CardBody(p["layout"]()), className="mb-3 shadow-sm")
    for p in PLUGINS if p["zone"] == "card"
]

def navbar():
    return dbc.Navbar(
        dbc.Container([
            html.Span("🎃 Halloween Dashboard", className="navbar-brand mb-0 h1"),
            html.Div(id="topbar-widgets", className="d-flex gap-2 ms-auto", children=topbar_items),
        ]),
        color="dark", dark=True, className="mb-3"
    )

app.layout = dbc.Container([
    navbar(),
    # Global tick that plugins can use if they need a steady refresh
    dcc.Interval(id="global-tick", interval=1000, n_intervals=0),
    html.Div(id="cards-area", children=card_items),
], fluid=True)

# Register plugin callbacks with shared services
SERVICES = {"mqtt": mqtt, "cache": CACHE, "app": app, "tick_id": "global-tick"}
for p in PLUGINS:
    try:
        p["register"](app, SERVICES)
    except Exception as e:
        print(f"[plugin:{p['name']}] register_callbacks failed: {e}")

def _on_exit():
    mqtt.disconnect()

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=PORT, debug=True)
    finally:
        _on_exit()
