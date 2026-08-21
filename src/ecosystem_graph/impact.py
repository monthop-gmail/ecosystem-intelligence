"""Impact Analysis (#18 #19 #20)

ตอบคำถาม "เปลี่ยนสิ่งนี้แล้วแผ่ไปถึงไหน" โดยแยกสามชั้นให้ชัด

    graph      ใครขึ้นกับใคร — ข้อเท็จจริงจาก M1
    change     การเปลี่ยนแปลงนี้ breaking หรือไม่ — วิเคราะห์จาก diff จริง
    cross-team แปลผลกระทบทางเทคนิคเป็นสิ่งที่แต่ละทีมต้องลงมือทำ

ชั้นกลางคือส่วนที่ยากที่สุด และเป็นส่วนที่ **ยอมตอบว่า "ไม่แน่ใจ" ได้**
การเดาว่า non-breaking แล้วผิด แพงกว่าการบอกว่าไม่แน่ใจแล้วให้คนดู
"""
from __future__ import annotations

import re
from typing import Any, Literal

from . import queries as q
from .db import fetch_all
from .github.client import GitHubClient, GitHubError

Level = Literal["breaking", "non-breaking", "unsure"]

CONTRACT_FILE = re.compile(r"^contracts/([a-z0-9-]+)/(v\d+)/")
SEMANTICS_FILES = ("contract-semantics.yaml",)
GOVERNANCE_DIRS = ("decisions/", "rfcs/")

# ลำดับความรุนแรง — รวมผลหลายไฟล์แล้วเอาตัวที่หนักที่สุด
SEVERITY = {"non-breaking": 0, "unsure": 1, "breaking": 2}


# ─────────────────────────────────────────────────────────────────────────
# #18 Dependency graph ที่คนอ่านรู้เรื่อง
# ─────────────────────────────────────────────────────────────────────────
def dependency_tree(conn, component_id: str, *, direction: str = "down",
                    depth: int = 5) -> dict[str, Any]:
    """สร้างต้นไม้จาก component หนึ่ง — down = ใครกระทบ, up = เราขึ้นกับใคร"""
    edges = fetch_all(conn, "SELECT dependent, dependency, via, kind FROM component_edges")
    forward: dict[str, list[dict]] = {}
    for e in edges:
        key = e["dependency"] if direction == "down" else e["dependent"]
        val = e["dependent"] if direction == "down" else e["dependency"]
        forward.setdefault(key, []).append({"node": val, "via": e["via"], "kind": e["kind"]})

    def build(node: str, level: int, seen: frozenset[str]) -> dict[str, Any]:
        children = []
        if level < depth:
            grouped: dict[str, list[str]] = {}
            for edge in forward.get(node, []):
                grouped.setdefault(edge["node"], []).append(edge["via"])
            for child, vias in sorted(grouped.items()):
                if child in seen:
                    children.append({"node": child, "via": sorted(set(vias)),
                                     "cycle": True, "children": []})
                    continue
                sub = build(child, level + 1, seen | {child})
                sub["via"] = sorted(set(vias))
                children.append(sub)
        return {"node": node, "children": children, "cycle": False}

    return build(component_id, 0, frozenset({component_id}))


def render_tree(tree: dict[str, Any], *, prefix: str = "", is_last: bool = True,
                root: bool = True) -> str:
    """ต้นไม้แบบอ่านด้วยตา — JSON ล้วนไม่มีใครเห็นภาพ (#18)"""
    lines = []
    if root:
        lines.append(tree["node"])
    else:
        via = ", ".join(tree.get("via", []))
        mark = "↺ " if tree.get("cycle") else ""
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{mark}{tree['node']}"
                     + (f"  ({via})" if via else ""))
        prefix += "    " if is_last else "│   "
    for i, child in enumerate(tree["children"]):
        lines.append(render_tree(child, prefix=prefix,
                                 is_last=(i == len(tree["children"]) - 1), root=False))
    return "\n".join(lines)


