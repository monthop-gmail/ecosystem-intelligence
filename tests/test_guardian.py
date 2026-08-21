"""Architecture Guardian (#21 #22 #23)

กฎบางข้อสร้างสถานะผิดใน DB ไม่ได้เลยเพราะ constraint กันไว้แล้ว —
เทสต์กลุ่มนั้นจึงตรวจตรรกะโดยตรง แล้วยืนยันว่า DB กันไว้อีกชั้น
"""
from __future__ import annotations

import pytest

from ecosystem_graph import queries as q
from ecosystem_graph.db import connect
from ecosystem_graph.guardian import checks, review

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def rules():
    return checks.load_rules()


# ── กฎต้องครบถ้วนในตัวเอง ──────────────────────────────────────────────
def test_ทุกกฎมีทางแก้(rules):
    """รายงานที่บอกว่าผิดแต่ไม่บอกว่าจะแก้ยังไง ไม่มีใครทำตาม"""
    for rid, r in rules.items():
        assert r.get("fix", "").strip(), f"{rid} ไม่มี fix"
        assert r.get("why", "").strip(), f"{rid} ไม่มี why"
        assert r["severity"] in ("error", "warn")


def test_ทุก_check_ที่อ้างถึงมีอยู่จริง(rules):
    for rid, r in rules.items():
        if r.get("check"):
            assert r["check"] in checks.CHECKS, f"{rid} อ้าง check ที่ไม่มี: {r['check']}"


# ── #21 Architecture ───────────────────────────────────────────────────
def test_ecosystem_ปัจจุบันไม่มี_error(conn):
    report = checks.run_all(conn)
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert errors == [], f"เจอ error: {errors}"


def test_manifest_drift_ถูกข้ามอย่างมีเสียง(conn):
    """ข้ามการตรวจแล้วรายงานว่า 'ผ่าน' คือการโกหก — ต้องบอกว่าข้าม"""
    report = checks.run_all(conn, include_remote=False)
    assert "manifest-drift" in report["rules_skipped"]
    assert "manifest-drift" not in report["rules_run"]


def test_orphan_เกิดไม่ได้เพราะ_FK_กันไว้(conn):
    """check นี้เป็น defense in depth — DB ปฏิเสธตั้งแต่แรกอยู่แล้ว"""
    import psycopg
    assert checks.orphan_components(conn, checks.load_rules()["orphan-component"]) == []
    with connect() as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("""INSERT INTO components (id, name, owner, status, outside_plane_model,
                                                 outside_plane_reason)
                         VALUES ('x','x','ghost-team','planned',true,'test')""")


def test_execution_ห้ามเป็นเจ้าของ_governance(conn, rules, monkeypatch):
    fake = [{"id": "bad-runtime", "implements": ["runtime"],
             "exposes": ["policy/v1"], "consumes": []}]
    monkeypatch.setattr(q, "list_components", lambda _c: fake)
    found = checks.execution_owns_governance(conn, rules["execution-owns-governance"])
    assert len(found) == 1
    assert found[0]["subject"] == "bad-runtime"
    assert found[0]["severity"] == "error"


def test_execution_ห้ามถือ_credential(conn, rules, monkeypatch):
    fake = [{"id": "bad-harness", "implements": ["harness"],
             "exposes": [], "consumes": ["provider/v1"]}]
    monkeypatch.setattr(q, "list_components", lambda _c: fake)
    found = checks.execution_holds_credential(conn, rules["execution-holds-credential"])
    assert len(found) == 1 and "provider/v1" in found[0]["detail"]


def test_orchestration_ห้ามเป็นเจ้าของ_artifact(conn, rules, monkeypatch):
    fake = [{"id": "bad-wf", "implements": ["workflow"],
             "exposes": ["artifact/v1"], "consumes": []}]
    monkeypatch.setattr(q, "list_components", lambda _c: fake)
    assert len(checks.orchestration_owns_artifact(
        conn, rules["orchestration-owns-artifact"])) == 1


