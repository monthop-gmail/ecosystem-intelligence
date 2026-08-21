# Delivery Integration (M6)

> เราไม่ได้ประดิษฐ์รูปแบบใหม่เพื่อคุยกับ ecosystem — เราเข้าไปเป็นสมาชิกตามกติกาที่มีอยู่

```bash
make conformance          # event ที่ปล่อยออกไป conform กับ event/v1 ไหม
make emit TEAM=knowledge-team   # ดู payload ที่จะปล่อย
make feedback             # เทียบ ecosystem.yaml กับของจริง แล้วเสนอส่วนต่าง
```

## ทำไมเป็น `event/v1` ไม่ใช่ "job"

`#25` เขียนว่า *"recommended work แปลงเป็นงานใน devfactory-core ได้"* ซึ่งฟังดูเหมือน
ต้องประดิษฐ์ payload รูปแบบ job ขึ้นมา — แต่ ecosystem มี contract ที่ตอบเรื่องนี้อยู่แล้ว
คือ `event/v1` และ `devfactory-core` ก็ pin มันไว้จริง

การสร้างรูปแบบใหม่ข้าง ๆ contract ที่มีอยู่ คือความผิดพลาดแบบเดียวกับที่ ecosystem นี้
เตือนตัวเองไว้ — goal `no-duplicate-abstraction`

## `ecosystem-intelligence` เป็น consumer ที่ conform แล้ว

ครบ 3 ข้อของ ADR-0006

| ข้อ | ของเรา |
| --- | --- |
| 1. manifest | [`platform-contract.yaml`](../platform-contract.yaml) — pin `event/v1` + `identity/v1` |
| 2. conformance test | [`conformance/payload_check.py`](../conformance/payload_check.py) |
| 3. release gate | job `conformance` ใน CI รันทุก PR |

**ไม่มี fixture ที่เขียนขึ้นเพื่อให้ schema ผ่าน** — payload ทุกใบที่ตรวจผลิตจากการรัน
advisor ทุกทีมและ guardian กับ ecosystem จริง (13 event ต่อรอบ) แล้ว validate กับ
schema ที่ vendor ไว้จาก commit ที่ pin

นอกจาก schema ยังตรวจ guarantee อีก 8 ข้อที่ JSON Schema ตรวจไม่ได้ — `event_id` ไม่ซ้ำ ·
tenant resolve ได้เสมอ · subject ตอบได้ทุกใบ · external คง source ไว้ · **ไม่ปลอม `job_id`** ·
ไม่มี chain-of-thought ใน metadata · `record` ต้องบอก `record_type` · `sequence` ไม่ซ้ำใน correlation เดียวกัน

### vocabulary ที่เพิ่มเข้ามา

| event_type | subject | ความหมาย |
| --- | --- | --- |
| `ADVISORY_ISSUED` | `record` / `ecosystem_advisory` | ระบบเสนอสิ่งที่ทีมหนึ่งควรทำต่อ พร้อมเหตุผล |
| `ECOSYSTEM_DRIFT_DETECTED` | `record` / `ecosystem_drift` | กฎ architecture หรือ contract ถูกละเมิด พร้อมทางแก้ |

**เพิ่มเองได้โดยไม่ต้องขอ ADR ที่ต้นทาง** — `$defs.EventTypeName` บังคับแค่ *รูปแบบชื่อ*
(`^[A-Z][A-Z0-9_]{2,63}$`) ไม่ได้บังคับตัวค่า ตาม ADR-0006 Rule 2

> ตอนแรกผมอ่านคำอธิบายของ `$defs.EventType` ที่มี `enum` 9 ค่าแล้วสรุปว่าเพิ่มไม่ได้
> ต้องไปขอ ADR — **ผิด** พอ validate กับ schema จริงถึงเห็นว่า `event_type` `$ref`
> ไปที่ `EventTypeName` ซึ่งเป็น pattern ไม่ใช่ enum · ถ้าเชื่อคำอธิบายโดยไม่ทดสอบ
> เราจะไปเปิด issue ขอสิ่งที่ทำเองได้อยู่แล้ว

## ให้ repo อื่นอ่าน ecosystem ได้ (#24)

[`integration/ecosystem_client.py`](../integration/ecosystem_client.py) — **ไฟล์เดียว ใช้แต่ stdlib**
ก๊อปไปวางใน repo ไหนก็ได้ ถ้าต้องลง package เพิ่มเพื่ออ่าน metadata ก็จะไม่มีใครยอมต่อ

```python
from ecosystem_client import EcosystemClient

eco = EcosystemClient("https://ecosystem.internal")
for c in eco.team("platform-team")["components"]:
    print(c["id"], c["conformance_status"])

eco.dependents("agent-platform")            # ก่อนเปลี่ยนอะไรที่คนอื่นใช้
eco.impact("execution/v1", level="breaking")  # กระทบใคร + ลำดับประสาน + ร่าง issue
```

