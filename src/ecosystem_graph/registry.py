"""Repository Registry (#8) — สะพานระหว่าง ecosystem.yaml กับ GitHub ของจริง

ตอบสองคำถามที่ตอบไม่ได้ถ้าไม่มีทะเบียน

    repo ที่เราประกาศไว้ ยังมีอยู่จริงไหม
    repo ที่มีอยู่จริง เราลืมประกาศตัวไหนบ้าง

ข้อสองสำคัญกว่าที่คิด — repo ที่ไม่มีใครประกาศคือ component ที่ไม่มีเจ้าของ
ซึ่งเป็นจุดที่ ecosystem เริ่มเพี้ยนโดยไม่มีใครรู้
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from .db import fetch_all

DEFAULT_OWNER = "monthop-gmail"


def entries(conn) -> list[dict]:
    """ทะเบียน — repo ผูกกับ component และทีมเจ้าของ"""
    return fetch_all(conn, """
        SELECT r.id, r.url, r.visibility, r.default_branch, r.does_exist, r.manifest,
               COALESCE(array_agg(c.id ORDER BY c.id)
                        FILTER (WHERE c.id IS NOT NULL), '{}') AS components,
               COALESCE(array_agg(DISTINCT c.owner)
                        FILTER (WHERE c.owner IS NOT NULL), '{}') AS teams
          FROM repositories r
          LEFT JOIN components c ON c.repository = r.id
         GROUP BY r.id
         ORDER BY r.does_exist DESC, r.id
    """)


def _gh_json(args: list[str]) -> Any:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def github_repos(owner: str = DEFAULT_OWNER, limit: int = 200) -> dict[str, dict] | None:
    """repo ทั้งหมดของ owner — คืน None ถ้าเรียก gh ไม่ได้ (ออฟไลน์ / ไม่ได้ล็อกอิน)"""
    data = _gh_json(["repo", "list", owner, "--limit", str(limit), "--json",
                     "name,visibility,defaultBranchRef,isArchived,isFork"])
    if data is None:
        return None
    return {
        r["name"]: {
            "visibility": (r.get("visibility") or "").lower(),
            "default_branch": (r.get("defaultBranchRef") or {}).get("name"),
            "archived": r.get("isArchived", False),
            "fork": r.get("isFork", False),
        }
        for r in data
    }


def reconcile(conn, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    """เทียบทะเบียนกับ GitHub จริง

    drift  = ปัญหาที่ต้องแก้
    unregistered = repo ที่มีอยู่จริงแต่ไม่อยู่ในทะเบียน (ข้อมูล ไม่ใช่ error —
                   ไม่ใช่ทุก repo ในบัญชีเป็นส่วนหนึ่งของ ecosystem นี้)
    """
    actual = github_repos(owner)
    if actual is None:
        return {"available": False, "reason": "เรียก gh ไม่ได้ — ยังไม่ได้ล็อกอินหรือออฟไลน์"}

    declared = {r["id"]: r for r in entries(conn)}
    drift: list[dict] = []

    for rid, row in declared.items():
        on_gh = actual.get(rid)
        if row["does_exist"] and on_gh is None:
            drift.append({"repository": rid, "kind": "missing",
                          "detail": "ประกาศว่ามีอยู่ แต่หาไม่เจอบน GitHub"})
        elif not row["does_exist"] and on_gh is not None:
            drift.append({"repository": rid, "kind": "now-exists",
                          "detail": "ประกาศว่ายังไม่มี แต่เกิดขึ้นแล้ว — อัปเดต ecosystem.yaml"})
        elif on_gh is not None:
            if row["default_branch"] and on_gh["default_branch"] != row["default_branch"]:
                drift.append({"repository": rid, "kind": "branch-mismatch",
                              "detail": f"{row['default_branch']} → {on_gh['default_branch']}"})
            if row["visibility"] and row["visibility"] != "unknown" \
                    and on_gh["visibility"] != row["visibility"]:
                drift.append({"repository": rid, "kind": "visibility-mismatch",
                              "detail": f"{row['visibility']} → {on_gh['visibility']}"})
            if on_gh["archived"]:
                drift.append({"repository": rid, "kind": "archived",
                              "detail": "ถูก archive บน GitHub แล้ว"})

    unregistered = sorted(name for name, meta in actual.items()
                          if name not in declared and not meta["fork"] and not meta["archived"])

    orphan_repos = sorted(rid for rid, row in declared.items() if not row["components"])

    return {
        "available": True,
        "owner": owner,
        "declared": len(declared),
        "on_github": len(actual),
        "drift": drift,
        "unregistered": unregistered,
        "repositories_without_component": orphan_repos,
    }


def main(argv: list[str] | None = None) -> int:
    import sys

    from .db import connect

    args = list(argv if argv is not None else sys.argv[1:])
    show_all = "--all" in args
    positional = [a for a in args if not a.startswith("--")]
    owner = positional[0] if positional else DEFAULT_OWNER
    with connect(readonly=True) as conn:
        rows = entries(conn)
        report = reconcile(conn, owner)

    print(f"ทะเบียน {len(rows)} repo\n")
    for r in rows:
        mark = "✓" if r["does_exist"] else "·"
        comps = ", ".join(r["components"]) or "— ยังไม่มี component"
        print(f"  {mark} {r['id']:<24} {comps}")

    if not report["available"]:
        print(f"\n⚠️  ข้ามการเทียบกับ GitHub: {report['reason']}")
        return 0

    print(f"\nเทียบกับ GitHub ({report['on_github']} repo ในบัญชี {report['owner']})")
    if report["drift"]:
        for d in report["drift"]:
            print(f"  ✗ {d['repository']}: {d['kind']} — {d['detail']}")
    else:
        print("  ✓ ตรงกันทั้งหมด")

    if report["repositories_without_component"]:
        print("\n  ทะเบียนที่ยังไม่มี component ผูกอยู่: "
              + ", ".join(report["repositories_without_component"]))
    if report["unregistered"]:
        names = report["unregistered"]
        shown = names if show_all else names[:12]
        print(f"\n  repo ในบัญชีที่ไม่อยู่ในทะเบียน: {len(names)} ตัว")
        print("    " + ", ".join(shown) + ("" if show_all or len(names) <= 12
                                           else f", … อีก {len(names) - 12} (--all เพื่อดูครบ)"))
        print("    บัญชีนี้มี repo เยอะและส่วนใหญ่ไม่เกี่ยวกับ ecosystem นี้ "
              "— ทะเบียนรับเฉพาะ repo ที่มี component")

    return 1 if report["drift"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