def render_mermaid(conn, *, only: set[str] | None = None) -> str:
    """graph ทั้ง ecosystem เป็น mermaid — แปะใน markdown ได้เลย"""
    edges = fetch_all(conn, "SELECT dependent, dependency, via FROM component_edges")
    teams = {c["id"]: c["owner"] for c in q.list_components(conn)}

    grouped: dict[tuple[str, str], list[str]] = {}
    for e in edges:
        if only and not ({e["dependent"], e["dependency"]} & only):
            continue
        grouped.setdefault((e["dependent"], e["dependency"]), []).append(e["via"])

    nodes = {n for pair in grouped for n in pair}
    lines = ["graph LR"]
    by_team: dict[str, list[str]] = {}
    for n in sorted(nodes):
        by_team.setdefault(teams.get(n, "unknown"), []).append(n)
    for team, members in sorted(by_team.items()):
        lines.append(f"  subgraph {team}")
        for m in members:
            lines.append(f"    {m.replace('-', '_')}[\"{m}\"]")
        lines.append("  end")
    for (dependent, dependency), vias in sorted(grouped.items()):
        label = ", ".join(sorted(set(vias))[:3])
        if len(set(vias)) > 3:
            label += f" +{len(set(vias)) - 3}"
        lines.append(f"  {dependent.replace('-', '_')} -->|{label}| "
                     f"{dependency.replace('-', '_')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# #19 Change analysis — breaking / non-breaking / ไม่แน่ใจ
# ─────────────────────────────────────────────────────────────────────────
def classify_patch(path: str, patch: str | None, status: str) -> dict[str, Any]:
    """จำแนกการเปลี่ยนแปลงของไฟล์เดียว

    ไม่ได้พยายาม parse YAML จาก diff — diff ไม่ใช่เอกสารที่สมบูรณ์
    ใช้สัญญาณที่อ่านจาก diff ได้ตรง ๆ แล้วยอมตอบ unsure เมื่อสัญญาณไม่ชัด
    """
    reasons: list[str] = []
    level: Level = "unsure"

    is_contract = bool(CONTRACT_FILE.match(path))
    is_schema = is_contract and path.endswith((".yaml", ".yml", ".json"))
    is_doc = path.endswith((".md", ".txt"))

    if status == "removed" and is_contract:
        return {"path": path, "level": "breaking", "reasons": ["ไฟล์ contract ถูกลบ"]}

    if status == "added" and is_contract:
        return {"path": path, "level": "non-breaking",
                "reasons": ["ไฟล์ใหม่ใน contract — การเพิ่มไม่ทำให้ของเดิมพัง"]}

    if path in SEMANTICS_FILES:
        return {"path": path, "level": "unsure",
                "reasons": ["แตะ contract-semantics.yaml — ความหมายเปลี่ยนได้โดยที่ "
                            "schema ไม่ขยับ ต้องให้คนอ่าน"]}

    if path.startswith(GOVERNANCE_DIRS):
        # ADR/RFC เปลี่ยนความหมายได้ แต่ถ้า PR เดียวกันมี schema diff ให้ดูด้วย
        # ให้เชื่อ schema เป็นหลัก — advisory=True บอกว่าอย่าเอาไปตัดสินคนเดียว
        return {"path": path, "level": "unsure", "advisory": True,
                "reasons": ["แตะ ADR / RFC — ความหมายเปลี่ยนได้โดยที่ schema ไม่ขยับ"]}

    if is_doc:
        # อ่านคำประกาศของผู้เขียนเฉพาะจาก CHANGELOG ของ contract เท่านั้น
        # เอกสารทั่วไปพูดถึงคำว่า breaking ในเชิงอธิบายนโยบายได้ ไม่ใช่คำประกาศ
        claim = _author_claim(patch) if (is_contract and path.endswith("CHANGELOG.md")) else None
        return {"path": path, "level": "non-breaking",
                "reasons": ["เอกสารอย่างเดียว ไม่กระทบ schema"],
                "author_claim": claim}

    if not patch:
        return {"path": path, "level": "unsure", "reasons": ["ไม่มี diff ให้ดู"]}

    added = [ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in patch.splitlines() if ln.startswith("-") and not ln.startswith("---")]

    # required: เป็นสัญญาณที่ชัดที่สุดใน JSON Schema
    req_added = _required_items(patch, "+")
    req_removed = _required_items(patch, "-")
    if req_added:
        level = "breaking"
        reasons.append(f"เพิ่ม required field: {', '.join(req_added)} "
                       f"— payload เดิมของ consumer จะไม่ผ่าน validation")
    if req_removed:
        level = "breaking" if level == "breaking" else "unsure"
        reasons.append(f"ถอด required field: {', '.join(req_removed)} "
                       f"— ผู้ผลิตไม่พัง แต่ผู้บริโภคที่คิดว่าต้องมีเสมออาจพัง")

    prop_removed = _property_keys(removed) - _property_keys(added)
    if prop_removed and is_schema:
        level = "breaking"
        reasons.append(f"ถอด property: {', '.join(sorted(prop_removed))}")

    type_changed = [ln.strip() for ln in removed if re.match(r"\s*type:\s*\S", ln)]
    if type_changed and any(re.match(r"\s*type:\s*\S", ln) for ln in added):
        level = "breaking"
        reasons.append("เปลี่ยน type ของ field ที่มีอยู่แล้ว")

    enum_removed = [ln.strip() for ln in removed if re.match(r"\s*- ['\"]?[A-Z_]{2,}", ln)]
    if enum_removed and not any(ln.strip() in [e for e in enum_removed] for ln in added):
        level = "breaking" if level != "breaking" else level
        reasons.append(f"ถอดค่าออกจาก enum: {len(enum_removed)} ค่า")

    if level == "unsure" and added and not removed:
        prop_added = _property_keys(added)
        if prop_added:
            level = "non-breaking"
            reasons.append(f"เพิ่ม optional property อย่างเดียว: {', '.join(sorted(prop_added))}")
        else:
            level = "non-breaking"
            reasons.append("เพิ่มบรรทัดอย่างเดียว ไม่มีการถอดอะไรออก")

    if not reasons:
        reasons.append("สัญญาณไม่ชัดพอจะตัดสิน — ต้องให้คนอ่าน diff")

    return {"path": path, "level": level, "reasons": reasons}


def _required_items(patch: str, sign: str) -> list[str]:
    """หา item ที่ถูกเพิ่ม/ถอดใต้บล็อก required:

    เดินทีละบรรทัดและจำว่าอยู่ใต้ required: หรือยัง — ออกจากบล็อกเมื่อเจอ key ใหม่
    """
    out, in_required, req_indent = [], False, 0
    for raw in patch.splitlines():
        if raw.startswith(("+++", "---", "@@")):
            in_required = False
            continue
        body = raw[1:] if raw[:1] in "+- " else raw
        stripped = body.strip()
        indent = len(body) - len(body.lstrip())

        if re.match(r"required:\s*$", stripped):
            in_required, req_indent = True, indent
            continue
        if in_required:
            m = re.match(r"-\s+['\"]?([A-Za-z_][\w-]*)", stripped)
            if m and indent > req_indent:
                if raw.startswith(sign):
                    out.append(m.group(1))
                continue
            if stripped and indent <= req_indent:
                in_required = False
    return out


def _property_keys(lines: list[str]) -> set[str]:
    keys = set()
    for ln in lines:
        m = re.match(r"^\s{2,}([a-z_][\w-]*):\s*$", ln)
        if m and m.group(1) not in ("properties", "required", "definitions", "$defs"):
            keys.add(m.group(1))
    return keys


def _author_claim(patch: str | None) -> str | None:
    """CHANGELOG ของ ecosystem นี้มักเขียนเองว่า breaking หรือไม่ — เก็บไว้เทียบ"""
    if not patch:
        return None
    text = "\n".join(ln[1:] for ln in patch.splitlines() if ln.startswith("+")).lower()
    if "ไม่ breaking" in text or "not breaking" in text or "non-breaking" in text:
        return "non-breaking"
    if "breaking" in text:
        return "breaking"
    return None


def analyze_pr(conn, repository: str, number: int, *,
               gh: GitHubClient | None = None) -> dict[str, Any]:
    """วิเคราะห์ PR หนึ่งใบจาก diff จริง — ต้องมี gh (ดึง patch สด ไม่เก็บลง DB)"""
    gh = gh or GitHubClient()
    try:
        files = gh.pull_files(repository, number)
    except GitHubError as e:
        return {"repository": repository, "number": number,
                "available": False, "reason": str(e)}

    per_file = [classify_patch(f["filename"], f.get("patch"), f.get("status", "modified"))
                for f in files]
    relevant = [c for c in per_file
                if CONTRACT_FILE.match(c["path"])
                or c["path"] in SEMANTICS_FILES
                or c["path"].startswith(GOVERNANCE_DIRS)
                or c["path"] == "platform-contract.yaml"]

    contracts = sorted({f"{m.group(1)}/{m.group(2)}"
                        for c in per_file
                        if (m := CONTRACT_FILE.match(c["path"]))})

    hard = [c for c in relevant if not c.get("advisory")]
    deciding = hard or relevant
    level: Level = "non-breaking"
    for c in deciding:
        if SEVERITY[c["level"]] > SEVERITY[level]:
            level = c["level"]

    advisory_notes = [c["path"] for c in relevant if c.get("advisory")]

    claims = {c.get("author_claim") for c in per_file if c.get("author_claim")}
    disagreement = None
    if len(claims) == 1:
        claim = next(iter(claims))
        if claim != level and level != "unsure":
            disagreement = (f"ผู้เขียนระบุว่า {claim} แต่ diff บอกว่า {level} "
                            f"— ควรอ่านด้วยตา")
    elif len(claims) > 1:
        disagreement = (f"CHANGELOG ในไฟล์ต่าง ๆ ระบุไม่ตรงกัน ({', '.join(sorted(claims))}) "
                        f"— diff บอกว่า {level}")

    return {
        "repository": repository,
        "number": number,
        "available": True,
        "level": level,
        "contracts_touched": contracts,
        "files": relevant or per_file[:5],
        "files_total": len(per_file),
        "author_claim": sorted(claims) or None,
        "disagreement": disagreement,
        "advisory_files": advisory_notes,
        "impact": [contract_change(conn, cid, level) for cid in contracts],
    }


def contract_change(conn, contract_id: str, level: Level = "unsure") -> dict[str, Any]:
    """เปลี่ยน contract นี้ที่ระดับนี้ แล้วกระทบใคร"""
    facts = q.contract_impact(conn, contract_id)
    consumers = facts["consumers"]

    if not consumers:
        why = "ยังไม่มี consumer ที่ pin ไว้ — เปลี่ยนได้โดยไม่กระทบใคร"
    elif level == "breaking":
        why = (f"{len(consumers)} consumer pin contract นี้ไว้จริง "
               f"— breaking change ทำให้ payload เดิมของเขาไม่ผ่าน validation")
    elif level == "non-breaking":
        why = (f"{len(consumers)} consumer pin ไว้ แต่การเพิ่ม optional "
               f"ไม่ทำให้ของเดิมพัง — ยังควรแจ้งให้รู้")
    else:
        why = f"{len(consumers)} consumer pin ไว้ และยังตัดสินไม่ได้ว่า breaking หรือไม่"

    return {
        "contract": contract_id,
        "level": level,
        "why": why,
        "affected_teams": facts["affected_teams"],
        "affected_components": facts["affected_components"],
        "affected_repositories": facts["affected_repositories"],
        "consumers": consumers,
        "expected_by": facts["expected_by"],
        "authority": facts["authority"],
        "semantics_owner": facts["semantics_owner"],
    }


def component_change(conn, component_id: str) -> dict[str, Any] | None:
    """เปลี่ยน component นี้แล้วกระทบใคร — ผ่าน contract ที่มัน expose"""
    comp = q.get_component(conn, component_id)
    if comp is None:
        return None
    dependents = q.dependents_of(conn, component_id)
    return {
        "component": component_id,
        "owner": comp["owner"],
        "exposes": comp["exposes"],
        "affected_components": [d["component"] for d in dependents],
        "affected_teams": sorted({(q.get_component(conn, d["component"]) or {}).get("owner")
                                  for d in dependents} - {None}),
        "paths": [{"component": d["component"], "depth": d["depth"], "via": d["via"]}
                  for d in dependents],
        "why": ("ไม่มีใครขึ้นกับ component นี้ผ่าน contract"
                if not dependents else
                f"{len(dependents)} component ขึ้นกับมันผ่าน contract ที่มัน expose"),
    }


# ─────────────────────────────────────────────────────────────────────────
# #20 Cross-team impact — แปลผลกระทบทางเทคนิคเป็นสิ่งที่แต่ละทีมต้องทำ
# ─────────────────────────────────────────────────────────────────────────
def _coordination_order(conn, change: dict[str, Any]) -> list[dict[str, Any]]:
    """ใครต้องรู้ก่อน

    ลำดับไม่ได้มาจากความสุภาพ แต่มาจากใครมีอำนาจตัดสินใจและใครพังก่อน
        1. เจ้าของ semantics — ถ้ามี ต้องเริ่มที่นั่นตาม ADR-0006 C2
        2. consumer ที่ conformance ยังไม่ passing — มองไม่เห็นว่าจะพังตรงไหน
        3. consumer ที่เหลือ
        4. ทีมที่ประกาศเจตนาจะใช้ — ยังไม่พัง แต่แผนเปลี่ยน
    """
    team_of_repo = {c["repository"]: c["owner"] for c in q.list_components(conn)
                    if c["repository"]}
    owner_of = {c["id"]: c["owner"] for c in q.list_components(conn)}
    steps: list[dict[str, Any]] = []
    order = 0

    if change.get("semantics_owner"):
        team = team_of_repo.get(change["semantics_owner"])
        steps.append({"order": order, "team": team or "-", "urgency": "blocking",
                      "action": f"เปิด RFC ที่ {change['semantics_owner']} ก่อน "
                                f"— semantics เป็นของเขา แก้ที่ {change['authority']} "
                                f"อย่างเดียวไม่ได้ (ADR-0006 C2)"})
        order += 1

    risky = [c for c in change["consumers"] if c.get("conformance") != "passing"]
    safe = [c for c in change["consumers"] if c.get("conformance") == "passing"]

    for c in risky:
        steps.append({"order": order, "team": c["team"], "urgency": "blocking",
                      "action": f"{c['component']} มี conformance={c['conformance']} "
                                f"— ต้องทำให้ผ่านก่อน ไม่งั้นไม่มีใครรู้ว่าจะพังตรงไหน"})
        order += 1
    for c in safe:
        urgency = "blocking" if change["level"] == "breaking" else "notify"
        steps.append({"order": order, "team": c["team"], "urgency": urgency,
                      "action": (f"{c['component']} pin ไว้ที่ "
                                 f"{(c.get('pinned_commit') or '')[:7] or 'ไม่ระบุ commit'} "
                                 f"— {'ต้องแก้และ re-pin ก่อนปล่อย' if urgency == 'blocking' else 'แจ้งให้รู้ ยังไม่ต้องแก้'}")})
        order += 1
    for comp in change["expected_by"]:
        steps.append({"order": order, "team": owner_of.get(comp, "-"), "urgency": "fyi",
                      "action": f"{comp} ประกาศเจตนาจะใช้ contract นี้ "
                                f"— ยังไม่พัง แต่แผนอาจต้องปรับ"})
        order += 1
    return steps


def draft_issues(change: dict[str, Any], coordination: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ร่าง issue สำหรับแต่ละ repo ที่กระทบ — **ร่างเท่านั้น ไม่สร้างให้**

    การเปิด issue ใน repo ของทีมอื่นเป็นการกระทำที่ย้อนยากและเป็นเรื่องของคน
    เครื่องมือนี้เตรียมข้อความให้ ส่วนจะเปิดหรือไม่ ให้คนตัดสิน
    """
    by_team = {}
    for step in coordination:
        by_team.setdefault(step["team"], []).append(step)

    drafts = []
    for consumer in change["consumers"]:
        steps = by_team.get(consumer["team"], [])
        urgency = "blocking" if any(s["urgency"] == "blocking" for s in steps) else "notify"
        verb = "ต้องแก้" if change["level"] == "breaking" else "ตรวจสอบ"
        body = [
            f"`{change['contract']}` กำลังจะเปลี่ยน — ระดับ **{change['level']}**",
            "",
            f"> {change['why']}",
            "",
            f"- component ที่กระทบ: `{consumer['component']}`",
            f"- pin ปัจจุบัน: `{(consumer.get('pinned_commit') or 'ไม่ระบุ')[:12]}`",
            f"- conformance: `{consumer.get('conformance')}`",
            f"- เจ้าของ contract: `{change['authority']}`"
            + (f" · semantics: `{change['semantics_owner']}`" if change.get("semantics_owner") else ""),
            "",
            "**ต้องทำอะไร**",
        ]
        body += [f"- {s['action']}" for s in steps] or ["- ตรวจว่า payload ปัจจุบันยังผ่าน conformance"]
        body += ["", "_ร่างโดย ecosystem-intelligence — ยังไม่ได้เปิด issue ให้_"]
        drafts.append({
            "repository": consumer["repository"],
            "team": consumer["team"],
            "urgency": urgency,
            "title": f"[{change['level']}] {verb} {consumer['component']} "
                     f"สำหรับการเปลี่ยน {change['contract']}",
            "body": "\n".join(body),
        })
    return drafts


def cross_team(conn, contract_id: str, *, level: Level = "unsure") -> dict[str, Any] | None:
    """output ตาม DoD ข้อ 2 ครบทุกด้าน + ลำดับการประสาน + ร่าง issue"""
    if q.get_contract(conn, contract_id) is None:
        return None
    change = contract_change(conn, contract_id, level)
    affected_contracts = sorted({
        k for comp in change["affected_components"]
        for k in (q.get_component(conn, comp) or {}).get("consumes", [])
    })
    coordination = _coordination_order(conn, change)

    risks = []
    if change["semantics_owner"]:
        risks.append(f"semantics เป็นของ {change['semantics_owner']} "
                     f"— เปลี่ยนที่ {change['authority']} ฝ่ายเดียวจะทำให้สองฝั่งไม่ตรงกัน")
    for c in change["consumers"]:
        if c.get("conformance") != "passing":
            risks.append(f"{c['component']} conformance={c.get('conformance')} "
                         f"— ประเมินผลกระทบไม่ได้จนกว่าจะผ่าน")
    if level == "breaking" and change["consumers"]:
        risks.append("ADR-0006 ห้ามปล่อย release ถ้า consumer ยัง failing "
                     "— ต้องรอทุกรายพร้อมก่อน")
    if not change["consumers"]:
        risks.append("ไม่มี consumer — ความเสี่ยงจริงคือปิด version ทิ้งทั้งที่ยังมีคนวางแผนจะใช้"
                     if change["expected_by"] else
                     "ไม่มี consumer และไม่มีใครวางแผนจะใช้ — เปลี่ยนได้อิสระ")

    return {
        "contract": contract_id,
        "level": level,
        "affected_teams": change["affected_teams"],
        "affected_components": change["affected_components"],
        "affected_repositories": change["affected_repositories"],
        "affected_contracts": affected_contracts,
        "potential_risks": risks,
        "recommended_coordination": coordination,
        "draft_issues": draft_issues(change, coordination),
        "why": change["why"],
    }
