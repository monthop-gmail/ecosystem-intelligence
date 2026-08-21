"""Architecture Guardian จาก command line

    make guardian                      ตรวจทั้ง ecosystem
    make guardian REMOTE=1             ตรวจ manifest drift ด้วย (ต้องมี gh)
    make guardian-pr PR=agent-platform#33
    make guardian-pr PR=... POST=1     คอมเมนต์จริง (ต้องเปิดใน guardian.yaml ก่อน)
"""
from __future__ import annotations

import argparse
import sys

from .db import connect
from .guardian import checks, review

ICON = {"error": "❌", "warn": "⚠️ "}


def _print_findings(findings: list[dict]) -> None:
    by_rule: dict[str, list[dict]] = {}
    for f in findings:
        by_rule.setdefault(f["rule"], []).append(f)
    for rule, items in by_rule.items():
        head = items[0]
        print(f"\n{ICON[head['severity']]} {head['title']}  ({rule})")
        print(f"   {head['why']}")
        for f in items:
            print(f"   · {f['subject']}: {f['detail']}")
        print(f"   ทางแก้: {head['fix']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Architecture Guardian")
    ap.add_argument("--pr", help="เช่น agent-platform#33")
    ap.add_argument("--remote", action="store_true", help="ตรวจ manifest drift ด้วย")
    ap.add_argument("--post", action="store_true", help="คอมเมนต์จริงบน PR")
    args = ap.parse_args(argv)

    with connect(readonly=True) as conn:
        if args.pr:
            repo, _, num = args.pr.partition("#")
            result = review.post_review(conn, repo, int(num), confirm=args.post)
            r = result["review"]
            if not r.get("available", True):
                print(f"❌ {r['reason']}")
                return 1
            print(f"PR {repo}#{num} · ระดับ {r['level']} · "
                  f"error {r['errors']} · warn {r['warnings']}")
            _print_findings(r["findings"])
            print("\n─── คอมเมนต์ที่จะโพสต์ " + "─" * 40)
            print(r["comment"])
            print("─" * 60)
            if result["posted"]:
                print("\n✅ คอมเมนต์แล้ว")
            else:
                print(f"\n⏸  ไม่ได้คอมเมนต์ — {result['reason']}")
            return 1 if r["should_block"] else 0

        report = checks.run_all(conn, include_remote=args.remote)
        print(f"ตรวจ {len(report['rules_run'])} กฎ · "
              f"error {report['errors']} · warn {report['warnings']}")
        if report["rules_skipped"]:
            print(f"⏭  ข้าม (ต้องออกเน็ต): {', '.join(report['rules_skipped'])} "
                  f"— ใส่ REMOTE=1 เพื่อตรวจด้วย")
        if not report["findings"]:
            print("\n✅ ไม่พบปัญหา")
            return 0
        _print_findings(report["findings"])
        return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
