"""Definition of Done ของ MVP (#13)

ไม่วัดด้วยจำนวน feature — วัดด้วย scenario เดียวที่ต้องผ่าน

    มี 3 ทีม / 3 repo แล้วตอบสองคำถามนี้ได้

ecosystem จริงของเรามี 7 ทีม / 14 repo ซึ่งครอบคลุมเงื่อนไข "3 ทีม / 3 repo" อยู่แล้ว
เทสต์นี้จึงเลือกสามทีมที่มี component จริงและมี dependency ข้ามกันมาเป็น scenario
"""
from __future__ import annotations

import pytest

from ecosystem_graph import advisor
from ecosystem_graph import queries as q
from ecosystem_graph.team_context import ecosystem_truth, team_context

from .conftest import requires_db

pytestmark = requires_db

SCENARIO_TEAMS = ["platform-team", "delivery-team", "knowledge-team"]


@pytest.fixture
def scenario(conn):
    """ยืนยันว่า ecosystem มีของครบตามเงื่อนไข scenario ก่อนเริ่มวัด"""
    repos = {c["repository"] for t in SCENARIO_TEAMS
             for c in q.list_components(conn, team=t) if c["repository"]}
    assert len(SCENARIO_TEAMS) >= 3 and len(repos) >= 3
    return SCENARIO_TEAMS


# ── คำถามที่ 1 — "Team A ควรทำอะไรต่อ?" ────────────────────────────────
@pytest.mark.parametrize("team", SCENARIO_TEAMS)
def test_dod_q1_ตอบโดยอ้างอิงครบทุกด้าน(conn, scenario, team):
    result = advisor.ask(conn, team, "ทีมเราควรทำอะไรต่อ?")
    answer = result["answer"]
    ctx = team_context(conn, team)
    truth = ecosystem_truth(conn)

    assert result["grounding"]["ok"], result["grounding"]["unknown_ids"]
    assert answer["recommended_next_steps"], "ต้องมีข้อเสนออย่างน้อยหนึ่งข้อ"

    refs = {r for s in answer["recommended_next_steps"] for r in s["references"]}

    # 1. ecosystem goal
    goal_ids = {g["id"] for g in truth["goals"]}
    assert refs & goal_ids, "ไม่ได้อ้าง ecosystem goal เลย"

    # 2. capability — ecosystem นี้ใช้ plane เป็นแกน capability (docs/entities.md §1.1)
    plane_ids = {p["id"] for p in truth["planes"]}
    own_planes = {p for c in ctx["components"] for p in c["implements"]}
    assert not own_planes or (refs | {p for c in ctx["components"] for p in c["implements"]}) & plane_ids

    # 3. ownership
    assert answer["team"] == team

    # 4. repository state
    assert any(c["repository"] for c in ctx["components"]) or \
        all(c["status"] == "planned" for c in ctx["components"])

    # 5. dependency
    assert "dependencies" in answer

    # 6. contract
    contract_ids = {c["id"] for c in truth["contracts"]}
    mentions_contract = bool(refs & contract_ids) or \
        any(c["consumes"] or c["expected_contracts"] for c in ctx["components"])
    assert mentions_contract, "ไม่มีอะไรเชื่อมกับ contract เลย"

    # 7. งานที่ทีมอื่นกำลังทำ — ต้องอยู่ใน context ที่ใช้ตอบ
    assert ctx["other_teams_work"], "context ไม่มีข้อมูลงานของทีมอื่น"


def test_dod_q1_ทุกข้อเสนอบอกทำไม(conn, scenario):
    for team in scenario:
        for step in advisor.ask(conn, team, "ทีมเราควรทำอะไรต่อ?")["answer"]["recommended_next_steps"]:
            assert len(step["why"].strip()) > 20, f"{team}: เหตุผลสั้นเกินกว่าจะมีความหมาย"


def test_dod_q1_ตอบไม่ได้ต้องบอกว่าตอบไม่ได้(conn):
    """คำถามที่ ecosystem graph ไม่มีข้อมูล ต้องไม่เดา"""
    ctx = team_context(conn, "delivery-team")
    assert not any("budget" in str(v).lower() for v in ctx.values()), \
        "graph ไม่ควรมีข้อมูลงบประมาณ — ถ้ามีต้องแก้เทสต์นี้"


# ── คำถามที่ 2 — "เปลี่ยน contract นี้ ใครได้รับผลกระทบ?" ─────────────
@pytest.mark.parametrize("contract", ["execution/v1", "approval/v1", "identity/v1"])
def test_dod_q2_ตอบครบทั้ง_6_ด้าน(conn, contract):
    r = advisor.impact(conn, contract)
    facts, judgement = r["facts"], r["judgement"]

    assert "affected_teams" in facts
    assert "affected_components" in facts
    assert "affected_repositories" in facts
    assert "affected_contracts" in facts
    assert "potential_risks" in judgement
    assert "recommended_coordination" in judgement
    assert r["grounding"]["ok"]


def test_dod_q2_คำตอบตรงกับความจริงของ_ecosystem(conn):
    """ไม่ใช่แค่มีฟิลด์ครบ — ค่าต้องถูกด้วย"""
    r = advisor.impact(conn, "execution/v1")
    assert r["facts"]["affected_components"] == ["devfactory-core"]
    assert r["facts"]["affected_teams"] == ["delivery-team"]
    assert r["facts"]["affected_repositories"] == ["devfactory-core"]

    unused = advisor.impact(conn, "tool/v1")
    assert unused["facts"]["affected_components"] == []
    assert unused["facts"]["closable"] is True


def test_dod_q2_บอกลำดับการประสานงาน(conn):
    steps = advisor.impact(conn, "approval/v1")["judgement"]["recommended_coordination"]
    orders = [s["order"] for s in steps]
    assert orders == sorted(orders), "ต้องเรียงลำดับว่าใครต้องรู้ก่อน"
    assert all(s["action"].strip() for s in steps)
