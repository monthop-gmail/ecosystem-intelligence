"""PR review (#23) — เอา Guardian ไปวางตรงจุดที่คนทำงานจริง

หลักที่ยึด

    default คือปิด        Guardian ไม่คอมเมนต์ที่ไหนจนกว่าจะเปิดทีละ repo
    เริ่มที่ warn         เปิดแล้วก็ยังไม่บล็อกใคร
    ไม่คอมเมนต์ซ้ำ         ใส่ fingerprint ในคอมเมนต์ เจอของเดิมแล้วข้าม
    บอกทางแก้เสมอ         คอมเมนต์ที่บอกแค่ว่าผิด ไม่มีใครทำตาม
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .. import impact
from .. import queries as q
from ..config import ROOT
from ..github.client import GitHubClient, GitHubError
from .checks import load_rules

CONFIG_PATH = ROOT / "guardian.yaml"
MARKER = "ecosystem-guardian"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or CONFIG_PATH
    if not p.exists():
        return {"default": {"enabled": False, "mode": "warn"}, "repositories": {}}
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def repo_config(repository: str, config: dict | None = None) -> dict[str, Any]:
    config = config or load_config()
    base = dict(config.get("default") or {})
    base.update((config.get("repositories") or {}).get(repository) or {})
    return base


def _finding(rule: dict, subject: str, detail: str) -> dict[str, Any]:
    return {"rule": rule["id"], "severity": rule["severity"], "title": rule["title"],
            "subject": subject, "detail": detail,
            "why": " ".join(rule["why"].split()), "fix": rule["fix"]}


def review_pr(conn, repository: str, number: int, *,
              gh: GitHubClient | None = None) -> dict[str, Any]:
    """ตรวจ PR หนึ่งใบ — คืน finding ที่เกี่ยวกับ PR นั้นเท่านั้น"""
    gh = gh or GitHubClient()
    rules = load_rules()

    analysis = impact.analyze_pr(conn, repository, number, gh=gh)
    if not analysis["available"]:
        return {"repository": repository, "number": number,
                "available": False, "reason": analysis["reason"]}

    try:
        pr = gh.api(f"repos/{gh.owner}/{repository}/pulls/{number}")
    except GitHubError:
        pr = {}
    text = f"{pr.get('title', '')}\n{pr.get('body') or ''}".lower()

    findings: list[dict] = []

    for cid in analysis["contracts_touched"]:
        contract = q.get_contract(conn, cid)
        if contract is None:
            continue

        # semantics เป็นของ repo อื่น → ต้องมี RFC ที่ต้นทางก่อน
        owner = contract["semantics_owner"]
        if owner and owner != repository:
            mentions_rfc = "rfc" in text or owner.lower() in text
            if not mentions_rfc:
                findings.append(_finding(
                    rules["semantics-change-without-rfc"], cid,
                    f"semantics ของ {cid} เป็นของ {owner} แต่ PR นี้อยู่ที่ {repository} "
                    f"และไม่ได้อ้างถึง RFC หรือ {owner} เลย"))

        if analysis["level"] == "breaking":
            change = impact.contract_change(conn, cid, "breaking")
            if change["consumers"]:
                who = ", ".join(f"{c['component']} ({c['team']})" for c in change["consumers"])
                findings.append(_finding(
                    rules["breaking-without-coordination"], cid,
                    f"เป็น breaking change และมี consumer ที่ pin ไว้อยู่: {who}"))
        elif analysis["level"] == "unsure":
            findings.append(_finding(
                rules["contract-change-unclear"], cid,
                "สัญญาณใน diff ไม่ชัดพอจะตัดสินว่า breaking หรือไม่"))

    if analysis.get("disagreement"):
        findings.append(_finding(rules["contract-change-unclear"], repository,
                                 analysis["disagreement"]))

    cfg = repo_config(repository)
    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "repository": repository,
        "number": number,
        "available": True,
        "level": analysis["level"],
        "contracts_touched": analysis["contracts_touched"],
        "findings": findings,
        "errors": len(errors),
        "warnings": len(findings) - len(errors),
        "config": cfg,
        "should_block": bool(errors) and cfg.get("mode") == "block",
        "fingerprint": fingerprint(findings),
    }


def fingerprint(findings: list[dict]) -> str:
    """ลายนิ้วมือของชุด finding — ใช้ตัดสินว่าเคยคอมเมนต์เรื่องนี้ไปแล้วหรือยัง"""
    key = "|".join(sorted(f"{f['rule']}:{f['subject']}" for f in findings))
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def render_comment(review: dict[str, Any]) -> str:
    icon = {"breaking": "🔴", "non-breaking": "🟢", "unsure": "🟡"}[review["level"]]
    lines = [
        f"<!-- {MARKER}:{review['fingerprint']} -->",
        f"## {icon} Architecture Guardian — {review['level']}",
        "",
    ]
    if review["contracts_touched"]:
        lines += [f"PR นี้แตะ contract: {', '.join(f'`{c}`' for c in review['contracts_touched'])}", ""]

    if not review["findings"]:
        lines += ["ไม่พบปัญหาจากกฎที่ตรวจอัตโนมัติได้", ""]
    else:
        # จัดกลุ่มตามกฎ — กฎเดียวกันที่โดนหลาย contract ไม่ควรพิมพ์คำอธิบายซ้ำ
        # คอมเมนต์ที่ยาวเพราะซ้ำ คือคอมเมนต์ที่ไม่มีใครอ่านจนจบ
        by_rule: dict[str, list[dict]] = {}
        for f in review["findings"]:
            by_rule.setdefault(f["rule"], []).append(f)

        for items in by_rule.values():
            head = items[0]
            mark = "❌" if head["severity"] == "error" else "⚠️"
            lines += [f"### {mark} {head['title']}", ""]
            for f in items:
                lines.append(f"- **`{f['subject']}`** — {f['detail']}")
            lines += ["", f"> {head['why']}", "", f"**ทางแก้:** {head['fix']}", ""]

    mode = review["config"].get("mode", "warn")
    lines += [
        "---",
        f"_ตรวจโดยกฎอัตโนมัติ ไม่ได้อ่านโค้ด · โหมด `{mode}`"
        + ("" if mode == "block" else " — คอมเมนต์อย่างเดียว ไม่บล็อกการ merge")
        + " · [ecosystem-intelligence](https://github.com/monthop-gmail/ecosystem-intelligence)_",
    ]
    return "\n".join(lines)


def already_commented(gh: GitHubClient, repository: str, number: int,
                      fp: str) -> bool:
    """เคยคอมเมนต์เรื่องเดิมบน PR ใบนี้ไปแล้วหรือยัง"""
    try:
        comments = gh.api(f"repos/{gh.owner}/{repository}/issues/{number}/comments"
                          f"?per_page=100", paginate=True) or []
    except GitHubError:
        return False
    return any(f"{MARKER}:{fp}" in (c.get("body") or "") for c in comments)


def post_review(conn, repository: str, number: int, *, confirm: bool = False,
                gh: GitHubClient | None = None) -> dict[str, Any]:
    """คอมเมนต์จริงบน PR

    ต้องครบสามข้อถึงจะยิง — ขาดข้อไหนก็คืนเหตุผลกลับไป ไม่เงียบ
        1. repo นั้นเปิด Guardian ไว้ใน guardian.yaml
        2. เรียกด้วย confirm=True (CLI ต้องใส่ --post)
        3. ยังไม่เคยคอมเมนต์ finding ชุดเดียวกันบน PR ใบนี้
    """
    gh = gh or GitHubClient()
    review = review_pr(conn, repository, number, gh=gh)
    if not review["available"]:
        return {"posted": False, "reason": review["reason"], "review": review}

    body = render_comment(review)
    review["comment"] = body

    if not review["config"].get("enabled"):
        return {"posted": False, "reason": f"guardian.yaml ปิด Guardian ไว้สำหรับ {repository}",
                "review": review}
    if not confirm:
        return {"posted": False, "reason": "ต้องยืนยันด้วย --post ก่อนจึงจะคอมเมนต์จริง",
                "review": review}
    if already_commented(gh, repository, number, review["fingerprint"]):
        return {"posted": False, "reason": "เคยคอมเมนต์เรื่องเดียวกันบน PR นี้แล้ว",
                "review": review}

    try:
        gh._run(["api", f"repos/{gh.owner}/{repository}/issues/{number}/comments",
                 "-f", f"body={body}"])
    except GitHubError as e:
        return {"posted": False, "reason": f"คอมเมนต์ไม่สำเร็จ: {e}", "review": review}
    return {"posted": True, "reason": None, "review": review}
