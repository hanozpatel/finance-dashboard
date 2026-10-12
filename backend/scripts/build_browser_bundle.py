"""Package the backend for the in-browser build.

    python backend/scripts/build_browser_bundle.py

The web build runs this backend inside the browser with Pyodide (see
``browser_bridge.py``). The browser needs the source as one file it can fetch,
so this zips exactly what the app imports at runtime — the application code and
the bundled state benchmarks — and nothing else: no tests, no build scripts, no
virtualenv, and above all no database or ``.env``. The file list is an
allowlist rather than "everything minus exclusions" for that reason: a new
local file can never end up published by accident.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BACKEND.parent / "frontend" / "public" / "py" / "backend.zip"

# Directories whose .py files the app imports, plus the data it reads.
PACKAGES = ("routers", "services", "models")
DATA = ("data/state_benchmarks.json",)


def files() -> list[Path]:
    out = sorted(BACKEND.glob("*.py"))
    for package in PACKAGES:
        out += sorted((BACKEND / package).glob("*.py"))
    out += [BACKEND / d for d in DATA]
    return out


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files():
            zf.write(f, f.relative_to(BACKEND).as_posix())
    print(f"Wrote {len(files())} files to {target} ({target.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
