"""Current work detection (#17) — "ตอนนี้แต่ละทีมทำอะไรอยู่จริง"

แยกสองอย่างที่คนมักปนกัน

    declared     เปิด issue ไว้ว่าจะทำ — ยังไม่มีสัญญาณว่าลงมือ
    in-progress  มี PR เปิดอยู่ หรือ issue มีคนรับและขยับล่าสุด

ความต่างนี้สำคัญ เพราะ advisor เอาไปเตือนงานซ้ำได้เฉพาะกับงานที่**กำลังทำอยู่จริง**
ถ้านับ issue ที่เปิดค้างมาสองปีเป็น "กำลังทำ" คำเตือนจะกลายเป็นเสียงรบกวน
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import fetch_all

ACTIVE_DAYS = 14        # ขยับภายในกี่วันถึงนับว่ายังมีชีวิต
CONTRACT_PATH = re.compile(r"^contracts/([a-z0-9-]+)/(v\d+)/")


def _age_days(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).days


def _classify(item: dict) -> tuple[str, str]:
    """คืน (state, confidence) — state คือ in-progress หรือ declared"""
    age = _age_days(item["updated_at"])
    fresh = age is not None and age <= ACTIVE_DAYS

    if item["kind"] == "pr":
        return ("in-progress", "high" if fresh else "medium")
    if item["assignees"] and fresh:
        return ("in-progress", "high")
    if item["assignees"] or fresh:
        return ("in-progress" if item["assignees"] else "declared", "medium")
    return ("declared", "low")


def _referenced_entities(conn, item: dict, ids: dict[str, set[str]]) -> list[str]:
    """งานชิ้นนี้เกี่ยวกับ entity ตัวไหนบ้าง — ใช้จับงานซ้ำข้ามทีม

    สองทาง
        จากไฟล์ที่ PR แตะ  แม่นที่สุด contracts/<name>/<version>/ → contract id
        จากชื่อเรื่อง        หยาบกว่า แต่ใช้ได้กับ issue ที่ยังไม่มีโค้ด
    """
    # งานที่อยู่ใน repo ของ component ไหน ก็เกี่ยวกับ component นั้นโดยปริยาย
    # ถ้าไม่ใส่ข้อนี้ issue ที่ไม่ได้เอ่ยชื่อตัวเองในหัวข้อจะกลายเป็นงานที่ไม่เกี่ยวกับอะไรเลย
    found: set[str] = {item["component"]} if item["component"] else set()

    if item["kind"] == "pr":
        for row in fetch_all(conn, "SELECT path FROM pr_files "
                                   "WHERE repository = %s AND number = %s",
                             (item["repository"], item["number"])):
            m = CONTRACT_PATH.match(row["path"])
            if m:
                found.add(f"{m.group(1)}/{m.group(2)}")

    title = item["title"].lower()
    for cid in ids["contracts"]:
        if cid.lower() in title:
            found.add(cid)
    for comp in ids["components"]:
        # ต้องเป็นคำเต็ม ไม่งั้น "agent-platform" จะไปแมตช์กับ "agent-platform-x"
        if re.search(rf"(?<![a-z0-9-]){re.escape(comp)}(?![a-z0-9-])", title):
            found.add(comp)

    return sorted(found)


def current_work(conn, team: str | None = None) -> list[dict[str, Any]]:
    ids = {
        "contracts": {r["id"] for r in fetch_all(conn, "SELECT id FROM contracts")},
        "components": {r["id"] for r in fetch_all(conn, "SELECT id FROM components")},
    }
    sql = "SELECT * FROM open_work"
    params: tuple = ()
    if team:
        sql += " WHERE team = %s"
        params = (team,)
    sql += " ORDER BY updated_at DESC NULLS LAST"

    out = []
    for item in fetch_all(conn, sql, params):
        state, confidence = _classify(item)
        out.append({
            "kind": item["kind"],
            "repository": item["repository"],
            "number": item["number"],
            "title": item["title"],
            "url": item["url"],
            "team": item["team"],
            "component": item["component"],
            "author": item["author"],
            "assignees": item["assignees"],
            "labels": item["labels"],
            "updated_days_ago": _age_days(item["updated_at"]),
            "state": state,
            "confidence": confidence,
            "about": _referenced_entities(conn, item, ids),
        })
    return out


def duplicate_risk(conn) -> list[dict[str, Any]]:
    """งานที่กำลังทำอยู่จริงของคนละทีม แต่แตะ entity เดียวกัน

    นับเฉพาะ state=in-progress — งานที่แค่ประกาศไว้ไม่ใช่ความเสี่ยงเรื่องทำซ้ำ
    """
    by_entity: dict[str, list[dict]] = {}
    for w in current_work(conn):
        if w["state"] != "in-progress" or not w["team"]:
            continue
        for entity in w["about"]:
            by_entity.setdefault(entity, []).append(w)

    risks = []
    for entity, items in sorted(by_entity.items()):
        teams = {i["team"] for i in items}
        if len(teams) > 1:
            risks.append({
                "entity": entity,
                "teams": sorted(teams),
                "work": [{"team": i["team"], "kind": i["kind"],
                          "repository": i["repository"], "number": i["number"],
                          "title": i["title"], "url": i["url"]} for i in items],
            })
    return risks


def repository_activity(conn) -> list[dict[str, Any]]:
    """สถานะ sync ราย repo — ใครสด ใครเงียบ ใคร sync ล้ม"""
    rows = fetch_all(conn, """
        SELECT s.*, c.id AS component, c.owner AS team,
               (SELECT count(*) FROM issues i
                 WHERE i.repository = s.repository AND i.state = 'open') AS open_issues_synced,
               (SELECT count(*) FROM pull_requests p
                 WHERE p.repository = s.repository AND p.state = 'open') AS open_prs
          FROM repo_sync_state s
          LEFT JOIN components c ON c.repository = s.repository
         ORDER BY s.pushed_at DESC NULLS LAST
    """)
    for r in rows:
        r["last_push_days_ago"] = _age_days(r["pushed_at"])
        r["last_synced_days_ago"] = _age_days(r["last_synced_at"])
    return rows


def contract_prs(conn, contract_id: str | None = None) -> list[dict[str, Any]]:
    """PR ที่แตะ contract / ADR / RFC — input ตรงของ M5 Architecture Guardian"""
    sql = """SELECT repository, number, title, state, author, url,
                    array_agg(DISTINCT kind) AS kinds,
                    array_agg(DISTINCT path ORDER BY path) AS paths
               FROM contract_touching_prs
              GROUP BY repository, number, title, state, author, url
              ORDER BY repository, number DESC"""
    rows = fetch_all(conn, sql)
    if contract_id:
        name, _, version = contract_id.partition("/")
        prefix = f"contracts/{name}/{version}/"
        rows = [r for r in rows if any(p.startswith(prefix) for p in r["paths"])]
    return rows


def main(argv: list[str] | None = None) -> int:
    import sys

    from ..db import connect

    with connect(readonly=True) as conn:
        items = current_work(conn)
        risks = duplicate_risk(conn)
        activity = repository_activity(conn)
        prs = contract_prs(conn)

    if not items and not activity:
        print("ยังไม่มีข้อมูลจาก GitHub — รัน make sync ก่อน")
        return 0

    in_progress = [w for w in items if w["state"] == "in-progress"]
    declared = [w for w in items if w["state"] == "declared"]

    print(f"งานที่เปิดอยู่ {len(items)} ชิ้น  ·  กำลังทำจริง {len(in_progress)}  ·  "
          f"ประกาศไว้เฉย ๆ {len(declared)}\n")

    if in_progress:
        print("กำลังทำอยู่จริง")
        for w in in_progress[:10]:
            print(f"  [{w['confidence']:<6}] {w['team'] or '-':<16} {w['kind']:<5} "
                  f"{w['repository']}#{w['number']}  ·  {w['title'][:52]}")
    else:
        print("ไม่มีงานที่นับว่ากำลังทำอยู่จริง "
              "(ไม่มี PR เปิดค้าง และไม่มี issue ที่มีคนรับ)")

    print(f"\nประกาศไว้แต่ยังไม่มีสัญญาณว่าเริ่ม — {len(declared)} ชิ้น")
    by_team: dict[str, int] = {}
    for w in declared:
        by_team[w["team"] or "-"] = by_team.get(w["team"] or "-", 0) + 1
    for team, n in sorted(by_team.items(), key=lambda kv: -kv[1]):
        print(f"  {team:<18} {n}")

    print(f"\nงานซ้ำข้ามทีม: {len(risks)}")
    for r in risks:
        print(f"  ⚠ {r['entity']} — {', '.join(r['teams'])}")
        for w in r["work"]:
            print(f"      {w['team']}: {w['repository']}#{w['number']} {w['title'][:50]}")

    print(f"\nPR ที่แตะ contract / ADR / RFC: {len(prs)}")
    for r in prs[:6]:
        print(f"  {r['repository']}#{r['number']:<4} [{r['state']:<6}] "
              f"{','.join(r['kinds']):<28} {r['title'][:44]}")

    print("\nความเคลื่อนไหวราย repo")
    for a in activity:
        mark = "✓" if a["last_ok"] else "✗"
        push = f"{a['last_push_days_ago']}d" if a["last_push_days_ago"] is not None else "-"
        print(f"  {mark} {a['repository']:<24} push {push:<6} "
              f"open issues {a['open_issues_synced']:<3} open PR {a['open_prs']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
