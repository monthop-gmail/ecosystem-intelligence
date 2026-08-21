"""รายงานสุขภาพ ecosystem — markdown ก้อนเดียวที่ใช้ได้ทั้งบนจอและใน CI

รวมผลจากทุก milestone ไว้ในที่เดียว เพราะสิ่งที่คนอยากรู้ตอนเปิดดูคือ
"ตอนนี้ ecosystem เป็นยังไง" ไม่ใช่ "แต่ละ subsystem รายงานว่าอะไร"

ออกแบบให้ **ไม่มีอะไรพังทั้งรายงานเพราะส่วนเดียวล้ม** — ส่วนที่ต้องออกเน็ต
ล้มได้ และจะบอกว่าล้ม ไม่ใช่หายไปเฉย ๆ
"""
from __future__ import annotations

import sys
from typing import Any

from . import queries as q
from .db import connect
from .github import work as gh_work
from .guardian import checks
from .registry import reconcile


def _section(title: str) -> list[str]:
    return ["", f"## {title}", ""]


def _safe(fn, fallback):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — ส่วนเดียวล้มต้องไม่ทำให้ทั้งรายงานหาย
        return fallback(e)


def build(conn, *, remote: bool = False) -> str:
    meta = q.meta(conn)
    components = q.list_components(conn)
    contracts = q.list_contracts(conn)

    lines: list[str] = [
        f"# สุขภาพ ecosystem — {meta.get('name', '?')}",
        "",
        f"ข้อมูล ณ `{meta.get('updated')}` · "
        f"{len(components)} components · {len(contracts)} contracts · "
        f"{len(q.list_planes(conn))} planes · {len(q.list_teams(conn))} teams",
    ]

    # ── conformance ───────────────────────────────────────────────────
    lines += _section("Conformance")
    by_status: dict[str, list[str]] = {}
    for c in components:
        by_status.setdefault(c["conformance_status"] or "unknown", []).append(c["id"])
    lines.append("| สถานะ | จำนวน | component |")
    lines.append("| --- | ---: | --- |")
    for status in ("passing", "failing", "unknown", "waived", "not-applicable"):
        if status in by_status:
            ids = by_status[status]
            lines.append(f"| `{status}` | {len(ids)} | {', '.join(f'`{i}`' for i in ids)} |")

    # ── guardian ──────────────────────────────────────────────────────
    report = _safe(lambda: checks.run_all(conn, include_remote=remote),
                   lambda e: {"findings": [], "errors": 0, "warnings": 0,
                              "rules_run": [], "rules_skipped": [], "failed": str(e)})
    lines += _section("Architecture Guardian")
    if report.get("failed"):
        lines.append(f"⚠️ ตรวจไม่สำเร็จ: `{report['failed'][:200]}`")
    else:
        lines.append(f"ตรวจ {len(report['rules_run'])} กฎ · "
                     f"**error {report['errors']}** · warn {report['warnings']}")
        if report["rules_skipped"]:
            lines.append(f"⏭ ข้าม (ต้องออกเน็ต): {', '.join(report['rules_skipped'])}")
        if report["findings"]:
            lines += ["", "| ระดับ | กฎ | เรื่อง |", "| --- | --- | --- |"]
            by_rule: dict[str, list[dict]] = {}
            for f in report["findings"]:
                by_rule.setdefault(f["rule"], []).append(f)
            for rule, items in by_rule.items():
                mark = "❌" if items[0]["severity"] == "error" else "⚠️"
                subjects = ", ".join(f"`{i['subject']}`" for i in items[:6])
                if len(items) > 6:
                    subjects += f" +{len(items) - 6}"
                lines.append(f"| {mark} | `{rule}` | {subjects} |")

    # ── contract ที่ปิดได้ ─────────────────────────────────────────────
    closable = [c["id"] for c in contracts if not c["consumers"] and not c["expected_by"]]
    waiting = {c["id"]: c["expected_by"] for c in contracts
               if not c["consumers"] and c["expected_by"]}
    lines += _section("Contract")
    lines.append(f"- ปิดเวอร์ชันได้เลย ({len(closable)}): "
                 + (", ".join(f"`{c}`" for c in closable) or "—"))
    for cid, who in waiting.items():
        lines.append(f"- `{cid}` ยังไม่มีใคร pin แต่ {', '.join(who)} รออยู่ — ปิดไม่ได้")

    # ── งานจริงจาก GitHub ─────────────────────────────────────────────
    items = _safe(lambda: gh_work.current_work(conn), lambda e: [])
    lines += _section("งานที่เปิดอยู่")
    if not items:
        lines.append("ยังไม่มีข้อมูลจาก GitHub — ต้องรัน sync ก่อน")
    else:
        in_progress = [w for w in items if w["state"] == "in-progress"]
        declared = [w for w in items if w["state"] == "declared"]
        lines.append(f"{len(items)} ชิ้น · กำลังทำจริง **{len(in_progress)}** · "
                     f"ประกาศไว้เฉย ๆ {len(declared)}")
        if in_progress:
            lines += ["", "| ทีม | งาน | ล่าสุด |", "| --- | --- | ---: |"]
            for w in in_progress[:10]:
                lines.append(f"| `{w['team'] or '-'}` | [{w['repository']}#{w['number']}]"
                             f"({w['url']}) {w['title'][:50]} | {w['updated_days_ago']}d |")
        risks = _safe(lambda: gh_work.duplicate_risk(conn), lambda e: [])
        if risks:
            lines += ["", "**งานซ้ำข้ามทีม**"]
            for r in risks:
                lines.append(f"- `{r['entity']}` — {', '.join(r['teams'])}")

    # ── registry ──────────────────────────────────────────────────────
    if remote:
        rec = _safe(lambda: reconcile(conn), lambda e: {"available": False, "reason": str(e)})
        lines += _section("Repository registry")
        if not rec.get("available"):
            lines.append(f"⚠️ เทียบกับ GitHub ไม่ได้: {rec.get('reason')}")
        elif rec["drift"]:
            lines += ["| repo | อาการ | รายละเอียด |", "| --- | --- | --- |"]
            for d in rec["drift"]:
                lines.append(f"| `{d['repository']}` | {d['kind']} | {d['detail']} |")
        else:
            lines.append(f"✅ ทะเบียน {rec['declared']} repo ตรงกับ GitHub ทั้งหมด")

    lines += ["", "---",
              "_สร้างโดย `make health` — ตรวจจากกฎอัตโนมัติ ไม่ได้อ่านโค้ด_"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    remote = "--remote" in argv
    with connect(readonly=True) as conn:
        print(build(conn, remote=remote))
    return 0


if __name__ == "__main__":
    sys.exit(main())
