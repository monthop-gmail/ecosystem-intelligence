"""ค่า config ที่ทุกเครื่องมือใช้ร่วมกัน — อ่านจาก .env ถ้ามี"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DSN = "postgresql://ecosystem:ecosystem@localhost:55434/ecosystem"


def _load_dotenv() -> None:
    """อ่าน .env แบบง่าย — ไม่ทับค่าที่ตั้งไว้ใน environment แล้ว"""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def dsn() -> str:
    _load_dotenv()
    return os.environ.get("ECOSYSTEM_DSN", DEFAULT_DSN)
