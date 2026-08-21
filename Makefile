PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: help install validate validate-github up down schema import import-dry \
        registry api openapi sync work graph mermaid impact guardian guardian-pr health \
        conformance feedback emit emit-sample \
        ask provider eval test test-all fmt

help:
	@echo "  make install          ติดตั้ง dependency ลง .venv"
	@echo ""
	@echo "  M0 — Ecosystem Map"
	@echo "  make validate         ตรวจ ecosystem.yaml (โครงสร้าง + referential integrity + กฎ)"
	@echo "  make validate-github  ตรวจเพิ่มว่า repo ที่ประกาศไว้มีอยู่จริงบน GitHub"
	@echo ""
	@echo "  M1 — Ecosystem Graph"
	@echo "  make up               ยก PostgreSQL ขึ้น (พอร์ต 55434)"
	@echo "  make schema           รัน migration"
	@echo "  make import           นำ ecosystem.yaml เข้า DB  (import-dry = ดูส่วนต่างเฉย ๆ)"
	@echo "  make registry         ทะเบียน repository + เทียบกับ GitHub จริง"
	@echo "  make api              รัน Ecosystem Graph API ที่ http://localhost:8000/docs"
	@echo "  make openapi          เขียน docs/openapi.json ใหม่"
	@echo ""
	@echo ""
	@echo "  M2 — Team Advisor"
	@echo "  make ask TEAM=delivery-team Q=\"ทีมเราควรทำอะไรต่อ?\"    ถาม advisor จาก CLI"
	@echo "  make provider         ดูว่าตอนนี้ใช้ LLM provider ตัวไหน"
	@echo "  make eval [P=offline,claude,chatgpt]  เทียบ provider ด้วยชุดคำถามทดสอบ"
	@echo ""
	@echo ""
	@echo "  M3 — GitHub Intelligence"
	@echo "  make sync             ดึง issue/PR/commit จาก GitHub เข้า graph (incremental)"
	@echo "  make work             ตอนนี้ใครทำอะไรอยู่ + งานซ้ำข้ามทีม"
	@echo ""
	@echo ""
	@echo "  M4 — Impact Analysis"
	@echo "  make graph COMPONENT=agent-platform [DIR=down]   ต้นไม้ dependency"
	@echo "  make impact CONTRACT=approval/v1 [LEVEL=breaking] ผลกระทบข้ามทีม + ร่าง issue"
	@echo "  make impact PR=agent-platform#35                  วิเคราะห์ PR จาก diff จริง"
	@echo "  make mermaid          graph ทั้ง ecosystem เป็น mermaid"
	@echo ""
	@echo ""
	@echo "  M5 — Architecture Guardian"
	@echo "  make guardian [REMOTE=1]              ตรวจทั้ง ecosystem"
	@echo "  make guardian-pr PR=agent-platform#33 [POST=1]   รีวิว PR"
	@echo ""
	@echo ""
	@echo ""
	@echo "  M6 — Delivery Integration"
	@echo "  make conformance      ตรวจว่า event ที่ปล่อยออกไป conform กับ event/v1"
	@echo "  make feedback         เทียบ ecosystem.yaml กับของจริง แล้วเสนอส่วนต่าง"
	@echo "  make emit [TEAM=...]  ปล่อย event/v1 (ไม่ใส่ TEAM = ทุกทีม + guardian)"
	@echo "  make emit-sample      สร้างตัวอย่างที่ตรึงเวลาไว้ ให้ปลายทางเทสต์ได้"
	@echo ""
	@echo "  รายงานรวม"
	@echo "  make health [REMOTE=1] รายงานสุขภาพ ecosystem เป็น markdown"
	@echo ""
	@echo "  make test             unit test — ไม่ต้องมี DB"
	@echo "  make test-all         test ทั้งหมด — ต้องมี DB"
	@echo "  make down             ปิด DB (ข้อมูลยังอยู่)"

install:
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -e ".[dev]"

validate:
	@$(PY) tools/validate_ecosystem.py

validate-github:
	@$(PY) tools/validate_ecosystem.py --github

up:
	docker compose up -d --wait

down:
	docker compose down

schema:
	@$(PY) -m ecosystem_graph.migrate

import:
	@$(PY) -m ecosystem_graph.importer

import-dry:
	@$(PY) -m ecosystem_graph.importer --dry-run

registry:
	@$(PY) -m ecosystem_graph.registry

api:
	@$(PY) -m uvicorn ecosystem_graph.api:app --reload --port 8000

openapi:
	@$(PY) tools/export_openapi.py

conformance:
	@$(PY) conformance/payload_check.py

feedback:
	@$(PY) -m ecosystem_graph.integration.feedback

emit:
	@$(PY) -m ecosystem_graph.integration.emit $(if $(TEAM),--team "$(TEAM)",--all)

emit-sample:
	@$(PY) -m ecosystem_graph.integration.emit --all --format jsonl \
		--occurred-at 2026-01-01T00:00:00Z --out integration/events/sample.jsonl

health:
	@$(PY) -m ecosystem_graph.health $(if $(REMOTE),--remote,)

guardian:
	@$(PY) -m ecosystem_graph.cli_guardian $(if $(REMOTE),--remote,)

guardian-pr:
	@$(PY) -m ecosystem_graph.cli_guardian --pr "$(PR)" $(if $(POST),--post,)

graph:
	@$(PY) -m ecosystem_graph.cli_impact --graph "$(COMPONENT)" --direction "$(or $(DIR),down)"

mermaid:
	@$(PY) -m ecosystem_graph.cli_impact --mermaid

impact:
ifdef PR
	@$(PY) -m ecosystem_graph.cli_impact --pr "$(PR)"
else
	@$(PY) -m ecosystem_graph.cli_impact --contract "$(CONTRACT)" --level "$(or $(LEVEL),unsure)"
endif

sync:
	@$(PY) -m ecosystem_graph.github.sync

work:
	@$(PY) -m ecosystem_graph.github.work

ask:
	@$(PY) -m ecosystem_graph.cli_ask --team "$(TEAM)" --question "$(Q)"

eval:
	@$(PY) -m ecosystem_graph.evaluation "$(or $(P),offline)" $(if $(SAVE),--save,)

provider:
	@$(PY) -c "from ecosystem_graph.llm import get_provider; p=get_provider(); print(f'provider={p.name} model={p.model}')"

test:
	@$(PY) -m pytest -q

test-all:
	@$(PY) -m pytest -q -m ""
