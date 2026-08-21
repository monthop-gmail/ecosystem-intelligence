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


def test_ไม่มี_route_ที่เขียนข้อมูล():
    methods = {m for route in app.routes for m in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD", "OPTIONS"}, f"เจอ method ที่เขียนได้: {methods}"


def test_read_only_ถูกบังคับที่ฐานข้อมูลจริง(loaded_db):
    """ไม่ใช่แค่ไม่มี route ที่เขียน — connection ของ API เขียนไม่ได้จริง"""
    import psycopg

    with connect(readonly=True) as c:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("DELETE FROM components")


def test_cycles_endpoint(client):
    body = client.get("/graph/cycles").json()
    assert body["count"] == 0
