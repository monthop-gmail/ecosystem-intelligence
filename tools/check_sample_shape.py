#!/usr/bin/env python3
"""ตรวจว่า sample.jsonl ยังตรงกับสิ่งที่ emitter ผลิต — **เทียบรูปร่าง ไม่ใช่เทียบไบต์**

ทำไมไม่ใช่ git diff --exit-code เหมือน openapi.json

    เนื้อหาของ event ขึ้นกับสภาพ ecosystem ตอนนั้น — คำแนะนำอ้างถึง issue ที่เปิดค้าง
    และบอกว่า "ขยับล่าสุดกี่วันก่อน" ซึ่งเปลี่ยนทุกวัน และใน CI ที่ยังไม่ได้ sync
    ก็ไม่มีข้อมูลนั้นเลย · เทียบไบต์จึงแดงตลอดโดยไม่มีอะไรผิดจริง

    สิ่งที่ต้องคงที่คือ **รูปร่าง** — key ที่มี ชนิดของ event ชนิดของ subject
    ถ้ารูปร่างเปลี่ยนแปลว่า emitter เปลี่ยน และปลายทางที่เขียนเทสต์ไว้จะพัง
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ecosystem_graph.db import connect  # noqa: E402
from ecosystem_graph.integration.emit import collect  # noqa: E402

SAMPLE = ROOT / "integration" / "events" / "sample.jsonl"


def shape(events: list[dict]) -> dict:
    """รูปร่างที่ปลายทางพึ่งพาได้ — ไม่รวมค่าที่เปลี่ยนตามสภาพ ecosystem

    เก็บเป็น **ชุดของชุด key ต่อ event_type** ไม่ใช่ union ทั้งไฟล์

    รอบแรกผมใช้ union แล้วลองลบ key ออกจาก event ใบเดียวเพื่อทดสอบ — **จับไม่ได้**
    เพราะใบอื่นยังมี key นั้นอยู่ union เลยไม่เปลี่ยน ปลายทางที่อ่านทีละใบจะเจอใบที่
    ขาด key โดยที่ CI บอกว่าผ่าน
    """
    by_type: dict[str, set] = {}
    for e in events:
        variant = (
            tuple(sorted(e)),
            tuple(sorted(e.get("metadata", {}))),
            e["subject_type"],
            e["metadata"].get("record_type"),
            e["source"]["kind"],
            tuple(sorted(e["source"])),
        )
        by_type.setdefault(e["event_type"], set()).add(variant)
    return {t: sorted(v) for t, v in sorted(by_type.items())}


def main() -> int:
    committed = [json.loads(x) for x in SAMPLE.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not committed:
        print(f"❌ {SAMPLE.name} ว่างเปล่า")
        return 1

    with connect(readonly=True) as conn:
        fresh = collect(conn, team=None, drift=False, all_teams=True,
                        occurred_at="2026-01-01T00:00:00Z")

    a, b = shape(committed), shape(fresh)
    if a == b:
        print(f"✅ {SAMPLE.name} ({len(committed)} event) รูปร่างตรงกับ emitter")
        return 0

    print("❌ รูปร่างไม่ตรง — emitter เปลี่ยนแต่ตัวอย่างยังเป็นของเก่า")
    for t in sorted(set(a) | set(b)):
        if a.get(t) != b.get(t):
            print(f"  {t}")
            only_file = [v for v in a.get(t, []) if v not in b.get(t, [])]
            only_emit = [v for v in b.get(t, []) if v not in a.get(t, [])]
            for v in only_file:
                print(f"    มีในไฟล์แต่ emitter ไม่ผลิต : keys={list(v[0])}")
                print(f"                                metadata={list(v[1])}")
            for v in only_emit:
                print(f"    emitter ผลิตแต่ไฟล์ไม่มี    : keys={list(v[0])}")
                print(f"                                metadata={list(v[1])}")
    print("\nรัน make emit-sample แล้ว commit ไฟล์ใหม่")
    return 1


if __name__ == "__main__":
    sys.exit(main())