มีเทสต์บังคับว่าไฟล์นี้ต้องไม่มี `requests` / `httpx` / `pydantic`

## วงจรปิด — `make feedback`

```text
ecosystem.yaml       สิ่งที่เราตั้งใจ      ← คนดูแล
GitHub + manifest    สิ่งที่เกิดขึ้นจริง    ← ระบบอ่าน
feedback             ส่วนต่าง              ← ระบบเสนอ คนตัดสิน
```

จับได้ 6 แบบ: repo ที่เกิดขึ้นแล้ว · manifest ที่โผล่มา/หายไป · pin ที่เปลี่ยน ·
conformance ที่ตรวจใหม่ · component ที่ยังเขียนว่า `planned` ทั้งที่ repo ขยับแล้ว

**ไม่มี `--apply` โดยตั้งใจ** — ระบบที่แก้แหล่งความจริงของตัวเองได้ จะไม่มีใครรู้ว่าอะไรคือของจริง

ครั้งแรกที่รันก็จับของจริงทันที: `care-agent-platform` รัน conformance ใหม่เมื่อ 2026-08-21
แต่ `ecosystem.yaml` ยังเขียน 2026-08-19 — แก้ตามหลักฐานใน manifest ของเขาแล้ว

## กฎใหม่ของ Guardian ที่ข้าม repo

| กฎ | ตรวจอะไร |
| --- | --- |
| `semantics-version-drift` | `derived_from.semantics_version` ที่ `agent-platform` pin ไว้ ตรงกับ `contract-semantics.yaml` ของ `devfactory-core` ไหม |
| `pinned-contract-stale` | schema ที่เรา vendor ไว้ เก่ากว่าต้นทางแล้วหรือยัง |

ข้อแรกสำคัญ เพราะ **เป็น drift ที่มองไม่เห็น** — schema ยังผ่าน validation ทุกใบ
แต่สองฝั่งเข้าใจความหมายไม่ตรงกัน `devfactory-core` เขียนกฎ `drift_check` นี้ไว้เอง
(ให้ pin `semantics_version` ไม่ใช่ commit SHA) แต่ยังไม่มีใครตรวจข้าม repo ให้ —
เราตรวจจากมุมของ ecosystem ซึ่งเห็นทั้งสองฝั่ง

ผลรันวันนี้: ทั้งคู่อยู่ที่ `1.2` — ไม่มี drift

## ที่ยังทำฝ่ายเดียวไม่ได้

บันทึกไว้ใน `platform-contract.yaml` หัวข้อ `blocking:` ตามแบบที่ consumer รายอื่นทำ

1. **`agent-platform/architecture/consumers.md` ยังไม่มีแถวของเรา** — เป็นการแก้ที่ repo ของเขา
   → เปิด issue แล้ว [agent-platform#40](https://github.com/monthop-gmail/agent-platform/issues/40)
2. **event ที่ปล่อยออกมายังไม่มีใครรับ** — `devfactory-core` รับ `event/v1` ได้ตามสัญญาอยู่แล้ว
   แต่การต่อท่อจริงต้องตกลงเรื่อง transport กันก่อน
   → [devfactory-core#32](https://github.com/monthop-gmail/devfactory-core/issues/32)

   **ค้างเพราะ deadlock ไม่ใช่เพราะยาก** — ทั้งสองฝั่งจบประโยคด้วย "รอ Architecture Owner"
   แล้วหยุด ต่างคนต่างคิดว่ากำลังรออีกฝ่าย

   แก้ด้วย trigger ตามเงื่อนไข ไม่ใช่วันที่ลอย ๆ เพราะสิ่งที่ขวางคือ `EventLog` ของ
   ปลายทางที่ยังเป็น in-memory ไม่ใช่เวลา — **store ต้องมาก่อน transport**

   | | |
   | --- | --- |
   | เคาะเมื่อ | `devfactory-core` `EventLog` มีที่เก็บถาวร |
   | backstop | `2026-10-31` — ถึงแล้วยังไม่มี store ให้ถือว่า artifact handoff คือท่อจริง |

   > **backstop ที่เขียนไว้แล้วไม่มีใครอ่าน คือคำสัญญาที่ไม่มีผล**
   > guardian rule `blocking-past-backstop` อ่าน `platform-contract.yaml` ของเราเอง
   > แล้วเตือนเมื่อเลยกำหนด — เราตรวจ ecosystem ให้คนอื่นได้ ก็ต้องยอมให้ตรวจตัวเอง
   > ด้วยเกณฑ์เดียวกัน ไม่งั้นเราก็ไม่ต่างจากงานที่ "ประกาศไว้เฉย ๆ" ที่เรารายงานว่าเป็นปัญหา

ร่างต้นฉบับอยู่ที่ [`integration/drafts/`](../integration/drafts/) และผูกกลับเข้า
`platform-contract.yaml` หัวข้อ `blocking:` เพื่อให้ตามรอยได้ว่าค้างอยู่ที่ไหน
