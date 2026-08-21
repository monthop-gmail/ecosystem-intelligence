# Architecture Guardian (M5)

> กันไม่ให้ ecosystem เพี้ยนไปตามเวลา — และวางไว้ตรงจุดที่คนทำงานจริง

```bash
make guardian                              # ตรวจทั้ง ecosystem
make guardian REMOTE=1                     # ตรวจ manifest drift ด้วย (ออกเน็ต)
make guardian-pr PR=agent-platform#33      # รีวิว PR (ไม่โพสต์)
make guardian-pr PR=... POST=1             # โพสต์จริง — ต้องเปิดใน guardian.yaml ก่อน
```

## กฎอยู่ในไฟล์ ไม่ได้ฝังในโค้ด

[`src/ecosystem_graph/guardian/rules.yaml`](../src/ecosystem_graph/guardian/rules.yaml)
— 14 กฎ แต่ละข้อมี `severity` · `why` · **`fix`**

> **ทุกกฎต้องมี `fix`** และมีเทสต์บังคับ — รายงานที่บอกว่าผิดแต่ไม่บอกว่าจะแก้ยังไง
> ไม่มีใครทำตาม

กฎที่ต้องให้ **คน** ตัดสินไม่ได้อยู่ในไฟล์นี้ — พวกนั้นคือ `architecture_rules`
ของ `ecosystem.yaml` และ `must_not` ของแต่ละ plane ซึ่งเป็นข้อความสำหรับคนอ่าน

| กฎ | severity | จับอะไร |
| --- | --- | --- |
| `orphan-component` | error | component ไม่มีทีมเจ้าของ |
| `execution-owns-governance` | error | ชั้น execution เป็นเจ้าของ `policy/v1` หรือ `approval/v1` |
| `execution-holds-credential` | error | ชั้น execution consume `provider/v1` ตรง ๆ |
| `orchestration-owns-artifact` | error | ชั้น orchestration เป็นเจ้าของ `artifact/v1` |
| `manifest-drift` | error | `ecosystem.yaml` ไม่ตรงกับ `platform-contract.yaml` ของจริง |
| `derived-contract-semantics-missing` | error | `derived: true` แต่ไม่ระบุ `semantics_owner` |
| `consumes-without-evidence` | error | ประกาศ `consumes` โดยไม่มี manifest |
| `duplicate-plane-implementation` | warn | plane เดียวมีหลาย implementation |
| `plane-without-implementation` | warn | plane ที่ยังไม่มีใครทำ |
| `contract-without-consumer` | warn | contract ที่ยังไม่มีใคร pin |
| `conformance-stale` | warn | `passing` ที่เก่ากว่า 90 วัน |

สามกฎสุดท้ายในไฟล์ (`breaking-without-coordination` · `semantics-change-without-rfc`
· `contract-change-unclear`) ไม่มี `check` เพราะใช้เฉพาะตอนรีวิว PR

## `manifest-drift` — กฎเดียวที่ออกเน็ต

เทียบ `consumes` ใน `ecosystem.yaml` กับ `platform-contract.yaml` **ของจริง** ในแต่ละ repo
เพราะแหล่งความจริงเรื่องการ pin คือ manifest ไม่ใช่ไฟล์ของเรา

ถ้าออกเน็ตไม่ได้ กฎนี้ถูก **ข้ามอย่างมีเสียง** — รายงานบอกว่าข้ามข้อไหน
ไม่ใช่รายงานว่า "ผ่าน" ทั้งที่ไม่ได้ตรวจ (มีเทสต์บังคับข้อนี้)

ผลรันจริงเมื่อ 2026-08-21: **ไม่พบ drift** — `ecosystem.yaml` ที่ทำใน M0 ตรงกับของจริงทุกตัว

## รีวิว PR (#23) — สามด่านก่อนจะคอมเมนต์จริง

```text
1. repo นั้นเปิดไว้ใน guardian.yaml   (default: ปิดทุก repo)
2. เรียกด้วย --post                    (default: แสดงคอมเมนต์เฉย ๆ)
3. ยังไม่เคยคอมเมนต์ finding ชุดเดิม   (fingerprint ในตัวคอมเมนต์)
```

ขาดข้อไหนก็คืนเหตุผลกลับมา ไม่เงียบ

**default คือปิดทุก repo และเปิดแล้วก็ยังเป็น `warn`** — bot ที่โผล่ไปคอมเมนต์ใน repo
ของทีมอื่นโดยไม่มีใครขอ คือ bot ที่จะถูกปิดภายในสัปดาห์เดียว
`guardian.yaml` มีหมายเหตุกำกับว่า repo ไหนควรคุยกับใครก่อนเปิด

### ไม่คอมเมนต์ซ้ำ

คอมเมนต์ทุกใบขึ้นต้นด้วย `<!-- ecosystem-guardian:<fingerprint> -->`
fingerprint คำนวณจากชุด `(rule, subject)` ที่เรียงแล้ว — ลำดับไม่ทำให้ต่างกัน
เจอ fingerprint เดิมบน PR ใบนั้นแล้วก็ข้าม

### คอมเมนต์จัดกลุ่มตามกฎ

กฎเดียวกันที่โดนหลาย contract พิมพ์คำอธิบายครั้งเดียว แล้วลิสต์ subject
— คอมเมนต์ที่ยาวเพราะซ้ำ คือคอมเมนต์ที่ไม่มีใครอ่านจนจบ

## เจอของจริงจาก PR จริง

รันกับ PR ของ `agent-platform` แล้วเจอ **false positive สองตัวใน M4** ซึ่งแก้ไปแล้ว

**1. heuristic `type:` หยาบเกินไป** — เห็น `type:` หายไปหนึ่งบรรทัดและโผล่มาอีกบรรทัด
แล้วสรุปว่า "เปลี่ยน type ของ field" ทั้งที่เป็นการย้าย definition ไปที่ `$defs`
ตอนนี้ลดเป็น *ไม่แน่ใจ* เพราะ diff ไม่ได้บอกว่าเป็นของ field ไหน

**2. `required: [a, b, c]` แบบ inline ไม่ถูกอ่านเลย** — ตัวอ่านรู้จักแต่แบบ block
ของจริงใช้ทั้งสองแบบ ตัวอ่านที่รู้จักแบบเดียวพลาดเงียบ ๆ

**และเจอกรณีที่ heuristic ไม่ควรตัดสินเลย** — [`agent-platform#33`](https://github.com/monthop-gmail/agent-platform/pull/33)
ย้าย `subject` ออกจาก `required` แล้วใส่ `oneOf(actor|subject)` แทน payload เดิมยัง valid ทุกใบ
แต่ diff แบบแบนอ่านว่า "เพิ่ม required field" → ตอนนี้เมื่อเจอ `oneOf`/`anyOf`/`if-then`
พร้อมกับ `required` ที่เปลี่ยน ระบบตอบ **ไม่แน่ใจ** ทันที และบอกว่าทำไม

## ผลรันปัจจุบัน

```text
ตรวจ 10 กฎ · error 0 · warn 12
```

warn ทั้ง 12 เป็นช่องว่างที่รู้อยู่แล้ว — plane ที่ยังไม่มีใครทำ 5 ตัว
และ contract ที่ยังไม่มีใคร pin 7 ตัว ไม่ใช่ความผิดพลาด แต่เป็นสิ่งที่ควรรู้ตัว
