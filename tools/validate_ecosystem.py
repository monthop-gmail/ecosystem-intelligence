#!/usr/bin/env python3
"""ตรวจ ecosystem.yaml — โครงสร้าง + referential integrity + กฎของ ecosystem

    python3 tools/validate_ecosystem.py [--github] [ecosystem.yaml]

--github  ตรวจเพิ่มว่า repo ที่ประกาศไว้มีอยู่จริงบน GitHub (ต้องมี gh CLI)

exit 0 = ผ่าน (มี warning ได้)   exit 1 = มี error
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ต้องมี pyyaml — pip install pyyaml")

CONFORMANCE_MAX_AGE_DAYS = 90  # ADR-0006: passing ที่เก่ากว่านี้ถือเป็น unknown

errors: list[str] = []
warnings: list[str] = []


def normalize_dates(node):
    """YAML แปลง 2026-08-19 เป็น date object ให้เอง — บังคับกลับเป็นสตริง ISO
    เพื่อให้ schema กับ ecosystem.yaml ใช้รูปแบบเดียวกันโดยไม่ต้อง quote ในไฟล์"""
    if isinstance(node, dict):
        return {k: normalize_dates(v) for k, v in node.items()}
    if isinstance(node, list):
        return [normalize_dates(v) for v in node]
    if isinstance(node, (date, datetime)):
        return node.isoformat()[:10]
    return node


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def check_schema(doc: dict, schema_path: Path) -> None:
    """ตรวจรูปร่างด้วย JSON Schema — ข้ามอย่างมีเสียงถ้าไม่มี jsonschema"""
    try:
        import jsonschema
    except ImportError:
        warn("ไม่มี jsonschema — ข้ามการตรวจโครงสร้าง (pip install jsonschema)")
        return
    import json

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(doc), key=lambda x: list(x.path)):
        loc = "/".join(str(p) for p in e.path) or "(root)"
        err(f"schema: {loc}: {e.message}")


def check_unique_ids(doc: dict) -> None:
    for section in ("contracts", "planes", "teams", "repositories", "components"):
        seen: set[str] = set()
        for item in doc.get(section, []):
            i = item.get("id")
            if i in seen:
                err(f"{section}: id ซ้ำ — {i}")
            seen.add(i)


def check_references(doc: dict, ids: dict[str, set[str]]) -> None:
    contracts, planes, teams, repos = (
        ids["contracts"], ids["planes"], ids["teams"], ids["repositories"]
    )

    if doc["metadata"]["maintained_by"] not in teams:
        err(f"metadata.maintained_by: ไม่รู้จักทีม {doc['metadata']['maintained_by']}")

    for name, src in doc.get("sources", {}).items():
        if src["owner"] not in repos:
            err(f"sources.{name}.owner: ไม่รู้จัก repository {src['owner']}")

    for c in doc["contracts"]:
        if c["authority"] not in repos:
            err(f"contracts.{c['id']}.authority: ไม่รู้จัก repository {c['authority']}")
        so = c.get("semantics_owner")
        if so and so not in repos:
            err(f"contracts.{c['id']}.semantics_owner: ไม่รู้จัก repository {so}")
        # derived กับ semantics_owner ต้องมาคู่กันเสมอ ไม่งั้นอ่านแล้วเข้าใจผิด
        if bool(c.get("derived")) != bool(so):
            err(f"contracts.{c['id']}: derived และ semantics_owner ต้องมาคู่กัน")

    for p in doc["planes"]:
        for cid in p["contracts"]:
            if cid not in contracts:
                err(f"planes.{p['id']}.contracts: ไม่รู้จัก contract {cid}")

    for comp in doc["components"]:
        cid = comp["id"]
        if comp["owner"] not in teams:
            err(f"components.{cid}.owner: ไม่รู้จักทีม {comp['owner']} — orphan component")
        repo = comp.get("repository")
        if repo is not None and repo not in repos:
            err(f"components.{cid}.repository: ไม่รู้จัก repository {repo}")
        for pid in comp["implements"]:
            if pid not in planes:
                err(f"components.{cid}.implements: ไม่รู้จัก plane {pid}")
        for field in ("exposes", "consumes", "expected_contracts"):
            for k in comp.get(field, []):
                if k not in contracts:
                    err(f"components.{cid}.{field}: ไม่รู้จัก contract {k}")
        for dep in comp.get("depends_on", []):
            if dep["component"] not in ids["components"]:
                err(f"components.{cid}.depends_on: ไม่รู้จัก component {dep['component']}")
            if dep["component"] == cid:
                err(f"components.{cid}.depends_on: ชี้ตัวเอง")


def check_rules(doc: dict, repo_by_id: dict[str, dict]) -> None:
    today = date.today()

    for comp in doc["components"]:
        cid = comp["id"]
        outside = comp.get("outside_plane_model", False)

        # อยู่นอก plane model ต้องบอกเหตุผล — ไม่ใช่ปล่อยว่างเงียบ ๆ
        if outside and not comp.get("outside_plane_reason"):
            err(f"components.{cid}: outside_plane_model ต้องมี outside_plane_reason")
        if outside and comp["implements"]:
            err(f"components.{cid}: outside_plane_model แต่ยัง implements plane อยู่")
        if not outside and not comp["implements"]:
            err(f"components.{cid}: ไม่ implement plane ใดเลย "
                f"— ถ้าตั้งใจ ต้องประกาศ outside_plane_model: true")

        # component ที่ทำงานอยู่จริง ต้องมี repo ที่มีอยู่จริง
        repo = repo_by_id.get(comp.get("repository") or "")
        if comp["status"] in ("active", "in-development", "scaffold"):
            if repo is None:
                err(f"components.{cid}: status={comp['status']} แต่ไม่มี repository")
            elif not repo["exists"]:
                err(f"components.{cid}: status={comp['status']} "
                    f"แต่ repository {repo['id']} ยังไม่มีอยู่จริง")

        # consumes ต้องมีหลักฐาน ไม่ใช่ความตั้งใจ — ความตั้งใจไปอยู่ที่ expected_contracts
        conf = comp["conformance"]
        if comp["consumes"] and not conf.get("manifest"):
            err(f"components.{cid}: ประกาศ consumes โดยไม่มี manifest เป็นหลักฐาน "
                f"— ถ้าเป็นความตั้งใจ ให้ย้ายไป expected_contracts")
        overlap = set(comp["consumes"]) & set(comp.get("expected_contracts", []))
        if overlap:
            err(f"components.{cid}: {sorted(overlap)} อยู่ทั้งใน consumes และ expected_contracts")

        status = conf["status"]
        if status == "passing":
            lv = conf.get("last_verified")
            if not lv:
                err(f"components.{cid}.conformance: passing ต้องมี last_verified")
            else:
                age = (today - datetime.strptime(lv, "%Y-%m-%d").date()).days
                if age > CONFORMANCE_MAX_AGE_DAYS:
                    warn(f"components.{cid}: conformance passing แต่ตรวจครั้งสุดท้าย {age} วันที่แล้ว "
                         f"— ADR-0006 ถือเป็น unknown")
            if not conf.get("manifest"):
                err(f"components.{cid}.conformance: passing ต้องมี manifest")
        if status == "waived" and not (conf.get("waived_until") and conf.get("waiver_ref")):
            err(f"components.{cid}.conformance: waived ต้องมี waived_until และ waiver_ref")

        # manifest ที่ประกาศใน component ต้องตรงกับที่ประกาศใน repository
        if repo is not None and conf.get("manifest") != repo.get("manifest"):
            err(f"components.{cid}: manifest ไม่ตรงกับ repositories.{repo['id']} "
                f"({conf.get('manifest')!r} vs {repo.get('manifest')!r})")

    # contract หนึ่งตัวต้องมีเจ้าของที่ expose คนเดียว
    exposer: dict[str, str] = {}
    for comp in doc["components"]:
        for k in comp["exposes"]:
            if k in exposer:
                err(f"contract {k} ถูก expose โดยทั้ง {exposer[k]} และ {comp['id']} "
                    f"— ต้องมีเจ้าของเดียว")
            exposer[k] = comp["id"]

    # ── warnings: ช่องว่างที่ควรรู้ ไม่ใช่ความผิด ──
    consumed = {k for c in doc["components"] for k in c["consumes"]}
    expected = {k for c in doc["components"] for k in c.get("expected_contracts", [])}
    for c in doc["contracts"]:
        if c["id"] not in consumed:
            waiting = sorted(x["id"] for x in doc["components"]
                             if c["id"] in x.get("expected_contracts", []))
            tail = f" — รออยู่: {', '.join(waiting)}" if waiting else " — ปิด version ได้ถ้าไม่มีใคร pin"
            warn(f"contract {c['id']}: ยังไม่มี consumer ที่ยืนยันแล้ว{tail}")
        if c["id"] not in exposer:
            warn(f"contract {c['id']}: ไม่มี component ไหน expose")

    implemented = {p for c in doc["components"] for p in c["implements"]}
    for p in doc["planes"]:
        if p["id"] not in implemented:
            warn(f"plane {p['id']}: ยังไม่มี component ไหน implement")

    used_repos = {c["repository"] for c in doc["components"] if c.get("repository")}
    for r in doc["repositories"]:
        if r["id"] not in used_repos:
            warn(f"repository {r['id']}: ไม่มี component ไหนอ้างถึง")

    # ข้อมูล ownership ต้องไม่ดูน่าเชื่อกว่าที่มันเป็น
    member_sets = {frozenset(t["members"]) for t in doc["teams"]}
    if len(member_sets) == 1 and len(doc["teams"]) > 1:
        only = sorted(next(iter(member_sets)))
        warn(f"ทุกทีม ({len(doc['teams'])} ทีม) มีสมาชิกชุดเดียวกัน {only} "
             f"— ownership ยังเป็นเชิงตรรกะ ไม่ใช่เชิงองค์กรจริง")


def check_github(doc: dict) -> None:
    default_owner = "monthop-gmail"
    for r in doc["repositories"]:
        declared = r["exists"]
        # ใช้ owner จาก url ถ้ามี ไม่งั้น fallback เป็น owner หลัก
        url = r.get("url") or ""
        slug = url.removeprefix("https://github.com/") if url else f"{default_owner}/{r['id']}"
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}", "-q", ".default_branch"],
            capture_output=True, text=True,
        )
        actual = proc.returncode == 0
        if declared and not actual:
            err(f"github: repositories.{r['id']} ประกาศว่า exists: true แต่หาไม่เจอบน GitHub")
        elif not declared and actual:
            err(f"github: repositories.{r['id']} ประกาศว่า exists: false แต่มีอยู่จริงแล้ว")
        elif actual:
            branch = proc.stdout.strip()
            if r.get("default_branch") and branch != r["default_branch"]:
                err(f"github: repositories.{r['id']} default_branch "
                    f"{r['default_branch']!r} แต่ของจริงคือ {branch!r}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_github = "--github" in sys.argv[1:]
    root = Path(__file__).resolve().parent.parent
    path = Path(args[0]) if args else root / "ecosystem.yaml"

    doc = normalize_dates(yaml.safe_load(path.read_text(encoding="utf-8")))

    check_schema(doc, root / "schema" / "ecosystem.schema.json")
    check_unique_ids(doc)

    ids = {s: {i["id"] for i in doc.get(s, [])}
           for s in ("contracts", "planes", "teams", "repositories", "components")}
    repo_by_id = {r["id"]: r for r in doc["repositories"]}

    check_references(doc, ids)
    if not errors:  # กฎเชิงความหมายจะอ่านผิดถ้า reference ยังพัง
        check_rules(doc, repo_by_id)
    if use_github:
        check_github(doc)

    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")

    counts = " · ".join(f"{len(v)} {k}" for k, v in ids.items())
    print()
    if errors:
        print(f"❌ {path.name}: {len(errors)} error, {len(warnings)} warning")
        return 1
    print(f"✅ {path.name}: {counts}")
    print(f"   ผ่านทั้งหมด — {len(warnings)} warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