def test_component_ที่ถูกกฎไม่ถูกจับ(conn, rules, monkeypatch):
    ok = [{"id": "good-runtime", "implements": ["runtime"],
           "exposes": [], "consumes": ["execution/v1", "policy/v1"]}]
    monkeypatch.setattr(q, "list_components", lambda _c: ok)
    assert checks.execution_owns_governance(conn, rules["execution-owns-governance"]) == []
    assert checks.execution_holds_credential(conn, rules["execution-holds-credential"]) == []


def test_plane_ที่ยังไม่มีคนทำถูกเตือน(conn, rules):
    found = checks.planes_without_implementation(conn, rules["plane-without-implementation"])
    assert {f["subject"] for f in found} >= {"tools", "policy", "workflow"}
    assert all(f["severity"] == "warn" for f in found)


# ── #22 Contract ───────────────────────────────────────────────────────
def test_contract_ที่มีคนรอใช้ปิดไม่ได้(conn, rules):
    """เดิมเทสต์นี้ยืนยันว่า mcp/v1 ปิดได้ — ซึ่งผิด และเป็นความเชื่อที่ทำให้
    รายงานฉบับ 2026-08-22 แนะนำให้ปิด contract ที่ปิดแล้วพัง
    ตอนนี้ต้องดูครบสามทาง: ใครรอใช้ · ใคร $ref ถึง · plane ไหนจองไว้"""
    found = {f["subject"]: f for f in
             checks.contracts_without_consumer(conn, rules["contract-without-consumer"])}
    assert found["tool/v1"]["closable"] is False, "มีคนประกาศเจตนาจะใช้ ปิดไม่ได้"
    assert "enterprise-knowledge" in found["tool/v1"]["detail"]
    # ตัวที่ไม่มีคนรอ ต้องไม่ตอบว่าปิดได้ตอนที่ยังตรวจ $ref ไม่ได้
    assert found["mcp/v1"]["closable"] is None


def test_conformance_ที่เก่าเกินถูกจับ(conn, rules, loaded_db):
    with connect() as c:
        c.execute("UPDATE conformance SET last_verified = '2020-01-01' "
                  "WHERE component_id = 'devfactory-core'")
        c.commit()
        try:
            found = checks.stale_conformance(c, rules["conformance-stale"])
            assert any(f["subject"] == "devfactory-core" for f in found)
        finally:
            c.execute("UPDATE conformance SET last_verified = '2026-08-19' "
                      "WHERE component_id = 'devfactory-core'")
            c.commit()


def test_manifest_drift_เทียบกับของจริง(conn, rules):
    """ใช้ gh ปลอมที่คืน manifest ที่ไม่ตรงกับ ecosystem.yaml"""
    class FakeGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            import base64
            body = "contracts:\n  - identity/v1\n  - execution/v1\n"
            return {"content": base64.b64encode(body.encode()).decode()}

    found = checks.manifest_drift(conn, rules["manifest-drift"], gh=FakeGH())
    subjects = {f["subject"] for f in found}
    assert "devfactory-core" in subjects
    drift = next(f for f in found if f["subject"] == "devfactory-core")
    assert "ecosystem.yaml มีแต่ manifest ไม่มี" in drift["detail"]


def test_อ่าน_manifest_ไม่ได้ต้องบอก_ไม่ใช่เงียบ(conn, rules):
    class BrokenGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            raise RuntimeError("404")

    found = checks.manifest_drift(conn, rules["manifest-drift"], gh=BrokenGH())
    assert found and all(f.get("skipped") for f in found)


# ── #23 PR review ──────────────────────────────────────────────────────
def test_default_คือปิดทุก_repo():
    cfg = review.load_config()
    assert cfg["default"]["enabled"] is False
    for name, r in (cfg.get("repositories") or {}).items():
        assert r.get("enabled") is False, f"{name} เปิดไว้ — default ต้องเป็นปิด"
        assert r.get("mode") == "warn", f"{name} ต้องเริ่มที่ warn"


def test_repo_config_ตกทอดจาก_default():
    cfg = {"default": {"enabled": False, "mode": "warn"},
           "repositories": {"a": {"enabled": True}}}
    assert review.repo_config("a", cfg) == {"enabled": True, "mode": "warn"}
    assert review.repo_config("ไม่รู้จัก", cfg) == {"enabled": False, "mode": "warn"}


