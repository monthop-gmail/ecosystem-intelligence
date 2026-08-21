"""Team Advisor (#10 #12) — เอา ecosystem truth + team context มาให้คำแนะนำ

สิ่งที่ทำให้ชั้นนี้ต่างจาก "ถาม LLM เฉย ๆ"

    1. ข้อเท็จจริงมาจาก graph ไม่ได้มาจาก model — model ได้เห็นแค่สิ่งที่ query มาให้
    2. คำตอบถูกบังคับ schema เดียวกันทุก provider
    3. **grounding check** — id ทุกตัวที่ model อ้างถึงต้องมีอยู่ใน context จริง
       ถ้าไม่มี แปลว่ามันแต่งขึ้นมา และเราจับได้ ไม่ใช่ปล่อยผ่าน
    4. คำถามที่ข้อมูลไม่พอ ต้องตอบว่าไม่พอ พร้อมบอกว่าขาดอะไร
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import queries as q
from .llm import LLMProvider, get_provider
from .team_context import ecosystem_truth, known_ids, team_context

ID_PATTERN = re.compile(r"\b[a-z][a-z0-9-]{2,}(?:/v\d+)?\b")

RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "team": {"type": "string"},
        "answerable": {"type": "boolean",
                       "description": "false ถ้าข้อมูลใน context ไม่พอจะตอบ"},
        "missing_information": {"type": "array", "items": {"type": "string"},
                                "description": "ขาดข้อมูลอะไรถึงตอบไม่ได้ — ว่างถ้า answerable"},
        "current_responsibility": {"type": "array", "items": {"type": "string"}},
        "current_state": {"type": "array", "items": {"type": "string"}},
        "recommended_next_steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string",
                            "description": "เหตุผลที่อ้าง ecosystem goal, dependency หรือ contract"},
                    "priority": {"type": "integer", "description": "1 = ทำก่อน"},
                    "references": {"type": "array", "items": {"type": "string"},
                                   "description": "id ของ component/contract/team ที่ใช้ตอบ"},
                },
                "required": ["title", "why", "priority", "references"],
                "additionalProperties": False,
            },
        },
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "affected_components": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["team", "answerable", "missing_information", "current_responsibility",
                 "current_state", "recommended_next_steps", "dependencies",
                 "affected_components", "risks"],
    "additionalProperties": False,
}

COORDINATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "potential_risks": {"type": "array", "items": {"type": "string"}},
        "recommended_coordination": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "with_team": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["order", "with_team", "action"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["potential_risks", "recommended_coordination"],
    "additionalProperties": False,
}

SYSTEM_RULES = """คุณคือ Ecosystem Advisor ของทีมวิศวกรรมที่มีหลายทีมและหลาย repository

กฎที่ห้ามละเมิด
1. ใช้ได้เฉพาะข้อเท็จจริงที่อยู่ใน <ecosystem> และ <team_context> เท่านั้น
   ห้ามเดา ห้ามเติมจากความรู้ทั่วไป ห้ามสมมติชื่อ component/contract/team ที่ไม่ได้ให้มา
2. ทุก id ที่อ้างถึงต้องปรากฏใน context ที่ให้มาแบบตรงตัว
3. ถ้าข้อมูลไม่พอจะตอบ ให้ตั้ง answerable=false แล้วระบุใน missing_information
   ว่าขาดอะไร — ห้ามเดาให้ได้คำตอบ
4. ทุกข้อเสนอต้องบอก "ทำไม" โดยอ้าง dependency, contract, conformance
   หรือกฎ architecture ที่ให้มา
5. เรียง recommended_next_steps ตามความสำคัญจริง priority=1 คือทำก่อน
6. ในส่วน risks ให้เตือนเรื่องการสร้างของซ้ำกับทีมอื่นเสมอถ้ามีสัญญาณ

