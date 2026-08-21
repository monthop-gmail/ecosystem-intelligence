"""Migration runner — ไม่แก้ schema ด้วยมือ (#5)

ไฟล์ใน migrations/ ตั้งชื่อ NNNN_name.sql และรันเรียงตามเลข
ที่รันไปแล้วบันทึกใน schema_migrations พร้อม checksum
— แก้ไฟล์ที่รันไปแล้วจะถูกจับได้ ไม่ใช่ผ่านไปเงียบ ๆ
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from .config import ROOT
from .db import connect, fetch_all

MIGRATIONS = ROOT / "migrations"

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def status() -> list[tuple[str, str]]:
    with connect() as conn:
        conn.execute(BOOTSTRAP)
        applied = {r["version"]: r["checksum"] for r in
                   fetch_all(conn, "SELECT version, checksum FROM schema_migrations")}
    out = []
    for f in _files():
        checksum = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        if f.stem not in applied:
            out.append((f.stem, "pending"))
        elif applied[f.stem] != checksum:
            out.append((f.stem, "CHANGED"))
        else:
            out.append((f.stem, "applied"))
    return out


def migrate() -> int:
    applied_count = 0
    with connect() as conn:
        conn.execute(BOOTSTRAP)
        applied = {r["version"]: r["checksum"] for r in
                   fetch_all(conn, "SELECT version, checksum FROM schema_migrations")}
        for f in _files():
            checksum = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
            if f.stem in applied:
                if applied[f.stem] != checksum:
                    raise SystemExit(
                        f"❌ {f.name} ถูกแก้หลังจากรันไปแล้ว "
                        f"({applied[f.stem]} → {checksum}) — เขียน migration ใหม่แทนการแก้ของเก่า"
                    )
                continue
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (f.stem, checksum),
            )
            print(f"  ✓ {f.stem}")
            applied_count += 1
    return applied_count


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--status" in argv:
        for version, state in status():
            mark = {"applied": "✓", "pending": "·", "CHANGED": "✗"}[state]
            print(f"  {mark} {version}  {state}")
        return 0
    n = migrate()
    print(f"✅ migrate: {'ไม่มีอะไรใหม่' if not n else f'รันไป {n} ไฟล์'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
