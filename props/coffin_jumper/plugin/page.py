# coffin jumper dashboard plugin
# props/coffin_jumper/plugin/page.py
from dash import html, dcc, Input, Output, State
import json

name = "Coffin Jumper"
path = "/coffin-jumper"       # not used by base app yet, but good to keep
zone = "card"                 # default; include for clarity

def layout():
    return html.Div([
        html.H4("Coffin Jumper"),
        html.Div(id="cj-fires", children="fires: —"),
        html.Div(className="d-flex gap-2", children=[
            dcc.Input(id="cj-volume", type="number", min=0, max=30, placeholder="volume"),
            html.Button("Trigger", id="cj-trigger", n_clicks=0),
        ])
    ])

def register_callbacks(app, services):
    mqtt = services["mqtt"]
    cache = services["cache"]
    tick = services["tick_id"]  # "global-tick"

    T_TELEM = "halloween/coffin_jumper/telemetry"
    T_CMD   = "halloween/coffin_jumper/cmd"

    def _on_telem(topic, payload: bytes):
        try:
            data = json.loads(payload.decode())
            cache["cj_fires"] = data.get("fires", "—")
        except Exception:
            cache["cj_fires"] = "—"

    mqtt.subscribe(T_TELEM, _on_telem)

    @app.callback(Output("cj-fires", "children"), Input(tick, "n_intervals"))
    def _render(_):
        return f"fires: {cache.get('cj_fires', '—')}"

    @app.callback(
        Output("cj-trigger", "n_clicks"),
        Input("cj-trigger", "n_clicks"),
        State("cj-volume", "value"),
        prevent_initial_call=True
    )
    def _trigger(_, volume):
        cmd = {"action": "trigger"}
        if volume is not None:
            cmd = {"action": "trigger", "params": {"volume": int(volume)}}
        mqtt.publish(T_CMD, json.dumps(cmd))
        return 0
