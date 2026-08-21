"""ค่า config ที่ทุกเครื่องมือใช้ร่วมกัน — อ่านจาก .env ถ้ามี"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DSN = "postgresql://ecosystem:ecosystem@localhost:55434/ecosystem"


def _detect_root() -> Path:
    """หาโฟลเดอร์ที่มีไฟล์ข้อมูล (ecosystem.yaml, migrations/, schema/)

    เดิมคำนวณจาก __file__ ขึ้นไปสามชั้น ซึ่งถูกเฉพาะตอนรันจาก src layout
    พอ pip install จริงโมดูลไปอยู่ใน site-packages แล้วสามชั้นขึ้นไปกลายเป็น
    /usr/local/lib/python3.12 — migrate เลย glob ไม่เจอไฟล์ไหนเลยแล้ว
    **รายงานว่าสำเร็จ** ทั้งที่ไม่ได้ทำอะไร ซึ่งอันตรายกว่าพัง

    ลำดับ: ตัวแปร env → layout ของ repo → cwd
    """
    env = os.environ.get("ECOSYSTEM_ROOT")
    if env:
        return Path(env).resolve()
    repo = Path(__file__).resolve().parent.parent.parent
    if (repo / "ecosystem.yaml").exists():
        return repo
    cwd = Path.cwd()
    if (cwd / "ecosystem.yaml").exists():
        return cwd
    return repo  # ปล่อยให้พังพร้อมชื่อ path จริง ดีกว่าเดาเงียบ ๆ


ROOT = _detect_root()


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
