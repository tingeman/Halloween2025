Dashboard plugin loader

This folder contains the small plugin loader used by the dashboard app. The
loader auto-discovers plugins from two locations:

- built-ins: `<builtins_root>/*.py` (app's builtin plugins)
- props: `<props_root>/*/plugin/page.py` (per-prop plugin modules)

Class-based plugin support
--------------------------

The loader supports two plugin styles for backwards compatibility:

1) Module-level API (legacy)
   - The module must expose:
     - `name` (str)
     - `layout()` (callable returning a Dash fragment)
     - `register_callbacks(app, services)` (callable that wires callbacks)
   - Optional: `zone` ("card" or "topbar").

2) Class-based API (new)
   - The module may export a `Plugin` class. The loader will try to
     instantiate `Plugin()` (no-argument constructor) and then read the
     following attributes or methods from the instance:
     - `name` (str)
     - `layout()` (callable)
     - `register(app, services)` or `register_callbacks(app, services)` (method)
     - optional `zone` (defaults to "card")
   - Example minimal plugin module:

```python
class Plugin:
    name = "My Plugin"
    zone = "card"

    def layout(self):
        # return Dash components
        ...

    def register(self, app, services):
        # wire MQTT subscriptions and Dash callbacks
        ...
```

Notes
-----
- The loader remains backwards compatible: existing module-level plugins
  continue to work without modification.
- Instantiation errors while creating `Plugin()` will cause the loader to
  skip the plugin and print an error; enable `DASHBOARD_DEBUG=1` for full
  tracebacks.
- Keep `Plugin.__init__()` cheap and side-effect free. The loader creates
  instances during discovery (before services like MQTT/cache are passed
  in).

