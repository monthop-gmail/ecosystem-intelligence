"""GitHub Intelligence (#14 #15 #16 #17)

ข้อมูลจริงจาก GitHub มีหรือไม่มีก็ได้ — เทสต์กลุ่มนี้ใส่ข้อมูลสังเคราะห์เอง
เพราะต้องพิสูจน์กลไก (เช่น การจับงานซ้ำข้ามทีม) ที่ ecosystem จริงยังไม่มีเคสให้
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ecosystem_graph.db import connect, fetch_all
from ecosystem_graph.github import work as gh_work
from ecosystem_graph.github.client import GitHubClient

from .conftest import requires_db

pytestmark = requires_db

FAKE_BASE = 900_000  # เลข issue/PR ปลอม — สูงพอไม่ชนของจริง


def _iso(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


@pytest.fixture
def synthetic(loaded_db):
    """ใส่งานปลอมแล้วเก็บกวาดให้หมด — ไม่ทิ้งขยะไว้ให้เทสต์อื่น"""
    rows = []
    with connect() as c:
        def add_issue(repo, n, title, *, state="open", assignees=(), days=1):
            c.execute("""INSERT INTO issues (repository, number, title, state, author,
                                             assignees, labels, updated_at, url)
                         VALUES (%s,%s,%s,%s,'tester',%s,'{}',%s,'http://x')""",
                      (repo, FAKE_BASE + n, title, state, list(assignees), _iso(days)))
            rows.append(("issues", repo, FAKE_BASE + n))

        def add_pr(repo, n, title, *, state="open", days=1, files=()):
            c.execute("""INSERT INTO pull_requests (repository, number, title, state,
                                                    author, updated_at, url)
                         VALUES (%s,%s,%s,%s,'tester',%s,'http://x')""",
                      (repo, FAKE_BASE + n, title, state, _iso(days)))
            rows.append(("pull_requests", repo, FAKE_BASE + n))
            for path in files:
                c.execute("""INSERT INTO pr_files (repository, number, path, status, changes)
                             VALUES (%s,%s,%s,'modified',1)""", (repo, FAKE_BASE + n, path))

        yield type("Fixtures", (), {"issue": staticmethod(add_issue),
                                    "pr": staticmethod(add_pr), "conn": c})()
        for table, repo, n in rows:
            c.execute(f"DELETE FROM {table} WHERE repository = %s AND number = %s", (repo, n))
        c.execute("DELETE FROM pr_files WHERE number >= %s", (FAKE_BASE,))
        c.commit()


# ── #17 การจัดประเภทงาน ────────────────────────────────────────────────
def test_pr_เปิดอยู่คือกำลังทำจริง(synthetic):
    synthetic.pr("devfactory-core", 1, "refactor job state machine", days=2)
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 1)
    assert item["state"] == "in-progress" and item["confidence"] == "high"


def test_issue_ที่มีคนรับและขยับล่าสุดคือกำลังทำจริง(synthetic):
    synthetic.issue("devfactory-core", 2, "add retry semantics",
                    assignees=["someone"], days=3)
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 2)
    assert item["state"] == "in-progress" and item["confidence"] == "high"


def test_issue_ไม่มีคนรับและเงียบนานคือแค่ประกาศไว้(synthetic):
    synthetic.issue("devfactory-core", 3, "someday idea", days=200)
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 3)
    assert item["state"] == "declared" and item["confidence"] == "low"


def test_issue_ปิดแล้วไม่ถูกนับ(synthetic):
    synthetic.issue("devfactory-core", 4, "done already", state="closed")
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        assert not [w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 4]


# ── #17 งานเกี่ยวกับ entity ตัวไหน ─────────────────────────────────────
def test_งานใน_repo_ไหนก็เกี่ยวกับ_component_นั้น(synthetic):
    synthetic.issue("devfactory-core", 5, "หัวข้อที่ไม่เอ่ยชื่ออะไรเลย")
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 5)
    assert "devfactory-core" in item["about"]


def test_จับ_contract_จากไฟล์ที่_PR_แตะ(synthetic):
    synthetic.pr("agent-platform", 6, "หัวข้อไม่ได้บอกว่าแตะ contract ไหน",
                 files=["contracts/execution/v1/execution.schema.yaml", "README.md"])
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 6)
    assert "execution/v1" in item["about"], "ไฟล์แม่นกว่าหัวข้อ — ต้องอ่านจากไฟล์ด้วย"


def test_ไม่แมตช์ชื่อที่เป็นแค่ส่วนหนึ่งของคำอื่น(synthetic):
    synthetic.issue("ai-web-harness", 7, "work on agent-platform-experimental only")
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        item = next(w for w in gh_work.current_work(c) if w["number"] == FAKE_BASE + 7)
    assert "agent-platform" not in item["about"]


# ── #17 งานซ้ำข้ามทีม ──────────────────────────────────────────────────
def test_จับงานซ้ำข้ามทีมได้(synthetic):
    """สองทีมเปิด PR แตะ execution/v1 พร้อมกัน — ต้องเตือน"""
    synthetic.pr("devfactory-core", 10, "rework execution/v1 handling",
                 files=["contracts/execution/v1/execution.schema.yaml"])
    synthetic.pr("enterprise-knowledge", 11, "adopt execution/v1",
                 files=["contracts/execution/v1/execution.schema.yaml"])
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        risks = [r for r in gh_work.duplicate_risk(c) if r["entity"] == "execution/v1"]
    assert len(risks) == 1
    assert set(risks[0]["teams"]) == {"delivery-team", "knowledge-team"}


def test_งานที่แค่ประกาศไว้ไม่นับเป็นงานซ้ำ(synthetic):
    """issue เก่าไม่มีคนรับ ไม่ใช่ความเสี่ยงเรื่องทำซ้ำ — ไม่งั้นคำเตือนจะกลายเป็นเสียงรบกวน"""
    synthetic.issue("devfactory-core", 12, "maybe touch identity/v1 someday", days=300)
    synthetic.issue("enterprise-knowledge", 13, "maybe touch identity/v1 too", days=300)
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        assert not [r for r in gh_work.duplicate_risk(c) if r["entity"] == "identity/v1"]


# ── #16 PR ที่แตะ contract ─────────────────────────────────────────────
def test_จำแนกชนิดไฟล์ที่_PR_แตะ(synthetic):
    synthetic.pr("devfactory-core", 20, "update manifest and rfc",
                 files=["platform-contract.yaml", "rfcs/0009-something.md", "src/x.py"])
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        rows = [r for r in gh_work.contract_prs(c) if r["number"] == FAKE_BASE + 20]
    assert rows and set(rows[0]["kinds"]) == {"consumer-manifest", "rfc"}
    assert "src/x.py" not in rows[0]["paths"], "ไฟล์ที่ไม่เกี่ยวต้องไม่ถูกนับ"


def test_กรอง_PR_ตาม_contract_ที่ระบุ(synthetic):
    synthetic.pr("agent-platform", 21, "touch identity",
                 files=["contracts/identity/v1/identity.schema.yaml"])
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        assert any(r["number"] == FAKE_BASE + 21 for r in gh_work.contract_prs(c, "identity/v1"))
        assert not any(r["number"] == FAKE_BASE + 21
                       for r in gh_work.contract_prs(c, "execution/v1"))


# ── #14 sync state ─────────────────────────────────────────────────────
def test_repository_activity_ผูกกลับไปหา_component(conn):
    rows = gh_work.repository_activity(conn)
    if not rows:
        pytest.skip("ยังไม่เคย sync — รัน make sync ก่อน")
    known = {r["repository"]: r for r in rows}
    if "devfactory-core" in known:
        assert known["devfactory-core"]["team"] == "delivery-team"


def test_advisor_ใช้งานจริงเตือนงานซ้ำ(synthetic):
    """#17 ข้อสุดท้าย — Team Advisor ต้องเอาข้อมูลนี้ไปเตือนได้"""
    from ecosystem_graph import advisor

    synthetic.pr("devfactory-core", 30, "rework enterprise-knowledge integration",
                 files=["src/x.py"])
    synthetic.conn.commit()
    with connect(readonly=True) as c:
        result = advisor.ask(c, "knowledge-team", "ทีมเราควรทำอะไรต่อ?")
    risks = " ".join(result["answer"]["risks"])
    assert "delivery-team" in risks and "enterprise-knowledge" in risks, \
        f"ไม่ได้เตือนงานซ้ำ: {risks}"
    assert result["grounding"]["ok"]


