"""importer — idempotent และ "ไม่ผ่าน = ไม่เขียน" (#7)"""
from __future__ import annotations

import pytest
import yaml

from ecosystem_graph.db import connect, fetch_one
from ecosystem_graph.importer import run
from ecosystem_graph.validate import ValidationError, load

from .conftest import requires_db

pytestmark = requires_db


def _counts() -> dict[str, int]:
    with connect() as c:
        return {t: fetch_one(c, f"SELECT count(*) AS n FROM {t}")["n"]
                for t in ("components", "contracts", "component_contracts", "teams")}


def test_import_ซ้ำได้ผลเท่าเดิม(loaded_db):
    before = _counts()
    out = run()
    assert out["changes"] == [], "import ซ้ำต้องไม่มีส่วนต่าง"
    assert _counts() == before


def test_dry_run_ไม่เขียนอะไร(loaded_db):
    before = _counts()
    with connect() as c:
        c.execute("DELETE FROM component_contracts")
        c.commit()
    out = run(dry_run=True)
    assert out["dry_run"] is True
    assert out["changes"], "ควรรายงานว่ามีส่วนต่างหลังลบข้อมูลทิ้ง"
    with connect() as c:
        assert fetch_one(c, "SELECT count(*) AS n FROM component_contracts")["n"] == 0
    run()  # คืนสภาพ
    assert _counts() == before


def test_ไฟล์ที่ไม่ผ่านไม่แตะ_DB(loaded_db, tmp_path):
    before = _counts()
    doc, _ = load(strict=False)
    doc["components"][0]["owner"] = "ghost-team"
    p = tmp_path / "broken.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValidationError):
        run(p)
    assert _counts() == before, "validate ต้องเกิดก่อนเปิดทรานแซกชัน"


def test_ข้อมูลตรงกับ_yaml(loaded_db):
    doc, _ = load(strict=False)
    with connect() as c:
        n = fetch_one(c, "SELECT count(*) AS n FROM components")["n"]
        assert n == len(doc["components"])
        row = fetch_one(c, "SELECT * FROM conformance WHERE component_id = 'devfactory-core'")
        assert row["status"] == "passing"
        assert row["pinned_commit"].startswith("3a01ab9")
