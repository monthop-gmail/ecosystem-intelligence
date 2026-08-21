"""นำ ecosystem.yaml เข้า Ecosystem Graph (#7)

หลักสามข้อที่ issue กำหนด และวิธีที่ทำให้เป็นจริง

    idempotent            เขียนใหม่ทั้งชุดในทรานแซกชันเดียว — import ซ้ำได้ผลเท่าเดิมเสมอ
    ไม่ผ่าน = ไม่เขียน     validate ก่อนเปิดทรานแซกชัน ไม่ใช่ระหว่างเขียน
    yaml เป็นแหล่งความจริง  DB ไม่มีทางแก้กลับ — API เป็น read-only (#6)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .db import connect, fetch_all
from .validate import ValidationError, load

# ลำดับการลบ — ลูกก่อนแม่ (FK) · ลำดับการเขียนคือกลับด้าน
TABLES = [
    "ecosystem_goals", "conformance", "component_deps", "component_contracts", "component_planes",
    "plane_contracts", "components", "contracts", "planes", "repositories",
    "teams", "sources", "architecture_rules", "ecosystem_meta",
]


def snapshot(conn) -> dict[str, set[tuple]]:
    """ถ่ายภาพสิ่งที่อยู่ใน DB ตอนนี้ เพื่อเทียบส่วนต่างก่อนเขียนทับ"""
    out: dict[str, set[tuple]] = {}
    for table in ("teams", "repositories", "planes", "contracts", "components"):
        rows = fetch_all(conn, f"SELECT id FROM {table}")
        out[table] = {(r["id"],) for r in rows}
    rows = fetch_all(conn, "SELECT component_id, contract_id, relation FROM component_contracts")
    out["component_contracts"] = {(r["component_id"], r["contract_id"], r["relation"]) for r in rows}
    return out


def _wanted(doc: dict) -> dict[str, set[tuple]]:
    return {
        "teams": {(t["id"],) for t in doc["teams"]},
        "repositories": {(r["id"],) for r in doc["repositories"]},
        "planes": {(p["id"],) for p in doc["planes"]},
        "contracts": {(c["id"],) for c in doc["contracts"]},
        "components": {(c["id"],) for c in doc["components"]},
        "component_contracts": {
            (c["id"], k, rel)
            for c in doc["components"]
            for rel, field in (("exposes", "exposes"), ("consumes", "consumes"),
                               ("expected", "expected_contracts"))
            for k in c.get(field, [])
        },
    }


def diff(before: dict[str, set[tuple]], after: dict[str, set[tuple]]) -> list[str]:
    lines: list[str] = []
    for table in after:
        added = after[table] - before.get(table, set())
        removed = before.get(table, set()) - after[table]
        for item in sorted(added):
            lines.append(f"  + {table}: {' '.join(item)}")
        for item in sorted(removed):
            lines.append(f"  - {table}: {' '.join(item)}")
    return lines


def _write(conn, doc: dict) -> None:
    ex = conn.execute
    for table in TABLES:
        ex(f"DELETE FROM {table}")

    meta = doc["metadata"]
    for key in ("name", "updated", "maintained_by", "note"):
        if meta.get(key):
            ex("INSERT INTO ecosystem_meta (key, value) VALUES (%s, %s)", (key, str(meta[key])))
    ex("INSERT INTO ecosystem_meta (key, value) VALUES (%s, %s)",
       ("apiVersion", doc["apiVersion"]))

    for g in doc.get("mission", {}).get("goals", []):
        ex("INSERT INTO ecosystem_goals (id, goal, source) VALUES (%s, %s, %s)",
           (g["id"], g["goal"], g["source"]))

    for rule in doc.get("architecture_rules", []):
        ex("INSERT INTO architecture_rules (id, rule) VALUES (%s, %s)", (rule["id"], rule["rule"]))

    for name, src in doc.get("sources", {}).items():
        ex("INSERT INTO sources (name, owner, url, rule, note) VALUES (%s, %s, %s, %s, %s)",
           (name, src["owner"], src["url"], src.get("rule"), src.get("note")))

    for t in doc["teams"]:
        ex("INSERT INTO teams (id, name, responsibilities, members) VALUES (%s, %s, %s, %s)",
           (t["id"], t["name"], t["responsibilities"], t["members"]))

    for r in doc["repositories"]:
        ex("""INSERT INTO repositories (id, url, visibility, default_branch, does_exist, manifest)
              VALUES (%s, %s, %s, %s, %s, %s)""",
           (r["id"], r.get("url"), r.get("visibility"), r.get("default_branch"),
            r["exists"], r.get("manifest")))

    for p in doc["planes"]:
        ex("INSERT INTO planes (id, name, responsibility, must_not) VALUES (%s, %s, %s, %s)",
           (p["id"], p["name"], p["responsibility"], p["must_not"]))

    for c in doc["contracts"]:
        ex("""INSERT INTO contracts (id, authority, semantics_owner, derived, status)
              VALUES (%s, %s, %s, %s, %s)""",
           (c["id"], c["authority"], c.get("semantics_owner"),
            bool(c.get("derived")), c["status"]))

    for p in doc["planes"]:
        for cid in p["contracts"]:
            ex("INSERT INTO plane_contracts (plane_id, contract_id) VALUES (%s, %s)", (p["id"], cid))

    for c in doc["components"]:
        ex("""INSERT INTO components
                 (id, name, owner, repository, status, outside_plane_model,
                  outside_plane_reason, implements_note)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
           (c["id"], c["name"], c["owner"], c.get("repository"), c["status"],
            bool(c.get("outside_plane_model")), c.get("outside_plane_reason"),
            c.get("implements_note")))
        for pid in c["implements"]:
            ex("INSERT INTO component_planes (component_id, plane_id) VALUES (%s, %s)",
               (c["id"], pid))
        for rel, field in (("exposes", "exposes"), ("consumes", "consumes"),
                           ("expected", "expected_contracts")):
            for k in c.get(field, []):
                ex("""INSERT INTO component_contracts (component_id, contract_id, relation)
                      VALUES (%s, %s, %s)""", (c["id"], k, rel))
        for dep in c.get("depends_on", []):
            ex("INSERT INTO component_deps (component_id, depends_on, reason) VALUES (%s, %s, %s)",
               (c["id"], dep["component"], dep["reason"]))
        conf = c["conformance"]
        ex("""INSERT INTO conformance
                 (component_id, status, manifest, pinned_commit, last_verified,
                  evidence, note, waived_until, waiver_ref)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
           (c["id"], conf["status"], conf.get("manifest"), conf.get("pinned_commit"),
            conf.get("last_verified"), conf.get("evidence"), conf.get("note"),
            conf.get("waived_until"), conf.get("waiver_ref")))


def run(path: Path | str | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    """validate → คำนวณส่วนต่าง → เขียนทับทั้งชุดในทรานแซกชันเดียว

    validate เกิดก่อนเปิดทรานแซกชันเสมอ — ไฟล์ที่ไม่ผ่านจะไม่แตะ DB แม้แต่แถวเดียว
    """
    doc, result = load(path)  # strict=True → ValidationError ถ้าไม่ผ่าน

    with connect() as conn:
        before = snapshot(conn)
        changes = diff(before, _wanted(doc))
        if dry_run:
            conn.rollback()
        else:
            _write(conn, doc)
            conn.commit()
    return {"changes": changes, "warnings": result.warnings, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]

    try:
        out = run(args[0] if args else None, dry_run=dry)
    except ValidationError as e:
        for msg in e.result.errors:
            print(f"  ERROR {msg}")
        print(f"\n❌ ไม่ผ่านการตรวจ — ไม่มีอะไรถูกเขียนลง DB ({len(e.result.errors)} error)")
        return 1

    for line in out["changes"]:
        print(line)
    verb = "จะเปลี่ยน" if dry else "เปลี่ยนแล้ว"
    if out["changes"]:
        print(f"\n✅ import{' (dry-run)' if dry else ''}: {verb} {len(out['changes'])} รายการ")
    else:
        print(f"\n✅ import{' (dry-run)' if dry else ''}: ไม่มีส่วนต่าง — DB ตรงกับ ecosystem.yaml แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
