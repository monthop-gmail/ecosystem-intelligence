"""Repository Registry (#8) — สะพานระหว่าง ecosystem.yaml กับ GitHub ของจริง

ตอบสองคำถามที่ตอบไม่ได้ถ้าไม่มีทะเบียน

    repo ที่เราประกาศไว้ ยังมีอยู่จริงไหม
    repo ที่มีอยู่จริง เราลืมประกาศตัวไหนบ้าง

ข้อสองสำคัญกว่าที่คิด — repo ที่ไม่มีใครประกาศคือ component ที่ไม่มีเจ้าของ
ซึ่งเป็นจุดที่ ecosystem เริ่มเพี้ยนโดยไม่มีใครรู้
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from .db import fetch_all
from .github.client import GitHubClient, GitHubError

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


def github_repos(owner: str = DEFAULT_OWNER, limit: int = 1000) -> dict[str, dict] | None:
    """repo ทั้งหมดของ owner — คืน None ถ้าเรียก gh ไม่ได้ (ออฟไลน์ / ไม่ได้ล็อกอิน)

    limit เดิมเป็น 200 ทั้งที่บัญชีนี้มี 229 repo — **ตัดทิ้ง 29 ตัวเงียบ ๆ**
    และรายงานก็พิมพ์ว่า "200 repo ในบัญชี" เหมือนเป็นจำนวนจริง
    ถ้าชนเพดานจะบอก ไม่ใช่ปล่อยให้เข้าใจว่าครบ
    """
    data = _gh_json(["repo", "list", owner, "--limit", str(limit), "--json",
                     "name,visibility,defaultBranchRef,isArchived,isFork"])
    if data is None:
        return None
    if len(data) >= limit:
        print(f"⚠️  ดึง repo ได้ {len(data)} ตัวซึ่งชนเพดาน {limit} — อาจมีมากกว่านี้",
              file=__import__("sys").stderr)
    return {
        r["name"]: {
            "visibility": (r.get("visibility") or "").lower(),
            "default_branch": (r.get("defaultBranchRef") or {}).get("name"),
            "archived": r.get("isArchived", False),
            "fork": r.get("isFork", False),
        }
        for r in data
    }


def _candidates(gh: GitHubClient, conn, actual: dict[str, dict],
                declared: dict[str, Any]) -> list[dict[str, Any]]:
    """repo ที่ไม่อยู่ในทะเบียนเรา **แต่มีหลักฐานว่าเกี่ยวกับ ecosystem นี้**

    เดิมเราทิ้งทุกตัวที่ไม่อยู่ในทะเบียนลงกองเดียวกันแล้วพิมพ์ 12 ชื่อแรก
    บัญชีนี้มี repo 229 ตัว กองนั้นจึงกลบสมาชิกจริงที่ปนอยู่ — `botforge` กับ
    `agent-builder-dsh-poc` conform มาตั้งแต่ ส.ค./ก.ย. โดยที่เราไม่เห็น

    หลักฐานที่รับ ไม่ใช่การเดาจากชื่อหรือคำอธิบาย
      registry  — อยู่ในทะเบียน consumer ของ agent-platform (แหล่งความจริงตาม ADR-0006)
      manifest  — มี platform-contract.yaml ของตัวเอง
      watchlist — เราบันทึกไว้เองว่าเจอที่อื่น พร้อมที่มา
    """
    import base64

    signals: dict[str, list[str]] = {}

    try:
        blob = gh.api(f"repos/{gh.owner}/agent-platform/contents/"
                      f"architecture/consumers.md")
        text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
        for name in set(re.findall(r"\[`([a-z0-9][a-z0-9-]*)`\]\(https://github\.com/"
                                   + re.escape(gh.owner) + r"/", text)):
            signals.setdefault(name, []).append("อยู่ในทะเบียน consumer ของ agent-platform")
    except Exception:  # noqa: BLE001
        pass

    for w in _watchlist():
        signals.setdefault(w["id"], []).append(f"เราบันทึกไว้เอง — {w.get('why', 'ไม่ระบุที่มา')}")

    # ตรวจ manifest เฉพาะตัวที่มีสัญญาณอื่นอยู่แล้ว — 229 repo × 1 call ไม่คุ้ม
    out = []
    for name, why in sorted(signals.items()):
        if name in declared or name not in actual:
            continue
        # manifest ไม่จำเป็นต้องอยู่ branch หลัก — botforge วางไว้ที่ v2
        # ตรวจแค่ default branch แล้วสรุปว่า "ไม่มี" คือการรายงานผิด
        found_on = None
        for ref in (None, "v2", "develop"):
            try:
                path = f"repos/{gh.owner}/{name}/contents/platform-contract.yaml"
                gh.api(path + (f"?ref={ref}" if ref else ""))
                found_on = ref or "branch หลัก"
                break
            except GitHubError:
                continue
        if found_on:
            why = why + [f"มี platform-contract.yaml ({found_on})"]
        out.append({"repository": name, "signals": why})
    return out


def _watchlist() -> list[dict[str, Any]]:
    """ชื่อที่เราได้ยินจากที่อื่น (เช่น โต๊ะ ai-collab) — บันทึกไว้พร้อมที่มา
    จะได้ไม่ต้องไปค้นใหม่ทุกครั้ง"""
    import yaml

    from .config import ROOT

    path = ROOT / "ecosystem.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc.get("watchlist") or []


def reconcile(conn, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    """เทียบทะเบียนกับ GitHub จริง

    drift      = ปัญหาที่ต้องแก้
    candidates = repo ที่มีหลักฐานว่าเกี่ยวกับ ecosystem แต่ยังไม่อยู่ในทะเบียน
    unrelated  = จำนวนที่เหลือ — ไม่ใช่ทุก repo ในบัญชีเป็นส่วนหนึ่งของ ecosystem นี้
    """
    gh = GitHubClient(owner)
    actual = github_repos(owner)
    if actual is None:
        return {"available": False, "reason": "เรียก gh ไม่ได้ — ยังไม่ได้ล็อกอินหรือออฟไลน์"}

    declared = {r["id"]: r for r in entries(conn)}
    drift: list[dict] = []

    # token ที่เห็นแต่ public จะทำให้ repo สมาชิกที่เป็น private อ่านได้ว่า "หาไม่เจอ"
    #
    # GITHUB_TOKEN ของ Actions เห็นเฉพาะ repo ตัวเองกับ public · บัญชีนี้มี private
    # เกินร้อย และเคยเปลี่ยน repo 21 ตัวเป็น private ในรอบเดียวเมื่อ 18 ก.ย.
    # ถ้ารันด้วย token แบบนั้น สมาชิกที่เป็น private จะถูกรายงานว่าหายไปทุกวัน
    # ซึ่งเป็น "ตรวจไม่ได้" ที่พิมพ์ออกมาหน้าตาเหมือน "ตรวจแล้วไม่พบ"
    # (ที่มา: ecosystem-brief ไปเปิด workflow ของเราอ่านแล้วทักมาในโต๊ะกลาง 21 ก.ย.)
    sees_private = any(m["visibility"] == "private" for m in actual.values())

    for rid, row in declared.items():
        on_gh = actual.get(rid)
        if row["does_exist"] and on_gh is None and not sees_private:
            drift.append({"repository": rid, "kind": "unverifiable",
                          "detail": "หาไม่เจอ — แต่ token นี้เห็นแต่ public จึงสรุปไม่ได้ "
                                    "ว่าไม่มีอยู่ หรือมีอยู่แต่เป็น private"})
        elif row["does_exist"] and on_gh is None:
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

    candidates = _candidates(gh, conn, actual, declared)
    visibility_counts: dict[str, int] = {}
    for m in actual.values():
        visibility_counts[m["visibility"] or "unknown"] = \
            visibility_counts.get(m["visibility"] or "unknown", 0) + 1
    cand_names = {c["repository"] for c in candidates}
    unrelated = sorted(name for name, meta in actual.items()
                       if name not in declared and name not in cand_names
                       and not meta["fork"] and not meta["archived"])

    orphan_repos = sorted(rid for rid, row in declared.items() if not row["components"])

    return {
        "available": True,
        "owner": owner,
        "declared": len(declared),
        "on_github": len(actual),
        "drift": drift,
        "candidates": candidates,
        "unrelated_count": len(unrelated),
        "unrelated": unrelated,
        "repositories_without_component": orphan_repos,
        "sees_private": sees_private,
        "visibility_counts": visibility_counts,
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

    vis = report["visibility_counts"]
    breakdown = " · ".join(f"{k} {n}" for k, n in sorted(vis.items()))
    print(f"\nเทียบกับ GitHub ({report['on_github']} repo ในบัญชี {report['owner']} — {breakdown})")
    if not report["sees_private"]:
        print("  ⚠️  token นี้ไม่เห็น private repo สักตัว — ผลด้านล่างครอบเฉพาะ public")
        print("      สมาชิกที่เป็น private จะอ่านได้ว่า 'หาไม่เจอ' และ repo ที่เกี่ยวแต่ private")
        print("      จะไม่ถูกเสนอเป็นผู้สมัครเลย · ใช้ token ที่มี scope repo ก่อนเชื่อผลนี้")
    if report["drift"]:
        for d in report["drift"]:
            print(f"  ✗ {d['repository']}: {d['kind']} — {d['detail']}")
    else:
        print("  ✓ ตรงกันทั้งหมด")

    if report["repositories_without_component"]:
        print("\n  ทะเบียนที่ยังไม่มี component ผูกอยู่: "
              + ", ".join(report["repositories_without_component"]))
    if report["candidates"]:
        print(f"\n  🔴 น่าจะเป็นสมาชิก ecosystem แต่ยังไม่อยู่ในทะเบียน "
              f"({len(report['candidates'])})")
        for c in report["candidates"]:
            print(f"    · {c['repository']}")
            for sig in c["signals"]:
                print(f"        {sig}")
    else:
        print("\n  ✓ ไม่มี repo ที่มีหลักฐานว่าเกี่ยวแต่ตกทะเบียน")

    scope = "" if report["sees_private"] else " (เฉพาะ public)"
    print(f"\n  repo อื่นในบัญชี{scope}: {report['unrelated_count']} ตัว "
          f"— ไม่มีหลักฐานว่าเกี่ยวกับ ecosystem นี้")
    if show_all and report["unrelated"]:
        print("    " + ", ".join(report["unrelated"]))
    elif report["unrelated"]:
        print("    (--all เพื่อดูรายชื่อ)")

    return 1 if (report["drift"] or report["candidates"]) else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
