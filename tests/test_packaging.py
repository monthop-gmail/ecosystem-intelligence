"""บั๊กที่โผล่เฉพาะตอน pip install จริง — ไม่ใช่ตอนรันจาก src/

เทสต์กลุ่มนี้เกิดจากการ containerize แล้วเจอว่า path ของไฟล์ข้อมูลคำนวณผิด
และที่แย่กว่านั้นคือ migrate **รายงานว่าสำเร็จ** ทั้งที่ไม่ได้ทำอะไรเลย
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_root_ชี้ไปที่โฟลเดอร์ที่มี_ecosystem_yaml():
    from ecosystem_graph.config import ROOT
    assert (ROOT / "ecosystem.yaml").exists(), f"ROOT ผิด: {ROOT}"
    assert (ROOT / "migrations").is_dir()
    assert (ROOT / "schema" / "ecosystem.schema.json").exists()


def test_env_ที่ตั้งไว้ชนะการเดาจาก_layout(monkeypatch, tmp_path):
    (tmp_path / "ecosystem.yaml").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ECOSYSTEM_ROOT", str(tmp_path))
    import ecosystem_graph.config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.ROOT == tmp_path.resolve()
    finally:
        monkeypatch.delenv("ECOSYSTEM_ROOT")
        importlib.reload(cfg)


def test_validate_ใช้_ROOT_ตัวเดียวกับ_config():
    from ecosystem_graph import validate
    from ecosystem_graph.config import ROOT
    assert validate.ROOT == ROOT, "สอง ROOT ที่คำนวณคนละทางจะเพี้ยนคนละแบบตอน deploy"


def test_ไม่มีไฟล์_migration_ต้องพัง_ไม่ใช่บอกว่าไม่มีอะไรใหม่(monkeypatch, tmp_path):
    """นี่คือบั๊กตัวจริง — glob ว่างแล้วรายงานสำเร็จ ทำให้ app พังทีหลังในที่ที่หาสาเหตุยาก"""
    from ecosystem_graph import migrate
    monkeypatch.setattr(migrate, "MIGRATIONS", tmp_path)
    with pytest.raises(SystemExit, match="ไม่มีไฟล์ .sql"):
        migrate._files()


def test_โฟลเดอร์_migration_ที่ไม่มีอยู่ก็ต้องพัง(monkeypatch, tmp_path):
    from ecosystem_graph import migrate
    monkeypatch.setattr(migrate, "MIGRATIONS", tmp_path / "ไม่มีจริง")
    with pytest.raises(SystemExit, match="ไม่มีโฟลเดอร์ migration"):
        migrate._files()


def test_ไฟล์ที่_image_ต้องใช้ถูก_copy_ครบ():
    """ทุก path ที่โค้ดอ่านตอน runtime ต้องอยู่ใน Dockerfile — ลืมตัวไหนคือพังตอน deploy"""
    from ecosystem_graph.config import ROOT
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for needed in ("ecosystem.yaml", "guardian.yaml", "schema", "migrations", "evaluation"):
        assert needed in dockerfile, f"Dockerfile ไม่ได้ copy {needed}"


def test_rules_yaml_มากับแพ็กเกจไม่ใช่จาก_ROOT():
    """rules.yaml เป็น package data — ต้องอยู่ข้างโมดูล ไม่ใช่อ้างจาก ROOT"""
    from ecosystem_graph.guardian import checks
    assert checks.RULES_PATH.parent.name == "guardian"
    assert checks.RULES_PATH.exists()
    assert checks.load_rules()