def test_fingerprint_เหมือนเดิมเมื่อ_finding_ชุดเดิม():
    a = [{"rule": "r1", "subject": "s1"}, {"rule": "r2", "subject": "s2"}]
    b = list(reversed(a))
    assert review.fingerprint(a) == review.fingerprint(b), "ลำดับไม่ควรทำให้ต่างกัน"
    assert review.fingerprint(a) != review.fingerprint(a + [{"rule": "r3", "subject": "s3"}])


def test_คอมเมนต์มีเหตุผลและทางแก้():
    r = {
        "level": "breaking", "fingerprint": "abc123", "contracts_touched": ["execution/v1"],
        "config": {"mode": "warn"},
        "findings": [{"rule": "breaking-without-coordination", "severity": "error",
                      "title": "T", "subject": "execution/v1", "detail": "D",
                      "why": "W", "fix": "F"}],
    }
    body = review.render_comment(r)
    assert "ecosystem-guardian:abc123" in body
    assert "W" in body and "**ทางแก้:** F" in body
    assert "ไม่บล็อกการ merge" in body, "โหมด warn ต้องบอกว่าไม่บล็อก"


def test_คอมเมนต์ตอนไม่มีปัญหาก็ยังบอกว่าตรวจแล้ว():
    r = {"level": "non-breaking", "fingerprint": "x", "contracts_touched": [],
         "config": {"mode": "warn"}, "findings": []}
    assert "ไม่พบปัญหา" in review.render_comment(r)


def test_ไม่โพสต์เมื่อ_repo_ปิดอยู่(conn, monkeypatch):
    monkeypatch.setattr(review, "review_pr", lambda *a, **k: {
        "available": True, "level": "breaking", "findings": [], "errors": 0, "warnings": 0,
        "contracts_touched": [], "fingerprint": "f", "should_block": False,
        "config": {"enabled": False, "mode": "warn"}})
    out = review.post_review(conn, "agent-platform", 1, confirm=True, gh=object())
    assert out["posted"] is False and "ปิด Guardian" in out["reason"]


def test_ไม่โพสต์เมื่อไม่ได้ยืนยัน(conn, monkeypatch):
    monkeypatch.setattr(review, "review_pr", lambda *a, **k: {
        "available": True, "level": "breaking", "findings": [], "errors": 0, "warnings": 0,
        "contracts_touched": [], "fingerprint": "f", "should_block": False,
        "config": {"enabled": True, "mode": "warn"}})
    out = review.post_review(conn, "agent-platform", 1, confirm=False, gh=object())
    assert out["posted"] is False and "--post" in out["reason"]


def test_ไม่คอมเมนต์ซ้ำเรื่องเดิม(conn, monkeypatch):
    monkeypatch.setattr(review, "review_pr", lambda *a, **k: {
        "available": True, "level": "breaking", "findings": [], "errors": 0, "warnings": 0,
        "contracts_touched": [], "fingerprint": "dup1", "should_block": False,
        "config": {"enabled": True, "mode": "warn"}})
    monkeypatch.setattr(review, "already_commented", lambda *a, **k: True)
    out = review.post_review(conn, "agent-platform", 1, confirm=True, gh=object())
    assert out["posted"] is False and "เคยคอมเมนต์" in out["reason"]


def test_block_mode_เท่านั้นที่บล็อกได้(conn, monkeypatch):
    findings = [{"rule": "r", "severity": "error", "title": "t", "subject": "s",
                 "detail": "d", "why": "w", "fix": "f"}]
    for mode, expected in (("warn", False), ("block", True)):
        cfg = {"default": {"enabled": True, "mode": mode}, "repositories": {}}
        monkeypatch.setattr(review, "load_config", lambda _c=cfg: _c)
        errors = [f for f in findings if f["severity"] == "error"]
        should_block = bool(errors) and review.repo_config("x", cfg)["mode"] == "block"
        assert should_block is expected


# ── เราตรวจ ecosystem ให้คนอื่น ก็ต้องยอมให้ตรวจตัวเอง ─────────────────
def test_backstop_ที่ยังไม่ถึงกำหนดไม่เตือน(conn, rules):
    """ของจริงตอนนี้ตั้งไว้ 2026-10-31 ยังไม่ถึง"""
    assert checks.blocking_past_backstop(conn, rules["blocking-past-backstop"]) == []


