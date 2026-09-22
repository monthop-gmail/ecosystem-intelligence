"""registry — เทียบทะเบียนกับ GitHub จริง

ไฟล์นี้เกิดหลังจาก registry พังมาแล้วสองครั้งโดยไม่มีเทสต์จับ
  · ดึง repo ได้แค่ 200 จาก 229 แล้วพิมพ์ "200 repo ในบัญชี" เหมือนเป็นจำนวนจริง
  · หา manifest เฉพาะ branch หลัก ทั้งที่ของ botforge อยู่ branch v2
ทั้งสองครั้งเป็นรูปเดียวกัน — **ตรวจไม่ได้ แต่พิมพ์ออกมาเหมือนตรวจแล้วไม่พบ**
"""
from __future__ import annotations

import pytest

from ecosystem_graph import registry

from .conftest import requires_db

pytestmark = requires_db


def _actual(*, private: bool) -> dict[str, dict]:
    """ภาพที่ได้จาก GitHub — สลับได้ว่า token เห็น private ไหม"""
    repos = {
        "agent-platform": "public", "devfactory-core": "public",
        "care-agent-platform": "public", "enterprise-knowledge": "public",
        "ai-web-harness": "public", "navi-ims": "public",
        "ecosystem-intelligence": "public", "botforge": "public",
        "agent-builder-dsh-poc": "public",
    }
    if private:
        repos["internal-mcp-gateway"] = "private"
    return {n: {"visibility": v, "default_branch": "main",
                "archived": False, "fork": False} for n, v in repos.items()}


@pytest.fixture
def no_candidates(monkeypatch):
    monkeypatch.setattr(registry, "_candidates", lambda *a, **k: [])
    monkeypatch.setattr(registry, "GitHubClient", lambda *a, **k: object())


def test_token_ที่เห็น_private_บอกสัดส่วนตามจริง(conn, loaded_db, no_candidates, monkeypatch):
    monkeypatch.setattr(registry, "github_repos", lambda owner=None, **k: _actual(private=True))
    r = registry.reconcile(conn)
    assert r["sees_private"] is True
    assert r["visibility_counts"]["private"] == 1


def test_สมาชิกที่หาไม่เจอด้วย_token_public_ต้องไม่ถูกตัดสินว่าหาย(conn, loaded_db,
                                                                no_candidates, monkeypatch):
    """GITHUB_TOKEN ของ Actions เห็นเฉพาะ repo ตัวเองกับ public

    บัญชีนี้มี private เกินร้อย และเคยเปลี่ยน repo 21 ตัวเป็น private ในรอบเดียว
    ถ้ารันด้วย token แบบนั้น สมาชิกที่เป็น private จะถูกรายงานว่าหายไปทุกวัน
    """
    partial = _actual(private=False)
    partial.pop("care-agent-platform")        # สมมติว่าเขาเปลี่ยนเป็น private
    monkeypatch.setattr(registry, "github_repos", lambda owner=None, **k: partial)

    r = registry.reconcile(conn)
    assert r["sees_private"] is False
    kinds = {d["repository"]: d["kind"] for d in r["drift"]}
    assert kinds.get("care-agent-platform") == "unverifiable", kinds
    detail = next(d["detail"] for d in r["drift"] if d["repository"] == "care-agent-platform")
    assert "public" in detail, "ต้องบอกสาเหตุ ไม่ใช่แค่เปลี่ยนป้าย"


def test_token_ที่เห็น_private_แล้วยังหาไม่เจอ_คือหายจริง(conn, loaded_db,
                                                        no_candidates, monkeypatch):
    """ถ้าไม่แยกสองกรณีนี้ การเปลี่ยนป้ายจะกลายเป็นการกลบ drift จริง"""
    partial = _actual(private=True)
    partial.pop("care-agent-platform")
    monkeypatch.setattr(registry, "github_repos", lambda owner=None, **k: partial)

    kinds = {d["repository"]: d["kind"] for d in registry.reconcile(conn)["drift"]}
    assert kinds.get("care-agent-platform") == "missing", kinds


def test_เรียก_gh_ไม่ได้ต้องบอก_ไม่ใช่รายงานว่าไม่มีอะไรผิด(conn, loaded_db, monkeypatch):
    monkeypatch.setattr(registry, "github_repos", lambda owner=None, **k: None)
    r = registry.reconcile(conn)
    assert r["available"] is False
    assert r["reason"]
