# tesla/hue/nest dashboard plugin
from dash import html, Input, Output
import json

name = "Tesla/Hue/Nest"
path = "/tesla-hue-nest"
zone = "card"

def layout():
    return html.Div([
        html.H4("Tesla / Hue / Nest"),
        html.Div(id="thn-status", children="status: —"),
    ])

def register_callbacks(app, services):
    mqtt = services["mqtt"]
    cache = services["cache"]
    tick = services["tick_id"]

    T_STATUS = "halloween/tesla_hue_nest/status"
    def _on_status(topic, payload: bytes):
        try:
            cache["thn_status"] = json.loads(payload.decode()).get("state", "—")
        except Exception:
            cache["thn_status"] = payload.decode("utf-8", "replace") or "—"

    mqtt.subscribe(T_STATUS, _on_status)

    @app.callback(Output("thn-status", "children"), Input(tick, "n_intervals"))
    def _render(_):
        return f"status: {cache.get('thn_status', '—')}"
