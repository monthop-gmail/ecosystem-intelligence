"""ทดสอบที่ต้องมี DB จะข้ามเองถ้าต่อไม่ได้ — ไม่ทำให้ทั้งชุดพังเพราะไม่ได้ยก docker"""
from __future__ import annotations

import pytest

from ecosystem_graph.db import connect


def _db_available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


DB_UP = _db_available()
requires_db = pytest.mark.skipif(not DB_UP, reason="ไม่มี PostgreSQL — รัน make up ก่อน")


@pytest.fixture(scope="session")
def loaded_db():
    """DB ที่ import ecosystem.yaml เข้าไปแล้ว — สถานะเดียวกับที่ make import ให้"""
    if not DB_UP:
        pytest.skip("ไม่มี PostgreSQL")
    from ecosystem_graph.importer import run
    from ecosystem_graph.migrate import migrate

    migrate()
    run()
    yield


@pytest.fixture
def conn(loaded_db):
    with connect(readonly=True) as c:
        yield c
