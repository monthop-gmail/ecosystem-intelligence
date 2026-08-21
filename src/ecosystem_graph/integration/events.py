"""ปล่อยคำแนะนำออกมาเป็น event/v1 (#25)

**ทำไมเป็น event ไม่ใช่ "job"**

แผนเดิมเขียนว่า "recommended work แปลงเป็นงานใน devfactory-core ได้" ซึ่งฟังดูเหมือน
ต้องประดิษฐ์ payload รูปแบบ job ขึ้นมาเอง — แต่ ecosystem นี้มี contract ที่ตอบเรื่องนี้
อยู่แล้วคือ `event/v1` และ `devfactory-core` ก็ pin มันไว้จริง

การสร้างรูปแบบใหม่ขึ้นมาข้าง ๆ contract ที่มีอยู่ คือความผิดพลาดแบบเดียวกับที่
ecosystem นี้เตือนตัวเองไว้ใน `planes/README.md`

**ข้อจำกัดที่ตรวจกับ schema จริงแล้ว**

- `event_type` เป็น **ชุดเปิด** — `EventTypeName` บังคับแค่รูปแบบ `^[A-Z][A-Z0-9_]{2,63}$`
  ไม่ได้บังคับตัวค่า จึงประกาศ `ADVISORY_ISSUED` ได้เองโดยไม่ต้องขอ ADR ที่ต้นทาง
  (ยืนยันด้วยการ validate กับ schema ที่ pin ไว้ ไม่ได้อนุมานจากคำอธิบาย)
- `subject_type: record` — advisory เป็นบันทึกของโดเมนที่ไม่ได้เกิดจาก job
  ชนิดจริงอยู่ใน `metadata.record_type` ตามที่ schema กำหนด
- **subject ของ advisory คือ "รอบการให้คำแนะนำ" ไม่ใช่ข้อเสนอแต่ละข้อ**
  เพราะ `sequence` ของ `event/v1` เรียง event **ภายใน subject เดียวกัน**
  ถ้าให้แต่ละข้อเป็น subject ของตัวเอง จะมี event ใบเดียวต่อ subject
  `sequence` ก็เป็น 1 ตลอดและไม่พาข้อมูลลำดับไปเลย (devfactory-core#32)
- **drift ไม่มี `sequence`** — แต่ละ finding เป็นเรื่องของ entity คนละตัว ไม่มีลำดับ
  ระหว่างกัน · field ที่มีค่าแต่ไม่มีความหมาย หลอกผู้อ่านให้คิดว่าเรียงได้
- **`event_id` ผูกกับ "เนื้อหา" ไม่ใช่ "เวลาที่รัน"** — คำแนะนำชุดเดิมบน ecosystem
  สถานะเดิม ได้ id เดิมเสมอ ทำให้ปลายทางอ่านซ้ำได้โดยไม่เกิดใบซ้ำ และไม่ต้องมี cursor
- `source.kind` — **บอกขอบเขตที่ event กำลังข้าม ณ ตอนที่เขียนลง ไม่ใช่คุณสมบัติติดตัว event**
  emitter ตัวนี้มีไว้ส่งข้ามขอบเขตออกไปอย่างเดียว จึงเป็น `external` เสมอ
  ถ้าวันหนึ่งเราเก็บ event ของตัวเองลง log ของตัวเอง ทางนั้นต้องเรียกด้วย
  `boundary="internal"` — ไม่งั้น log ของเราจะบอกว่า event ที่เราสร้างเองมาจากข้างนอก
  (ข้อสังเกตจาก agent-platform#40)
- `tenant_id: default` — ecosystem นี้ยังเป็น single tenant (devfactory-core RFC-0006)
- **ห้ามใส่ chain-of-thought ลง metadata** — 🔒 invariant ของ event/v1
  เราใส่เฉพาะผลลัพธ์ที่มีโครงสร้าง (title, why, references) ไม่ใส่ร่องรอยการคิดของ model
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# ขอบเขตที่ event กำลังข้าม → source.kind
# ไม่มีค่า default ที่ถูกเสมอ เพราะ external แปลว่า "นอกจากใคร" ซึ่งขึ้นกับผู้อ่าน
BOUNDARY_KIND = {"outbound": "external", "internal": "internal"}

ADVISORY_ISSUED = "ADVISORY_ISSUED"
DRIFT_DETECTED = "ECOSYSTEM_DRIFT_DETECTED"
SOURCE_SYSTEM = "ecosystem-intelligence"
DEFAULT_TENANT = "default"

ID_MAX = 63


def _digest(*parts: Any) -> str:
    """ลายนิ้วมือของเนื้อหา — id ต้องเปลี่ยนเมื่อเนื้อหาเปลี่ยน ไม่ใช่เมื่อเวลาเปลี่ยน"""
    blob = "\u0000".join(
        json.dumps(p, ensure_ascii=False, sort_keys=True) if not isinstance(p, str) else p
        for p in parts
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _id(*parts: str) -> str:
    """id ตาม identity/v1 Id: ^[a-z0-9][a-z0-9_-]{0,62}$"""
    raw = "-".join(p for p in parts if p).lower()
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in raw)
    safe = safe.lstrip("-_") or "e"
    if len(safe) > ID_MAX:
        digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
        safe = f"{safe[:ID_MAX - 9]}-{digest}"
    return safe


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source(boundary: str) -> dict[str, str]:
    if boundary not in BOUNDARY_KIND:
        raise ValueError(f"boundary ต้องเป็น {' หรือ '.join(BOUNDARY_KIND)} ไม่ใช่ {boundary!r}")
    return {"kind": BOUNDARY_KIND[boundary], "system": SOURCE_SYSTEM}


def advisory_events(result: dict[str, Any], *, tenant_id: str = DEFAULT_TENANT,
                    occurred_at: str | None = None,
                    boundary: str = "outbound") -> list[dict[str, Any]]:
    """แปลงคำตอบของ advisor เป็น event/v1 หนึ่งใบต่อหนึ่งข้อเสนอ

    หนึ่งใบต่อหนึ่งข้อเสนอ ไม่ใช่ใบเดียวรวมทุกข้อ เพราะแต่ละข้อถูกรับไปทำแยกกันได้
    ทุกใบผูกกันด้วย correlation_id เดียว
    """
    answer = result["answer"]
    team = answer["team"]
    stamp = occurred_at or _now()
    steps = answer["recommended_next_steps"]

    # id มาจากเนื้อหา ไม่ใช่จากเวลา — คำแนะนำชุดเดิมบน ecosystem สถานะเดิม
    # ต้องได้ id เดิม ไม่งั้นปลายทางที่อ่านซ้ำจะได้ใบซ้ำที่ระบบเขามองไม่ออกว่าซ้ำ
    correlation = _id("adv", team, _digest(team, result["question"],
                                           result.get("as_of") or "", steps))

    events: list[dict[str, Any]] = []
    for i, step in enumerate(steps, start=1):
        events.append({
            "event_id": _id(correlation, str(i)),
            "event_type": ADVISORY_ISSUED,
            "tenant_id": tenant_id,
            "subject_type": "record",
            # subject = รอบการให้คำแนะนำ ไม่ใช่ข้อเสนอแต่ละข้อ — sequence จึงเรียงได้จริง
            "subject_id": correlation,
            "correlation_id": correlation,
            "occurred_at": stamp,
            "sequence": i,
            "source": _source(boundary),
            "metadata": {
                "record_type": "ecosystem_advisory",
                "team": team,
                "question": result["question"],
                "title": step["title"],
                "why": step["why"],
                "priority": step["priority"],
                "references": list(step["references"]),
                "generated_by": result["generated_by"],
                "ecosystem_as_of": result["as_of"],
                "grounded": result["grounding"]["ok"],
            },
        })
    return events


def drift_events(findings: list[dict[str, Any]], *, tenant_id: str = DEFAULT_TENANT,
                 occurred_at: str | None = None,
                 boundary: str = "outbound") -> list[dict[str, Any]]:
    """finding ของ Guardian ที่เป็น error → event หนึ่งใบต่อหนึ่ง finding

    เฉพาะ error — warning เป็นข้อสังเกต ไม่ใช่เหตุการณ์ที่ต้องบันทึกถาวร
    """
    stamp = occurred_at or _now()
    errors = [f for f in findings if f["severity"] == "error"]
    correlation = _id("drift", _digest(
        [{"rule": f["rule"], "subject": f["subject"], "detail": f["detail"]} for f in errors]))

    return [{
        # แต่ละ finding เป็นเรื่องของ entity คนละตัว — subject จึงเป็นตัวมันเอง
        # และไม่มี sequence เพราะไม่มีลำดับระหว่างกัน
        "event_id": _id("drift", _digest(f["rule"], f["subject"], f["detail"])),
        "event_type": DRIFT_DETECTED,
        "tenant_id": tenant_id,
        "subject_type": "record",
        "subject_id": _id(f["rule"], f["subject"]),
        "correlation_id": correlation,
        "occurred_at": stamp,
        "source": _source(boundary),
        "metadata": {
            "record_type": "ecosystem_drift",
            "rule": f["rule"],
            "subject": f["subject"],
            "detail": f["detail"],
            "fix": f["fix"],
        },
    } for f in errors]


def assert_outbound(payloads: list[dict[str, Any]]) -> None:
    """กันลืม — อะไรที่ส่งออกนอกต้องเป็น external ทุกใบ

    ใช้ตรงจุดที่เขียนไฟล์หรือส่งออก ไม่ใช่ตรงที่สร้าง เพราะจุดที่ผิดพลาดได้จริง
    คือวันที่มีคนเอา event ที่สร้างไว้สำหรับ log ภายในมาส่งออกโดยไม่ได้ตั้งใจ
    """
    wrong = [e["event_id"] for e in payloads if e["source"]["kind"] != "external"]
    if wrong:
        raise ValueError(
            f"event ที่ส่งออกนอกต้องมี source.kind=external — ผิด {len(wrong)} ใบ: "
            f"{wrong[:5]}"
        )
