PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: help install validate validate-github up down schema import import-dry \
        registry api openapi ask provider test test-all fmt

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

ask:
	@$(PY) -m ecosystem_graph.cli_ask --team "$(TEAM)" --question "$(Q)"

provider:
	@$(PY) -c "from ecosystem_graph.llm import get_provider; p=get_provider(); print(f'provider={p.name} model={p.model}')"

test:
	@$(PY) -m pytest -q

test-all:
	@$(PY) -m pytest -q -m ""
