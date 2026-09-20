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
- **`event_id` ผูกกับ "ตัวตนของ record" ไม่ใช่ทุกไบต์ในใบ** — ดู EVENT_ID_IDENTITY
  ข้างล่าง · เวอร์ชันก่อน 2026-09-20 hash ทุกอย่างที่เห็น รวม `as_of` และถ้อยคำ
  `why` ที่โมเดลเขียน · ผลคือแก้ `ecosystem.yaml` เรื่องที่ไม่เกี่ยวเลย หรือโมเดล
  เรียบเรียงประโยคใหม่ **id เปลี่ยนทั้งชุด** ทั้งที่คำแนะนำเหมือนเดิม
  แบบนั้นเรียกว่า "ผูกกับเนื้อหา" ไม่ได้ และรับเป็นคำสัญญาให้ใครไม่ได้ (devfactory-core#32)
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

# ── ตัวตนของ record: สิ่งเดียวที่ event_id ผูกอยู่ ────────────────────────
#
# ประกาศไว้ใน platform-contract.yaml (event_id_derivation) และถือเป็น frozen —
# แก้รายการนี้คือ breaking ต้องแจ้ง consumer ตาม ADR-0006 ไม่ใช่แก้เงียบ ๆ
#
# ที่ไม่อยู่ในนี้โดยเจตนา:
#   why / detail   ถ้อยคำที่โมเดลหรือกฎเขียน — เรียบเรียงใหม่ไม่ใช่ record ใหม่
#                  และของ advisor มาจาก LLM ซึ่งไม่ deterministic ข้ามรุ่นอยู่แล้ว
#   ecosystem_as_of / occurred_at / generated_by / grounded
#                  บอกว่า "ดูเมื่อไร ใครดู" ไม่ได้บอกว่า "เรื่องอะไร"
#   sequence       ตำแหน่งในรอบ ไม่ใช่ตัวตน — แทรกข้อใหม่ไม่ควรย้าย id ของข้ออื่น
ADVISORY_IDENTITY = ("team", "question", "title", "priority", "references")
DRIFT_IDENTITY = ("rule", "subject")

EVENT_ID_IDENTITY = {
    ADVISORY_ISSUED: ADVISORY_IDENTITY,
    DRIFT_DETECTED: DRIFT_IDENTITY,
}


def identity_of(event: dict[str, Any]) -> dict[str, Any]:
    """ดึงฟิลด์ที่ประกอบเป็นตัวตน ออกจากใบที่ปล่อยไปแล้ว

    มีไว้ให้ "คำนวณ id ซ้ำจากใบเอง" ได้ — ซึ่งคือสิ่งที่ทำให้มันเป็นคำสัญญา
    ที่ตรวจได้ ไม่ใช่คำอธิบายพฤติกรรม
    """
    kind = event.get("event_type")
    fields = EVENT_ID_IDENTITY.get(kind)
    if fields is None:
        raise ValueError(
            f"ไม่ได้ประกาศตัวตนของ event_type {kind!r} — ใบที่คำนวณ id ซ้ำไม่ได้ "
            "คือใบที่ปลายทางมองไม่ออกว่าซ้ำ")
    md = event.get("metadata") or {}
    return {f: md.get(f) for f in fields}


def event_id_for(event: dict[str, Any]) -> str:
    """คำนวณ event_id จากใบ — ต้องได้ค่าเดิมกับที่ emitter ใส่ไว้เสมอ"""
    # identity_of ฟ้องก่อนถ้าไม่รู้จักชนิด — ที่นี่จึงไม่ต้องเดา
    ident = identity_of(event)
    kind = "adv" if event["event_type"] == ADVISORY_ISSUED else "drift"
    return _id(kind, _digest(ident))


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

    # ตัวตนของแต่ละข้อ ไม่ใช่ทุกไบต์ในใบ — ดู EVENT_ID_IDENTITY
    identities = [{"team": team, "question": result["question"],
                   "title": s["title"], "priority": s["priority"],
                   "references": list(s["references"])} for s in steps]

    # รอบหนึ่ง = ชุดข้อเสนอชุดหนึ่ง · correlation จึงผูกกับชุด แต่ id ของแต่ละใบ
    # ผูกกับตัวมันเอง — แก้ถ้อยคำข้อ 1 ต้องไม่ย้าย id ของข้อ 2
    correlation = _id("adv", team, _digest(identities))

    seen: set[str] = set()
    events: list[dict[str, Any]] = []
    for i, (step, ident) in enumerate(zip(steps, identities), start=1):
        eid = _id("adv", _digest(ident))
        if eid in seen:
            raise ValueError(
                f"ข้อเสนอสองข้อในรอบเดียวกันมีตัวตนเหมือนกัน (ข้อ {i}: {step['title']!r}) "
                "— id จะชนกันและปลายทางจะทิ้งใบหนึ่งไปเงียบ ๆ")
        seen.add(eid)
        events.append({
            "event_id": eid,
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
        [{"rule": f["rule"], "subject": f["subject"]} for f in errors]))

    return [{
        # แต่ละ finding เป็นเรื่องของ entity คนละตัว — subject จึงเป็นตัวมันเอง
        # และไม่มี sequence เพราะไม่มีลำดับระหว่างกัน
        # ตัวตน = (กฎ, สิ่งที่ผิดกฎ) · `detail` ไม่อยู่ในนี้เพราะมันพาจำนวนวันมาด้วย
        # เงื่อนไขเดิมที่ยังไม่ถูกแก้ ต้องได้ id เดิมทุกวัน ไม่ใช่ใบใหม่วันละใบ
        "event_id": _id("drift", _digest({"rule": f["rule"], "subject": f["subject"]})),
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
