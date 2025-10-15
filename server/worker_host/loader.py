# server/worker_host/worker_host/loader.py
from __future__ import annotations
import importlib.util, os, sys, traceback, importlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Type, Optional
import types
from pydantic import BaseModel
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
    config_model: Optional[Type[BaseModel]]


def _load_module_from_path(name: str, file_path: Path):
    """
    Load a python module from file_path.

    - If the backend directory contains __init__.py (is a package), import the
      module as a package member (e.g. props.<prop>.backend.worker) using
      importlib.import_module so relative imports and package semantics work.
    - Otherwise, load the single-file module via spec_from_file_location but
      create synthetic parent package entries (props, props.<prop>, props.<prop>.backend)
      in sys.modules to allow relative imports inside the backend to resolve.
    """
    backend_dir = file_path.parent
    prop_dir = backend_dir.parent
    props_dir = prop_dir.parent

    # Compute parent package names/paths if layout looks like props/<prop>/backend/...
    parent_packages = []
    package_paths = []
    if props_dir.name == "props":
        prop_pkg = prop_dir.name
        package_root = "props"
        parent_packages = [
            package_root,
            f"{package_root}.{prop_pkg}",
            f"{package_root}.{prop_pkg}.backend",
        ]
        package_paths = [
            str(props_dir),
            str(prop_dir),
            str(backend_dir),
        ]

    # If backend is a real package, import using package semantics
    package_init = backend_dir / "__init__.py"
    if package_init.exists():
        # ensure repo root (parent of 'props') is on sys.path so importlib can find 'props'
        repo_root = Path(props_dir).parent
        repo_root_str = str(repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)

        if props_dir.name == "props":
            pkg_base = f"props.{prop_pkg}.backend"
            module_name = f"{pkg_base}.{file_path.stem}"
        else:
            # fallback to loading by filename as top-level module name
            module_name = name

        try:
            mod = importlib.import_module(module_name)
            return mod
        except Exception as e:
            # Don't fail hard here; fall back to file-based loading below.
            print(f"[worker_loader] Package import failed for {module_name}: {e}")
            if DEBUG:
                traceback.print_exc()

    # Non-package backend: create lightweight parent package modules so relative imports work
    for pkg, pkg_path in zip(parent_packages, package_paths):
        if pkg not in sys.modules:
            m = types.ModuleType(pkg)
            m.__path__ = [pkg_path]
            sys.modules[pkg] = m

    # Load module from file using a package-like name when possible so relative
    # imports inside the backend file resolve correctly. If we can't compute a
    # package name (non-standard layout) fall back to the caller-provided name.
    if props_dir.name == "props":
        fallback_name = f"props.{prop_pkg}.backend.{file_path.stem}"
    else:
        fallback_name = name

    spec = importlib.util.spec_from_file_location(fallback_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {file_path}")

    mod = importlib.util.module_from_spec(spec)
    # Register module under the fallback/package-like name so relative imports work.
    sys.modules[fallback_name] = mod
    # Also register under the caller-provided name to preserve previous behavior
    # (some callers expect a stable unique key).
    if fallback_name != name:
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

        # Discover config file
        cfg_json = worker_py.with_name("config.json")
        cfg_yaml = worker_py.with_name("config.yaml")
        cfg_yml  = worker_py.with_name("config.yml")
        config_path = next((p for p in [cfg_json, cfg_yaml, cfg_yml] if p.exists()), None)

        # Discover Pydantic config model
        ConfigModel = getattr(m, "ConfigModel", None)
        if ConfigModel and not (isinstance(ConfigModel, type) and issubclass(ConfigModel, BaseModel)):
            print(f"[worker_loader] {worker_py.parent.parent.name}: `ConfigModel` must be a Pydantic BaseModel subclass.")
            ConfigModel = None # Ignore invalid model

        # Determine prop_id
        prop_id = getattr(m, "PROP_ID", None) or prop_id_hint or worker_py.stem

        return WorkerDesc(
            prop_id=prop_id,
            cls=cls,
            origin=worker_py,
            config_path=config_path,
            config_model=ConfigModel,
        )

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

    # Ensure repo root (parent of props_root) is on sys.path so package imports work.
    # This makes importlib.import_module("props.<prop>.backend.worker") possible.
    try:
        repo_root = Path(props_root).resolve().parent
        repo_root_str = str(repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)
    except Exception:
        pass

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
