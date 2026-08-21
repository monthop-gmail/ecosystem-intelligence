.PHONY: validate validate-github help

help:
	@echo "make validate         ตรวจ ecosystem.yaml (โครงสร้าง + referential integrity + กฎ)"
	@echo "make validate-github  ตรวจเพิ่มว่า repo ที่ประกาศไว้มีอยู่จริงบน GitHub"

validate:
	@python3 tools/validate_ecosystem.py

validate-github:
	@python3 tools/validate_ecosystem.py --github
