"""ดู event/v1 ที่ระบบจะปล่อยออกไป — ไม่ได้ส่งไปไหน

การส่งจริงต้องตกลงเรื่อง transport กับปลายทางก่อน (บันทึกไว้ใน platform-contract.yaml
หัวข้อ blocking) ตอนนี้ทำได้แค่แสดงให้ดูว่า payload หน้าตาเป็นยังไง
"""
from __future__ import annotations

import argparse
import json
import sys

from .. import advisor
from ..db import connect
from ..guardian import checks
from . import events


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="แสดง event/v1 ที่จะปล่อยออกไป")
    ap.add_argument("--team")
    ap.add_argument("--drift", action="store_true", help="แสดง event ของ guardian แทน")
    args = ap.parse_args(argv)

    with connect(readonly=True) as conn:
        if args.drift:
            report = checks.run_all(conn)
            payloads = events.drift_events(report["findings"])
            if not payloads:
                print("ไม่มี error ของ guardian จึงไม่มี event ให้ปล่อย "
                      "(warning ไม่ใช่เหตุการณ์ที่ต้องบันทึกถาวร)")
                return 0
        else:
            if not args.team:
                ap.error("ต้องระบุ --team หรือใช้ --drift")
            result = advisor.ask(conn, args.team, "ทีมเราควรทำอะไรต่อ?")
            if result is None:
                print(f"❌ ไม่รู้จักทีม {args.team}")
                return 1
            payloads = events.advisory_events(result)

    print(json.dumps(payloads, ensure_ascii=False, indent=1))
    print(f"\n{len(payloads)} event · ยังไม่ได้ส่งไปไหน", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
