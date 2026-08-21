"""Delivery Integration (#24 #25)

หัวใจคือ: event ที่เราปล่อยออกไปต้อง conform กับ contract ของ ecosystem จริง
ไม่ใช่รูปแบบที่เราคิดขึ้นเอง — validate กับ schema ที่ vendor ไว้จาก commit ที่ pin
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ecosystem_graph import advisor
from ecosystem_graph.config import ROOT
from ecosystem_graph.integration import events, feedback
from ecosystem_graph.integration.client import EcosystemClient, EcosystemError

from .conftest import requires_db

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


@pytest.fixture(scope="module")
def validator():
    base = ROOT / "conformance" / "schemas"
    ev = yaml.safe_load((base / "event-v1.schema.yaml").read_text(encoding="utf-8"))
    idn = yaml.safe_load((base / "identity-v1.schema.yaml").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (idn["$id"], Resource(contents=idn, specification=DRAFT202012)),
        (ev["$id"], Resource(contents=ev, specification=DRAFT202012)),
    ])
    return Draft202012Validator(ev, registry=registry)


@pytest.fixture
def sample_result():
    return {
        "question": "ทีมเราควรทำอะไรต่อ?",
        "as_of": "2026-08-21",
        "generated_by": {"provider": "offline", "model": "rule-engine"},
        "grounding": {"ok": True, "unknown_ids": [], "suspicious_mentions": []},
        "answer": {
            "team": "knowledge-team", "answerable": True, "missing_information": [],
            "current_responsibility": [], "current_state": [],
            "recommended_next_steps": [
                {"title": "ทำให้ conform", "why": "เพราะยังไม่มี manifest",
                 "priority": 1, "references": ["enterprise-knowledge"]},
                {"title": "pin tool/v1", "why": "ประกาศเจตนาไว้แล้ว",
                 "priority": 2, "references": ["tool/v1"]},
            ],
            "dependencies": [], "affected_components": [], "risks": [],
        },
    }


# ── event/v1 conformance ───────────────────────────────────────────────
def test_advisory_event_ผ่าน_schema_จริง(validator, sample_result):
    for e in events.advisory_events(sample_result):
        assert not list(validator.iter_errors(e)), \
            [x.message for x in validator.iter_errors(e)]


def test_drift_event_ผ่าน_schema_จริง(validator):
    findings = [{"rule": "manifest-drift", "severity": "error", "subject": "devfactory-core",
                 "detail": "ไม่ตรงกัน", "fix": "แก้ ecosystem.yaml", "title": "t", "why": "w"},
                {"rule": "x", "severity": "warn", "subject": "y", "detail": "d",
                 "fix": "f", "title": "t", "why": "w"}]
    payloads = events.drift_events(findings)
    assert len(payloads) == 1, "warning ไม่ใช่เหตุการณ์ที่ต้องบันทึกถาวร — เอาเฉพาะ error"
    assert not list(validator.iter_errors(payloads[0]))


def test_id_ทุกตัวตรงรูปแบบของ_identity_v1(sample_result):
    for e in events.advisory_events(sample_result):
        for field in ("event_id", "subject_id", "correlation_id", "tenant_id"):
            assert ID_RE.match(e[field]), f"{field}={e[field]!r} ผิดรูปแบบ Id"


def test_id_ยาวเกินถูกย่อโดยไม่ชนกัน():
    long_a = events._id("x" * 100, "a")
    long_b = events._id("x" * 100, "b")
    assert len(long_a) <= 63 and ID_RE.match(long_a)
    assert long_a != long_b, "ย่อแล้วต้องไม่ชนกัน"


def test_หนึ่งข้อเสนอหนึ่งใบ_ผูกกันด้วย_correlation(sample_result):
    evs = events.advisory_events(sample_result)
    assert len(evs) == 2
    assert len({e["correlation_id"] for e in evs}) == 1
    assert [e["sequence"] for e in evs] == [1, 2]


def test_ห้ามปลอม_job_id(sample_result):
    """RFC-0008: event ที่ไม่ได้เกิดจาก job ต้องไม่มี job_id ไม่ใช่ใส่ค่าปลอม"""
    for e in events.advisory_events(sample_result):
        assert "job_id" not in e


def test_ห้ามเก็บ_chain_of_thought(sample_result):
    """🔒 invariant ของ event/v1"""
    forbidden = {"thinking", "reasoning", "chain_of_thought", "scratchpad", "raw_response"}
    for e in events.advisory_events(sample_result):
        assert not (forbidden & set(e["metadata"]))


def test_source_external_ถูกคงไว้เสมอ(sample_result):
    for e in events.advisory_events(sample_result):
        assert e["source"]["kind"] == "external"
        assert e["source"]["system"] == "ecosystem-intelligence"


def test_subject_type_record_ต้องบอกชนิดจริง(sample_result):
    for e in events.advisory_events(sample_result):
        assert e["subject_type"] == "record"
        assert e["metadata"]["record_type"] == "ecosystem_advisory"


def test_event_type_ตรงรูปแบบที่_schema_บังคับ(sample_result):
    pattern = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
    assert pattern.match(events.ADVISORY_ISSUED)
    assert pattern.match(events.DRIFT_DETECTED)


# ── manifest ───────────────────────────────────────────────────────────
def test_manifest_ประกาศตรงกับสิ่งที่ปล่อยจริง():
    manifest = yaml.safe_load((ROOT / "platform-contract.yaml").read_text(encoding="utf-8"))
    assert set(manifest["contracts"]) == {"event/v1", "identity/v1"}
    declared = {v["name"] for v in manifest["vocabulary_added"]}
    assert declared == {events.ADVISORY_ISSUED, events.DRIFT_DETECTED}, \
        "vocabulary ที่ประกาศต้องตรงกับที่โค้ดปล่อยจริง"


def test_pin_ตรงกับที่บันทึกใน_manifest():
    pinned = yaml.safe_load((ROOT / "conformance" / "pinned.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ROOT / "platform-contract.yaml").read_text(encoding="utf-8"))
    assert manifest["pinned_contracts_commit"] == pinned["commit"]


def test_schema_ที่_vendor_ไว้มีครบตามที่_pinned_บอก():
    pinned = yaml.safe_load((ROOT / "conformance" / "pinned.yaml").read_text(encoding="utf-8"))
    for path in pinned["schemas"]:
        name = Path(path).parts[1]
        assert (ROOT / "conformance" / "schemas" / f"{name}-v1.schema.yaml").exists()


# ── client ─────────────────────────────────────────────────────────────
def test_client_ไม่พึ่ง_dependency_นอก_stdlib():
    text = (ROOT / "integration" / "ecosystem_client.py").read_text(encoding="utf-8")
    for pkg in ("import requests", "import httpx", "import pydantic", "from fastapi"):
        assert pkg not in text, f"client ต้องก๊อปไปใช้ได้โดยไม่ต้องลงอะไรเพิ่ม — เจอ {pkg}"


def test_client_แปลง_error_ให้อ่านรู้เรื่อง(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(EcosystemError) as e:
        EcosystemClient("http://x").team("ghost")
    assert e.value.status == 404


def test_client_ประกอบ_url_ถูก(monkeypatch):
    seen = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"ok": True}).encode()

    def fake(req, timeout=None):
        seen["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake)
    EcosystemClient("http://x/").components(team="delivery-team", plane=None)
    assert seen["url"] == "http://x/components?team=delivery-team"


# ── feedback ───────────────────────────────────────────────────────────
@requires_db
def test_feedback_จับ_conformance_ที่ใหม่กว่า(conn):
    import base64

    class FakeGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            body = yaml.safe_dump({
                "contracts": ["identity/v1", "execution/v1", "policy/v1",
                              "error/v1", "approval/v1", "event/v1"],
                "conformance": {"status": "passing", "last_verified": "2099-01-01"},
            })
            return {"content": base64.b64encode(body.encode()).decode()}

    items = feedback.proposals(conn, gh=FakeGH())
    kinds = {i["kind"] for i in items}
    assert "conformance-newer" in kinds
    assert any(i["subject"] == "devfactory-core" for i in items)


@requires_db
def test_feedback_ไม่แก้ไฟล์ให้เอง(conn):
    """ecosystem.yaml เป็นแหล่งความจริงที่คนดูแล — ระบบเสนอเท่านั้น"""
    before = (ROOT / "ecosystem.yaml").read_text(encoding="utf-8")

    class NoGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            raise RuntimeError("offline")

    feedback.proposals(conn, gh=NoGH())
    assert (ROOT / "ecosystem.yaml").read_text(encoding="utf-8") == before


@requires_db
def test_event_จากการรันจริงก็ยัง_conform(conn, validator):
    """ไม่ใช่แค่ payload ตัวอย่าง — ของที่ advisor ผลิตจริงต้องผ่านด้วย"""
    result = advisor.ask(conn, "knowledge-team", "ทีมเราควรทำอะไรต่อ?")
    payloads = events.advisory_events(result)
    assert payloads
    for e in payloads:
        assert not list(validator.iter_errors(e))
