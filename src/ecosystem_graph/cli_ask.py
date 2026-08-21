"""ถาม advisor จาก command line — `make ask TEAM=... Q="..."`"""
from __future__ import annotations

import argparse
import sys

from . import advisor
from .db import connect
from .llm import LLMError, get_provider


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ถาม Ecosystem Team Advisor")
    ap.add_argument("--team", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--provider", default=None, help="claude | chatgpt | offline")
    ap.add_argument("--effort", default="high")
    args = ap.parse_args(argv)

    try:
        provider = get_provider(args.provider)
    except LLMError as e:
        print(f"❌ {e}")
        return 2

    with connect(readonly=True) as conn:
        try:
            result = advisor.ask(conn, args.team, args.question,
                                 provider=provider, effort=args.effort)
        except LLMError as e:
            print(f"❌ provider ตอบไม่ได้: {e}")
            return 2

    if result is None:
        print(f"❌ ไม่รู้จักทีม {args.team}")
        return 1

    a = result["answer"]
    gen = result["generated_by"]
    print(f"ทีม {a['team']}  ·  ตอบโดย {gen['provider']}/{gen['model']}  ·  ข้อมูล ณ {result['as_of']}\n")

    if not a["answerable"]:
        print("ตอบไม่ได้จากข้อมูลที่มี — ขาด:")
        for m in a["missing_information"]:
            print(f"  · {m}")
        return 0

    print("สถานะปัจจุบัน")
    for line in a["current_state"]:
        print(f"  · {line}")

    print("\nควรทำอะไรต่อ")
    for s in a["recommended_next_steps"]:
        print(f"  [{s['priority']}] {s['title']}")
        print(f"      {s['why']}")
        print(f"      อ้างอิง: {', '.join(s['references'])}")

    if a["dependencies"]:
        print("\nขึ้นกับ: " + ", ".join(a["dependencies"]))
    if a["risks"]:
        print("\nความเสี่ยง")
        for r in a["risks"]:
            print(f"  ⚠ {r}")

    g = result["grounding"]
    if not g["ok"]:
        print(f"\n❌ คำตอบอ้าง id ที่ไม่มีอยู่จริง: {', '.join(g['unknown_ids'])}")
        return 1
    if g["suspicious_mentions"]:
        print(f"\n⚠  พบชื่อที่คล้าย contract แต่ไม่มีใน ecosystem: "
              f"{', '.join(g['suspicious_mentions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
