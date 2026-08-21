# ecosystem-intelligence

> **AI-powered engineering intelligence for multi-team, multi-repository ecosystems.**

ทำให้ทั้งองค์กร **รู้ว่าควรสร้างอะไร และทำไม** — ไม่ใช่ chatbot ให้ทีมถามตอบ แต่เป็นชั้น intelligence
ที่ทุกทีมถามจากมุมของตัวเองได้ โดย AI ใช้ **ภาพ ecosystem เดียวกัน** ในการตอบ

> **เป้าหมายของ repo นี้:** ทุกทีมถาม AI จากมุมของตัวเองได้ โดย AI ใช้ภาพ ecosystem เดียวกันในการตอบ
>
> เป้าหมายข้อนี้เคยอยู่ใน `mission.goals` ของ `ecosystem.yaml` ซึ่งผิดที่ — นั่นคือ
> เป้าหมายของ **ecosystem** ไม่ใช่ของ repo ใด repo หนึ่ง · ecosystem จะมีเป้าหมายนี้
> ก็ต่อเมื่อมันตัดสินใจว่าอยากมีเรา ซึ่งไม่ใช่สิ่งที่เราประกาศแทนได้

```text
                     ┌──────────────────────────────┐
                     │      ECOSYSTEM MISSION       │
                     │   Goals / Capabilities / KPI │
                     └───────────────┬──────────────┘
                                     │
                     ┌───────────────▼──────────────┐
                     │      ECOSYSTEM KNOWLEDGE     │
                     │  Architecture · Components   │
                     │  Contracts · Dependencies    │
                     │  Teams · Roadmap · Repos     │
                     └───────────────┬──────────────┘
                                     │
                     ┌───────────────▼──────────────┐
                     │         ECOSYSTEM AI         │
                     │  Planner · Impact Analyzer   │
                     │  Architecture Guardian       │
                     │  Dependency · Team Advisor   │
                     └───────────────┬──────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
         ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
         │ Team A  │            │ Team B  │            │ Team C  │
         │   AI    │            │   AI    │            │   AI    │
         └────┬────┘            └────┬────┘            └────┬────┘
              │                      │                      │
           Repo A                 Repo B                 Repo C
              └──────────────────────┼──────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  GitHub / Issues    │
                          │  PR / CI / Code     │
                          └─────────────────────┘
```

## ทำไมต้องเป็น repo แยก

responsibility คนละเรื่องกับที่มีอยู่:

