# server/dashboard/plugin_loader.py
import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Dict, Any, Tuple

# Toggle verbose tracebacks by setting ENV: DASHBOARD_DEBUG=1
import os
DEBUG = os.getenv("DASHBOARD_DEBUG", "0") == "1"


@dataclass
class PluginDesc:
    name: str
    layout: Callable[[], Any]
    register: Callable[[Any, Dict[str, Any]], None]
    zone: str  # "card" | "topbar"


def _load_module_from_path(name: str, file_path: str):
    """Load a Python module from an arbitrary file path with a stable module name."""
    spec = importlib.util.spec_from_file_location(name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _validate_plugin(module, origin: Path) -> Tuple[PluginDesc | None, List[str]]:
    """Validate required symbols and types; return (PluginDesc or None, errors)."""
    errors: List[str] = []
    # Required attributes
    required = ["name", "layout", "register_callbacks"]
    missing = [attr for attr in required if not hasattr(module, attr)]
    if missing:
        errors.append(f"Missing required attribute(s): {', '.join(missing)}")

    # Early exit if missing
    if errors:
        return None, errors

    name = getattr(module, "name")
    layout = getattr(module, "layout")
    register = getattr(module, "register_callbacks")
    zone = getattr(module, "zone", "card")

    # Type checks
    if not isinstance(name, str) or not name.strip():
        errors.append("Attribute 'name' must be a non-empty string.")
    if not callable(layout):
        errors.append("Attribute 'layout' must be a callable returning a Dash component.")
    if not callable(register):
        errors.append("Attribute 'register_callbacks' must be a callable (app, services) -> None.")
    if zone not in ("card", "topbar"):
        errors.append("Attribute 'zone' must be 'card' or 'topbar' if provided.")

    if errors:
        return None, errors

    return PluginDesc(name=name, layout=layout, register=register, zone=zone), []


def _try_load_one(module_name: str, file_path: Path) -> PluginDesc | None:
    try:
        m = _load_module_from_path(module_name, str(file_path))
    except Exception as e:
        print(f"[plugin_loader] Import failed for {file_path}: {e}")
        if DEBUG:
            traceback.print_exc()
        return None

    desc, errors = _validate_plugin(m, file_path)
    if errors:
        print(f"[plugin_loader] {file_path} is not a valid plugin:")
        for err in errors:
            print(f"  - {err}")
        # Optional hint: show what attributes actually exist
        if DEBUG:
            have = sorted([a for a in dir(m) if not a.startswith('_')])
            print(f"  Available attributes: {have}")
        return None

    print(f"[plugin_loader] Loaded plugin '{desc.name}' from {file_path} (zone={desc.zone})")
    return desc


def discover_plugins(props_root: str, builtins_root: str) -> List[Dict]:
    """
    Discover plugins from:
      - built-ins: <builtins_root>/*.py
      - props:     <props_root>/*/plugin/page.py
    Returns a list of dicts as expected by app.py:
      { "name", "layout", "register", "zone" }
    """
    plugins: List[Dict] = []

    # Built-in plugins
    for f in sorted(Path(builtins_root).glob("*.py")):
        desc = _try_load_one(f"builtin_{f.stem}", f)
        if desc:
            plugins.append({"name": desc.name, "layout": desc.layout, "register": desc.register, "zone": desc.zone})

    # Prop plugins
    for page in sorted(Path(props_root).glob("*/plugin/page.py")):
        mod_name = f"plugin_{page.parent.parent.name}"
        desc = _try_load_one(mod_name, page)
        if desc:
            plugins.append({"name": desc.name, "layout": desc.layout, "register": desc.register, "zone": desc.zone})

    if not plugins:
        print("[plugin_loader] No plugins found. Expected /app/builtin_plugins/*.py or /opt/props/*/plugin/page.py")

    return plugins
