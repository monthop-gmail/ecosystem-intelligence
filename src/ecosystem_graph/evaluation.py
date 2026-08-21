"""เทียบ provider ด้วยชุดคำถามทดสอบ (#11)

ตอบคำถามเดียว: **LLM ตอบดีกว่า rule engine จริงไหม**

ถ้าตอบแย่กว่า baseline แปลว่าปัญหาอยู่ที่ prompt หรือ context ไม่ใช่ที่ model
— และเราจะรู้จากตัวเลข ไม่ใช่จากความรู้สึกตอนอ่านคำตอบหนึ่งใบ

เกณฑ์เป็น "ข้อเท็จจริงที่ต้องมี" ไม่ใช่การเทียบข้อความคำต่อคำ เพราะภาษาที่
LLM เขียนต่างกันได้ แต่ข้อเท็จจริงต้องตรงกันเสมอ
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from . import advisor
from .config import ROOT
from .db import connect
from .llm import LLMError, get_provider

QUESTIONS_PATH = ROOT / "evaluation" / "questions.yaml"


def load_cases() -> list[dict[str, Any]]:
    return yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))


def run_case(conn, case: dict, provider) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = advisor.ask(conn, case["team"], case["question"], provider=provider)
    except LLMError as e:
        return {"case": case["id"], "ok": False, "error": str(e)[:300],
                "elapsed": time.perf_counter() - started}
    except Exception as e:  # noqa: BLE001 — SDK โยน error นอกเหนือจากที่เรา map ไว้ได้
        return {"case": case["id"], "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:260]}",
                "elapsed": time.perf_counter() - started}
    elapsed = time.perf_counter() - started

    answer = result["answer"]
    mentioned = {r for s in answer["recommended_next_steps"] for r in s["references"]}
    mentioned |= set(answer["affected_components"])

    missing = [m for m in case["must_reference"] if m not in mentioned]
    forbidden = [n for n in case["must_not_mention"] if n in mentioned]
    answerable_ok = answer["answerable"] == case["expect_answerable"]
    grounded = result["grounding"]["ok"]

    checks = {
        "must_reference": not missing,
        "must_not_mention": not forbidden,
        "answerable": answerable_ok,
        "grounded": grounded,
        "has_steps": bool(answer["recommended_next_steps"]) or not case["expect_answerable"],
        "why_present": all(len(s["why"].strip()) > 20
                           for s in answer["recommended_next_steps"]),
    }
    return {
        "case": case["id"],
        "team": case["team"],
        "ok": all(checks.values()),
        "checks": checks,
        "missing_references": missing,
        "forbidden_mentions": forbidden,
        "unknown_ids": result["grounding"]["unknown_ids"],
        "suspicious": result["grounding"]["suspicious_mentions"],
        "steps": len(answer["recommended_next_steps"]),
        "referenced": sorted(mentioned),
        "risks": len(answer["risks"]),
        "elapsed": elapsed,
        "usage": getattr(provider, "last_usage", None),
        "answer": answer,
    }


def run_suite(conn, provider_names: list[str]) -> dict[str, Any]:
    cases = load_cases()
    out: dict[str, Any] = {"cases": [c["id"] for c in cases], "providers": {}}
    for name in provider_names:
        try:
            provider = get_provider(name)
        except LLMError as e:
            out["providers"][name] = {"available": False, "reason": str(e)}
            continue
        results = [run_case(conn, c, provider) for c in cases]
        usages = [r["usage"] for r in results if r.get("usage")]
        out["providers"][name] = {
            "available": True,
            "model": provider.model,
            "results": results,
            "passed": sum(1 for r in results if r["ok"]),
            "total": len(results),
            "elapsed_total": sum(r["elapsed"] for r in results),
            "input_tokens": sum(u["input_tokens"] for u in usages) or None,
            "output_tokens": sum(u["output_tokens"] for u in usages) or None,
            "cache_read": sum(u["cache_read"] for u in usages) or None,
        }
    return out


def compare(report: dict[str, Any], baseline: str = "offline") -> list[str]:
    """เทียบกับ baseline — สิ่งที่หาเจอเพิ่ม กับสิ่งที่หลุดไป"""
    base = report["providers"].get(baseline)
    if not base or not base["available"]:
        return []
    base_refs = {r["case"]: set(r["referenced"]) for r in base["results"]}

    lines = []
    for name, data in report["providers"].items():
        if name == baseline or not data["available"]:
            continue
        for r in data["results"]:
            if "referenced" not in r:
                continue
            mine, theirs = set(r["referenced"]), base_refs.get(r["case"], set())
            gained, lost = sorted(mine - theirs), sorted(theirs - mine)
            if gained or lost:
                lines.append(f"  {r['case']} ({name})")
                if gained:
                    lines.append(f"      + หาเจอเพิ่ม : {', '.join(gained)}")
                if lost:
                    lines.append(f"      − หลุดไป     : {', '.join(lost)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    names = (argv[0].split(",") if argv else ["offline"])
    save = "--save" in argv

    with connect(readonly=True) as conn:
        report = run_suite(conn, names)

    print(f"ชุดคำถาม {len(report['cases'])} ข้อ\n")
    header = f"  {'provider':<12} {'model':<24} {'ผ่าน':<8} {'เวลา':<9} {'token in/out':<16} cache"
    print(header)
    print("  " + "─" * (len(header) - 2))
    for name, d in report["providers"].items():
        if not d["available"]:
            print(f"  {name:<12} — ใช้ไม่ได้: {d['reason'][:60]}")
            continue
        tok = (f"{d['input_tokens']}/{d['output_tokens']}"
               if d["input_tokens"] else "—")
        cache = str(d["cache_read"]) if d["cache_read"] else "—"
        print(f"  {name:<12} {d['model'][:24]:<24} {d['passed']}/{d['total']:<6} "
              f"{d['elapsed_total']:>6.2f}s  {tok:<16} {cache}")

    for name, d in report["providers"].items():
        if not d["available"]:
            continue
        failed = [r for r in d["results"] if not r["ok"]]
        if failed:
            print(f"\n  ❌ {name} ตกที่:")
            for r in failed:
                if r.get("error"):
                    print(f"      {r['case']}: {r['error']}")
                    continue
                bad = [k for k, v in r["checks"].items() if not v]
                detail = []
                if r["missing_references"]:
                    detail.append(f"ไม่ได้อ้าง {', '.join(r['missing_references'])}")
                if r["forbidden_mentions"]:
                    detail.append(f"ไปอ้าง {', '.join(r['forbidden_mentions'])}")
                if r["unknown_ids"]:
                    detail.append(f"แต่ง id: {', '.join(r['unknown_ids'])}")
                print(f"      {r['case']}: {', '.join(bad)}"
                      + (f" — {' · '.join(detail)}" if detail else ""))

    diffs = compare(report)
    if diffs:
        print("\n  ต่างจาก baseline (offline rule engine)")
        print("\n".join(diffs))

    if save:
        out = ROOT / "evaluation" / "last-run.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        print(f"\n  บันทึกผลไว้ที่ {out.relative_to(ROOT)}")

    usable = [d for d in report["providers"].values() if d["available"]]
    return 0 if usable and all(d["passed"] == d["total"] for d in usable) else 1


if __name__ == "__main__":
    sys.exit(main())
