"""Coffin Jumper plugin (class-based)

This module is intentionally small and defensive: MQTT telemetry updates a
shared cache and a periodic Dash callback reads that cache to avoid race
conditions between asynchronous MQTT callbacks and Dash renders.

"""

from dash import html, dcc, Input, Output, State
import json

# Import BasePlugin from the standalone plugin_base package so plugins get thread-safe helpers
from plugin_base import BasePlugin


class Plugin(BasePlugin):
    """Class-based plugin object for Coffin Jumper.

    The loader will instantiate this class and use its attributes/methods
    to integrate the plugin into the dashboard. The instance methods mirror
    the previous module-level API.
    """

    name = "Coffin Jumper"
    zone = "card"

    T_TEL = "halloween/esp32-coffin-jumper-01/telemetry"
    T_CMD = "halloween/esp32-coffin-jumper-01/cmd"
    T_AVAIL = "halloween/esp32-coffin-jumper-01/availability"

    def layout(self):
        """Return the Dash layout for the plugin."""
        return html.Div([
            # Show the prop name and an inline availability badge next to it
            html.H4([
                self.name,
                # outer span has minimal layout responsibility; use a small
                # Bootstrap spacing utility so the badge doesn't touch the name
                html.Span(id="cj-availability", className="ms-2", children=[
                    html.Span("unknown", className="badge bg-secondary text-white")
                ]),
            ]),
            html.Div(id="cj-fires", children="fires: —"),
            # Telemetry table: a simple key / value table. The callback
            # will populate this table with rows showing the current
            # telemetry snapshot. We keep the initial placeholder so the
            # DOM element exists before the first tick.
            html.Table(id="cj-telem", children=[
                html.Tbody([html.Tr([html.Td("telemetry:"), html.Td("—")])])
            ]),
            html.Div(className="d-flex gap-2", children=[
                dcc.Input(id="cj-volume", type="number", min=0, max=30, value=20, placeholder="volume"),
                html.Button("Trigger", id="cj-trigger", n_clicks=0),
                html.Button("Play", id="cj-play", n_clicks=0),
            ])
        ])

    def on_register(self, app, services):
        """Register callbacks and MQTT subscriptions.

        This method is called by BasePlugin.register after services have been
        bound and helpers (cache_get/cache_set/mqtt_publish) are available.
        """

        # Subscribe instance method for telemetry using helper
        self.mqtt_subscribe(self.T_TEL, self._on_telem)
        # Subscribe to availability (LWT / retained) so we can show online/offline
        self.mqtt_subscribe(self.T_AVAIL, self._on_avail)

        # Register Dash callbacks using bound instance methods.
        # Note: app.callback(...) returns a decorator; calling that decorator
        # with a callable (here, the bound method `self._render`) registers
        # the instance method as the callback. Using a bound method ensures
        # the callback runs with the plugin instance (so `self` is available
        # for helpers like self.cache_get / self.cache_set). We use
        # `self._tick` as the Input so this plugin's periodic interval drives
        # the render.
        app.callback(
            Output("cj-fires", "children"),
            Input(self._tick, "n_intervals"),
        )(self._render_fire_count)

        # Register a periodic render for the raw telemetry view. We use the
        # same tick input so both views update together.
        app.callback(
            Output("cj-telem", "children"),
            Input(self._tick, "n_intervals"),
        )(self._render_telem)

        # Periodic render for availability badge
        app.callback(
            Output("cj-availability", "children"),
            Input(self._tick, "n_intervals"),
        )(self._render_avail)

        # Register trigger button callback
        # n_clicks is the button click count; by returning 0 from the callback, we prevent multiple clicks
        # from accumulating in the button state (which would cause repeated triggers on a single press)
        # On button press the callback is triggered as:
        # _trigger(n_clicks, volume) -> 0 
        app.callback(
            Output("cj-trigger", "n_clicks"),
            Input("cj-trigger", "n_clicks"),
            State("cj-volume", "value"),
            prevent_initial_call=True,
        )(self._trigger)
        
        app.callback(
            Output("cj-play", "n_clicks"),
            Input("cj-play", "n_clicks"),
            State("cj-volume", "value"),
            prevent_initial_call=True,
        )(self._play)


    def _on_telem(self, topic, payload: bytes):
        """Instance method to handle incoming telemetry payloads."""
        try:
            data = json.loads(payload.decode())
            # Use the thread-safe dict-like cache exposed by BasePlugin.
            # Store both the derived 'fires' count and the full telemetry
            # dict. Storing the entire telemetry in the shared cache makes
            # it easy for render methods to show a snapshot without race
            # conditions. Be mindful of payload size; if telemetry grows
            # large, consider trimming or storing only selected fields.
            self.cache["cj_fires"] = data.get("fires", "—")
            self.cache["cj_telem"] = data
        except Exception:
            self.cache["cj_fires"] = "—"
            self.cache["cj_telem"] = None

    def _render_fire_count(self, _):
        """Render callback: read the cached fires count and return text."""
        return f"fires: {self.cache.get('cj_fires', '—')}"

    def _on_avail(self, topic, payload: bytes):
        """Handle availability messages (LWT / retained).

        We expect payloads like 'online'/'offline' or JSON with a 'status'
        field for compatibility with different publishers.
        """
        try:
            text = payload.decode()
            # try JSON first
            try:
                parsed = json.loads(text)
                status = parsed.get("status") if isinstance(parsed, dict) else None
            except Exception:
                status = None

            if not status:
                # fallback to plain text
                status = text.strip()

            self.cache["cj_avail"] = status
        except Exception:
            self.cache["cj_avail"] = None

    def _render_avail(self, _):
        """Render the availability badge as a colored inline element."""
        s = (self.cache.get("cj_avail") or "unknown").lower()
        if s in ("online", "true", "up"):
            # Bootstrap green badge
            return html.Span("online", className="badge bg-success text-white")
        if s in ("offline", "false", "down"):
            return html.Span("offline", className="badge bg-danger text-white")
        return html.Span(s, className="badge bg-secondary text-white")

    def _trigger(self, _, volume):
        """Handle Trigger button presses and publish MQTT commands."""
        cmd = {"action": "trigger"}
        if volume is not None:
            cmd = {"action": "trigger", "params": {"volume": int(volume)}}
        # publish using helper made available by BasePlugin
        self.mqtt_publish(self.T_CMD, json.dumps(cmd))
        return 0

    def _trigger(self, _, volume):
        """Handle Trigger button presses and publish MQTT commands."""
        cmd = {"action": "play"}
        if volume is not None:
            cmd["params"] = {"volume": int(volume)}
        # publish using helper made available by BasePlugin
        self.mqtt_publish(self.T_CMD, json.dumps(cmd))
        return 0

    def _render_telem(self, _):
        """Render the cached telemetry dict as pretty-printed JSON.

        This is driven by the same periodic tick as the other render to
        avoid mixing UI updates across different timers.
        """
        telem = self.cache.get("cj_telem")
        if not telem:
            # return a small table with a placeholder
            return html.Table(html.Tbody([html.Tr([html.Td("telemetry:"), html.Td("—")])]))
        try:
            # Build table rows for each telemetry key/value
            rows = []
            # ensure stable ordering for the UI
            for k in sorted(telem.keys()):
                v = telem[k]
                if isinstance(v, (dict, list)):
                    cell = html.Pre(json.dumps(v, indent=2, sort_keys=True), style={"whiteSpace": "pre-wrap"})
                else:
                    cell = str(v)
                rows.append(html.Tr([html.Td(k), html.Td(cell)]))

            return html.Table(html.Tbody(rows), className="table table-sm")
        except Exception:
            # Fallback to str() if JSON serialization fails
            return html.Table(html.Tbody([html.Tr([html.Td("telemetry:"), html.Td(str(telem))])]))