| Repo | Responsibility |
| --- | --- |
| [`agent-platform`](https://github.com/monthop-gmail/agent-platform) | Agent execution platform — ทำให้ agent **ทำงานได้** |
| [`devfactory-core`](https://github.com/monthop-gmail/devfactory-core) | Development / delivery foundation — ทำให้ software **ถูกสร้างได้** |
| **`ecosystem-intelligence`** | เข้าใจทั้ง ecosystem และแนะนำทีม — ทำให้องค์กร **รู้ว่าควรสร้างอะไร และทำไม** |

## หลักการ

แยก 3 เรื่องออกจากกันให้ชัด

- **Ecosystem Truth** — ecosystem เป็นอะไร (capability, component, contract, dependency, owner, repository, architecture)
- **Team Context** — ทีมนี้รับผิดชอบอะไร (responsibilities, current work, sprint, repos, dependencies)
- **AI Reasoning** — เอาสองอย่างข้างบนมาวิเคราะห์ตอบคำถามของทีม

MVP **เป็น Advisor ก่อน ไม่ใช่ autonomous agent**

## Roadmap

งานทั้งหมดแตกเป็น issue ไว้แล้วใต้ [milestones](https://github.com/monthop-gmail/ecosystem-intelligence/milestones) (26 issues)

| Milestone | ชื่อ | สาระ |
| --- | --- | --- |
| **M0** ✅ | Ecosystem Foundation | นิยาม entity / relationship / ownership → `ecosystem.yaml` |
| **M1** ✅ | Ecosystem Graph | PostgreSQL, Ecosystem Graph API, import ecosystem definition, repository registry |
| **M2** ✅ | Team Advisor | Team context, Ask API, LLM reasoning, recommended work ← **MVP อยู่ตรงนี้** |
| **M3** ✅ | GitHub Intelligence | Repository sync, issues, PRs, current work detection |
| **M4** ✅ | Impact Analysis | Dependency graph, change analysis, cross-team impact |
| **M5** ✅ | Architecture Guardian | Architecture / contract validation, PR & issue review |
| **M6** ✅ | Delivery Integration | เชื่อม agent-platform, devfactory-core, delivery orchestrator |

## Definition of Done (MVP)

ไม่วัดด้วยจำนวน agent หรือจำนวน feature แต่วัดด้วย scenario — มี 3 ทีม / 3 repo แล้วถามได้ว่า

1. **"Team A ควรทำอะไรต่อ?"** → ตอบโดยอ้าง ecosystem goal, capability, ownership, repository state, dependency, contract และงานที่ทีมอื่นกำลังทำ
2. **"ถ้าเราเปลี่ยน contract นี้ ใครได้รับผลกระทบ?"** → ตอบ affected teams / components / repositories / contracts + risks + recommended coordination

ถ้า demo นี้ผ่าน ถือว่าแกนถูกต้องแล้ว

## สถานะ

| Milestone | สถานะ |
| --- | --- |
| **M0 — Ecosystem Foundation** | ✅ เสร็จ — Ecosystem Map v0.1 |
| **M1 — Ecosystem Graph** | ✅ เสร็จ — PostgreSQL + import + read-only API + registry |
| **M2 — Team Advisor** | ✅ เสร็จ — **MVP** · DoD scenario ผ่าน |
| **M3 — GitHub Intelligence** | ✅ เสร็จ — sync issue/PR + current work detection |
| **M4 — Impact Analysis** | ✅ เสร็จ — dependency graph + breaking detection + ร่าง issue |
| **M5 — Architecture Guardian** | ✅ เสร็จ — 16 กฎในไฟล์ + รีวิว PR (default ปิด) |
| **M6 — Delivery Integration** | ✅ เสร็จ — เป็น consumer ที่ conform + client + วงจรปิด |

ครอบคลุมของจริง **15 contracts · 11 planes · 14 components · 14 repositories · 7 teams**

## เริ่มใช้งาน

```bash
docker compose --profile app up -d --build   # db + api ในคอนเทนเนอร์
curl localhost:8000/health
```

หรือรันจาก source

```bash
make install           # .venv + dependency
cp .env.example .env

make validate          # ตรวจ ecosystem.yaml — ไม่ต้องมี DB
make up && make schema # PostgreSQL (พอร์ต 55434) + migration
make import            # นำ ecosystem.yaml เข้า graph
make api               # http://localhost:8000/docs
```

```bash
make guardian                           # ตรวจ ecosystem ตาม 14 กฎ
make guardian-pr PR=agent-platform#33   # รีวิว PR (ไม่โพสต์จนกว่าจะเปิดและยืนยัน)
make graph COMPONENT=agent-platform     # ต้นไม้ dependency
make impact CONTRACT=approval/v1 LEVEL=breaking
make impact PR=agent-platform#35        # วิเคราะห์ PR จาก diff จริง
make sync        # ดึง issue/PR จาก GitHub เข้า graph (incremental)
make work        # ตอนนี้ใครทำอะไรอยู่ + งานซ้ำข้ามทีม
make ask TEAM=delivery-team Q="ทีมเราควรทำอะไรต่อ?"   # ถาม advisor
make conformance # event ที่ปล่อยออกไป conform กับ event/v1 ไหม
make feedback    # เทียบ ecosystem.yaml กับของจริง แล้วเสนอส่วนต่าง
make health      # รายงานสุขภาพ ecosystem (CI รันทุกวัน)
make provider    # ดูว่าตอนนี้ใช้ LLM ตัวไหน
make test        # unit test — ไม่ต้องมี DB (ที่ต้องใช้ DB จะข้ามเอง)
make test-all    # ทั้งหมด
make registry    # ทะเบียน repository + เทียบกับ GitHub จริง
```

## ถาม advisor

```bash
curl localhost:8000/ask -H 'content-type: application/json' \
  -d '{"team":"knowledge-team","question":"ทีมเราควรทำอะไรต่อ?"}'
```
```text
[1] ทำให้ enterprise-knowledge conform ตาม ADR-0006
    enterprise-knowledge ยังไม่มี manifest — platform นับเป็น unknown
    ซึ่งมีผลตอนตัดสินใจปิด contract version
    อ้างอิง: enterprise-knowledge, enterprise-knowledge#17, declared-equals-real
```

LLM รองรับ **Claude** และ **ChatGPT** สลับได้ด้วย config ตัวเดียว
default เป็น `offline` (rule engine ในเครื่อง) เพื่อให้รันและเทสต์ได้โดยไม่ต้องมี API key
— รายละเอียดที่ [`docs/llm.md`](docs/llm.md)

หลัง `make sync` advisor จะรู้ด้วยว่ามี issue เรื่องนี้เปิดค้างอยู่แล้วหรือยัง
และเตือนได้เมื่อทีมอื่น**กำลังทำ**เรื่องเดียวกันอยู่ — [`docs/github.md`](docs/github.md)

ทุกคำตอบผ่าน **grounding check** — id ที่ model อ้างถึงต้องมีอยู่ใน ecosystem จริง
ถ้าแต่งขึ้นมา `grounding.ok` เป็น false พร้อมบอกว่าแต่งอะไร

## ตัวอย่างที่ตอบได้แล้ววันนี้

```bash
curl localhost:8000/contracts/execution/v1/impact
```
```json
{ "affected_components": ["devfactory-core"],
  "affected_teams": ["delivery-team"],
  "consumers": [{ "conformance": "passing", "pinned_commit": "3a01ab9d…" }],
  "expected_by": ["agent-backend-os", "agent-fleet"],
  "closable": false }
```

```bash
curl localhost:8000/teams/delivery-team/components      # ทีมนี้ดูแลอะไร
curl localhost:8000/components/agent-platform/dependents # เปลี่ยนแล้วใครกระทบ
curl localhost:8000/graph/cycles                         # มี circular dependency ไหม
```

## ไฟล์สำคัญ

| ไฟล์ | คืออะไร |
| --- | --- |
| [`ecosystem.yaml`](ecosystem.yaml) | **แหล่งความจริง** — team, ownership, repo↔component↔plane mapping · DB เป็นแค่สำเนาที่ query ได้ |
| [`docs/entities.md`](docs/entities.md) | data model + เหตุผลที่เลือกแบบนี้ + สิ่งที่จงใจไม่ทำ |
| [`schema/ecosystem.schema.json`](schema/ecosystem.schema.json) | JSON Schema ของไฟล์ข้างบน |
| [`migrations/`](migrations/) | schema ของ graph — ไม่แก้ด้วยมือ |
| [`src/ecosystem_graph/`](src/ecosystem_graph/) | validate · migrate · import · queries · api · registry |
| [`docs/llm.md`](docs/llm.md) | ชั้น LLM — provider, prompt caching, grounding |
| [`docs/github.md`](docs/github.md) | GitHub sync, declared vs in-progress, งานซ้ำข้ามทีม |
| [`docs/impact.md`](docs/impact.md) | dependency graph, breaking detection, ลำดับการประสาน |
| [`docs/guardian.md`](docs/guardian.md) | กฎ 14 ข้อ, manifest drift, การรีวิว PR |
| [`docs/deploy.md`](docs/deploy.md) | Dockerfile, compose profile, ทำไม migration ไม่รันเองตอนบูต |
| [`docs/integration.md`](docs/integration.md) | เป็น consumer ของ event/v1, client สำหรับ repo อื่น, วงจรปิด |
| [`platform-contract.yaml`](platform-contract.yaml) | consumer manifest ตาม ADR-0006 |
| [`guardian.yaml`](guardian.yaml) | เปิด/ปิด Guardian รายrepo — **default ปิดทั้งหมด** |
| [`evaluation/questions.yaml`](evaluation/questions.yaml) | ชุดคำถามทดสอบ + คำตอบที่คาดหวัง |
| [`docs/openapi.json`](docs/openapi.json) | OpenAPI spec — CI ตรวจว่าตรงกับโค้ดเสมอ |

> ⚠️ **repo นี้ไม่ใช่เจ้าของ contract** — schema เป็นของ [`agent-platform`](https://github.com/monthop-gmail/agent-platform/tree/main/contracts)
> เปลี่ยนได้ผ่าน ADR เท่านั้น เราอ้างอิงและรวบรวม ไม่ประกาศแทน ([เหตุผล](docs/entities.md))
>
> ⚠️ **API อ่านอย่างเดียว** — บังคับด้วย `SET TRANSACTION READ ONLY` ที่ระดับ PostgreSQL
> ไม่ใช่แค่ไม่มี route ที่เขียน · การเปลี่ยนแปลงทำผ่าน `make import` ทางเดียว

## Reference

- [`ref/chatgpt-ecosystem-overview.md`](ref/chatgpt-ecosystem-overview.md) — บทสนทนาออกแบบต้นทางฉบับเต็ม ที่มาของ architecture และ roadmap ทั้งหมดในไฟล์นี้
