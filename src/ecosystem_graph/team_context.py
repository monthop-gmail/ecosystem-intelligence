"""Team Context (#9) — ประกอบ "มุมมองของทีม" จาก ecosystem graph

ชั้นนี้มีแต่ **ข้อเท็จจริง** ห้ามมีการตีความ
การตีความเป็นหน้าที่ของ advisor.py — แยกกันเพื่อให้ตรวจได้ว่าคำตอบของ LLM
อ้างอิงอะไร และไม่ได้แต่งขึ้นมาเอง (#11)

ขนาดต้องพอใส่ prompt ได้ — ไม่ dump ทั้ง ecosystem
"""
from __future__ import annotations

from typing import Any

from . import queries as q


def ecosystem_truth(conn) -> dict[str, Any]:
    """ส่วนที่เหมือนกันสำหรับทุกทีม — เปลี่ยนน้อยมาก

    แยกออกมาเพราะเป็น prefix ที่นิ่งที่สุด ใช้ทำ prompt cache ได้เต็มที่
    """
    meta = q.meta(conn)
    return {
        "ecosystem": meta.get("name"),
        "as_of": meta.get("updated"),
        "goals": q.goals(conn),
        "architecture_rules": q.architecture_rules(conn),
        "planes": [
            {"id": p["id"], "responsibility": p["responsibility"],
             "must_not": p["must_not"], "contracts": p["contracts"],
             "implemented_by": p["implemented_by"]}
            for p in q.list_planes(conn)
        ],
        "contracts": [
            {"id": c["id"], "authority": c["authority"],
             "semantics_owner": c["semantics_owner"],
             "exposed_by": c["exposed_by"], "consumers": c["consumers"],
             "expected_by": c["expected_by"]}
            for c in q.list_contracts(conn)
        ],
        "teams": [{"id": t["id"], "responsibilities": t["responsibilities"]}
                  for t in q.list_teams(conn)],
    }


def _component_view(conn, comp: dict) -> dict[str, Any]:
    return {
        "id": comp["id"],
        "status": comp["status"],
        "implements": comp["implements"],
        "repository": comp["repository"],
        "exposes": comp["exposes"],
        "consumes": comp["consumes"],
        "expected_contracts": comp["expected_contracts"],
        "conformance": {
            "status": comp["conformance_status"],
            "declared": comp["conformance_declared"],
            "last_verified": str(comp["conformance_last_verified"] or ""),
            "age_days": comp["conformance_age_days"],
            "manifest": comp["manifest"],
            "note": comp["note"],
        },
        "depends_on": [d["component"] for d in q.dependencies_of(conn, comp["id"], depth=1)],
        "depended_on_by": [d["component"] for d in q.dependents_of(conn, comp["id"], depth=1)],
    }


def team_context(conn, team_id: str) -> dict[str, Any] | None:
    """มุมมองของทีมหนึ่ง — ข้อเท็จจริงล้วน ไม่มีการตีความ"""
    team = q.get_team(conn, team_id)
    if team is None:
        return None

    components = q.list_components(conn, team=team_id)
    comp_ids = [c["id"] for c in components]

    upstream: dict[str, list[str]] = {}
    downstream: dict[str, list[str]] = {}
    for c in components:
        for d in q.dependencies_of(conn, c["id"]):
            upstream.setdefault(d["component"], []).extend(d["via"] or [])
        for d in q.dependents_of(conn, c["id"]):
            downstream.setdefault(d["component"], []).extend(d["via"] or [])

    all_components = q.list_components(conn)
    owner_of = {c["id"]: c["owner"] for c in all_components}
    team_of_repo = {c["repository"]: c["owner"] for c in all_components if c["repository"]}

    # contract ที่ "ความหมาย" เป็นของทีมนี้ (ADR-0006 C2) — เป็นความรับผิดชอบที่มองไม่เห็น
    # ถ้าไม่ใส่ไว้ใน context เพราะมันไม่ได้อยู่ในตาราง components
    semantics_owned = [
        {"contract": c["id"], "consumers": c["consumers"], "expected_by": c["expected_by"]}
        for c in q.list_contracts(conn)
        if c["semantics_owner"] and team_of_repo.get(c["semantics_owner"]) == team_id
    ]
    # contract ที่ทีมนี้เป็นผู้ expose — ต้องรู้ว่ามีใครใช้หรือยัง
    exposed = [
        {"contract": c["id"], "consumers": c["consumers"], "expected_by": c["expected_by"]}
        for c in q.list_contracts(conn)
        if c["exposed_by"] in comp_ids
    ]

    return {
        "team": {
            "id": team["id"],
            "name": team["name"],
            "responsibilities": team["responsibilities"],
            "members": team["members"],
        },
        "components": [_component_view(conn, c) for c in components],
        "repositories": sorted({c["repository"] for c in components if c["repository"]}),
        "depends_on": [
            {"component": cid, "via": sorted(set(via)), "owned_by": owner_of.get(cid)}
            for cid, via in sorted(upstream.items()) if cid not in comp_ids
        ],
        "depended_on_by": [
            {"component": cid, "via": sorted(set(via)), "owned_by": owner_of.get(cid)}
            for cid, via in sorted(downstream.items()) if cid not in comp_ids
        ],
        "semantics_owned": semantics_owned,
        "exposed_contracts": exposed,
        "other_teams_work": [
            {"team": t["id"], "components": [c["id"] for c in q.list_components(conn, team=t["id"])]}
            for t in q.list_teams(conn) if t["id"] != team_id
        ],
    }


def known_ids(truth: dict, ctx: dict) -> set[str]:
    """id ทุกตัวที่ปรากฏใน context — ใช้ตรวจว่า LLM ไม่ได้แต่งชื่อขึ้นมาเอง (#11)"""
    ids: set[str] = set()
    ids.update(g["id"] for g in truth["goals"])
    ids.update(p["id"] for p in truth["planes"])
    ids.update(c["id"] for c in truth["contracts"])
    ids.update(t["id"] for t in truth["teams"])
    for c in truth["contracts"]:
        ids.update(filter(None, [c["authority"], c["semantics_owner"], c["exposed_by"]]))
        ids.update(c["consumers"] or [])
        ids.update(c["expected_by"] or [])
    ids.add(ctx["team"]["id"])
    ids.update(c["id"] for c in ctx["components"])
    for entry in ctx["semantics_owned"] + ctx["exposed_contracts"]:
        ids.add(entry["contract"])
        ids.update(entry["consumers"] or [])
        ids.update(entry["expected_by"] or [])
    ids.update(ctx["repositories"])
    ids.update(d["component"] for d in ctx["depends_on"])
    ids.update(d["component"] for d in ctx["depended_on_by"])
    for entry in ctx["other_teams_work"]:
        ids.add(entry["team"])
        ids.update(entry["components"])
    for p in truth["planes"]:
        ids.update(p["implemented_by"] or [])
    return {i for i in ids if i}
