<!-- ร่างสำหรับเปิดที่ monthop-gmail/agent-platform — ยังไม่ได้เปิด -->
# ขอลงทะเบียน `ecosystem-intelligence` เป็น consumer ของ `event/v1`

`ecosystem-intelligence` conform ครบ 3 ข้อของ [ADR-0006](../decisions/0006-contract-versioning.md) แล้ว
แต่ยังไม่มีแถวใน [`architecture/consumers.md`](../architecture/consumers.md)

| ข้อ | หลักฐาน |
| --- | --- |
| manifest | [`platform-contract.yaml`](https://github.com/monthop-gmail/ecosystem-intelligence/blob/main/platform-contract.yaml) |
| conformance test | [`conformance/payload_check.py`](https://github.com/monthop-gmail/ecosystem-intelligence/blob/main/conformance/payload_check.py) — validate event 13 ใบ/รอบ ที่ผลิตจากการรัน advisor และ guardian กับ ecosystem จริง ไม่มี fixture ที่เขียนขึ้นเพื่อให้ผ่าน · ตรวจ guarantee ที่ JSON Schema ตรวจไม่ได้อีก 8 ข้อ |
| release gate | job `conformance` ใน CI รันทุก PR |

**pin:** `event/v1` · `identity/v1` ที่ commit `6e97e085`

**บทบาทต่างจาก consumer รายอื่น** — repo นี้เป็น **ผู้ผลิต** event ไม่ใช่ผู้บริโภค
แต่ต้อง conform เท่ากัน เพราะฝั่งที่ผลิต payload ผิดคือฝั่งที่ทำให้ audit log ของคนอื่นพัง

**vocabulary ที่เพิ่ม** (ตาม ADR-0006 Rule 2 — `EventTypeName` บังคับแค่รูปแบบชื่อ)

| event_type | subject_type | metadata.record_type |
| --- | --- | --- |
| `ADVISORY_ISSUED` | `record` | `ecosystem_advisory` |
| `ECOSYSTEM_DRIFT_DETECTED` | `record` | `ecosystem_drift` |

แถวที่เสนอให้เพิ่มใน `consumers.md`:

> | [`ecosystem-intelligence`](https://github.com/monthop-gmail/ecosystem-intelligence) | ✅ `platform-contract.yaml` | `passing` | `event/v1` `identity/v1` | 2026-08-21 | **ผู้ผลิต event ไม่ใช่ผู้บริโภค** — ปล่อย `ADVISORY_ISSUED` และ `ECOSYSTEM_DRIFT_DETECTED` · เป็นชั้นที่อธิบาย ecosystem ทั้งหมดรวมถึง repo นี้เอง |
