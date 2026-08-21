"""Impact Analysis (#18 #19 #20)

การจำแนก breaking ทดสอบด้วย patch สังเคราะห์ — ต้องไม่พึ่งเน็ตและต้องคุมเคสได้ครบ
ส่วนที่เดินบน graph ใช้ข้อมูล ecosystem จริง
"""
from __future__ import annotations

import pytest

from ecosystem_graph import impact

from .conftest import requires_db

pytestmark = requires_db


# ── #19 classify_patch — ไม่ต้องมี DB ─────────────────────────────────
def test_เพิ่ม_optional_property_ไม่_breaking():
    patch = """@@ -100,6 +100,11 @@ properties:
   escalation_target:
     $ref: something
+  correlation_id:
+    $ref: something
+    description: ผูกใบอนุมัติเข้ากับสายงานเดียวกัน
"""
    r = impact.classify_patch("contracts/approval/v1/approval.schema.yaml", patch, "modified")
    assert r["level"] == "non-breaking"
    assert "correlation_id" in r["reasons"][0]


def test_เพิ่ม_required_field_คือ_breaking():
    patch = """@@ -10,6 +10,7 @@
 required:
   - id
   - tenant_id
+  - correlation_id
"""
    r = impact.classify_patch("contracts/event/v1/event.schema.yaml", patch, "modified")
    assert r["level"] == "breaking"
    assert "correlation_id" in " ".join(r["reasons"])


def test_ถอด_property_คือ_breaking():
    patch = """@@ -20,8 +20,6 @@ properties:
   keep_me:
     type: string
-  remove_me:
-    type: string
"""
    r = impact.classify_patch("contracts/policy/v1/policy.schema.yaml", patch, "modified")
    assert r["level"] == "breaking"
    assert "remove_me" in " ".join(r["reasons"])


def test_ถอด_required_ตอบไม่แน่ใจ():
    """ผู้ผลิตไม่พัง แต่ผู้บริโภคที่คิดว่าต้องมีเสมออาจพัง — ไม่ควรฟันธง"""
    patch = """@@ -10,7 +10,6 @@
 required:
   - id
-  - tenant_id
   - subject
"""
    r = impact.classify_patch("contracts/event/v1/event.schema.yaml", patch, "modified")
    assert r["level"] == "unsure"


def test_ลบไฟล์_contract_คือ_breaking():
    r = impact.classify_patch("contracts/tool/v1/tool.schema.yaml", None, "removed")
    assert r["level"] == "breaking"


def test_ไฟล์_contract_ใหม่ไม่_breaking():
    r = impact.classify_patch("contracts/newthing/v1/x.schema.yaml", None, "added")
    assert r["level"] == "non-breaking"


def test_semantics_file_ตอบไม่แน่ใจเสมอ():
    """schema ไม่ขยับ แต่ความหมายเปลี่ยนได้ — เครื่องตัดสินแทนคนไม่ได้"""
    r = impact.classify_patch("contract-semantics.yaml", "@@\n+something", "modified")
    assert r["level"] == "unsure"
    assert not r.get("advisory")


def test_adr_เป็น_advisory_ไม่ตัดสินแทน_schema():
    r = impact.classify_patch("decisions/0019-x.md", "@@\n+text", "modified")
    assert r["level"] == "unsure" and r["advisory"] is True


def test_เอกสารทั่วไปไม่กระทบ_schema():
    r = impact.classify_patch("README.md", "@@\n+text", "modified")
    assert r["level"] == "non-breaking"
    assert r["author_claim"] is None


def test_อ่านคำประกาศจาก_CHANGELOG_ของ_contract_เท่านั้น():
    claim_patch = "@@\n+## v1.1.0\n+ไม่ breaking — เพิ่ม optional field อย่างเดียว"
    inside = impact.classify_patch("contracts/approval/v1/CHANGELOG.md", claim_patch, "modified")
    outside = impact.classify_patch("docs/policy.md", claim_patch, "modified")
    assert inside["author_claim"] == "non-breaking"
    assert outside["author_claim"] is None, \
        "เอกสารทั่วไปพูดถึงคำว่า breaking ในเชิงอธิบายได้ ไม่ใช่คำประกาศ"


def test_ไม่มี_diff_ตอบไม่แน่ใจ():
    r = impact.classify_patch("contracts/x/v1/x.schema.yaml", None, "modified")
    assert r["level"] == "unsure"


# ── #18 dependency graph ──────────────────────────────────────────────
def test_ต้นไม้ขาลงจาก_agent_platform(conn):
    tree = impact.dependency_tree(conn, "agent-platform", direction="down")
    kids = {c["node"] for c in tree["children"]}
    assert kids == {"devfactory-core", "care-agent-platform", "ecosystem-intelligence"}


