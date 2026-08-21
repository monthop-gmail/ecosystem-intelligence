"""การเชื่อมต่อ PostgreSQL

read_only() ไม่ใช่แค่ธรรมเนียม — ตั้ง transaction เป็น READ ONLY จริง
เพื่อให้ข้อบังคับ "API อ่านอย่างเดียว" (#6) ถูกบังคับที่ฐานข้อมูล ไม่ใช่แค่ที่ routing
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from .config import dsn


@contextmanager
def connect(*, readonly: bool = False) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn(), row_factory=dict_row) as conn:
        if readonly:
            conn.execute("SET TRANSACTION READ ONLY")
        yield conn


def fetch_all(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn: psycopg.Connection, sql: str, params: Any = None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()
