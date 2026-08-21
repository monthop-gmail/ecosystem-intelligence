"""Architecture & Contract validation (#21 #22)

ทุก check คืน finding เป็นรูปแบบเดียวกัน เพื่อให้ report, API และ PR review
ใช้ผลชุดเดียวกันได้โดยไม่ต้องแปลงไปมา

finding = {rule, severity, title, subject, detail, fix, source}
    subject  สิ่งที่ผิด (component / contract / repo id) — ใช้จัดกลุ่มและ dedupe
    detail   ข้อเท็จจริงของเคสนี้ ไม่ใช่คำอธิบายกฎ (คำอธิบายกฎอยู่ที่ why)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import yaml

from .. import queries as q
from ..db import fetch_all
from ..github.client import GitHubClient, GitHubError

RULES_PATH = Path(__file__).with_name("rules.yaml")

# plane ที่นับว่าเป็น "ชั้น execution" และ "ชั้น orchestration" ตาม planes/README
EXECUTION_PLANES = {"runtime", "harness"}
ORCHESTRATION_PLANES = {"workflow"}
GOVERNANCE_CONTRACTS = {"policy/v1", "approval/v1"}
CREDENTIAL_CONTRACTS = {"provider/v1"}
ARTIFACT_CONTRACTS = {"artifact/v1"}

CONFORMANCE_MAX_AGE_DAYS = 90

# check ที่ต้องอ่านจาก repo อื่น — ข้ามได้ แต่ต้องข้ามอย่างมีเสียง
REMOTE_CHECKS = {"manifest_drift", "semantics_version_drift", "pinned_contract_stale",
                 "contracts_without_consumer"}


def load_rules() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["rules"]}


def _finding(rule: dict, subject: str, detail: str, **extra) -> dict[str, Any]:
    return {
        "rule": rule["id"],
        "severity": rule["severity"],
        "title": rule["title"],
        "subject": subject,
        "detail": detail,
        "why": " ".join(rule["why"].split()),
        "fix": rule["fix"],
        "source": rule.get("source"),
        **extra,
    }


# ─────────────────────────────────────────────────────────────────────────
# #21 Architecture
# ─────────────────────────────────────────────────────────────────────────
def orphan_components(conn, rule) -> list[dict]:
    rows = fetch_all(conn, """
        SELECT c.id FROM components c
         LEFT JOIN teams t ON t.id = c.owner
         WHERE t.id IS NULL
    """)
    return [_finding(rule, r["id"], "ไม่มีทีมไหนเป็นเจ้าของ") for r in rows]


def duplicate_plane_implementations(conn, rule) -> list[dict]:
    rows = fetch_all(conn, """
        SELECT cp.plane_id, array_agg(c.id ORDER BY c.id) AS components
          FROM component_planes cp
          JOIN components c ON c.id = cp.component_id
         WHERE c.status IN ('active', 'in-development', 'scaffold')
         GROUP BY cp.plane_id
        HAVING count(*) > 1
    """)
    return [_finding(rule, r["plane_id"],
                     f"มี {len(r['components'])} component ที่ implement plane นี้: "
                     f"{', '.join(r['components'])}")
            for r in rows]


def _components_in_planes(conn, planes: set[str]) -> list[dict]:
    return [c for c in q.list_components(conn) if set(c["implements"]) & planes]


def execution_owns_governance(conn, rule) -> list[dict]:
    out = []
    for c in _components_in_planes(conn, EXECUTION_PLANES):
        bad = sorted(set(c["exposes"]) & GOVERNANCE_CONTRACTS)
        if bad:
            out.append(_finding(rule, c["id"],
                                f"อยู่ใน plane {', '.join(c['implements'])} "
                                f"แต่เป็นเจ้าของ {', '.join(bad)}"))
    return out


def execution_holds_credential(conn, rule) -> list[dict]:
    out = []
    for c in _components_in_planes(conn, EXECUTION_PLANES):
        bad = sorted(set(c["consumes"]) & CREDENTIAL_CONTRACTS)
        if bad:
            out.append(_finding(rule, c["id"],
                                f"อยู่ใน plane {', '.join(c['implements'])} "
                                f"แต่ consume {', '.join(bad)} ตรง ๆ"))
    return out


def orchestration_owns_artifact(conn, rule) -> list[dict]:
    out = []
    for c in _components_in_planes(conn, ORCHESTRATION_PLANES):
        bad = sorted(set(c["exposes"]) & ARTIFACT_CONTRACTS)
        if bad:
            out.append(_finding(rule, c["id"],
                                f"อยู่ใน plane {', '.join(c['implements'])} "
                                f"แต่เป็นเจ้าของ {', '.join(bad)}"))
    return out


def planes_without_implementation(conn, rule) -> list[dict]:
    return [_finding(rule, p["id"], f"{p['name']} — {p['responsibility']}")
            for p in q.list_planes(conn) if not p["implemented_by"]]


# ─────────────────────────────────────────────────────────────────────────
# #22 Contract
# ─────────────────────────────────────────────────────────────────────────
REF_URL = re.compile(r"schemas\.agent-platform\.internal/([a-z0-9-]+)/(v\d+)/")


def contract_ref_graph(gh: GitHubClient, authority: str = "agent-platform") -> dict[str, set[str]]:
    """contract ไหนถูก contract อื่น $ref ถึงบ้าง

    `event/v1` $ref ไปหา `identity` `policy` `capability` `model` `error` —
    contract ที่ไม่มี consumer โดยตรงจึงยัง "มีคนใช้" ผ่านสายนี้ได้
    ตัดทิ้งแล้ว schema ของคนอื่น resolve ไม่ได้ทั้งชุด
    """
    referenced: dict[str, set[str]] = {}
    dirs = gh.api(f"repos/{gh.owner}/{authority}/contents/contracts")
    for entry in dirs:
        if entry["type"] != "dir":
            continue
        name = entry["name"]
        try:
            files = gh.api(f"repos/{gh.owner}/{authority}/contents/contracts/{name}/v1")
        except GitHubError:
            continue
        for f in files:
            if not f["name"].endswith((".yaml", ".yml")):
                continue
            import base64
            blob = gh.api(f"repos/{gh.owner}/{authority}/contents/"
                          f"contracts/{name}/v1/{f['name']}")
            text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
            for m in REF_URL.finditer(text):
                target = f"{m.group(1)}/{m.group(2)}"
                if m.group(1) != name:
                    referenced.setdefault(target, set()).add(f"{name}/v1")
    return referenced


def contracts_without_consumer(conn, rule, *, gh: GitHubClient | None = None) -> list[dict]:
    """contract ที่ไม่มีใคร pin — และ **ตรวจ $ref ก่อนบอกว่าปิดได้**

    เดิม check นี้นับแค่ความสัมพันธ์ที่บันทึกใน ecosystem.yaml แล้วสรุปว่า "ปิดได้"
    ซึ่งมองไม่เห็น $ref ระหว่าง contract ด้วยกันเอง — รายงานฉบับ 2026-08-22
    จึงบอกว่า artifact/v1 และ model/v1 ปิดได้ ทั้งที่ execution/v1 และ event/v1
    $ref ถึงทั้งคู่ · ปิดจริงจะทำให้ schema ของ consumer ที่ conform อยู่ 3 ราย
    resolve ไม่ได้
    """
    referenced: dict[str, set[str]] | None = None
    if gh is not None:
        try:
            referenced = contract_ref_graph(gh)
        except Exception as e:  # noqa: BLE001
            referenced = None
            rule = {**rule, "_ref_error": str(e)[:100]}

    # plane จอง contract ไว้ได้ก่อนมีคน implement — contract ที่ผูกกับ plane
    # ที่ยังไม่มีเจ้าของ ไม่ใช่ contract ที่ไม่มีใครต้องการ
    plane_of: dict[str, list[str]] = {}
    for p in q.list_planes(conn):
        for cid in p["contracts"]:
            plane_of.setdefault(cid, []).append(p["id"])

    out = []
    for c in q.list_contracts(conn):
        if c["consumers"]:
            continue
        waiting = c["expected_by"]
        by_ref = sorted(referenced.get(c["id"], set())) if referenced is not None else None
        planes = plane_of.get(c["id"], [])

        if waiting:
            detail = f"ยังไม่มีใคร pin — แต่ {', '.join(waiting)} ประกาศเจตนาจะใช้ ปิดตอนนี้แผนเขาพัง"
            closable = False
        elif by_ref:
            detail = (f"ไม่มีใคร pin โดยตรง แต่ {', '.join(by_ref)} $ref ถึง "
                      f"— ปิดแล้ว schema ของเขา resolve ไม่ได้")
            closable = False
        elif referenced is None:
            detail = ("ยังไม่มีใคร pin — **ยังไม่ได้ตรวจว่ามี contract อื่น $ref ถึงหรือเปล่า** "
                      "ใส่ REMOTE=1 ก่อนสรุปว่าปิดได้")
            closable = None
        elif planes:
            detail = (f"ไม่มีใคร pin และไม่มี contract ไหน $ref ถึง "
                      f"— แต่ plane {', '.join(planes)} จองไว้ ยังไม่มีใคร implement "
                      f"ปิดคือการตัดสินว่า plane นั้นจะไม่ใช้มัน")
            closable = False
        else:
            detail = "ไม่มีใคร pin · ไม่มี $ref · ไม่มี plane จองไว้ — ไม่มีใครใช้จริง"
            closable = True

        out.append(_finding(rule, c["id"], detail, closable=closable,
                            referenced_by=by_ref, reserved_by=planes or None))
    return out


def derived_without_semantics_owner(conn, rule) -> list[dict]:
    rows = fetch_all(conn, """
        SELECT id FROM contracts WHERE derived AND semantics_owner IS NULL
    """)
    return [_finding(rule, r["id"], "derived: true แต่ไม่ระบุ semantics_owner") for r in rows]


def stale_conformance(conn, rule) -> list[dict]:
    rows = fetch_all(conn, """
        SELECT component_id, declared_status, status, age_days
          FROM conformance_effective
         WHERE declared_status = 'passing' AND age_days > %s
    """, (CONFORMANCE_MAX_AGE_DAYS,))
    return [_finding(rule, r["component_id"],
                     f"ประกาศ passing แต่ตรวจครั้งสุดท้าย {r['age_days']} วันที่แล้ว "
                     f"— นับเป็น {r['status']}")
            for r in rows]


def consumes_without_manifest(conn, rule) -> list[dict]:
    rows = fetch_all(conn, """
        SELECT c.id, array_agg(cc.contract_id ORDER BY cc.contract_id) AS contracts
          FROM components c
          JOIN component_contracts cc
            ON cc.component_id = c.id AND cc.relation = 'consumes'
          LEFT JOIN conformance cf ON cf.component_id = c.id
         WHERE cf.manifest IS NULL
         GROUP BY c.id
    """)
    return [_finding(rule, r["id"],
                     f"ประกาศ consumes {', '.join(r['contracts'])} โดยไม่มี manifest")
            for r in rows]


def blocking_past_backstop(conn, rule) -> list[dict]:
    """ข้อที่เราประกาศว่าค้าง และตั้งกำหนดกับตัวเองไว้ — เลยกำหนดแล้วหรือยัง

    อ่านจาก platform-contract.yaml ของ repo นี้เอง ไม่ใช่ของคนอื่น
    เราตรวจ ecosystem ให้คนอื่นได้ ก็ต้องยอมให้ตรวจตัวเองด้วยเกณฑ์เดียวกัน
    """
    from datetime import date

    from ..config import ROOT

    path = ROOT / "platform-contract.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    today = date.today()
    out = []
    for item in doc.get("blocking") or []:
        backstop = item.get("backstop")
        if not backstop or item.get("status") == "resolved":
            continue
        if isinstance(backstop, str):
            backstop = date.fromisoformat(backstop)
        if today > backstop:
            out.append(_finding(
                rule, item["id"],
                f"ตั้ง backstop ไว้ {backstop} ผ่านมาแล้ว {(today - backstop).days} วัน "
                f"· status ยังเป็น {item.get('status')}"
                + (f" · {item['issue']}" if item.get("issue") else "")))
    return out


def manifest_drift(conn, rule, *, gh: GitHubClient | None = None) -> list[dict]:
    """เทียบ ecosystem.yaml กับ platform-contract.yaml ของจริงในแต่ละ repo

    นี่คือ check เดียวที่ต้องออกเน็ต — ถ้าออกไม่ได้ ให้ข้ามอย่างมีเสียง
    ไม่ใช่รายงานว่า "ผ่าน" ทั้งที่ไม่ได้ตรวจ
    """
    gh = gh or GitHubClient()
    rows = fetch_all(conn, """
        SELECT c.id AS component, c.repository, cf.manifest,
               COALESCE((SELECT array_agg(contract_id ORDER BY contract_id)
                           FROM component_contracts
                          WHERE component_id = c.id AND relation = 'consumes'), '{}') AS declared
          FROM components c
          JOIN conformance cf ON cf.component_id = c.id
         WHERE cf.manifest IS NOT NULL AND c.repository IS NOT NULL
    """)
    out = []
    for r in rows:
        path = f"repos/{gh.owner}/{r['repository']}/contents/{r['manifest']}"
        try:
            import base64
            blob = gh.api(path)
            text = base64.b64decode(blob["content"]).decode("utf-8")
            actual_doc = yaml.safe_load(text) or {}
        except (GitHubError, Exception) as e:  # noqa: BLE001
            out.append(_finding(rule, r["component"],
                                f"อ่าน {r['manifest']} ไม่ได้: {str(e)[:120]}",
                                skipped=True))
            continue

        actual = sorted(actual_doc.get("contracts") or [])
        declared = sorted(r["declared"])
        if actual != declared:
            missing = sorted(set(actual) - set(declared))
            extra = sorted(set(declared) - set(actual))
            parts = []
            if missing:
                parts.append(f"manifest มีแต่ ecosystem.yaml ไม่มี: {', '.join(missing)}")
            if extra:
                parts.append(f"ecosystem.yaml มีแต่ manifest ไม่มี: {', '.join(extra)}")
            out.append(_finding(rule, r["component"], " · ".join(parts),
                                manifest=actual, declared=declared))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Cross-repo (M6) — ต้องอ่านจาก repo อื่น จึงออกเน็ตทั้งคู่
# ─────────────────────────────────────────────────────────────────────────
def _fetch_yaml(gh: GitHubClient, repo: str, path: str, ref: str | None = None) -> dict:
    import base64
    url = f"repos/{gh.owner}/{repo}/contents/{path}" + (f"?ref={ref}" if ref else "")
    blob = gh.api(url)
    return yaml.safe_load(base64.b64decode(blob["content"]).decode("utf-8")) or {}


def semantics_version_drift(conn, rule, *, gh: GitHubClient | None = None) -> list[dict]:
    """เทียบ semantics_version ที่ contract pin ไว้ กับต้นทางที่เป็นเจ้าของความหมาย

    devfactory-core เขียนกฎ drift_check นี้ไว้เอง (pin semantics_version ไม่ใช่ commit SHA)
    แต่ยังไม่มีใครตรวจข้ามrepo ให้ — เราตรวจจากมุมของ ecosystem ซึ่งเห็นทั้งสองฝั่ง
    """
    gh = gh or GitHubClient()
    out: list[dict] = []
    rows = fetch_all(conn, """
        SELECT id, authority, semantics_owner FROM contracts
         WHERE derived AND semantics_owner IS NOT NULL
    """)
    upstream: dict[str, str] = {}
    for r in rows:
        owner = r["semantics_owner"]
        if owner not in upstream:
            try:
                doc = _fetch_yaml(gh, owner, "contract-semantics.yaml")
                upstream[owner] = str(doc.get("semantics_version", ""))
            except Exception as e:  # noqa: BLE001
                out.append(_finding(rule, r["id"],
                                    f"อ่าน contract-semantics.yaml ของ {owner} ไม่ได้: "
                                    f"{str(e)[:100]}", skipped=True))
                upstream[owner] = ""
        want = upstream[owner]
        if not want:
            continue
        name, _, version = r["id"].partition("/")
        path = f"contracts/{name}/{version}/{name}.schema.yaml"
        try:
            schema = _fetch_yaml(gh, r["authority"], path)
        except Exception as e:  # noqa: BLE001
            out.append(_finding(rule, r["id"], f"อ่าน schema ไม่ได้: {str(e)[:100]}",
                                skipped=True))
            continue
        got = str((schema.get("derived_from") or {}).get("semantics_version", ""))
        if got != want:
            out.append(_finding(rule, r["id"],
                                f"{r['authority']} pin ไว้ {got or 'ไม่ระบุ'} "
                                f"แต่ {owner} อยู่ที่ {want}",
                                pinned=got, upstream=want))
    return out


def pinned_contract_stale(conn, rule, *, gh: GitHubClient | None = None) -> list[dict]:
    """schema ที่เรา vendor ไว้ ยังตรงกับ commit ที่ pin ไหม และต้นทางขยับไปแค่ไหน"""
    from ..config import ROOT

    gh = gh or GitHubClient()
    pinned_path = ROOT / "conformance" / "pinned.yaml"
    if not pinned_path.exists():
        return []
    pin = yaml.safe_load(pinned_path.read_text(encoding="utf-8"))
    repo = pin["repo"].split("/")[-1]

    try:
        commits = gh.api(f"repos/{gh.owner}/{repo}/commits?path=contracts&per_page=1")
        head = commits[0]["sha"] if commits else None
    except Exception as e:  # noqa: BLE001
        return [_finding(rule, repo, f"ตรวจ commit ล่าสุดไม่ได้: {str(e)[:100]}", skipped=True)]

    if head and head != pin["commit"]:
        return [_finding(rule, repo,
                         f"pin ไว้ที่ {pin['commit'][:12]} แต่ contracts/ ขยับไปถึง "
                         f"{head[:12]} แล้ว", pinned=pin["commit"], head=head)]
    return []


# ─────────────────────────────────────────────────────────────────────────
CHECKS: dict[str, Callable] = {
    "blocking_past_backstop": blocking_past_backstop,
    "semantics_version_drift": semantics_version_drift,
    "pinned_contract_stale": pinned_contract_stale,
    "orphan_components": orphan_components,
    "duplicate_plane_implementations": duplicate_plane_implementations,
    "execution_owns_governance": execution_owns_governance,
    "execution_holds_credential": execution_holds_credential,
    "orchestration_owns_artifact": orchestration_owns_artifact,
    "planes_without_implementation": planes_without_implementation,
    "contracts_without_consumer": contracts_without_consumer,
    "derived_without_semantics_owner": derived_without_semantics_owner,
    "stale_conformance": stale_conformance,
    "consumes_without_manifest": consumes_without_manifest,
    "manifest_drift": manifest_drift,
}


def run_all(conn, *, include_remote: bool = False,
            gh: GitHubClient | None = None) -> dict[str, Any]:
    rules = load_rules()
    findings: list[dict] = []
    ran, skipped = [], []
    if include_remote and gh is None:
        gh = GitHubClient()   # check ที่ต้องออกเน็ตต้องมี client จริง ไม่ใช่ None เงียบ ๆ

    for rule_id, rule in rules.items():
        check_name = rule.get("check")
        if not check_name:
            continue  # กฎที่ใช้เฉพาะตอน review PR ไม่มี check ระดับ ecosystem
        fn = CHECKS[check_name]
        if check_name in REMOTE_CHECKS:
            if not include_remote:
                # contracts_without_consumer ยังรันแบบ local ได้ — แต่จะบอกเองว่า
                # ยังไม่ได้ตรวจ $ref · ที่เหลือข้ามไปเลยเพราะ local ทำอะไรไม่ได้
                if check_name == "contracts_without_consumer":
                    findings.extend(fn(conn, rule, gh=None))
                    ran.append(rule_id)
                else:
                    skipped.append(rule_id)
                continue
            findings.extend(fn(conn, rule, gh=gh))
        else:
            findings.extend(fn(conn, rule))
        ran.append(rule_id)

    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "findings": findings,
        "errors": len(errors),
        "warnings": len(findings) - len(errors),
        "rules_run": ran,
        "rules_skipped": skipped,
    }