def test_ต้นไม้ขาขึ้นจาก_devfactory(conn):
    tree = impact.dependency_tree(conn, "devfactory-core", direction="up")
    assert [c["node"] for c in tree["children"]] == ["agent-platform"]


def test_render_tree_อ่านด้วยตาได้(conn):
    text = impact.render_tree(impact.dependency_tree(conn, "agent-platform"))
    assert "agent-platform" in text.splitlines()[0]
    assert "└──" in text or "├──" in text
    assert "execution/v1" in text, "ต้องบอกด้วยว่าเชื่อมกันผ่าน contract ไหน"


def test_mermaid_มี_subgraph_ตามทีม(conn):
    diagram = impact.render_mermaid(conn)
    assert diagram.startswith("graph LR")
    assert "subgraph delivery-team" in diagram
    assert "-->" in diagram


def test_จำกัดความลึกได้(conn):
    shallow = impact.dependency_tree(conn, "agent-platform", depth=1)
    assert all(not c["children"] for c in shallow["children"])


# ── #20 cross-team ────────────────────────────────────────────────────
def test_cross_team_ครบทุกด้านตาม_DoD(conn):
    r = impact.cross_team(conn, "approval/v1", level="breaking")
    for field in ("affected_teams", "affected_components", "affected_repositories",
                  "affected_contracts", "potential_risks", "recommended_coordination"):
        assert r[field] is not None, field
    assert r["affected_teams"] == ["care-team", "delivery-team"]


def test_derived_contract_ต้องเริ่มที่เจ้าของ_semantics(conn):
    r = impact.cross_team(conn, "approval/v1", level="breaking")
    first = min(r["recommended_coordination"], key=lambda s: s["order"])
    assert first["team"] == "delivery-team"
    assert first["urgency"] == "blocking"
    assert "RFC" in first["action"]


def test_non_breaking_แค่แจ้งไม่ใช่บล็อก(conn):
    r = impact.cross_team(conn, "identity/v1", level="non-breaking")
    urgencies = {s["urgency"] for s in r["recommended_coordination"]}
    assert "notify" in urgencies
    assert "blocking" not in urgencies, "non-breaking ไม่ควรบล็อกใคร"


def test_contract_ที่ไม่มีใครใช้เปลี่ยนได้อิสระ(conn):
    r = impact.cross_team(conn, "mcp/v1", level="breaking")
    assert r["affected_teams"] == []
    assert r["draft_issues"] == []
    assert any("อิสระ" in x for x in r["potential_risks"])


def test_ร่าง_issue_ไม่ได้เปิดให้จริง(conn):
    r = impact.cross_team(conn, "execution/v1", level="breaking")
    draft = r["draft_issues"][0]
    assert draft["repository"] == "devfactory-core"
    assert "3a01ab9" in draft["body"], "ต้องบอกว่า pin อยู่ที่ commit ไหน"
    assert "ยังไม่ได้เปิด issue ให้" in draft["body"]


def test_ทีมที่แค่ประกาศเจตนาได้แค่_fyi(conn):
    r = impact.cross_team(conn, "execution/v1", level="breaking")
    fyi = [s for s in r["recommended_coordination"] if s["urgency"] == "fyi"]
    assert {s["team"] for s in fyi} == {"platform-team"}


def test_contract_ที่ไม่มีคืน_None(conn):
    assert impact.cross_team(conn, "ghost/v1") is None


# ── component change ──────────────────────────────────────────────────
def test_component_change_เดินตาม_contract_ที่_expose(conn):
    r = impact.component_change(conn, "agent-platform")
    assert set(r["affected_components"]) == {"devfactory-core", "care-agent-platform", "ecosystem-intelligence"}
    assert set(r["affected_teams"]) == {"delivery-team", "care-team", "ecosystem-team"}


def test_component_ที่ไม่มีใครขึ้นกับ(conn):
    r = impact.component_change(conn, "navi-ims")
    assert r["affected_components"] == []
    assert "ไม่มีใครขึ้นกับ" in r["why"]


# ── กฎ deterministic ต้องตรงกับที่ advisor baseline ตอบ ────────────────
def test_deterministic_กับ_baseline_ให้ลำดับเดียวกัน(conn):
    """M4 เป็นกฎ · M2 เป็นความเห็นของ model — ถ้าไม่ตรงกันแปลว่าอันใดอันหนึ่งผิด"""
    from ecosystem_graph import advisor

    rule = impact.cross_team(conn, "approval/v1", level="breaking")
    model = advisor.impact(conn, "approval/v1")

    rule_first = min(rule["recommended_coordination"], key=lambda s: s["order"])["team"]
    model_first = min(model["judgement"]["recommended_coordination"],
                      key=lambda s: s["order"])["with_team"]
    assert rule_first == model_first == "delivery-team"
