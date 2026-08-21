"""Provider ที่ไม่เรียกเน็ต — ใช้ตอนเทสต์และตอนยังไม่มี API key

**ไม่ใช่ LLM และไม่แกล้งเป็น** เป็น rule engine ที่อ่าน context แล้วสรุปตามกฎตรง ๆ
มีไว้สองเหตุผล

    1. ทดสอบ pipeline ทั้งเส้น (context → schema → grounding → คำตอบ) โดยไม่ต้องมี key
    2. เป็น baseline — ถ้า LLM ตอบแย่กว่า rule engine แปลว่า prompt มีปัญหา ไม่ใช่ model

คำตอบของมันถูก mark ว่า generated_by=offline เสมอ จะได้ไม่มีใครเผลอคิดว่าเป็นคำตอบจาก LLM
"""
from __future__ import annotations

import json
from typing import Any


class OfflineProvider:
    name = "offline"
    model = "rule-engine"

    def complete_json(self, *, stable_system: str, volatile_context: str,
                      question: str, schema: dict[str, Any],
                      effort: str = "high") -> dict[str, Any]:
        payload = json.loads(volatile_context)
        required = set(schema.get("required", []))
        if "recommended_coordination" in required:
            return self._coordination(payload)
        return self._recommendation(payload)

    def _coordination(self, facts: dict[str, Any]) -> dict[str, Any]:
        """ความเสี่ยงและลำดับการประสาน — อนุมานจาก conformance ของผู้ใช้ contract"""
        risks, steps = [], []
        for i, c in enumerate(facts.get("consumers", []), start=1):
            conf = c.get("conformance")
            if conf != "passing":
                risks.append(f"{c['component']} มี conformance={conf} "
                             f"— ตรวจไม่ได้ว่าจะพังตรงไหนถ้าเปลี่ยน")
            steps.append({"order": i, "with_team": c.get("team") or "-",
                          "action": f"แจ้ง {c['component']} ก่อนปล่อยเวอร์ชันใหม่"
                                    + (f" (pin ที่ {c['pinned_commit'][:7]})"
                                       if c.get("pinned_commit") else "")})
        if facts.get("semantics_owner"):
            risks.append(f"semantics เป็นของ {facts['semantics_owner']} "
                         f"— ต้องมี RFC ที่ต้นทางก่อน แก้ที่ {facts.get('authority')} อย่างเดียวไม่ได้")
            steps.insert(0, {"order": 0,
                             "with_team": facts.get("semantics_owner_team") or "-",
                             "action": "เปิด RFC ที่เจ้าของ semantics ก่อนเป็นอันดับแรก"})
        if not facts.get("consumers"):
            risks.append("ยังไม่มีใคร pin — เปลี่ยนหรือปิดเวอร์ชันได้โดยไม่กระทบใคร")
        for w in facts.get("expected_by", []):
            risks.append(f"{w} ประกาศเจตนาจะใช้ — เปลี่ยนตอนนี้จะเพิ่มงานให้เขา")
        return {"potential_risks": risks, "recommended_coordination": steps}

    # ผูกกฎแต่ละข้อกับเป้าหมายระดับ ecosystem ที่มันรับใช้
    GOAL_OF_RULE = {
        "conform": "conformance-provable",
        "pin": "conformance-provable",
        "planned": "ownership-unambiguous",
        "stale": "conformance-provable",
        "semantics": "contract-single-source",
        "unused": "no-duplicate-abstraction",
        "review": "one-ecosystem-view",
    }

    def _recommendation(self, ctx: dict[str, Any]) -> dict[str, Any]:
        team = ctx["team"]
        comps = ctx["components"]

        steps: list[dict[str, Any]] = []

        # กฎ 1 — component ที่ยังไม่ conform คืองานที่ค้างชัดที่สุด
        for c in comps:
            conf = c["conformance"]
            if conf["status"] == "unknown" and c["status"] in ("active", "in-development"):
                steps.append({
                    "title": f"ทำให้ {c['id']} conform ตาม ADR-0006",
                    "goal": self.GOAL_OF_RULE["conform"],
                    "why": (f"{c['id']} ยัง{'ไม่มี manifest' if not conf['manifest'] else 'ไม่ผ่าน conformance'} "
                            f"— platform นับเป็น unknown ซึ่งมีผลตอนตัดสินใจปิด contract version"),
                    "priority": 1,
                    "references": [c["id"]],
                })

        # กฎ 2 — contract ที่ตั้งใจใช้แต่ยังไม่ pin
        # ข้าม component ที่ยังไม่มี repo — pin contract ใน repo ที่ไม่มีอยู่ทำไม่ได้
        # (กฎ 3 จัดการ component พวกนั้นแทน)
        for c in comps:
            if c["status"] == "planned":
                continue
            for k in c["expected_contracts"]:
                steps.append({
                    "title": f"pin {k} ใน platform-contract.yaml ของ {c['id']}",
                    "goal": self.GOAL_OF_RULE["pin"],
                    "why": f"{c['id']} ประกาศเจตนาใช้ {k} แต่ยังไม่มีหลักฐาน จึงไม่ถูกนับเป็น consumer",
                    "priority": 2,
                    "references": [c["id"], k],
                })

        # กฎ 3 — component ที่ยังไม่มี repo
        for c in comps:
            if c["status"] == "planned":
                steps.append({
                    "title": f"ตัดสินใจเรื่อง {c['id']} ว่าจะสร้างจริงหรือยุบ",
                    "goal": self.GOAL_OF_RULE["planned"],
                    "why": (f"{c['id']} อยู่ในแผนแต่ยังไม่มี repo — จนกว่าจะมี repo "
                            f"ก็ทำอะไรกับมันไม่ได้เลย รวมถึง pin contract ที่ประกาศเจตนาไว้ "
                            f"({', '.join(c['expected_contracts']) or 'ยังไม่ระบุ'})"),
                    "priority": 2,
                    "references": [c["id"]],
                })

        # กฎ 4 — conformance ที่ใกล้หมดอายุ 90 วันตาม ADR-0006
        for c in comps:
            age = c["conformance"].get("age_days")
            if c["conformance"]["status"] == "passing" and age is not None and age > 60:
                steps.append({
                    "title": f"รัน conformance ของ {c['id']} ใหม่",
                    "goal": self.GOAL_OF_RULE["stale"],
                    "why": f"ตรวจครั้งสุดท้าย {age} วันที่แล้ว — เกิน 90 วัน ADR-0006 นับเป็น unknown ทันที",
                    "priority": 2,
                    "references": [c["id"]],
                })

        # กฎ 5 — contract ที่ทีมนี้เป็นเจ้าของความหมาย ต้องดูว่ามีคนรอใช้ค้างอยู่ไหม
        for entry in ctx.get("semantics_owned", []):
            for waiting in entry["expected_by"]:
                steps.append({
                    "title": f"ตาม {waiting} ให้ pin {entry['contract']} ให้จบ",
                    "goal": self.GOAL_OF_RULE["semantics"],
                    "why": (f"ทีมนี้เป็นเจ้าของ semantics ของ {entry['contract']} "
                            f"— {waiting} ประกาศเจตนาจะใช้แต่ยังไม่ pin จึงยังไม่นับเป็น consumer"),
                    "priority": 3,
                    "references": [entry["contract"], waiting],
                })

        # กฎ 6 — contract ที่ทีมนี้ expose แต่ยังไม่มีใครใช้
        for entry in ctx.get("exposed_contracts", []):
            if not entry["consumers"]:
                steps.append({
                    "title": f"ตัดสินใจเรื่อง {entry['contract']} ที่ยังไม่มีใคร pin",
                    "goal": self.GOAL_OF_RULE["unused"],
                    "why": ("ยังไม่มี consumer ที่ยืนยันแล้ว — ปิดเวอร์ชันได้ หรือหา consumer "
                            "รายที่สองตามเกณฑ์รับ contract"),
                    "priority": 4,
                    "references": [entry["contract"]],
                })

        # ไม่มีงานค้างเลย ก็ยังมีงานหนึ่งอย่างเสมอ คือตรวจว่าแผนที่ยังตรงกับความจริง
        if not steps:
            steps.append({
                "title": "ทบทวน ecosystem.yaml ว่ายังตรงกับความจริง",
                    "goal": self.GOAL_OF_RULE["review"],
                "why": (f"ทีม {team['id']} ไม่มีงานค้างที่ graph มองเห็น "
                        f"— งานที่เหลือคือยืนยันว่าข้อมูลที่ใช้ตัดสินใจยังถูกต้อง"),
                "priority": 5,
                "references": [c["id"] for c in comps] or [team["id"]],
            })

        risks: list[str] = []
        for other in ctx["other_teams_work"]:
            if other["components"]:
                continue
        for dep in ctx["depends_on"]:
            risks.append(
                f"อย่าสร้างของที่ {dep['component']} มีอยู่แล้ว — ทีมนี้ขึ้นกับมันผ่าน "
                f"{', '.join(dep['via']) or 'dependency ตรง'}"
            )

        for st in steps:
            goal = st.pop("goal", None)
            if goal:
                st["references"] = list(st["references"]) + [goal]

        return {
            "team": team["id"],
            "answerable": True,
            "missing_information": [],
            "current_responsibility": list(team["responsibilities"]),
            "current_state": [
                f"{c['id']}: status={c['status']}, conformance={c['conformance']['status']}"
                for c in comps
            ],
            "recommended_next_steps": sorted(steps, key=lambda s: s["priority"])[:5],
            "dependencies": [d["component"] for d in ctx["depends_on"]],
            "affected_components": [c["id"] for c in comps]
                                   + [d["component"] for d in ctx["depended_on_by"]],
            "risks": risks or ["ยังไม่พบความเสี่ยงจากข้อมูลที่มี"],
        }
