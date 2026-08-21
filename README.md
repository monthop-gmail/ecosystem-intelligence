# ecosystem-intelligence

> **AI-powered engineering intelligence for multi-team, multi-repository ecosystems.**

ทำให้ทั้งองค์กร **รู้ว่าควรสร้างอะไร และทำไม** — ไม่ใช่ chatbot ให้ทีมถามตอบ แต่เป็นชั้น intelligence
ที่ทุกทีมถามจากมุมของตัวเองได้ โดย AI ใช้ **ภาพ ecosystem เดียวกัน** ในการตอบ

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
| **M0** | Ecosystem Foundation | นิยาม entity / relationship / ownership → `ecosystem.yaml` |
| **M1** | Knowledge Plane | PostgreSQL, Knowledge API, import ecosystem definition, repository registry |
| **M2** | Team Advisor | Team context, Ask API, LLM reasoning, recommended work ← **MVP อยู่ตรงนี้** |
| **M3** | GitHub Intelligence | Repository sync, issues, PRs, current work detection |
| **M4** | Impact Analysis | Dependency graph, change analysis, cross-team impact |
| **M5** | Architecture Guardian | Architecture / contract validation, PR & issue review |
| **M6** | Delivery Integration | เชื่อม agent-platform, devfactory-core, delivery orchestrator |

## Definition of Done (MVP)

ไม่วัดด้วยจำนวน agent หรือจำนวน feature แต่วัดด้วย scenario — มี 3 ทีม / 3 repo แล้วถามได้ว่า

1. **"Team A ควรทำอะไรต่อ?"** → ตอบโดยอ้าง ecosystem goal, capability, ownership, repository state, dependency, contract และงานที่ทีมอื่นกำลังทำ
2. **"ถ้าเราเปลี่ยน contract นี้ ใครได้รับผลกระทบ?"** → ตอบ affected teams / components / repositories / contracts + risks + recommended coordination

ถ้า demo นี้ผ่าน ถือว่าแกนถูกต้องแล้ว

## สถานะ

✅ **M0 — Ecosystem Foundation** — Ecosystem Map v0.1 พร้อมแล้ว
ครอบคลุมของจริง 15 contracts · 11 planes · 14 components · 14 repositories · 7 teams

```bash
make validate          # โครงสร้าง + referential integrity + กฎของ ecosystem
make validate-github   # ตรวจเพิ่มว่า repo ที่ประกาศไว้มีอยู่จริง
```

⏭️ ถัดไป **M1** — ยกข้อมูลชุดนี้ขึ้น Knowledge Plane ที่ query ได้

## ไฟล์สำคัญ

| ไฟล์ | คืออะไร |
| --- | --- |
| [`ecosystem.yaml`](ecosystem.yaml) | **Ecosystem Map v0.1** — แหล่งความจริงเรื่อง team, ownership และ repo↔component↔plane mapping |
| [`docs/entities.md`](docs/entities.md) | data model + เหตุผลที่เลือกแบบนี้ รวมถึงสิ่งที่จงใจไม่ทำ |
| [`schema/ecosystem.schema.json`](schema/ecosystem.schema.json) | JSON Schema ของไฟล์ข้างบน |
| [`tools/validate_ecosystem.py`](tools/validate_ecosystem.py) | validator — stdlib + pyyaml (jsonschema ถ้ามี) |

> ⚠️ **repo นี้ไม่ใช่เจ้าของ contract** — schema เป็นของ [`agent-platform`](https://github.com/monthop-gmail/agent-platform/tree/main/contracts)
> เปลี่ยนได้ผ่าน ADR เท่านั้น เราอ้างอิงและรวบรวม ไม่ประกาศแทน ([เหตุผล](docs/entities.md))

## Reference

- [`ref/chatgpt-ecosystem-overview.md`](ref/chatgpt-ecosystem-overview.md) — บทสนทนาออกแบบต้นทางฉบับเต็ม ที่มาของ architecture และ roadmap ทั้งหมดในไฟล์นี้
