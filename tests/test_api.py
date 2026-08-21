"""API — read-only และตอบคำถามที่ #6 กำหนด"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecosystem_graph.api import app
from ecosystem_graph.db import connect

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture(scope="module")
def client(loaded_db):
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ecosystem"] == "monthop-ecosystem"
    assert body["components"] >= 14


def test_ทีมนี้เป็นเจ้าของ_component_อะไรบ้าง(client):
    r = client.get("/teams/delivery-team/components")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["devfactory-core"]


def test_component_เดี่ยวมีข้อมูลครบ(client):
    body = client.get("/components/devfactory-core").json()
    assert body["owner"] == "delivery-team"
    assert "execution/v1" in body["consumes"]
    assert body["conformance_status"] in ("passing", "unknown")


def test_กรอง_component(client):
    assert {c["id"] for c in client.get("/components?plane=knowledge").json()} \
        == {"enterprise-knowledge"}
    assert {c["id"] for c in client.get("/components?team=platform-team").json()} \
        >= {"agent-platform"}


def test_dependencies_และ_dependents(client):
    up = client.get("/components/devfactory-core/dependencies").json()
    assert [r["component"] for r in up["results"]] == ["agent-platform"]
    down = client.get("/components/agent-platform/dependents").json()
    assert {r["component"] for r in down["results"]} == {"devfactory-core", "care-agent-platform"}


def test_impact_ของ_contract(client):
    body = client.get("/contracts/execution/v1/impact").json()
    assert body["affected_teams"] == ["delivery-team"]
    assert body["closable"] is False


def test_contract_ที่มี_slash_ใน_id_เรียกได้(client):
    body = client.get("/contracts/approval/v1").json()
    assert body["id"] == "approval/v1"
    assert body["semantics_owner"] == "devfactory-core"


def test_ไม่พบ_ตอบ_404(client):
    for path in ("/teams/ไม่มี", "/components/ไม่มี", "/planes/ไม่มี", "/repositories/ไม่มี"):
        assert client.get(path).status_code == 404


def test_มีเพียง_ask_ที่เป็น_POST():
    """/ask เป็น POST เพราะคำถามต้องอยู่ใน body ไม่ใช่เพราะเขียนข้อมูล

    ข้อรับประกันจริงเรื่อง read-only อยู่ที่ระดับฐานข้อมูล (ดูเทสต์ถัดไป)
    ไม่ใช่ที่ HTTP method — เทสต์นี้กันไม่ให้มี route เขียนข้อมูลแอบเข้ามาโดยไม่ตั้งใจ
    """
    non_get = {
        route.path: sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
        for route in app.routes
        if getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
    }
    assert non_get == {"/ask": ["POST"]}, f"เจอ route ที่ไม่ใช่ GET เกินคาด: {non_get}"


def test_ask_ไม่เขียนอะไรลง_DB(client):
    """POST /ask ต้องไม่เปลี่ยนข้อมูลใน graph"""
    from ecosystem_graph.db import fetch_one

    with connect() as c:
        before = fetch_one(c, "SELECT count(*) AS n FROM components")["n"]
    r = client.post("/ask", json={"team": "delivery-team", "question": "ทีมเราควรทำอะไรต่อ?"})
    assert r.status_code == 200
    with connect() as c:
        assert fetch_one(c, "SELECT count(*) AS n FROM components")["n"] == before


def test_ask_ตอบครบและ_grounded(client):
    body = client.post("/ask", json={
        "team": "knowledge-team", "question": "ทีมเราควรทำอะไรต่อ?"
    }).json()
    assert body["grounding"]["ok"] is True
    assert body["generated_by"]["provider"] == "offline"
    assert body["answer"]["recommended_next_steps"]


def test_ask_ทีมที่ไม่มี_404(client):
    r = client.post("/ask", json={"team": "ghost-team", "question": "อะไรก็ตาม"})
    assert r.status_code == 404


def test_ask_provider_ที่ไม่รู้จัก_400(client):
    r = client.post("/ask", json={"team": "delivery-team", "question": "ควรทำอะไรต่อ?",
                                  "provider": "gemini"})
    assert r.status_code == 400


def test_coordination_endpoint(client):
    body = client.get("/contracts/approval/v1/coordination").json()
    assert body["facts"]["semantics_owner_team"] == "delivery-team"
    assert body["judgement"]["recommended_coordination"]


def test_provider_endpoint(client):
    body = client.get("/advisor/provider").json()
    assert body["provider"] == "offline" and body["configured"] is True


def test_read_only_ถูกบังคับที่ฐานข้อมูลจริง(loaded_db):
    """ไม่ใช่แค่ไม่มี route ที่เขียน — connection ของ API เขียนไม่ได้จริง"""
    import psycopg

    with connect(readonly=True) as c:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("DELETE FROM components")


def test_cycles_endpoint(client):
    body = client.get("/graph/cycles").json()
    assert body["count"] == 0
