"""Impact analysis จาก command line

    make graph  COMPONENT=agent-platform [DIR=down|up]
    make impact CONTRACT=approval/v1 [LEVEL=breaking]
    make impact PR=agent-platform#35
"""
from __future__ import annotations

import argparse
import sys

from . import impact
from .db import connect


def _print_change(r: dict) -> None:
    icon = {"breaking": "🔴", "non-breaking": "🟢", "unsure": "🟡"}[r["level"]]
    print(f"{icon} {r['level'].upper()}\n")
    for f in r["files"]:
        tag = " (advisory)" if f.get("advisory") else ""
        print(f"  [{f['level']:<12}]{tag} {f['path']}")
        for why in f["reasons"]:
            print(f"                  · {why}")
    if r.get("disagreement"):
        print(f"\n  ⚠ {r['disagreement']}")
    print()
    for i in r["impact"]:
        print(f"  {i['contract']}")
        print(f"    {i['why']}")
        if i["affected_teams"]:
            print(f"    ทีมที่กระทบ: {', '.join(i['affected_teams'])}")


def _print_cross_team(r: dict) -> None:
    icon = {"breaking": "🔴", "non-breaking": "🟢", "unsure": "🟡"}[r["level"]]
    print(f"{icon} เปลี่ยน {r['contract']} ระดับ {r['level']}\n")
    print(f"  {r['why']}\n")
    print(f"  ทีมที่กระทบ      : {', '.join(r['affected_teams']) or '—'}")
    print(f"  component ที่กระทบ: {', '.join(r['affected_components']) or '—'}")
    print(f"  repo ที่กระทบ     : {', '.join(r['affected_repositories']) or '—'}")
    print(f"  contract ที่พัวพัน : {', '.join(r['affected_contracts']) or '—'}")

    print("\n  ความเสี่ยง")
    for x in r["potential_risks"]:
        print(f"    ⚠ {x}")

    print("\n  ลำดับการประสานงาน")
    for s in r["recommended_coordination"]:
        print(f"    {s['order']}. [{s['urgency']:<8}] {s['team']:<16} {s['action']}")

    if r["draft_issues"]:
        print(f"\n  ร่าง issue {len(r['draft_issues'])} ใบ (ยังไม่ได้เปิดให้)")
        for d in r["draft_issues"]:
            print(f"    → {d['repository']}: {d['title']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ecosystem impact analysis")
    ap.add_argument("--contract")
    ap.add_argument("--component")
    ap.add_argument("--pr", help="เช่น agent-platform#35")
    ap.add_argument("--graph", help="component id ที่จะวาด graph")
    ap.add_argument("--direction", default="down", choices=["down", "up"])
    ap.add_argument("--depth", type=int, default=5)
    ap.add_argument("--level", default="unsure",
                    choices=["breaking", "non-breaking", "unsure"])
    ap.add_argument("--mermaid", action="store_true")
    args = ap.parse_args(argv)

    with connect(readonly=True) as conn:
        if args.mermaid:
            print(impact.render_mermaid(conn))
            return 0
        if args.graph:
            label = "ใครกระทบถ้าเปลี่ยนตัวนี้" if args.direction == "down" else "ตัวนี้ขึ้นกับใคร"
            print(f"{label}\n")
            print(impact.render_tree(
                impact.dependency_tree(conn, args.graph,
                                       direction=args.direction, depth=args.depth)))
            return 0
        if args.pr:
            repo, _, num = args.pr.partition("#")
            r = impact.analyze_pr(conn, repo, int(num))
            if not r["available"]:
                print(f"❌ ดึง PR ไม่ได้: {r['reason']}")
                return 1
            _print_change(r)
            return 0
        if args.contract:
            r = impact.cross_team(conn, args.contract, level=args.level)
            if r is None:
                print(f"❌ ไม่รู้จัก contract {args.contract}")
                return 1
            _print_cross_team(r)
            return 0
        if args.component:
            r = impact.component_change(conn, args.component)
            if r is None:
                print(f"❌ ไม่รู้จัก component {args.component}")
                return 1
            print(f"เปลี่ยน {r['component']} (ของ {r['owner']})\n  {r['why']}\n")
            for p in r["paths"]:
                print(f"    depth={p['depth']} {p['component']}  ({', '.join(p['via'] or [])})")
            return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
