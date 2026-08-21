# Ecosystem Entities, Relationships & Ownership

นิยาม data model ของ `ecosystem.yaml` — ปิด issue #1 (entities), #2 (relationships), #3 (ownership)

> **หลักที่ใช้ตัดสินทุกข้อในเอกสารนี้**
> model นี้ถูกบังคับด้วย repo ที่มีอยู่จริง ไม่ได้ออกแบบจากจินตนาการ
> ทุก entity ที่นิยามไว้ต้องมีตัวอย่างจริงอย่างน้อย 1 ตัวจาก ecosystem ปัจจุบัน

---

## 0. เราไม่ใช่เจ้าของข้อมูลทุกอย่าง — เรื่องนี้ต้องชัดก่อน

ก่อนจะนิยาม entity ต้องตอบก่อนว่า **อะไรเป็นของเรา อะไรไปอ่านจากที่อื่น** เพราะ ecosystem นี้
มีแหล่งความจริงอยู่แล้วสองแห่ง และการทำ registry ซ้อนขึ้นมาอีกชั้นคือความผิดพลาดที่แพงที่สุด
ที่ repo นี้ทำได้

| ข้อมูล | เจ้าของจริง | บทบาทของ `ecosystem-intelligence` |
| --- | --- | --- |
| **Contract schema + version** | [`agent-platform/contracts/`](https://github.com/monthop-gmail/agent-platform/tree/main/contracts) — เปลี่ยนได้ผ่าน ADR เท่านั้น | **อ้างอิง** ห้ามประกาศ contract ใหม่ที่นี่ |
| **Contract semantics ของ `approval` / `event`** | [`devfactory-core/contract-semantics.yaml`](https://github.com/monthop-gmail/devfactory-core/blob/main/contract-semantics.yaml) (ADR-0006 C2) | **อ้างอิง** |
| **repo ไหน pin contract อะไร** | `platform-contract.yaml` ใน repo ของ consumer แต่ละราย | **รวบรวม** ไม่ใช่ประกาศแทน |
| **ผลการ conform** | CI ของ consumer แต่ละราย | **รวบรวม** |
| **Plane boundary** | [`agent-platform/planes/`](https://github.com/monthop-gmail/agent-platform/tree/main/planes) | **อ้างอิง** |
| **Team / ownership / เป้าหมายระดับ ecosystem** | *ไม่มีใครเป็นเจ้าของ* | ✅ **เราเป็นเจ้าของ** |
| **repo ↔ component ↔ plane mapping ข้าม repo** | *ไม่มีใครเป็นเจ้าของ* | ✅ **เราเป็นเจ้าของ** |

ช่องว่างจริงที่ ecosystem นี้ยังไม่มีคือ **สองแถวล่าง** — นั่นคือเหตุผลที่ repo นี้ควรมีอยู่
ส่วนที่เหลือเรา *derive* ไม่ใช่ *author*

`agent-platform/architecture/consumers.md` ทำหน้าที่รวบรวมไปแล้วส่วนหนึ่ง — แต่เป็น Markdown
ที่คนดูแลด้วยมือ machine ใช้ต่อไม่ได้ และมองจากมุม "ใคร consume ฉัน" เท่านั้น
`ecosystem.yaml` เป็นรูปแบบที่ machine อ่านได้ และมองจากมุมของทั้ง ecosystem

---

## 1. Entities

### 1.1 `plane` — ขอบเขตทางสถาปัตยกรรม

หน่วยการแบ่งความรับผิดชอบระดับบนสุดของ ecosystem นี้ มี 11 ตัว นิยามโดย `agent-platform/planes/`

```yaml
- id: knowledge
  name: Knowledge Plane
  responsibility: ingest, retrieval, citation, ACL
  must_not:
    - generate คำตอบเอง (retrieval ไม่ generate)
  contracts: [tool/v1]
  source: https://github.com/monthop-gmail/agent-platform/blob/main/planes/knowledge.md
```

**ทำไมใช้ `plane` แทน `capability`** — แผนต้นทางเสนอ entity ชื่อ `Capability` แต่ ecosystem นี้
มี `capability/v1` เป็น **contract** อยู่แล้ว (ADR-0009) ซึ่งหมายถึง "สิ่งที่ agent ทำได้ในเวลา runtime"
คนละความหมายกับ "ความสามารถระดับธุรกิจ" ถ้าตั้งชื่อชนกันจะสับสนถาวร

และ `plane` ทั้ง 11 ตัว **คือการแบ่ง capability ของ ecosystem นี้อยู่แล้ว** — มีนิยามครบ
มีข้อห้ามครบ มีคนตัดสินชัด การเพิ่มชั้น capability ขนานขึ้นมาอีกโดยไม่มีข้อมูลใหม่
คือการ over-model ที่ M0 ตั้งใจหลีกเลี่ยง

> `must_not` ไม่ใช่ของประดับ — `agent-platform/planes/` ระบุ "สิ่งที่ห้ามทำ" ของทุก plane ไว้ชัด
> และนี่คือ input ตรงของ **M5 Architecture Guardian** ถ้าไม่เก็บตั้งแต่ M0 ต้องกลับมาทำใหม่

### 1.2 `component` — สิ่งที่ทำงานได้จริง

ผู้ implement plane หนึ่ง ๆ

```yaml
- id: enterprise-knowledge
  name: Enterprise Knowledge
  implements: [knowledge]
  owner: knowledge-team
  repository: enterprise-knowledge
  status: in-development
  consumes: [tool/v1]
  conformance: { status: unknown, manifest: false }
```

| ข้อ | กฎ |
| --- | --- |
| ต้องมี owner **หนึ่งทีมเท่านั้น** | ห้ามกำกวม — ดู §3 |
| `implements` เป็นลิสต์ว่างได้ | เมื่อ component อยู่นอกโมเดล plane ของ agent-platform (เช่น `navi-ims` ที่เป็น system of record, `model-gateway` ที่เป็น outbound, หรือ `ecosystem-intelligence` เองที่อยู่เหนือขึ้นไป) — ต้องใส่ `outside_plane_model: true` + `outside_plane_reason` กำกับ ไม่ใช่ปล่อยว่างเงียบ ๆ |
| `implements` มีได้หลาย plane | `agent-backend-os` เป็นทั้ง `backend-os` และบ้านของ native runtime ตาม ADR-0005 C2 — ความสัมพันธ์นี้จึงเป็น N:M ไม่ใช่ N:1 |
| `repository` เป็น `null` ได้ | component ที่วางแผนไว้แต่ยังไม่มี repo — เป็นสถานะที่ ecosystem นี้มีจริงถึง 7 ตัว |

**อะไรไม่ใช่ component** — โฟลเดอร์ในโค้ด, package ภายใน repo, และ plane เอง
ถ้ามันไม่มีสิทธิ์มี repo เป็นของตัวเองได้ในอนาคต มันไม่ใช่ component

### 1.3 `contract` — interface ระหว่าง component

**อ้างอิงเท่านั้น** — schema จริงอยู่ที่ `agent-platform`

```yaml
- id: approval/v1
  authority: agent-platform          # เจ้าของรูปร่างบน wire
  semantics_owner: devfactory-core   # เจ้าของความหมาย (ADR-0006 C2)
  status: v1
  derived: true
```

field `semantics_owner` มีอยู่เพราะ ecosystem นี้มีของจริงแบบนั้น — `approval/v1` และ `event/v1`
แยกเจ้าของ "รูปร่าง" กับ "ความหมาย" ออกจากกัน model ที่ไม่รองรับจะอธิบายสองตัวนี้ผิด

### 1.4 `repository` — ที่อยู่ของโค้ด

```yaml
- id: devfactory-core
  url: https://github.com/monthop-gmail/devfactory-core
  visibility: public
  default_branch: main
  exists: true
  manifest: platform-contract.yaml
```

`exists: false` เป็นสถานะที่ถูกต้อง ใช้กับ repo ที่ถูกอ้างถึงในแผนแต่ยังไม่มีตัวตน
— **ตรวจได้อัตโนมัติ** และเป็นตัวป้อนของ M1.4 Repository Registry

### 1.5 `team` — หน่วยที่รับผิดชอบ

```yaml
- id: platform-team
  name: Platform Team
  responsibilities: [contract authority, plane boundary, ADR]
  members: [monthop-gmail]
```

> ⚠️ **สภาพจริงตอนนี้: ทุกทีมมีสมาชิกคนเดียวกัน** — ecosystem นี้ยังเป็น personal account
> เราจงใจ**ไม่**ยุบ team ทิ้ง เพราะ team เป็นแกนของ M2 Team Advisor และเป็นสิ่งที่ต้องมีตอนสเกลจริง
> แต่ก็จงใจ**ไม่**แกล้งว่ามีหลายคน — validator จะเตือนเมื่อทุกทีมมี member ชุดเดียวกัน
> เพื่อไม่ให้ข้อมูลนี้ดูน่าเชื่อกว่าที่มันเป็น

### 1.6 อะไร **ไม่ใช่** entity นั้น — กันไม่ให้ model บวม

ทุก entity ต้องมีเส้นตัด ไม่งั้นอีกหกเดือนจะมีอะไรก็ได้อยู่ในนี้

| Entity | ไม่ใช่ |
| --- | --- |
| `plane` | ไม่ใช่ repo และไม่ใช่โฟลเดอร์ — `agent-platform/planes/` เก็บ**เอกสารขอบเขต** ไม่ใช่ code (ADR-0001) · plane เพิ่มใหม่ไม่ได้จากที่นี่ ต้องไปแก้ที่ `agent-platform` |
| `component` | ไม่ใช่ package ภายใน repo, ไม่ใช่โฟลเดอร์, ไม่ใช่ service ที่ deploy คู่กันเสมอ — **เกณฑ์ตัด: ถ้ามันไม่มีสิทธิ์มี repo เป็นของตัวเองได้ในอนาคต มันไม่ใช่ component** |
| `contract` | ไม่ใช่ API ภายในของ component และไม่ใช่ทุก interface — เป็น contract ต่อเมื่อผ่านเกณฑ์ 4 ข้อของ ADR-0012 (มีของเดิมตอบไม่ได้ · มี consumer ≥2 หรือ 1 ที่ใช้จริง+ระบุรายที่สองได้ · มี implementation จริง · มีเจ้าของ semantics ชัด) |
| `repository` | ไม่ใช่ทุก repo ใน account — เฉพาะ repo ที่มี component ของ ecosystem นี้อยู่ (`llm-gateway`, `botforge`, workshop ต่าง ๆ ไม่อยู่ในนี้จนกว่าจะมี component) |
| `team` | ไม่ใช่คน และไม่ใช่ GitHub team — เป็น**หน่วยรับผิดชอบ** ที่ยังคงอยู่แม้คนเปลี่ยน · คนคือ `members` |

---

## 2. Relationships

```text
Component  ──implements──▶   Plane            N:M   (ว่างได้ ถ้าอยู่นอก plane model)
Component  ──lives_in────▶   Repository       N:1   (repository เป็น null ได้)
Component  ──exposes─────▶   Contract         N:M
Component  ──consumes────▶   Contract         N:M   ◀── แกนหลักของ dependency
Component  ──depends_on──▶   Component        N:M   (ใช้เมื่ออธิบายด้วย contract ไม่ได้)
Team       ──owns────────▶   Component        1:N
Contract   ──authored_by─▶   Repository       N:1
Contract   ──semantics_by▶   Repository       N:1   (optional)
Plane      ──governed_by─▶   Contract         N:M
```

### 2.1 ตัดสินใจแล้ว: dependency ประกาศที่ระดับ **contract** ไม่ใช่ระดับ component

issue #2 ถามข้อนี้ไว้ คำตอบคือ contract และ ecosystem นี้พิสูจน์ให้เห็นแล้วว่าทำไม

```text
❌ ระดับ component:  devfactory-core  depends_on  agent-platform
   → บอกได้แค่ "พึ่งพากัน" เปลี่ยนอะไรก็ตามใน agent-platform ก็ดูเหมือนกระทบหมด

✅ ระดับ contract:   devfactory-core  consumes  execution/v1, identity/v1, policy/v1,
                                                error/v1, approval/v1, event/v1
   → เปลี่ยน tool/v1 → devfactory-core ไม่กระทบ  (พิสูจน์ได้ ไม่ใช่เดา)
   → เปลี่ยน execution/v1 → กระทบแน่ พร้อมบอกได้ว่า pin commit ไหนอยู่
```

M4 Impact Analysis ทั้ง milestone ยืนอยู่บนความละเอียดระดับนี้ ถ้า M0 เลือกผิดตรงนี้
M4 จะได้คำตอบที่กว้างจนใช้ตัดสินใจไม่ได้

`depends_on` ระดับ component ยังเก็บไว้ สำหรับความสัมพันธ์ที่ไม่ผ่าน contract จริง ๆ
(เช่น พึ่งพา data ตรง ๆ) — แต่ต้องมี `reason` กำกับเสมอ ไม่ให้ใช้เป็นทางลัด

### 2.1.1 `consumes` ต้องมีหลักฐาน — `expected_contracts` คือความตั้งใจ

ตอนใส่ข้อมูลจริงรอบแรกเราเผลอเขียนว่า `enterprise-knowledge` consumes `tool/v1` เพราะ
`planes/knowledge.md` ระบุไว้แบบนั้น — **ซึ่งผิด** repo นั้นยังไม่มี `platform-contract.yaml`
เลยด้วยซ้ำ ทะเบียนของ `agent-platform` เองก็นับ `tool/v1` ว่า *"ยังไม่มีใคร"*

ถ้าปล่อยไว้ M4 จะรายงาน dependency ที่ไม่มีอยู่จริง ซึ่งแย่กว่าไม่รายงานเลย
model จึงแยกสองอย่างนี้ออกจากกันถาวร

| field | ความหมาย | ที่มา | ใช้คำนวณ impact ได้ไหม |
| --- | --- | --- | --- |
| `consumes` | pin ไว้จริง | `platform-contract.yaml` ของ repo นั้น | ✅ ได้ |
| `expected_contracts` | *ควร* ใช้ตาม plane หรือ roadmap | เอกสาร / แผน | ❌ ไม่ได้ |

**validator บังคับกฎนี้:** component ที่ไม่มี `manifest` ประกาศ `consumes` ไม่ได้เลย
และ contract เดียวกันอยู่ทั้งสอง field พร้อมกันไม่ได้

ผลพลอยได้: รายการ contract ที่ยัง "ไม่มีใคร pin" ที่ validator พิมพ์ออกมา
**ตรงกับตาราง Version usage ของ `agent-platform` ทุกตัว** — เป็นการ cross-check ฟรี ๆ
ว่าเราอ่าน ecosystem ตรงกับที่เจ้าของ contract เข้าใจ

### 2.2 `conformance` — ไม่ใช่แค่ประกาศว่าใช้ แต่พิสูจน์แล้วว่าใช้ถูก

ADR-0006 แยกสองอย่างนี้ออกจากกัน และ model ของเราต้องแยกตาม

```yaml
conformance:
  status: passing            # passing | failing | unknown | waived
  manifest: platform-contract.yaml
  pinned_commit: 3a01ab9d0a68594463382b0ec618dc07ccf6408c
  last_verified: 2026-08-19
```

| ค่า | ความหมาย |
| --- | --- |
| `passing` | CI conformance ผ่าน **และ** `last_verified` ไม่เกิน 90 วัน |
| `failing` | test ไม่ผ่าน — ADR-0006 ห้ามปล่อย release |
| `unknown` | ไม่มี manifest / ไม่เคยรัน / `last_verified` เกิน 90 วัน |
| `waived` | ยกเว้นชั่วคราว ต้องมีวันหมดอายุ + issue อ้างอิง |

> **กฎ 90 วันเป็นของ ecosystem ไม่ใช่ของไฟล์** — `passing` ที่เก่าเกิน 90 วัน
> ต้องถูกคำนวณเป็น `unknown` โดย validator ไม่ว่าไฟล์จะเขียนว่าอะไร

### 2.3 Graph จริงจาก 3 repo ที่มีอยู่

ไม่ใช่ตัวอย่างสมมติ — ทุกเส้นในนี้ตรวจกับ repo จริงแล้วเมื่อ 2026-08-21

```text
                          agent-platform  (platform-team)
                          เจ้าของ contract ทั้ง 15 ตัว
                                    │ exposes
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
   identity/v1                 execution/v1                 tool/v1
   policy/v1                   approval/v1 🔗                    │
   error/v1                    event/v1   🔗                     │
        │                           │                           │
        │ consumes                  │ consumes                  │ expected
        ▼                           ▼                           ▼
  care-agent-platform         devfactory-core            enterprise-knowledge
  (care-team)                 (delivery-team)            (knowledge-team)
  ✅ passing 2026-08-19       ✅ passing 2026-08-19       ⚠️ unknown — ไม่มี manifest
  pin 7 contracts             pin 6 contracts            implements: knowledge plane
                                    │
                                    │ semantics_owner
                                    ▼
                          approval/v1 · event/v1  🔗
                          (รูปร่างเป็นของ agent-platform
                           ความหมายเป็นของ devfactory-core — ADR-0006 C2)
```

**อ่านอะไรได้จาก graph นี้บ้าง** — และนี่คือเหตุผลที่ M0 ต้องมาก่อน M4

```text
เปลี่ยน execution/v1   → กระทบ devfactory-core เท่านั้น (pin 3a01ab9)
เปลี่ยน tool/v1        → ไม่กระทบใครที่ยืนยันแล้ว แต่ enterprise-knowledge รออยู่
เปลี่ยน approval/v1    → ต้องไปแก้ที่ devfactory-core ก่อน ไม่ใช่ที่ agent-platform
ปิด identity/v1        → ไม่ได้ มี consumer 2 รายที่ passing อยู่
```

---

## 3. Ownership

### กฎ

1. **ทุก component ต้องมี owner เพียงหนึ่งทีม** — ห้าม `owners: [a, b]` เพราะ "รับผิดชอบร่วมกัน" แปลว่าไม่มีใครรับผิดชอบ
2. **component ที่ไม่มี owner = orphan** — เป็น error ของ validator ไม่ใช่ warning และไม่ใช่ค่า default เงียบ ๆ
3. **owner ของ contract คือ authority ไม่ใช่ทีม** — contract เป็นของ repo (`agent-platform`) ตามกติกา ADR ไม่ใช่ของทีมใดทีมหนึ่ง เพื่อไม่ให้เปลี่ยน contract ได้ด้วยอำนาจของทีม
4. **`semantics_owner` แยกจาก `authority` ได้** — มีของจริงแล้ว 2 ตัว (`approval/v1`, `event/v1`)

### Team map ปัจจุบัน

| Team | รับผิดชอบ | Components |
| --- | --- | --- |
| `platform-team` | contract authority, plane boundary, ADR | `agent-platform` |
| `delivery-team` | job lifecycle, governance, orchestration + เจ้าของ semantics ของ `approval`/`event` | `devfactory-core` |
| `knowledge-team` | retrieval, ACL, provenance, evaluation | `enterprise-knowledge` |
| `care-team` | domain consumer — care/memory | `care-agent-platform` |
| `harness-team` | execution policy ของ web build | `ai-web-harness` |
| `ims-team` | system of record (Odoo) | `navi-ims` |
| `ecosystem-team` | ecosystem knowledge + advisory | `ecosystem-intelligence` |

component ที่ยังไม่มี repo ให้ owner เป็นทีมที่จะรับไปทำจริง — ไม่ปล่อยว่าง เพราะ orphan เป็น error

---

## 4. สิ่งที่จงใจไม่ทำใน v0.1

| ไม่ทำ | เหตุผล |
| --- | --- |
| แตกเป็น 7 ไฟล์ YAML | cross-file reference จะเจ็บก่อนได้ประโยชน์ — แตกเมื่อโตจริง (issue #4) |
| entity `capability` แยกต่างหาก | ชนกับ `capability/v1` และ `plane` ทำหน้าที่นี้อยู่แล้ว (§1.1) |
| `ecosystem goal` / KPI | **เพิ่มแล้วใน M2 แต่ทำผิดรอบแรก** — ดู §5 |
| sync อัตโนมัติจาก GitHub | เป็นงานของ M3 — v0.1 ตั้งใจให้คนดูแลด้วยมือแต่ machine ตรวจได้ |
| เก็บ contract schema ไว้ที่นี่ | `agent-platform` เป็นเจ้าของ (§0) |


---

## 5. `mission.goals` — บทเรียนที่แพงที่สุดในเอกสารนี้

M0 เลื่อนเรื่องเป้าหมายไว้เพราะ "ยังไม่มีข้อมูลจริง ใส่ไปก็เป็นของปลอม"
พอถึง M2 ที่ DoD บังคับให้คำตอบต้องอ้าง **ecosystem goal** เราจึงเพิ่มเข้ามา 5 ข้อ
พร้อม `source` ที่ตรวจย้อนได้ทุกข้อ ดูเหมือนทำถูก

**แต่ 4 ใน 5 ไม่ใช่เป้าหมาย**

| ที่ติดป้ายว่าเป้าหมาย | จริง ๆ คือ |
| --- | --- |
| contract เป็นแหล่งความจริงเดียว | กติกา (ADR-0006) |
| conformance ต้องพิสูจน์ได้ | กลไก (ADR-0006 ข้อ 2) |
| ทุก component มีเจ้าของหนึ่งทีม | กฎ — ซ้ำกับ guardian `orphan-component` |
| ไม่สร้าง abstraction ซ้ำ | ข้อห้าม — ซ้ำกับ `duplicate-plane-implementation` |

ส่วนข้อที่ 5 (*ทุกทีมถาม AI ได้*) เป็นเป้าหมายของ **repo นี้** ไม่ใช่ของ ecosystem

### ทำไมมันแย่กว่าแค่ "ตั้งชื่อผิด"

guardian rule อ้าง goal เป็น `source` ส่วน goal ก็คือกฎข้อนั้นเขียนใหม่ — **อ้างวนกัน**
และ advisor ก็ตอบวนตาม: *"ทำให้ conform เพราะ conformance ต้องพิสูจน์ได้"*
ซึ่งไม่ใช่เหตุผล มันคือการพูดสิ่งเดิมสองรอบ

> เป้าหมายตอบว่า **"อยากไปถึงอะไร"** · กติกาตอบว่า **"ห้ามทำอะไร"** — คนละชั้น

และที่หนักที่สุด: **DoD ข้อ 1 ผ่านเพราะเราสร้างสิ่งที่ข้อสอบต้องการขึ้นมาเอง**
ค้นทั้ง 3 repo หาคำว่า goal / mission / KPI ได้ **0 ผลลัพธ์** — ecosystem นี้ไม่เคยเขียน
เป้าหมายไว้ที่ไหนเลย เราควรรายงานว่ามันหายไป แทนที่จะเอากติกามาเติมให้ครบ

### ที่แก้แล้ว

- เป้าหมายจริง 3 ข้อ **ตัดสินโดย Architecture Owner** ไม่ได้ derive จากเอกสารไหน
  และบันทึกว่าใครตัดสินเมื่อไหร่ — เพราะเป้าหมายที่ไม่มีเจ้าของคือเป้าหมายที่ใครก็แต่งเพิ่มได้
- guardian rule ชี้ไปต้นทางจริง (`planes/README.md`) ไม่ชี้มาที่ goal ที่เขียนกฎซ้ำ
- mapping กฎ→เป้าหมายไม่วนแล้ว: กฎเป็นกลไก เป้าหมายเป็นผลลัพธ์ และไม่ใช่ของเดียวกัน
- **schema ยอมให้ `goals` ว่างได้** — บังคับให้ต้องมี คือบังคับให้คนที่ยังไม่ได้ตัดสิน
  ไปแต่งขึ้นมา ซึ่งคือความผิดพลาดเดิมทุกประการ · ว่างแล้ว validator เตือนเอง
- เทสต์กันการถอยกลับ: ถ้าสี่ข้อเดิมโผล่กลับมาเป็นเป้าหมาย CI แดงทันที
