"""ผลลัพธ์การ deliver ย้อนกลับมาอัปเดต ecosystem state (#25)

วงจรปิดของ ecosystem นี้ไม่ได้เกิดจากการที่ระบบเขียนสถานะของตัวเองทับ
แต่เกิดจากการ **เทียบสิ่งที่ตั้งใจกับสิ่งที่เกิดขึ้นจริง แล้วเสนอส่วนต่าง**

    ecosystem.yaml   สิ่งที่เราตั้งใจ    ← คนดูแล
    GitHub + manifest  สิ่งที่เกิดขึ้นจริง  ← ระบบอ่าน
    feedback           ส่วนต่าง            ← ระบบเสนอ คนตัดสิน

**ไม่มี --apply โดยตั้งใจ** — ecosystem.yaml เป็นแหล่งความจริงที่คนดูแล
ระบบที่แก้แหล่งความจริงของตัวเองได้ จะไม่มีใครรู้ว่าอะไรคือของจริง
"""
from __future__ import annotations

import base64
from typing import Any

import yaml

from ..db import fetch_all
from ..github.client import GitHubClient, GitHubError


def _manifest_of(gh: GitHubClient, repo: str, path: str = "platform-contract.yaml"):
    try:
        blob = gh.api(f"repos/{gh.owner}/{repo}/contents/{path}")
        return yaml.safe_load(base64.b64decode(blob["content"]).decode("utf-8")) or {}
    except (GitHubError, Exception):  # noqa: BLE001 — ไม่มี manifest เป็นเรื่องปกติ
        return None


def proposals(conn, *, gh: GitHubClient | None = None) -> list[dict[str, Any]]:
    gh = gh or GitHubClient()
    out: list[dict[str, Any]] = []
    unreachable: list[str] = []

    repos = fetch_all(conn, """
        SELECT r.id, r.does_exist, r.manifest, r.default_branch, r.visibility,
               c.id AS component, c.status, c.owner,
               cf.manifest AS conf_manifest, cf.status AS conf_status,
               cf.last_verified,
               COALESCE((SELECT array_agg(contract_id ORDER BY contract_id)
                           FROM component_contracts
                          WHERE component_id = c.id AND relation = 'consumes'), '{}') AS consumes
          FROM repositories r
          LEFT JOIN components c ON c.repository = r.id
          LEFT JOIN conformance cf ON cf.component_id = c.id
         ORDER BY r.id
    """)
    activity = {a["repository"]: a for a in fetch_all(conn, "SELECT * FROM repo_sync_state")}

    for r in repos:
        seen = activity.get(r["id"])

        # 1. repo ที่เคยบอกว่ายังไม่มี แต่เกิดขึ้นแล้ว
        if not r["does_exist"]:
            try:
                gh.api(f"repos/{gh.owner}/{r['id']}")
            except GitHubError as e:
                if not e.not_found:      # ต่อไม่ติด = ตอบไม่ได้ ต้องบอก
                    unreachable.append(r["id"])
                continue                 # 404 = ยังไม่มีจริง ตรงกับที่ประกาศไว้ ไม่ใช่ปัญหา
            except Exception:  # noqa: BLE001
                unreachable.append(r["id"])
                continue
            out.append({
                "kind": "repo-now-exists", "subject": r["id"],
                "detail": f"ประกาศว่า exists: false แต่ {r['id']} มีอยู่จริงแล้ว",
                "suggest": f"repositories[{r['id']}].exists: true และเติม url/default_branch",
            })
            continue

        # 2. manifest โผล่มาแล้วแต่ ecosystem.yaml ยังไม่รู้
        actual = _manifest_of(gh, r["id"])
        if actual is None:
            if r["manifest"]:
                out.append({
                    "kind": "manifest-gone", "subject": r["id"],
                    "detail": f"ecosystem.yaml บอกว่ามี {r['manifest']} แต่หาไม่เจอใน repo",
                    "suggest": f"repositories[{r['id']}].manifest: null และย้าย consumes ไป expected_contracts",
                })
            continue

        if not r["manifest"]:
            out.append({
                "kind": "manifest-appeared", "subject": r["id"],
                "detail": f"{r['id']} มี platform-contract.yaml แล้ว "
                          f"(pin {', '.join(actual.get('contracts') or []) or 'ยังไม่ระบุ'})",
                "suggest": f"repositories[{r['id']}].manifest: platform-contract.yaml "
                           f"และย้าย expected_contracts ที่ตรงกันไป consumes",
            })
            continue

        # 3. pin เปลี่ยน
        declared, real = sorted(r["consumes"] or []), sorted(actual.get("contracts") or [])
        if declared != real:
            out.append({
                "kind": "pins-changed", "subject": r["component"] or r["id"],
                "detail": f"manifest pin {', '.join(real) or '—'} "
                          f"แต่ ecosystem.yaml เขียน {', '.join(declared) or '—'}",
                "suggest": f"components[{r['component']}].consumes: [{', '.join(real)}]",
            })

        # 4. conformance ถูกตรวจใหม่แล้ว
        conf = (actual.get("conformance") or {})
        upstream_date = str(conf.get("last_verified") or "")
        ours = str(r["last_verified"] or "")
        if upstream_date and ours and upstream_date > ours:
            out.append({
                "kind": "conformance-newer", "subject": r["component"] or r["id"],
                "detail": f"manifest บอกว่าตรวจล่าสุด {upstream_date} "
                          f"แต่ ecosystem.yaml ยัง {ours}",
                "suggest": f"components[{r['component']}].conformance.last_verified: {upstream_date}",
            })
        if conf.get("status") and r["conf_status"] and conf["status"] != r["conf_status"]:
            out.append({
                "kind": "conformance-status-differs", "subject": r["component"] or r["id"],
                "detail": f"manifest บอก {conf['status']} แต่ ecosystem.yaml เขียน {r['conf_status']}",
                "suggest": f"components[{r['component']}].conformance.status: {conf['status']}",
            })

        # 5. component ที่ยังเขียนว่า planned ทั้งที่ repo ขยับอยู่
        if r["status"] == "planned" and seen and seen["pushed_at"]:
            out.append({
                "kind": "planned-but-active", "subject": r["component"],
                "detail": f"status: planned แต่ {r['id']} มี push ล่าสุดแล้ว",
                "suggest": f"components[{r['component']}].status: in-development",
            })

    if unreachable:
        out.append({
            "kind": "github-unreachable", "subject": ", ".join(unreachable[:5]),
            "detail": f"ตรวจ {len(unreachable)} repo กับ GitHub ไม่ได้ "
                      f"— ผลที่รายงานจึงไม่ครบ",
            "suggest": "ตรวจ gh auth status แล้วรันใหม่",
        })
    return out


def main(argv: list[str] | None = None) -> int:
    import sys

    from ..db import connect

    with connect(readonly=True) as conn:
        items = proposals(conn)

    if not items:
        print("✅ ecosystem.yaml ตรงกับสิ่งที่เกิดขึ้นจริงทั้งหมด — ไม่มีอะไรต้องอัปเดต")
        return 0

    print(f"เสนอให้อัปเดต {len(items)} รายการ "
          f"(ระบบไม่แก้ ecosystem.yaml ให้ — คนตัดสิน)\n")
    for p in items:
        print(f"  [{p['kind']}] {p['subject']}")
        print(f"      {p['detail']}")
        print(f"      → {p['suggest']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
