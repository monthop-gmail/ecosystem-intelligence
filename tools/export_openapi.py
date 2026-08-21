#!/usr/bin/env python3
"""เขียน OpenAPI spec ลง docs/openapi.json — commit ไว้ให้รีวิวได้โดยไม่ต้องรัน server"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ecosystem_graph.api import app  # noqa: E402

out = ROOT / "docs" / "openapi.json"
out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
paths = len(app.openapi()["paths"])
print(f"✅ {out.relative_to(ROOT)} — {paths} paths")
