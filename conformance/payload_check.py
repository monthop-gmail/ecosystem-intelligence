#!/usr/bin/env python3
"""Conformance ของ ecosystem-intelligence ต่อ event/v1 (ADR-0006 ข้อ 2)

**ไม่มี fixture ที่เขียนขึ้นเพื่อให้ schema ผ่าน** — payload ทุกใบที่ตรวจในนี้
ผลิตจากการรัน advisor และ guardian กับข้อมูล ecosystem จริง

ตรวจสองชั้น
    1. JSON Schema ของ event/v1 ที่ pin ไว้ใน conformance/pinned.yaml
    2. guarantee ที่ JSON Schema ตรวจไม่ได้ — 8 ข้อด้านล่าง

รัน: python conformance/payload_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ecosystem_graph import advisor, queries  # noqa: E402
from ecosystem_graph.db import connect  # noqa: E402
from ecosystem_graph.guardian import checks  # noqa: E402
from ecosystem_graph.integration import events  # noqa: E402

SCHEMAS = ROOT / "conformance" / "schemas"
PINNED = yaml.safe_load((ROOT / "conformance" / "pinned.yaml").read_text(encoding="utf-8"))

# คำที่ห้ามโผล่ใน metadata — event/v1 invariant: ห้ามเก็บ private reasoning
FORBIDDEN_KEYS = {"thinking", "reasoning", "chain_of_thought", "scratchpad", "raw_response"}


def _validator() -> Draft202012Validator:
    ev = yaml.safe_load((SCHEMAS / "event-v1.schema.yaml").read_text(encoding="utf-8"))
    idn = yaml.safe_load((SCHEMAS / "identity-v1.schema.yaml").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (idn["$id"], Resource(contents=idn, specification=DRAFT202012)),
        (ev["$id"], Resource(contents=ev, specification=DRAFT202012)),
    ])
    return Draft202012Validator(ev, registry=registry)


def collect() -> list[dict]:
    """ผลิต payload จากการทำงานจริง ไม่ใช่เขียนตัวอย่างขึ้นมา"""
    produced: list[dict] = []
    with connect(readonly=True) as conn:
        for team in queries.list_teams(conn):
            result = advisor.ask(conn, team["id"], "ทีมเราควรทำอะไรต่อ?")
            if result:
                produced.extend(events.advisory_events(result))
        report = checks.run_all(conn)
        produced.extend(events.drift_events(report["findings"]))
    return produced


def guarantees(payloads: list[dict]) -> list[str]:
    """8 ข้อที่ JSON Schema ตรวจไม่ได้ — มาจาก invariant ที่กำกับไว้ใน event/v1"""
    problems: list[str] = []

    # 1. event_id ต้องไม่ซ้ำ — audit log ที่มี id ซ้ำคือ log ที่อ้างอิงไม่ได้
    ids = [e["event_id"] for e in payloads]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        problems.append(f"event_id ซ้ำ: {sorted(dupes)}")

    for e in payloads:
        tag = e["event_id"]

        # 2. tenant ต้อง resolve ได้เสมอ — ห้ามเดา ห้ามว่าง
        if not e.get("tenant_id"):
            problems.append(f"{tag}: ไม่มี tenant_id")

        # 3. ทุกใบต้องตอบได้ว่าเกี่ยวกับอะไร
        if not e.get("subject_type") or not e.get("subject_id"):
            problems.append(f"{tag}: subject ตอบไม่ได้")

        # 4. external ต้องคง source ไว้ตลอดไป
        if e.get("source", {}).get("kind") != "external":
            problems.append(f"{tag}: source.kind ต้องเป็น external")
        if not e.get("source", {}).get("system"):
            problems.append(f"{tag}: ไม่ได้บอกว่ามาจากระบบไหน")

        # 5. ห้ามปลอม job_id — เราไม่ได้เกิดจาก job จึงต้องไม่มี field นี้เลย
        if "job_id" in e:
            problems.append(f"{tag}: ใส่ job_id ทั้งที่ไม่ได้เกิดจาก job")

        # 6. ห้ามเก็บ chain-of-thought เป็น audit record
        meta = e.get("metadata") or {}
        leaked = FORBIDDEN_KEYS & set(meta)
        if leaked:
            problems.append(f"{tag}: metadata มี {sorted(leaked)}")

        # 7. subject_type=record ต้องบอกชนิดจริงใน metadata.record_type
        if e["subject_type"] == "record" and not meta.get("record_type"):
            problems.append(f"{tag}: subject_type=record แต่ไม่มี metadata.record_type")

    # 8. sequence ใช้เรียงภายใน correlation เดียวกัน ต้องไม่ซ้ำกันเอง
    by_corr: dict[str, list[int]] = {}
    for e in payloads:
        if e.get("correlation_id") and e.get("sequence") is not None:
            by_corr.setdefault(e["correlation_id"], []).append(e["sequence"])
    for corr, seqs in by_corr.items():
        if len(seqs) != len(set(seqs)):
            problems.append(f"correlation {corr}: sequence ซ้ำกันเอง")

    return problems


def main() -> int:
    print(f"pin: {PINNED['repo']} @ {PINNED['commit'][:12]}\n")
    payloads = collect()
    if not payloads:
        print("❌ ไม่ได้ payload สักใบ — conformance ที่ไม่มีของให้ตรวจไม่ใช่ conformance")
        return 1

    validator = _validator()
    schema_errors = []
    for e in payloads:
        for err in validator.iter_errors(e):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            schema_errors.append(f"{e['event_id']} · {loc}: {err.message[:120]}")

    problems = guarantees(payloads)

    by_type: dict[str, int] = {}
    for e in payloads:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    print(f"ตรวจ {len(payloads)} event ที่ผลิตจากการทำงานจริง")
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")

    for err in schema_errors:
        print(f"  ❌ schema  {err}")
    for p in problems:
        print(f"  ❌ guarantee  {p}")

    if schema_errors or problems:
        print(f"\n❌ conformance ไม่ผ่าน — schema {len(schema_errors)} · guarantee {len(problems)}")
        return 1
    print(f"\n✅ conformance ผ่าน — schema ครบทุกใบ · guarantee 8 ข้อครบ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
