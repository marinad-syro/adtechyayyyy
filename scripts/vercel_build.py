#!/usr/bin/env python3
"""Copy frontend assets into paths the serverless bundle can serve."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend"

if not SRC.is_dir():
    print(f"ERROR: missing {SRC}", file=sys.stderr)
    raise SystemExit(1)

for dest in (ROOT / "backend" / "_frontend", ROOT / "_frontend", ROOT / "public"):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SRC, dest)
    print(f"Copied frontend -> {dest}")