def test_backstop_ที่เลยกำหนดแล้วต้องเตือน(conn, rules, tmp_path, monkeypatch):
    import yaml as y

    from ecosystem_graph.guardian import checks as mod

    fake_root = tmp_path
    (fake_root / "platform-contract.yaml").write_text(y.safe_dump({
        "blocking": [
            {"id": "เลยกำหนด", "status": "raised", "backstop": "2020-01-01",
             "issue": "http://x/1"},
            {"id": "ยังไม่ถึง", "status": "raised", "backstop": "2999-01-01"},
            {"id": "ปิดแล้ว", "status": "resolved", "backstop": "2020-01-01"},
            {"id": "ไม่ได้ตั้ง", "status": "raised"},
        ]}), encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", fake_root, raising=False)
    import ecosystem_graph.config as cfg
    monkeypatch.setattr(cfg, "ROOT", fake_root)

    found = mod.blocking_past_backstop(conn, rules["blocking-past-backstop"])
    assert {f["subject"] for f in found} == {"เลยกำหนด"}
    assert "http://x/1" in found[0]["detail"]


# ── contract ที่ "ไม่มีใครใช้" ต้องดูให้ครบสามทาง ─────────────────────
def test_contract_ที่มี_ref_ถึงห้ามบอกว่าปิดได้(conn, rules):
    """รายงาน 2026-08-22 บอกว่า artifact/v1 กับ model/v1 ปิดได้ ทั้งที่
    execution/v1 และ event/v1 $ref ถึง — ปิดจริง schema ของ consumer 3 ราย
    resolve ไม่ได้ · นี่คือกรณีที่ check ผ่านทั้งที่คำตอบผิดและอันตราย"""
    class FakeGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            import base64
            if path.endswith("contents/contracts"):
                return [{"type": "dir", "name": n} for n in ("event", "model", "mcp")]
            if path.endswith("/v1"):
                name = path.split("/contracts/")[1].split("/")[0]
                return [{"name": f"{name}.schema.yaml"}]
            name = path.split("/contracts/")[1].split("/")[0]
            body = ("$ref: https://schemas.agent-platform.internal/model/v1/x.yaml#/$defs/A"
                    if name == "event" else "type: object")
            return {"content": base64.b64encode(body.encode()).decode()}

    graph = checks.contract_ref_graph(FakeGH())
    assert graph["model/v1"] == {"event/v1"}

    found = {f["subject"]: f for f in checks.contracts_without_consumer(
        conn, rules["contract-without-consumer"], gh=FakeGH())}
    assert found["model/v1"]["closable"] is False
    assert "event/v1" in found["model/v1"]["detail"]


def test_ไม่มี_gh_ต้องบอกว่ายังไม่ได้ตรวจ_ไม่ใช่บอกว่าปิดได้(conn, rules):
    """local ตรวจ $ref ไม่ได้ — ต้องตอบว่า 'ยังไม่รู้' ไม่ใช่ 'ปิดได้'"""
    found = {f["subject"]: f for f in checks.contracts_without_consumer(
        conn, rules["contract-without-consumer"], gh=None)}
    unknown = [f for f in found.values() if f["closable"] is None]
    assert unknown, "ต้องมีอย่างน้อยหนึ่งตัวที่ตอบว่ายังไม่ได้ตรวจ"
    assert all("ยังไม่ได้ตรวจ" in f["detail"] for f in unknown)


def test_contract_ที่_plane_จองไว้ห้ามบอกว่าปิดได้(conn, rules):
    """mcp/v1 ไม่มีใคร pin และไม่มี $ref — แต่ plane tools จองไว้
    ปิดคือการตัดสินแทนคนที่จะมา implement plane นั้น"""
    class NoRefGH:
        owner = "monthop-gmail"

        def api(self, path, **kw):
            if path.endswith("contents/contracts"):
                return []
            return []

    found = {f["subject"]: f for f in checks.contracts_without_consumer(
        conn, rules["contract-without-consumer"], gh=NoRefGH())}
    assert found["mcp/v1"]["closable"] is False
    assert "tools" in found["mcp/v1"]["detail"]
