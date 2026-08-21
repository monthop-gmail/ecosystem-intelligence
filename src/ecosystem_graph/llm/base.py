"""สัญญาของชั้น LLM (#11)

advisor.py รู้จักแค่ interface นี้ — เปลี่ยน provider ได้โดยไม่ต้องแก้ logic
schema เป็น JSON Schema ตัวเดียวที่ทุก provider ใช้ร่วมกัน ไม่ใช่ของใครของมัน
"""
from __future__ import annotations

from typing import Any, Protocol


class LLMError(RuntimeError):
    """เรียก provider ไม่สำเร็จ — แยกจาก error ของ logic ฝั่งเรา"""


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self,
        *,
        stable_system: str,
        volatile_context: str,
        question: str,
        schema: dict[str, Any],
        effort: str = "high",
    ) -> dict[str, Any]:
        """ตอบเป็น JSON ที่ตรง schema

        พารามิเตอร์ถูกแยกเป็นสามก้อนตามความถี่ที่เปลี่ยน — จากนิ่งไปหาผันผวน

            stable_system     ecosystem truth · เหมือนกันทุกทีม ทุกคำถาม
            volatile_context  team context · เปลี่ยนตามทีม
            question          คำถาม · เปลี่ยนทุกครั้ง

        การเรียงแบบนี้ทำให้ prompt cache ของทุก provider ทำงานได้เต็มที่
        (cache เป็น prefix match — ของนิ่งต้องมาก่อนเสมอ)
        """
        ...