ความหมายที่ต้องเข้าใจให้ถูก
- consumes = pin ไว้จริงมีหลักฐาน · expected_contracts = แค่ตั้งใจ ยังไม่นับเป็น dependency
- conformance unknown = ยังพิสูจน์ไม่ได้ว่าใช้ contract ถูก ไม่ได้แปลว่าใช้ผิด
- contract เปลี่ยนได้ผ่าน ADR ที่ repo เจ้าของเท่านั้น ทีมอื่นเปิด issue ไม่ใช่แก้เอง"""


def _stable_system(truth: dict) -> str:
    return (f"{SYSTEM_RULES}\n\n<ecosystem>\n"
            f"{json.dumps(truth, ensure_ascii=False, sort_keys=True, default=str)}\n</ecosystem>")


def check_grounding(answer: dict, known: set[str]) -> dict[str, Any]:
    """id ทุกตัวที่คำตอบอ้างถึง ต้องมีอยู่ใน context จริง

    ตรวจสองระดับ
        strict  ฟิลด์ที่เป็น id ตรง ๆ — หลุดคือ error
        loose   token ที่หน้าตาเหมือน id ในข้อความอิสระ — หลุดคือ warning
                (ข้อความไทยมีคำที่หน้าตาเหมือน id ได้ จึงไม่นับเป็น error)
    """
    strict: list[str] = []
    for step in answer.get("recommended_next_steps", []):
        strict.extend(step.get("references", []))
    for field in ("dependencies", "affected_components"):
        strict.extend(answer.get(field, []))
    if answer.get("team"):
        strict.append(answer["team"])

    unknown = sorted({i for i in strict if i and i not in known})

    free_text = " ".join(
        [*answer.get("risks", []), *answer.get("current_state", []),
         *(s.get("why", "") for s in answer.get("recommended_next_steps", []))]
    )
    suspicious = sorted({
        t for t in ID_PATTERN.findall(free_text)
        if "/v" in t and t not in known
    })

    return {"ok": not unknown, "unknown_ids": unknown, "suspicious_mentions": suspicious}


def ask(conn, team_id: str, question: str, *,
        provider: LLMProvider | None = None, effort: str = "high") -> dict[str, Any] | None:
    """ถามจากมุมของทีมหนึ่ง — คืน None ถ้าไม่รู้จักทีมนั้น"""
    ctx = team_context(conn, team_id)
    if ctx is None:
        return None

    truth = ecosystem_truth(conn)
    provider = provider or get_provider()

    answer = provider.complete_json(
        stable_system=_stable_system(truth),
        volatile_context=json.dumps(ctx, ensure_ascii=False, sort_keys=True, default=str),
        question=question,
        schema=RECOMMENDATION_SCHEMA,
        effort=effort,
    )
    answer.setdefault("answerable", True)
    answer.setdefault("missing_information", [])

    return {
        "team": team_id,
        "question": question,
        "answer": answer,
        "grounding": check_grounding(answer, known_ids(truth, ctx)),
        "generated_by": {"provider": provider.name, "model": provider.model},
        "as_of": truth["as_of"],
    }


def impact(conn, contract_id: str, *,
           provider: LLMProvider | None = None, effort: str = "high") -> dict[str, Any] | None:
    """เปลี่ยน contract นี้แล้วใครกระทบ

    ข้อเท็จจริงมาจาก graph ทั้งหมด — LLM เติมเฉพาะ "ความเสี่ยง" กับ "ลำดับการประสาน"
    ซึ่งเป็นการตีความ ไม่ใช่ข้อเท็จจริง แยกกันชัดเพื่อให้ตรวจได้ว่าอะไรมาจากไหน
    """
    if q.get_contract(conn, contract_id) is None:
        return None

    facts = q.contract_impact(conn, contract_id)
    facts["affected_contracts"] = sorted({
        k for c in facts["affected_components"]
        for k in (q.get_component(conn, c) or {}).get("consumes", [])
    })
    # authority / semantics_owner เป็น "repo" — แต่คนที่ต้องไปคุยด้วยคือ "ทีม"
    # ถ้าไม่แปลตรงนี้ คำแนะนำจะบอกให้ไปคุยกับชื่อ repo ซึ่งไม่ใช่หน่วยที่ตัดสินใจได้
    team_of_repo = {c["repository"]: c["owner"] for c in q.list_components(conn) if c["repository"]}
    facts["authority_team"] = team_of_repo.get(facts["authority"])
    facts["semantics_owner_team"] = team_of_repo.get(facts["semantics_owner"])

    truth = ecosystem_truth(conn)
    provider = provider or get_provider()

    try:
        judgement = provider.complete_json(
            stable_system=_stable_system(truth),
            volatile_context=json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str),
            question=(f"ถ้าเราเปลี่ยน {contract_id} จะมีความเสี่ยงอะไร "
                      f"และควรประสานงานกับใครตามลำดับไหน"),
            schema=COORDINATION_SCHEMA,
            effort=effort,
        )
    except NotImplementedError:  # pragma: no cover
        judgement = {"potential_risks": [], "recommended_coordination": []}

    # ทีมที่ถูกแนะนำให้ไปประสานงานด้วย ต้องเป็นทีมที่มีอยู่จริง
    teams = {t["id"] for t in truth["teams"]}
    bad_teams = sorted({s["with_team"] for s in judgement["recommended_coordination"]
                        if s["with_team"] not in teams and s["with_team"] != "-"})

    return {
        "facts": facts,
        "judgement": judgement,
        "grounding": {"ok": not bad_teams, "unknown_ids": bad_teams, "suspicious_mentions": []},
        "generated_by": {"provider": provider.name, "model": provider.model},
        "as_of": truth["as_of"],
    }
