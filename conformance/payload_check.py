#!/usr/bin/env python3
"""Conformance ของ ecosystem-intelligence ต่อ event/v1 (ADR-0006 ข้อ 2)

**ไม่มี fixture ที่เขียนขึ้นเพื่อให้ schema ผ่าน** — payload ทุกใบที่ตรวจในนี้
ผลิตจากการรัน advisor และ guardian กับข้อมูล ecosystem จริง

ตรวจสองชั้น
    1. JSON Schema ของ event/v1 ที่ pin ไว้ใน conformance/pinned.yaml
    2. guarantee ที่ JSON Schema ตรวจไม่ได้ — 10 ข้อด้านล่าง

รัน: python conformance/payload_check.py
"""
from __future__ import annotations

import re
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

MANIFEST = yaml.safe_load((ROOT / "platform-contract.yaml").read_text(encoding="utf-8"))
DECLARED_TEXT = {f["path"] for f in MANIFEST.get("text_fields") or []}
POINTER_LEAVES = {f["path"] for f in MANIFEST.get("pointer_leaves") or []}
DECIDED_LEAVES = DECLARED_TEXT | POINTER_LEAVES
THAI = re.compile(r"[\u0e00-\u0e7f]")


def _leaves(node, path="$"):
    """เดินถึง leaf — object กับ array เป็นภาชนะ ไม่ใช่ค่า (RFC-0013 ข้อ 1)"""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, f"{path}.{k}")
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v, f"{path}[]")
    else:
        yield path, node


def _is_human_text(v) -> bool:
    """เอนเอียงไปทาง 'ใช่' โดยตั้งใจ — ถูกบังคับให้ประกาศเกิน ดีกว่าหลุดโดยไม่มีใครเห็น"""
    return isinstance(v, str) and (" " in v or len(v) > 64 or bool(THAI.search(v)))


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

        # ในสถานะปกติ guardian ไม่มี error — ซึ่งแปลว่า ECOSYSTEM_DRIFT_DETECTED
        # **ไม่เคยถูกตรวจเลยสักใบตั้งแต่เขียนมา** · metadata.detail กับ metadata.fix
        # ไม่เคยผ่านตาตัวไล่ leaf ของ guarantee 9 ทั้งที่ประกาศไว้ใน text_fields
        #
        # นี่คือ "fixture เล็กกว่าสิ่งที่มันแทน" ซึ่งเราสองฝั่งเจอกันมาแล้วคนละครั้ง
        # (devfactory-core: external metadata เป็น {} · เรา: sequence scope ผิด)
        #
        # ไม่เขียน fixture ขึ้นมาใหม่ — ยกป้าย severity ของ finding จริงจากรอบเดียวกัน
        # ตัวอักษรทุกตัวมาจากกฎจริงกับ subject จริง มีแต่ป้ายที่ยก
        if not any(e["event_type"] == events.DRIFT_DETECTED for e in produced):
            lifted = [{**f, "severity": "error"} for f in report["findings"]
                      if f["severity"] == "warn"]
            produced.extend(events.drift_events(lifted))
    return produced