# ── client ─────────────────────────────────────────────────────────────
def test_client_นับจำนวน_call_เอง():
    """rate_limit ของ GitHub ไม่ขยับทันที — ตัวเลขที่รายงานต้องนับเอง"""
    c = GitHubClient()
    assert c.calls == 0


def test_404_กับต่อไม่ติดต้องแยกกัน():
    """404 = "ไม่มีอยู่จริง" ซึ่งเป็นคำตอบ · ต่อไม่ติด = "ตอบไม่ได้" ซึ่งไม่ใช่คำตอบ

    ปนกันเมื่อไหร่ รายงานจะบอกว่า repo ที่ตั้งใจไม่ให้มี "ตรวจไม่ได้"
    ซึ่งกลบสัญญาณจริงจนหมด — เจอกับตัวตอนรัน feedback ครั้งแรก
    """
    from ecosystem_graph.github.client import GitHubError

    missing = GitHubError("gh: Not Found (HTTP 404)", status=404)
    offline = GitHubError("dial tcp: lookup api.github.com: no such host")
    assert missing.not_found is True
    assert offline.not_found is False


def test_client_อ่าน_status_จากข้อความของ_gh(monkeypatch):
    from ecosystem_graph.github import client as mod

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "gh: Not Found (HTTP 404)"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: FakeProc())
    c = mod.GitHubClient()
    with pytest.raises(mod.GitHubError) as e:
        c.api("repos/x/y")
    assert e.value.status == 404 and e.value.not_found
