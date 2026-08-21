"""graph traversal — หัวใจที่ M4 จะยืนอยู่บน"""
from __future__ import annotations

from ecosystem_graph import queries as q

from .conftest import requires_db

pytestmark = requires_db


def test_ขาขึ้น_devfactory_ขึ้นกับ_agent_platform(conn):
    deps = q.dependencies_of(conn, "devfactory-core")
    ids = {d["component"] for d in deps}
    assert ids == {"agent-platform"}
    row = next(d for d in deps if d["component"] == "agent-platform")
    assert set(row["via"]) == {"identity/v1", "execution/v1", "policy/v1",
                               "error/v1", "approval/v1", "event/v1"}


def test_ขาลง_ใครขึ้นกับ_agent_platform(conn):
    ids = {d["component"] for d in q.dependents_of(conn, "agent-platform")}
    assert ids == {"devfactory-core", "care-agent-platform"}


def test_expected_ไม่ถูกนับเป็น_dependency(conn):
    """enterprise-knowledge แค่ 'คาดว่าจะใช้' tool/v1 — ยังไม่ใช่ dependency จริง"""
    ids = {d["component"] for d in q.dependencies_of(conn, "enterprise-knowledge")}
    assert ids == set()


def test_impact_ของ_execution_v1(conn):
    r = q.contract_impact(conn, "execution/v1")
    assert r["affected_components"] == ["devfactory-core"]
    assert r["affected_teams"] == ["delivery-team"]
    assert r["closable"] is False
    assert set(r["expected_by"]) == {"agent-backend-os", "agent-fleet"}


def test_impact_ของ_tool_v1_ยังปิดได้(conn):
    r = q.contract_impact(conn, "tool/v1")
    assert r["affected_components"] == []
    assert r["closable"] is True


def test_semantics_owner_ปรากฏใน_impact(conn):
    r = q.contract_impact(conn, "approval/v1")
    assert r["authority"] == "agent-platform"
    assert r["semantics_owner"] == "devfactory-core"


def test_ยังไม่มี_circular_dependency(conn):
    assert q.cycles(conn) == []


def test_กรอง_component_ตามทีมและ_plane(conn):
    assert {c["id"] for c in q.list_components(conn, team="delivery-team")} == {"devfactory-core"}
    assert {c["id"] for c in q.list_components(conn, plane="knowledge")} == {"enterprise-knowledge"}
    assert all(c["status"] == "planned"
               for c in q.list_components(conn, status="planned"))


def test_conformance_90_วันถูกคำนวณในฐานข้อมูล(conn):
    """view conformance_effective ต้องบังคับกฎ ADR-0006 ไม่ใช่เชื่อค่าในไฟล์"""
    row = q.get_component(conn, "devfactory-core")
    assert row["conformance_declared"] == "passing"
    assert row["conformance_age_days"] is not None
    expected = "passing" if row["conformance_age_days"] <= 90 else "unknown"
    assert row["conformance_status"] == expected


def test_agent_backend_os_กินสอง_plane(conn):
    row = q.get_component(conn, "agent-backend-os")
    assert set(row["implements"]) == {"backend-os", "runtime"}
