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
        # เทียบกับ ecosystem.yaml ไม่ใช่กับ SHA ที่ฝังไว้ — ทีมอื่น re-pin เมื่อไหร่
        # เทสต์ที่ฝังค่าจะแดงทั้งที่ไม่มีอะไรผิด (เกิดขึ้นแล้วเมื่อ 17 ก.ย.)
        want = next(x for x in doc["components"] if x["id"] == "devfactory-core")
        assert row["pinned_commit"] == want["conformance"]["pinned_commit"]


def test_แก้เนื้อในแถวต้องถูกรายงาน_ไม่ใช่เงียบ(loaded_db, tmp_path):
    """ตัวนับส่วนต่างเดิมถ่ายภาพแค่ id ของแถว ไม่ได้ถ่ายเนื้อในแถว

    ผลคือ 22 ก.ย. ตอน re-pin ไป event/v1 v1.8.1 · import เขียน pin ใหม่ลง DB
    สำเร็จ แล้วพิมพ์ว่า "ไม่มีส่วนต่าง" · ข้อมูลลงถูก แต่รายงานบอกว่าไม่ได้ลง

    อันตรายเพราะบรรทัดนั้นคือสิ่งเดียวที่คนอ่านเพื่อยืนยันว่าที่แก้ไปมีผล
    ถ้าแก้ผิดบรรทัดก็เงียบเหมือนกันทุกประการ
    """
    doc, _ = load()
    ours = next(c for c in doc["components"] if c["id"] == "ecosystem-intelligence")
    ours["conformance"]["pinned_commit"] = "0" * 40
    ours["conformance"]["last_verified"] = "2026-01-01"
    path = tmp_path / "ecosystem.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    changes = run(path, dry_run=True)["changes"]
    text = "\n".join(changes)
    assert "pinned_commit" in text, f"pin เปลี่ยนแต่ไม่ถูกรายงาน — {changes}"
    assert "last_verified" in text, f"วันที่เปลี่ยนแต่ไม่ถูกรายงาน — {changes}"
    assert "ecosystem-intelligence" in text, "ต้องบอกด้วยว่าแถวไหน"


def test_เปลี่ยนเจ้าของ_component_ต้องถูกรายงาน(loaded_db, tmp_path):
    """ไม่ใช่แค่ conformance — ทุก field ที่ตัดสินใจไว้ต้องมองเห็น"""
    doc, _ = load()
    ours = next(c for c in doc["components"] if c["id"] == "botforge")
    ours["owner"] = "delivery-team"
    path = tmp_path / "ecosystem.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    text = "\n".join(run(path, dry_run=True)["changes"])
    assert "owner" in text and "platform-team → delivery-team" in text, text


def test_dry_run_ที่มีส่วนต่างต้องไม่เขียนจริง(loaded_db, tmp_path):
    """ตอนนี้ dry-run เขียนลง transaction แล้ว rollback — ต้องพิสูจน์ว่า rollback จริง"""
    doc, _ = load()
    next(c for c in doc["components"] if c["id"] == "botforge")["owner"] = "delivery-team"
    path = tmp_path / "ecosystem.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert run(path, dry_run=True)["changes"], "ต้องเห็นส่วนต่างก่อน ไม่งั้นเทสต์นี้ไม่ได้ตรวจอะไร"
    with connect() as c:
        owner = fetch_one(c, "SELECT owner FROM components WHERE id = 'botforge'")["owner"]
    assert owner == "platform-team", "dry-run เขียนจริงลง DB"
