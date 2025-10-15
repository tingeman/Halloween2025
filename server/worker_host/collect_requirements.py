"""
Collect requirements.txt from server/worker_host and all props/*/backend,
dedupe entries and write combined requirements to a target file.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys

def find_repo_root(start: Path) -> Path | None:
    """
    On host, the repo root contains both 'props' and 'server' directories.

    Walk upward from `start` looking for a directory that contains both
    'props' and 'server' folders (heuristic for repo root). Return None
    if not found.
    """
    for p in (start, *start.parents):
        if (p / "props").is_dir() and (p / "server").is_dir():
            return p
    return None

# Allow explicit override (useful in Dockerfile or CI)
env_root = os.getenv("REPO_ROOT")
if env_root:
    ROOT = Path(env_root)
else:
    # Start from the script directory
    start_dir = Path(__file__).resolve().parent
    found = find_repo_root(start_dir)
    if found:
        ROOT = found
    else:
        # fallback: keep previous heuristic (script was two levels down in repo)
        ROOT = Path(__file__).resolve().parents[2]


print(f"collect_requirements.py: Repo root: {ROOT}")
# Adjust if you want a different output path
out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/combined-requirements.txt")

req_files = []
req_files += list(ROOT.glob("**/worker_host/requirements.txt"))
req_files += list(ROOT.glob("**/worker_host/builtin_workers/requirements.txt"))
req_files += list((ROOT / "props").glob("*/backend/requirements.txt"))

seen = {}
lines = []
for rf in req_files:
    print(f"collect_requirements.py: Processing: {rf}")
    if not rf.exists():
        continue
    for raw in rf.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split(";", 1)[0].strip()
        if key in seen:
            continue
        seen[key] = line
        lines.append(line)
        print(f"  + {line}  (from {rf})")

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("\n".join(sorted(lines)) + "\n")
print(f"Wrote combined requirements to: {out_path}")