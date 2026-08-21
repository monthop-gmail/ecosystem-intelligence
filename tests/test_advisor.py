"""Team Advisor — context, grounding และชุดคำถามทดสอบ (#9 #11 #12)"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ecosystem_graph import advisor
from ecosystem_graph.llm import get_provider
from ecosystem_graph.team_context import ecosystem_truth, known_ids, team_context

from .conftest import requires_db

pytestmark = requires_db

QUESTIONS = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "evaluation" / "questions.yaml")
    .read_text(encoding="utf-8")
)


# ── #9 Team context ────────────────────────────────────────────────────
def test_context_มีข้อเท็จจริงครบ(conn):
    ctx = team_context(conn, "delivery-team")
    assert ctx["team"]["id"] == "delivery-team"
    assert [c["id"] for c in ctx["components"]] == ["devfactory-core"]
    assert ctx["repositories"] == ["devfactory-core"]
    assert [d["component"] for d in ctx["depends_on"]] == ["agent-platform"]
    assert ctx["depends_on"][0]["owned_by"] == "platform-team"


def test_context_เล็กพอใส่_prompt(conn):
    """ห้าม dump ทั้ง ecosystem — context ต่อทีมต้องเล็ก"""
    for team in ("delivery-team", "platform-team", "knowledge-team"):
        size = len(json.dumps(team_context(conn, team), ensure_ascii=False, default=str))
        assert size < 20_000, f"{team} context ใหญ่เกินไป: {size} bytes"


def test_ทีมที่ไม่มีคืน_None(conn):
    assert team_context(conn, "ghost-team") is None


def test_context_ไม่มีการตีความ(conn):
    """ชั้นนี้ต้องมีแต่ข้อเท็จจริง — ห้ามมีคำแนะนำปนมา"""
    ctx = team_context(conn, "knowledge-team")
    assert "recommendation" not in ctx and "advice" not in ctx
    assert set(ctx) == {"team", "components", "repositories", "depends_on",
                        "depended_on_by", "semantics_owned", "exposed_contracts",
                        "other_teams_work"}


# ── #11 Grounding ──────────────────────────────────────────────────────
def test_grounding_จับ_id_ที่แต่งขึ้น(conn):
    known = known_ids(ecosystem_truth(conn), team_context(conn, "delivery-team"))
    fake = {
        "team": "delivery-team",
        "recommended_next_steps": [
            {"title": "x", "why": "y", "priority": 1,
             "references": ["devfactory-core", "quantum-mesh-service"]}
        ],
        "dependencies": ["agent-platform"],
        "affected_components": ["nonexistent-thing"],
        "risks": [],
        "current_state": [],
    }
    result = advisor.check_grounding(fake, known)
    assert result["ok"] is False
    assert result["unknown_ids"] == ["nonexistent-thing", "quantum-mesh-service"]


def test_grounding_ผ่านเมื่อ_id_มีจริง(conn):
    known = known_ids(ecosystem_truth(conn), team_context(conn, "delivery-team"))
    good = {
        "team": "delivery-team",
        "recommended_next_steps": [
            {"title": "x", "why": "y", "priority": 1, "references": ["execution/v1"]}
        ],
        "dependencies": ["agent-platform"],
        "affected_components": ["devfactory-core"],
        "risks": [], "current_state": [],
    }
    assert advisor.check_grounding(good, known)["ok"] is True


def test_grounding_จับ_contract_ปลอมในข้อความอิสระ(conn):
    known = known_ids(ecosystem_truth(conn), team_context(conn, "delivery-team"))
    answer = {
        "team": "delivery-team", "recommended_next_steps": [], "dependencies": [],
        "affected_components": [], "current_state": [],
        "risks": ["ระวังเรื่อง billing/v2 ที่จะมาใหม่"],
    }
    result = advisor.check_grounding(answer, known)
    assert result["ok"] is True, "ข้อความอิสระเป็น warning ไม่ใช่ error"
    assert "billing/v2" in result["suspicious_mentions"]


# ── #12 Recommended work ───────────────────────────────────────────────
@pytest.mark.parametrize("case", QUESTIONS, ids=[c["id"] for c in QUESTIONS])
def test_ชุดคำถามทดสอบ(conn, case):
    """รันกับ provider ที่ตั้งไว้ — offline โดย default

    เกณฑ์เป็นข้อเท็จจริงที่ต้องมี ไม่ใช่การเทียบข้อความคำต่อคำ
    """
    result = advisor.ask(conn, case["team"], case["question"], provider=get_provider())
    assert result is not None
    answer = result["answer"]

    assert result["grounding"]["ok"], \
        f"อ้าง id ที่ไม่มีจริง: {result['grounding']['unknown_ids']}"

    mentioned = {r for s in answer["recommended_next_steps"] for r in s["references"]}
    mentioned.update(answer["affected_components"])

    for must in case["must_reference"]:
        assert must in mentioned, f"คำตอบไม่ได้อ้างถึง {must}"
    for never in case["must_not_mention"]:
        assert never not in mentioned, f"คำตอบไปอ้างถึง {never} ซึ่งไม่ใช่ของทีมนี้"

    if case["expect_answerable"]:
        assert answer["recommended_next_steps"], "ตอบได้แต่ไม่มีข้อเสนอเลย"


def test_ทุกข้อเสนอบอกเหตุผลและเรียงลำดับ(conn):
    answer = advisor.ask(conn, "knowledge-team", "ทีมเราควรทำอะไรต่อ?")["answer"]
    steps = answer["recommended_next_steps"]
    assert steps
    assert all(s["why"].strip() for s in steps), "ทุกข้อเสนอต้องบอกทำไม"
    assert all(s["references"] for s in steps), "ทุกข้อเสนอต้องอ้างอิงกลับไปที่ entity"
    assert [s["priority"] for s in steps] == sorted(s["priority"] for s in steps)


def test_ทีมที่ไม่มีคืน_None_จาก_ask(conn):
    assert advisor.ask(conn, "ghost-team", "อะไรก็ตาม") is None


# ── impact / coordination ──────────────────────────────────────────────
def test_impact_แยกข้อเท็จจริงออกจากการตีความ(conn):
    r = advisor.impact(conn, "approval/v1")
    assert r["facts"]["affected_teams"] == ["care-team", "delivery-team"]
    assert r["facts"]["semantics_owner"] == "devfactory-core"
    assert r["facts"]["semantics_owner_team"] == "delivery-team"
    assert r["judgement"]["recommended_coordination"]
    assert r["grounding"]["ok"], "ทีมที่แนะนำให้ประสานงานต้องมีอยู่จริง"


def test_impact_รู้ว่า_derived_contract_ต้องเริ่มที่ต้นทาง(conn):
    """approval/v1 semantics เป็นของ devfactory-core — แก้ที่ agent-platform อย่างเดียวไม่ได้"""
    r = advisor.impact(conn, "approval/v1")
    first = min(r["judgement"]["recommended_coordination"], key=lambda s: s["order"])
    assert first["with_team"] == "delivery-team"


def test_impact_contract_ที่ไม่มีคืน_None(conn):
    assert advisor.impact(conn, "ghost/v1") is None
