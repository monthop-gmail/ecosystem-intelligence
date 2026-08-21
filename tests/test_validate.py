"""validator — ตัวเดียวกับที่ importer ใช้ ไม่ต้องมี DB"""
from __future__ import annotations

import copy

import pytest

from ecosystem_graph.validate import ValidationError, load, validate


@pytest.fixture(scope="module")
def doc():
    d, _ = load(strict=False)
    return d


def test_ecosystem_yaml_ผ่าน():
    doc, result = load(strict=False)
    assert result.ok, result.errors
    assert len(doc["components"]) >= 14


def test_มี_warning_ได้โดยไม่ตก():
    _, result = load(strict=False)
    assert result.warnings, "ควรเตือนเรื่องทีมสมาชิกซ้ำและ contract ที่ยังไม่มี consumer"
    assert result.ok


def test_owner_ที่ไม่มีจริงคือ_orphan(doc):
    bad = copy.deepcopy(doc)
    bad["components"][0]["owner"] = "ghost-team"
    result = validate(bad)
    assert not result.ok
    assert any("orphan" in e for e in result.errors)


def test_consumes_ต้องมีหลักฐาน(doc):
    """component ที่ไม่มี manifest ประกาศ consumes ไม่ได้ — กัน M4 รายงาน dependency ปลอม"""
    bad = copy.deepcopy(doc)
    comp = next(c for c in bad["components"] if c["id"] == "enterprise-knowledge")
    comp["consumes"] = ["tool/v1"]
    result = validate(bad)
    assert not result.ok
    assert any("ไม่มี manifest" in e for e in result.errors)


def test_contract_มีผู้_expose_ได้รายเดียว(doc):
    bad = copy.deepcopy(doc)
    comp = next(c for c in bad["components"] if c["id"] == "enterprise-knowledge")
    comp["exposes"] = ["tool/v1"]
    result = validate(bad)
    assert not result.ok
    assert any("ต้องมีเจ้าของเดียว" in e for e in result.errors)


def test_conformance_เกิน_90_วันถูกเตือน(doc):
    bad = copy.deepcopy(doc)
    comp = next(c for c in bad["components"] if c["id"] == "devfactory-core")
    comp["conformance"]["last_verified"] = "2020-01-01"
    result = validate(bad)
    assert result.ok, "เก่าเกินเป็น warning ไม่ใช่ error"
    assert any("ADR-0006 ถือเป็น unknown" in w for w in result.warnings)


def test_derived_ต้องมาคู่กับ_semantics_owner(doc):
    bad = copy.deepcopy(doc)
    c = next(x for x in bad["contracts"] if x["id"] == "approval/v1")
    del c["semantics_owner"]
    result = validate(bad)
    assert not result.ok
    assert any("ต้องมาคู่กัน" in e for e in result.errors)


def test_strict_โยน_ValidationError(tmp_path):
    import yaml
    d, _ = load(strict=False)
    d["components"][0]["owner"] = "ghost-team"
    p = tmp_path / "broken.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError):
        load(p)


# ── mission.goals ต้องเป็นเป้าหมาย ไม่ใช่กติกาที่เขียนใหม่ ─────────────
def test_เป้าหมายต้องบอกว่าใครตัดสิน(doc):
    """ไม่มีเอกสารไหนใน ecosystem เขียนเป้าหมายไว้ — จึง derive ไม่ได้ ต้องมีคนตัดสิน"""
    import copy
    bad = copy.deepcopy(doc)
    del bad["mission"]["decided_by"]
    for g in bad["mission"]["goals"]:
        g.pop("decided_by", None)
    result = validate(bad)
    assert not result.ok
    assert any("ใครตัดสิน" in e for e in result.errors)


def test_ไม่มีเป้าหมายเลยเตือน_ไม่ใช่บล็อก(doc):
    """schema ต้องยอมให้ว่าง — บังคับให้ต้องมี คือบังคับให้คนที่ยังไม่ได้ตัดสินไปแต่งขึ้นมา
    ซึ่งเป็นความผิดพลาดที่ทำให้ต้องรื้อ mission ทั้งก้อนมาแล้วครั้งหนึ่ง"""
    import copy
    bad = copy.deepcopy(doc)
    bad["mission"]["goals"] = []
    result = validate(bad)
    assert result.ok, f"ว่างต้องไม่เป็น error: {result.errors}"
    assert any("ไม่มีเป้าหมายระดับ ecosystem" in w for w in result.warnings)


def test_เป้าหมายห้ามชื่อชนกับกฎ(doc):
    """ถ้าเป้าหมายคือกฎที่เขียนใหม่ advisor จะตอบว่า 'ทำ X เพราะกฎ X' ซึ่งไม่ใช่เหตุผล"""
    import copy
    bad = copy.deepcopy(doc)
    bad["mission"]["goals"][0]["id"] = bad["architecture_rules"][0]["id"]
    result = validate(bad)
    assert not result.ok
    assert any("เป้าหมายกับกฎต้องไม่ใช่ของเดียวกัน" in e for e in result.errors)


def test_เป้าหมายปัจจุบันไม่ใช่กติกาที่เขียนใหม่(doc):
    """กันการถอยกลับ — สี่ข้อนี้เคยถูกใส่เป็นเป้าหมายทั้งที่เป็นกฎ"""
    ids = {g["id"] for g in doc["mission"]["goals"]}
    เคยผิด = {"contract-single-source", "conformance-provable",
              "ownership-unambiguous", "no-duplicate-abstraction", "one-ecosystem-view"}
    assert not (ids & เคยผิด), f"เป้าหมายที่จริง ๆ เป็นกฎกลับมาแล้ว: {ids & เคยผิด}"
