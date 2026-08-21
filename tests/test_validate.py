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
