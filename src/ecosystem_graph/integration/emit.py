"""ปล่อย event/v1 ออกมาเป็นไฟล์ — artifact handoff (devfactory-core#32)

**ทำไมเป็นไฟล์ ไม่ใช่ HTTP**

ตอนเปิด issue ผมเสนอสามทาง (webhook / ดึงจาก API / broker) โดยไม่ได้ตรวจว่า
ทางไหนมีอยู่จริง — devfactory-core ตรวจให้แล้วพบว่า **ไม่มีสักทาง**
เราไม่มี endpoint สำหรับ event เขาไม่มี endpoint รับ และ broker ก็ยังไม่มีใน ecosystem

ทางที่ 4 ที่เขาเสนอกลับมาคือ artifact handoff — ศูนย์ service ทั้งสองฝั่ง
ทดสอบใน CI ได้วันนี้ และพิสูจน์ว่าท่อไหลได้จริงก่อนตัดสินใจลงทุน

    --out            เขียนลงไฟล์แทน stdout
    --format jsonl   หนึ่งบรรทัดหนึ่ง event — อ่านทีละใบได้โดยไม่ต้องโหลดทั้งก้อน
    --occurred-at    ตรึงเวลาให้ผลออกมาเหมือนเดิมทุกครั้ง สำหรับตัวอย่างที่ commit ไว้
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import advisor, queries
from ..db import connect
from ..guardian import checks
from . import events


def collect(conn, *, team: str | None, drift: bool, all_teams: bool,
            occurred_at: str | None) -> list[dict]:
    payloads: list[dict] = []
    if all_teams or team:
        targets = ([t["id"] for t in queries.list_teams(conn)] if all_teams else [team])
        for t in targets:
            result = advisor.ask(conn, t, "ทีมเราควรทำอะไรต่อ?")
            if result:
                payloads.extend(events.advisory_events(result, occurred_at=occurred_at))
    if drift or all_teams:
        report = checks.run_all(conn)
        payloads.extend(events.drift_events(report["findings"], occurred_at=occurred_at))
    return payloads


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ปล่อย event/v1 ที่ระบบผลิต")
    ap.add_argument("--team")
    ap.add_argument("--all", action="store_true", help="ทุกทีม + guardian")
    ap.add_argument("--drift", action="store_true", help="เฉพาะ event ของ guardian")
    ap.add_argument("--format", choices=["json", "jsonl"], default="json")
    ap.add_argument("--out", help="เขียนลงไฟล์แทน stdout")
    ap.add_argument("--occurred-at", help="ตรึงเวลา เช่น 2026-01-01T00:00:00Z")
    args = ap.parse_args(argv)

    if not (args.team or args.all or args.drift):
        ap.error("ต้องระบุ --team, --all หรือ --drift")

    with connect(readonly=True) as conn:
        if args.team and not advisor.ask(conn, args.team, "ping"):
            print(f"❌ ไม่รู้จักทีม {args.team}")
            return 1
        payloads = collect(conn, team=args.team, drift=args.drift,
                           all_teams=args.all, occurred_at=args.occurred_at)

    if not payloads:
        print("ไม่มี event ให้ปล่อย", file=sys.stderr)
        return 0

    if args.format == "jsonl":
        text = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True)
                         for e in payloads) + "\n"
    else:
        text = json.dumps(payloads, ensure_ascii=False, indent=1) + "\n"

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"เขียน {len(payloads)} event ลง {args.out}", file=sys.stderr)
    else:
        print(text, end="")
        print(f"\n{len(payloads)} event · ยังไม่ได้ส่งไปไหน", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
