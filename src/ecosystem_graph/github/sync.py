"""ดึงสถานะจริงจาก GitHub เข้า Ecosystem Graph (#14 #15 #16)

หลักที่ทั้งสามงานยึดร่วมกัน

    ล้มบางส่วนไม่ทำให้ทั้งรอบพัง   แต่ละ repo อยู่ใน try ของตัวเอง บันทึกผลราย repo
    incremental                    ใช้ since จาก last_synced_at · PR กรองด้วย updated_at
    เคารพ rate limit               ตรวจก่อนเริ่ม และหยุดถ้าเหลือน้อยเกินไป
    upsert ไม่ใช่ลบแล้วเขียนใหม่    ข้อมูลเก่ายังอยู่ถ้ารอบนี้ล้ม
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import connect, fetch_all, fetch_one
from .client import GitHubClient, GitHubError

MIN_RATE_REMAINING = 200      # ต่ำกว่านี้ไม่เริ่ม — กันไปแย่งโควตางานอื่น
PR_FILE_WINDOW_DAYS = 120     # ดึงรายการไฟล์เฉพาะ PR ที่ยังสด — คุมจำนวน API call
FIRST_SYNC_LOOKBACK_DAYS = 365


def _repos_to_sync(conn) -> list[str]:
    """เฉพาะ repo ที่ ecosystem.yaml บอกว่ามีอยู่จริง"""
    return [r["id"] for r in fetch_all(
        conn, "SELECT id FROM repositories WHERE does_exist ORDER BY id")]


def _since_for(conn, repo: str) -> str:
    row = fetch_one(conn, "SELECT last_synced_at FROM repo_sync_state WHERE repository = %s",
                    (repo,))
    if row and row["last_synced_at"]:
        return row["last_synced_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    start = datetime.now(timezone.utc) - timedelta(days=FIRST_SYNC_LOOKBACK_DAYS)
    return start.isoformat().replace("+00:00", "Z")


def _sync_repo_meta(conn, gh: GitHubClient, repo: str) -> None:
    meta = gh.repo(repo)
    commit = gh.latest_commit(repo, meta["default_branch"]) or {}
    author = (commit.get("commit") or {}).get("author") or {}
    conn.execute("""
        INSERT INTO repo_sync_state
            (repository, default_branch, pushed_at, last_commit_sha, last_commit_at,
             open_issues, visibility, archived)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (repository) DO UPDATE SET
            default_branch = EXCLUDED.default_branch,
            pushed_at = EXCLUDED.pushed_at,
            last_commit_sha = EXCLUDED.last_commit_sha,
            last_commit_at = EXCLUDED.last_commit_at,
            open_issues = EXCLUDED.open_issues,
            visibility = EXCLUDED.visibility,
            archived = EXCLUDED.archived
    """, (repo, meta["default_branch"], meta.get("pushed_at"), commit.get("sha"),
          author.get("date"), meta.get("open_issues_count"),
          (meta.get("visibility") or "").lower(), meta.get("archived", False)))


def _sync_issues(conn, gh: GitHubClient, repo: str, since: str) -> int:
    n = 0
    for item in gh.issues(repo, since=since):
        if "pull_request" in item:
            continue  # endpoint นี้คืน PR ปนมาด้วย — PR มีตารางของตัวเอง
        conn.execute("""
            INSERT INTO issues (repository, number, title, state, author, assignees,
                                labels, milestone, created_at, updated_at, closed_at, url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (repository, number) DO UPDATE SET
                title = EXCLUDED.title, state = EXCLUDED.state,
                assignees = EXCLUDED.assignees, labels = EXCLUDED.labels,
                milestone = EXCLUDED.milestone, updated_at = EXCLUDED.updated_at,
                closed_at = EXCLUDED.closed_at
        """, (repo, item["number"], item["title"], item["state"],
              (item.get("user") or {}).get("login"),
              [a["login"] for a in item.get("assignees") or []],
              [lbl["name"] for lbl in item.get("labels") or []],
              (item.get("milestone") or {}).get("title"),
              item.get("created_at"), item.get("updated_at"), item.get("closed_at"),
              item.get("html_url")))
        n += 1
    return n


def _sync_pulls(conn, gh: GitHubClient, repo: str, since: str) -> int:
    cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
    file_cutoff = datetime.now(timezone.utc) - timedelta(days=PR_FILE_WINDOW_DAYS)
    n = 0
    for pr in gh.pulls(repo):
        updated = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
        if updated < cutoff:
            break  # เรียงตาม updated desc — เจอตัวเก่ากว่า cutoff แล้วหยุดได้เลย

        state = "merged" if pr.get("merged_at") else pr["state"]
        conn.execute("""
            INSERT INTO pull_requests (repository, number, title, state, author, draft,
                                       created_at, updated_at, merged_at, closed_at, url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (repository, number) DO UPDATE SET
                title = EXCLUDED.title, state = EXCLUDED.state, draft = EXCLUDED.draft,
                updated_at = EXCLUDED.updated_at, merged_at = EXCLUDED.merged_at,
                closed_at = EXCLUDED.closed_at
        """, (repo, pr["number"], pr["title"], state,
              (pr.get("user") or {}).get("login"), pr.get("draft", False),
              pr.get("created_at"), pr.get("updated_at"), pr.get("merged_at"),
              pr.get("closed_at"), pr.get("html_url")))
        n += 1

        # ไฟล์ของ PR ราคาแพงกว่า (1 call ต่อ PR) — ดึงเฉพาะที่ยังสดและยังไม่เคยดึง
        if updated < file_cutoff:
            continue
        done = fetch_one(conn, "SELECT files_synced FROM pull_requests "
                               "WHERE repository = %s AND number = %s", (repo, pr["number"]))
        if done and done["files_synced"] and state != "open":
            continue
        try:
            files = gh.pull_files(repo, pr["number"])
        except GitHubError:
            continue  # ไฟล์ดึงไม่ได้ ไม่ใช่เหตุให้ทั้ง repo ล้ม
        conn.execute("DELETE FROM pr_files WHERE repository = %s AND number = %s",
                     (repo, pr["number"]))
        for f in files:
            conn.execute("""INSERT INTO pr_files (repository, number, path, status, changes)
                            VALUES (%s,%s,%s,%s,%s)
                            ON CONFLICT DO NOTHING""",
                         (repo, pr["number"], f["filename"], f.get("status"), f.get("changes")))
        conn.execute("UPDATE pull_requests SET files_synced = true "
                     "WHERE repository = %s AND number = %s", (repo, pr["number"]))
    return n


def sync(repos: list[str] | None = None, *, owner: str = "monthop-gmail") -> dict[str, Any]:
    gh = GitHubClient(owner)
    if not gh.available():
        return {"available": False, "reason": "gh ยังไม่ได้ล็อกอิน"}

    rate = gh.rate_limit()
    if rate["remaining"] < MIN_RATE_REMAINING:
        return {"available": False,
                "reason": f"rate limit เหลือ {rate['remaining']} — ต่ำกว่าเกณฑ์ {MIN_RATE_REMAINING}"}

    results: list[dict[str, Any]] = []
    with connect() as conn:
        targets = repos or _repos_to_sync(conn)
        for repo in targets:
            since = _since_for(conn, repo)
            started = datetime.now(timezone.utc)
            try:
                _sync_repo_meta(conn, gh, repo)
                n_issues = _sync_issues(conn, gh, repo, since)
                n_prs = _sync_pulls(conn, gh, repo, since)
                conn.execute("""UPDATE repo_sync_state
                                   SET last_synced_at = %s, last_ok = true, last_error = NULL
                                 WHERE repository = %s""", (started, repo))
                conn.commit()
                results.append({"repository": repo, "ok": True,
                                "issues": n_issues, "pull_requests": n_prs})
            except (GitHubError, Exception) as e:  # noqa: BLE001 — ล้มหนึ่ง repo ต้องไม่ล้มทั้งรอบ
                conn.rollback()
                conn.execute("""INSERT INTO repo_sync_state (repository, last_ok, last_error)
                                VALUES (%s, false, %s)
                                ON CONFLICT (repository) DO UPDATE
                                   SET last_ok = false, last_error = EXCLUDED.last_error""",
                             (repo, str(e)[:500]))
                conn.commit()
                results.append({"repository": repo, "ok": False, "error": str(e)[:200]})

    return {
        "available": True,
        "results": results,
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "api_calls_used": gh.calls,
        "rate_remaining_before": rate["remaining"],
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repos = [a for a in argv if not a.startswith("--")] or None
    report = sync(repos)
    if not report["available"]:
        print(f"⚠️  ข้าม sync: {report['reason']}")
        return 0
    for r in report["results"]:
        if r["ok"]:
            print(f"  ✓ {r['repository']:<24} issues={r['issues']:<4} prs={r['pull_requests']}")
        else:
            print(f"  ✗ {r['repository']:<24} {r['error']}")
    print(f"\n✅ sync: สำเร็จ {report['ok']} · ล้ม {report['failed']} "
          f"· เรียก gh api {report['api_calls_used']} ครั้ง "
          f"(โควตาตอนเริ่ม {report['rate_remaining_before']})")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
