#!/usr/bin/env python3
"""CLI ของ validator — ตัวจริงอยู่ที่ src/ecosystem_graph/validate.py

    python3 tools/validate_ecosystem.py [--github] [ecosystem.yaml]

exit 0 = ผ่าน (มี warning ได้)   exit 1 = มี error
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecosystem_graph.validate import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
