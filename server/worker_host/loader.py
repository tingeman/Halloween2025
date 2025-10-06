# server/worker_host/worker_host/loader.py
from __future__ import annotations
import importlib.util, os, sys, traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List, Type, Optional
from .base import BaseWorker

DEBUG = os.getenv("WORKER_DEBUG", "0") == "1"

def _csv_set(envname: str) -> set[str]:
    v = os.getenv(envname, "")
    return {s.strip() for s in v.split(",") if s.strip()}

DISABLE_ALL_BUILTINS = os.getenv("WORKER_DISABLE_ALL_BUILTINS", "0") == "1"
BUILTINS_ALLOW = _csv_set("WORKER_BUILTINS_ALLOW")      # e.g. "heartbeat,smoketest"
BUILTINS_DISABLE = _csv_set("WORKER_BUILTINS_DISABLE")  # e.g. "heartbeat"

@dataclass
class WorkerDesc:
    prop_id: str
    cls: Type[BaseWorker]
    origin: Path
    config_path: Optional[Path]

def _load_module_from_path(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

def _validate_worker(module, origin: Path) -> Optional[Type[BaseWorker]]:
    Worker = getattr(module, "Worker", None)
    if Worker is None:
        print(f"[worker_loader] {origin}: missing class `Worker`")
        return None
    if not isinstance(Worker, type) or not issubclass(Worker, BaseWorker):
        print(f"[worker_loader] {origin}: `Worker` must subclass BaseWorker")
        return None
    return Worker

def _maybe_prop_id_from_builtin(worker_py: Path) -> str:
    # Allow an explicit PROP_ID variable in builtin modules; fallback to filename.
    try:
        txt = worker_py.read_text(encoding="utf-8", errors="ignore")
        for line in txt.splitlines():
            if line.strip().startswith("PROP_ID"):
                # naive parse: PROP_ID = "foo"
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    except Exception:
        pass
    return worker_py.stem

def _try_load_one(mod_name: str, worker_py: Path, prop_id_hint: Optional[str] = None) -> Optional[WorkerDesc]:
    try:
        m = _load_module_from_path(mod_name, worker_py)
        cls = _validate_worker(m, worker_py)
        if not cls:
            return None
        cfg_json = worker_py.with_name("config.json")
        cfg_yaml = worker_py.with_name("config.yaml")
        cfg_yml  = worker_py.with_name("config.yml")
        config_path = cfg_json if cfg_json.exists() else (cfg_yaml if cfg_yaml.exists() else (cfg_yml if cfg_yml.exists() else None))

        if worker_py.parent.name == "backend" and worker_py.parent.parent.parent.name == "props":
            prop_id = worker_py.parent.parent.name
        else:
            prop_id = prop_id_hint or getattr(m, "PROP_ID", None) or _maybe_prop_id_from_builtin(worker_py)

        return WorkerDesc(prop_id=prop_id, cls=cls, origin=worker_py, config_path=config_path)

    except Exception as e:
        print(f"[worker_loader] Import failed for {worker_py}: {e}")
        if DEBUG:
            traceback.print_exc()
        return None

def _builtin_enabled(name: str) -> bool:
    # Precedence: disable-all → allow-list (if set) → disable-list
    if DISABLE_ALL_BUILTINS:
        return False
    if BUILTINS_ALLOW:
        return name in BUILTINS_ALLOW
    if BUILTINS_DISABLE:
        return name not in BUILTINS_DISABLE
    return True

def discover_workers(props_root: Path, builtin_root: Optional[Path] = None) -> List[WorkerDesc]:
    workers: List[WorkerDesc] = []

    # Built-ins (optional)
    if builtin_root and builtin_root.exists():
        for wf in sorted(builtin_root.glob("*.py")):
            if wf.name.startswith("_"):
                continue
            builtin_name = wf.stem  # e.g., "heartbeat"
            if not _builtin_enabled(builtin_name):
                print(f"[worker_loader] Skipping builtin '{builtin_name}' (disabled by env)")
                continue
            mod_name = f"builtin_worker_{builtin_name}"
            desc = _try_load_one(mod_name, wf, prop_id_hint=builtin_name)
            if desc:
                workers.append(desc)

    # Prop backends
    for worker_py in sorted(Path(props_root).glob("*/backend/worker.py")):
        mod_name = f"prop_worker_{worker_py.parent.parent.name}"
        desc = _try_load_one(mod_name, worker_py)
        if desc:
            workers.append(desc)

    if not workers:
        print("[worker_loader] No workers found. Expected built-ins or /app/props/*/backend/worker.py")

    return workers