def guarantees(payloads: list[dict]) -> list[str]:
    """10 ข้อที่ JSON Schema ตรวจไม่ได้ — มาจาก invariant ที่กำกับไว้ใน event/v1"""
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

    # 9. สำมะโน leaf เป็นชุดปิด — ทุกเส้นทางต้องมีคนตัดสินแล้ว
    #    (event/v1 semantics 1.3/1.5 · devfactory-core RFC-0013 ข้อ 1–2 · RFC-0017)
    #
    # เดิมข้อนี้ตัดสินจาก **ค่า**: leaf ไหนหน้าตาเหมือนข้อความของคน (มีช่องว่าง
    # ยาวเกิน 64 มีอักษรไทย) ต้องประกาศ · ที่เหลือปล่อยผ่าน
    #
    # ซึ่งแปลว่า 'Somchai' 'Ann' 'somchai@example.com' '0812345678' ผ่านหมด —
    # และนั่นคือ actor.display_name ที่ care-agent-platform โดนมาแล้วจริง
    # ตัวตรวจ **เดินถึง leaf เห็นค่า แล้วเดาผิด** ไม่ใช่เดินไม่ถึง
    #
    # ตอนนี้ตัดสินจาก **เส้นทาง** — เส้นทางเป็นสิ่งที่มีคนตัดสิน ค่าเป็นสิ่งที่ตัวตรวจเดา
    # leaf เส้นทางใหม่ที่ยังไม่มีใครตัดสินใจเรื่องมัน = แดง ไม่ใช่ผ่านเงียบ
    # (รูปนี้มาจาก botforge ในโต๊ะกลาง 20 ก.ย.)
    wild = sorted(p for p in DECIDED_LEAVES if "*" in p)
    if wild:
        problems.append(f"ใบประกาศมี wildcard {wild} — จะกลืน ratchet ของตัวเอง "
                        f"key ใหม่ที่เป็นข้อความของคนจะผ่านเพราะ 'ประกาศไว้แล้ว'")

    unknown: dict[str, str] = {}
    pointer_holding_text: dict[str, str] = {}
    walked = 0
    for e in payloads:
        for path, value in _leaves(e):
            walked += 1
            if path not in DECIDED_LEAVES:
                unknown.setdefault(path, str(value)[:60])
            elif path in POINTER_LEAVES and _is_human_text(value):
                pointer_holding_text.setdefault(path, str(value)[:60])
    for path, sample in sorted(unknown.items()):
        problems.append(f"{path}: leaf เส้นทางนี้ยังไม่มีใครตัดสินว่าเป็นตัวชี้หรือข้อความของคน "
                        f"— ใส่ใน pointer_leaves หรือ text_fields ก่อน · ตัวอย่างค่า {sample!r}")
    for path, sample in sorted(pointer_holding_text.items()):
        problems.append(f"{path}: ประกาศไว้ว่าเป็นตัวชี้ แต่ค่าที่ปล่อยจริงเป็นข้อความ "
                        f"— {sample!r}")

    # ตัวตรวจที่ตอบว่า "ไม่เจอ" ต้องบอกด้วยว่ามันเดินไปกี่ที่ — ศูนย์จากการเดิน N ที่
    # กับศูนย์จากการไม่ได้เดิน เป็นคนละคำตอบ (devfactory-core ในโต๊ะกลาง 20 ก.ย.)
    problems.append(f"__walked__{walked}")

    # 10. คำนวณ event_id ซ้ำจากใบเองต้องได้ค่าเดิม
    #
    # นี่คือสิ่งที่ทำให้ "id ผูกกับเนื้อหา" เป็นคำสัญญาที่ตรวจได้ ไม่ใช่คำอธิบาย
    # พฤติกรรม — devfactory-core#32 ถามตรง ๆ ว่ามันเป็นอันไหน และ store ของเขา
    # ปฏิเสธของซ้ำด้วย event_id ถ้า id ขยับตามถ้อยคำ log เขาจะบวมเงียบ ๆ
    for e in payloads:
        try:
            expect = events.event_id_for(e)
        except ValueError as err:
            problems.append(f"{e['event_id']}: {err}")
            continue
        if expect != e["event_id"]:
            problems.append(f"{e['event_id']}: คำนวณซ้ำจากใบได้ {expect} — id ไม่ได้ผูกกับตัวตน")

    # 8. sequence เรียง event **ภายใน subject เดียวกัน** ไม่ใช่ภายใน correlation
    #
    # เดิมตรวจที่ระดับ correlation ซึ่งเป็นคนละ scope กับที่ event/v1 นิยามไว้
    # ทำให้ผ่านทั้งที่ทุก subject มี event ใบเดียวและ sequence เป็น 1 ตลอด
    # — field ที่มีค่าแต่ไม่พาข้อมูล หลอกผู้อ่านให้คิดว่าเรียงได้ (devfactory-core#32)
    by_subject: dict[str, list[int]] = {}
    for e in payloads:
        seq = e.get("sequence")
        if seq is None:
            continue
        # ปลายทางปฏิเสธ sequence ที่ไม่ใช่ int >= 1 ที่ intake (MalformedSequence)
        # bool เป็น int ใน Python — ส่ง True ไปจะกลายเป็น 1 เงียบ ๆ ถ้าไม่กันตรงนี้
        # อย่าส่งของที่รู้อยู่แล้วว่าเขาจะปฏิเสธ
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            problems.append(f"{e['event_id']}: sequence={seq!r} ไม่ใช่ตำแหน่ง "
                            f"— event/v1 ต้องเป็น integer >= 1")
            continue
        by_subject.setdefault(e["subject_id"], []).append(seq)
    for subject, seqs in by_subject.items():
        if len(seqs) != len(set(seqs)):
            problems.append(f"subject {subject}: sequence ซ้ำกันเอง")
        elif sorted(seqs) != list(range(1, len(seqs) + 1)):
            problems.append(f"subject {subject}: sequence ไม่ต่อเนื่องจาก 1 — {sorted(seqs)}")

    # subject ที่มี event ใบเดียวไม่ผิด — รอบที่มีข้อเสนอเดียวก็มีจริง
    # ที่ผิดคือ **ทั้งชุดไม่มี subject ไหนเกินหนึ่งใบเลย** แปลว่า sequence
    # เพิ่มไม่ได้โดยโครงสร้าง ไม่ใช่โดยข้อมูล — นั่นคือ scope ผิด
    if by_subject and all(len(s) == 1 for s in by_subject.values()):
        problems.append(
            f"sequence ไม่เคยเกิน 1 เลยทั้งชุด ({len(by_subject)} subject) "
            f"— แปลว่าเพิ่มไม่ได้โดยโครงสร้าง scope ของ subject น่าจะผิด")

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
    walked = next((int(p.removeprefix("__walked__")) for p in problems
                   if p.startswith("__walked__")), 0)
    problems = [p for p in problems if not p.startswith("__walked__")]

    by_type: dict[str, int] = {}
    for e in payloads:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    print(f"ตรวจ {len(payloads)} event ที่ผลิตจากการทำงานจริง · "
          f"เดิน {walked} leaf ({len(DECIDED_LEAVES)} เส้นทางที่ตัดสินแล้วในใบ)")
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")

    for err in schema_errors:
        print(f"  ❌ schema  {err}")
    for p in problems:
        print(f"  ❌ guarantee  {p}")

    if schema_errors or problems:
        print(f"\n❌ conformance ไม่ผ่าน — schema {len(schema_errors)} · guarantee {len(problems)}")
        return 1
    print(f"\n✅ conformance ผ่าน — schema ครบทุกใบ · guarantee 10 ข้อครบ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
