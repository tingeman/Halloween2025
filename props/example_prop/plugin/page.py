
from dash import html, dcc, Input, Output
import json

name = "Example Prop"
path = "/example-prop"

def layout():
    return html.Div([
        html.H4("Example Prop"),
        html.Div(id="ex-fires", children="fires: —"),
        html.Button("Trigger", id="ex-trigger", n_clicks=0),
    ])

def register_callbacks(app, services):
    mqtt = services["mqtt"]
    cache = services["cache"]

    T_TELEM = "halloween/example_prop/telemetry"
    T_CMD   = "halloween/example_prop/cmd"

    def _on_telem(topic, payload: bytes):
        try:
            data = json.loads(payload.decode())
            cache["ex_fires"] = data.get("fires", "—")
        except Exception:
            cache["ex_fires"] = "—"

    mqtt.subscribe(T_TELEM, _on_telem)

    @app.callback(Output("ex-fires", "children"), Input("uptime-poll", "n_intervals"))
    def _render(_):
        return f"fires: {cache.get('ex_fires', '—')}"

    @app.callback(Output("ex-trigger", "n_clicks"), Input("ex-trigger", "n_clicks"), prevent_initial_call=True)
    def _trigger(_n):
        mqtt.publish(T_CMD, json.dumps({"action": "trigger"}))
        return 0
