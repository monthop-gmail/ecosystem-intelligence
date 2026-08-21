#!/usr/bin/env python3
"""ตรวจ ecosystem.yaml — โครงสร้าง + referential integrity + กฎของ ecosystem

ใช้ได้สองทาง
    make validate                              CLI ผ่าน tools/validate_ecosystem.py
    from ecosystem_graph.validate import load   ให้ importer เรียกก่อนเขียน DB

importer ต้องใช้ตัวเดียวกันกับ CLI — ไม่งั้นของที่ผ่าน make validate
อาจเข้า DB ไม่ได้ หรือแย่กว่านั้นคือเข้าได้ทั้งที่ผิด
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

class Result:
    """ผลการตรวจหนึ่งครั้ง — ok เมื่อไม่มี error (warning ไม่ทำให้ตก)"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


class ValidationError(Exception):
    """ยกขึ้นเมื่อเรียก load(strict=True) แล้วไฟล์ไม่ผ่าน — importer พึ่งข้อนี้"""

    def __init__(self, result: "Result") -> None:
        super().__init__(f"ecosystem.yaml ไม่ผ่านการตรวจ — {len(result.errors)} error")
        self.result = result


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


def check_schema(res: Result, doc: dict, schema_path: Path) -> None:
    """ตรวจรูปร่างด้วย JSON Schema — ข้ามอย่างมีเสียงถ้าไม่มี jsonschema"""
    try:
        import jsonschema
    except ImportError:
        res.warn("ไม่มี jsonschema — ข้ามการตรวจโครงสร้าง (pip install jsonschema)")
        return
    import json

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(doc), key=lambda x: list(x.path)):
        loc = "/".join(str(p) for p in e.path) or "(root)"
        res.err(f"schema: {loc}: {e.message}")


def check_unique_ids(res: Result, doc: dict) -> None:
    for section in ("contracts", "planes", "teams", "repositories", "components"):
        seen: set[str] = set()
        for item in doc.get(section, []):
            i = item.get("id")
            if i in seen:
                res.err(f"{section}: id ซ้ำ — {i}")
            seen.add(i)


def check_references(res: Result, doc: dict, ids: dict[str, set[str]]) -> None:
    contracts, planes, teams, repos = (
        ids["contracts"], ids["planes"], ids["teams"], ids["repositories"]
    )

    if doc["metadata"]["maintained_by"] not in teams:
        res.err(f"metadata.maintained_by: ไม่รู้จักทีม {doc['metadata']['maintained_by']}")

    for name, src in doc.get("sources", {}).items():
        if src["owner"] not in repos:
            res.err(f"sources.{name}.owner: ไม่รู้จัก repository {src['owner']}")

    for c in doc["contracts"]:
        if c["authority"] not in repos:
            res.err(f"contracts.{c['id']}.authority: ไม่รู้จัก repository {c['authority']}")
        so = c.get("semantics_owner")
        if so and so not in repos:
            res.err(f"contracts.{c['id']}.semantics_owner: ไม่รู้จัก repository {so}")
        # derived กับ semantics_owner ต้องมาคู่กันเสมอ ไม่งั้นอ่านแล้วเข้าใจผิด
        if bool(c.get("derived")) != bool(so):
            res.err(f"contracts.{c['id']}: derived และ semantics_owner ต้องมาคู่กัน")

    for p in doc["planes"]:
        for cid in p["contracts"]:
            if cid not in contracts:
                res.err(f"planes.{p['id']}.contracts: ไม่รู้จัก contract {cid}")

    for comp in doc["components"]:
        cid = comp["id"]
        if comp["owner"] not in teams:
            res.err(f"components.{cid}.owner: ไม่รู้จักทีม {comp['owner']} — orphan component")
        repo = comp.get("repository")
        if repo is not None and repo not in repos:
            res.err(f"components.{cid}.repository: ไม่รู้จัก repository {repo}")
        for pid in comp["implements"]:
            if pid not in planes:
                res.err(f"components.{cid}.implements: ไม่รู้จัก plane {pid}")
        for field in ("exposes", "consumes", "expected_contracts"):
            for k in comp.get(field, []):
                if k not in contracts:
                    res.err(f"components.{cid}.{field}: ไม่รู้จัก contract {k}")
        for dep in comp.get("depends_on", []):
            if dep["component"] not in ids["components"]:
                res.err(f"components.{cid}.depends_on: ไม่รู้จัก component {dep['component']}")
            if dep["component"] == cid:
                res.err(f"components.{cid}.depends_on: ชี้ตัวเอง")


def check_rules(res: Result, doc: dict, repo_by_id: dict[str, dict]) -> None:
    today = date.today()

    for comp in doc["components"]:
        cid = comp["id"]
        outside = comp.get("outside_plane_model", False)

        # อยู่นอก plane model ต้องบอกเหตุผล — ไม่ใช่ปล่อยว่างเงียบ ๆ
        if outside and not comp.get("outside_plane_reason"):
            res.err(f"components.{cid}: outside_plane_model ต้องมี outside_plane_reason")
        if outside and comp["implements"]:
            res.err(f"components.{cid}: outside_plane_model แต่ยัง implements plane อยู่")
        if not outside and not comp["implements"]:
            res.err(f"components.{cid}: ไม่ implement plane ใดเลย "
                f"— ถ้าตั้งใจ ต้องประกาศ outside_plane_model: true")

        # component ที่ทำงานอยู่จริง ต้องมี repo ที่มีอยู่จริง
        repo = repo_by_id.get(comp.get("repository") or "")
        if comp["status"] in ("active", "in-development", "scaffold"):
            if repo is None:
                res.err(f"components.{cid}: status={comp['status']} แต่ไม่มี repository")
            elif not repo["exists"]:
                res.err(f"components.{cid}: status={comp['status']} "
                    f"แต่ repository {repo['id']} ยังไม่มีอยู่จริง")

        # consumes ต้องมีหลักฐาน ไม่ใช่ความตั้งใจ — ความตั้งใจไปอยู่ที่ expected_contracts
        conf = comp["conformance"]
        if comp["consumes"] and not conf.get("manifest"):
            res.err(f"components.{cid}: ประกาศ consumes โดยไม่มี manifest เป็นหลักฐาน "
                f"— ถ้าเป็นความตั้งใจ ให้ย้ายไป expected_contracts")
        overlap = set(comp["consumes"]) & set(comp.get("expected_contracts", []))
        if overlap:
            res.err(f"components.{cid}: {sorted(overlap)} อยู่ทั้งใน consumes และ expected_contracts")

        status = conf["status"]
        if status == "passing":
            lv = conf.get("last_verified")
            if not lv:
                res.err(f"components.{cid}.conformance: passing ต้องมี last_verified")
            else:
                age = (today - datetime.strptime(lv, "%Y-%m-%d").date()).days
                if age > CONFORMANCE_MAX_AGE_DAYS:
                    res.warn(f"components.{cid}: conformance passing แต่ตรวจครั้งสุดท้าย {age} วันที่แล้ว "
                         f"— ADR-0006 ถือเป็น unknown")
            if not conf.get("manifest"):
                res.err(f"components.{cid}.conformance: passing ต้องมี manifest")
        if status == "waived" and not (conf.get("waived_until") and conf.get("waiver_ref")):
            res.err(f"components.{cid}.conformance: waived ต้องมี waived_until และ waiver_ref")

        # manifest ที่ประกาศใน component ต้องตรงกับที่ประกาศใน repository
        if repo is not None and conf.get("manifest") != repo.get("manifest"):
            res.err(f"components.{cid}: manifest ไม่ตรงกับ repositories.{repo['id']} "
                f"({conf.get('manifest')!r} vs {repo.get('manifest')!r})")

    # contract หนึ่งตัวต้องมีเจ้าของที่ expose คนเดียว
    exposer: dict[str, str] = {}
    for comp in doc["components"]:
        for k in comp["exposes"]:
            if k in exposer:
                res.err(f"contract {k} ถูก expose โดยทั้ง {exposer[k]} และ {comp['id']} "
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
            res.warn(f"contract {c['id']}: ยังไม่มี consumer ที่ยืนยันแล้ว{tail}")
        if c["id"] not in exposer:
            res.warn(f"contract {c['id']}: ไม่มี component ไหน expose")

    implemented = {p for c in doc["components"] for p in c["implements"]}
    for p in doc["planes"]:
        if p["id"] not in implemented:
            res.warn(f"plane {p['id']}: ยังไม่มี component ไหน implement")

    used_repos = {c["repository"] for c in doc["components"] if c.get("repository")}
    for r in doc["repositories"]:
        if r["id"] not in used_repos:
            res.warn(f"repository {r['id']}: ไม่มี component ไหนอ้างถึง")

    # เป้าหมายที่หายไป ต้องรายงานว่าหายไป ไม่ใช่เอากติกามาติดป้ายแทน
    mission = doc.get("mission") or {}
    goals = mission.get("goals") or []
    if not goals:
        res.warn("ไม่มีเป้าหมายระดับ ecosystem — advisor จะตอบว่า 'ทำไม' ไม่ได้ "
                 "อย่าเอากติกามาเติมแทน เป้าหมายต้องมีคนตัดสิน")
    for g in goals:
        if not (g.get("decided_by") or mission.get("decided_by")):
            res.err(f"mission.goals.{g['id']}: ไม่ระบุว่าใครตัดสิน "
                    f"— ไม่มีเอกสารไหนใน ecosystem เขียนเป้าหมายไว้ จึง derive ไม่ได้ "
                    f"เป้าหมายที่ไม่มีเจ้าของคือเป้าหมายที่ใครก็แต่งเพิ่มได้")

    # เป้าหมายที่ไปซ้ำกับกฎ ทำให้ advisor ตอบวนกลับที่ตัวเอง
    rule_ids = {r["id"] for r in doc.get("architecture_rules", [])}
    for g in goals:
        if g["id"] in rule_ids:
            res.err(f"mission.goals.{g['id']}: ชื่อชนกับ architecture_rules "
                    f"— เป้าหมายกับกฎต้องไม่ใช่ของเดียวกัน")

    # ข้อมูล ownership ต้องไม่ดูน่าเชื่อกว่าที่มันเป็น
    member_sets = {frozenset(t["members"]) for t in doc["teams"]}
    if len(member_sets) == 1 and len(doc["teams"]) > 1:
        only = sorted(next(iter(member_sets)))
        res.warn(f"ทุกทีม ({len(doc['teams'])} ทีม) มีสมาชิกชุดเดียวกัน {only} "
             f"— ownership ยังเป็นเชิงตรรกะ ไม่ใช่เชิงองค์กรจริง")


def check_github(res: Result, doc: dict) -> None:
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
            res.err(f"github: repositories.{r['id']} ประกาศว่า exists: true แต่หาไม่เจอบน GitHub")
        elif not declared and actual:
            res.err(f"github: repositories.{r['id']} ประกาศว่า exists: false แต่มีอยู่จริงแล้ว")
        elif actual:
            branch = proc.stdout.strip()
            if r.get("default_branch") and branch != r["default_branch"]:
                res.err(f"github: repositories.{r['id']} default_branch "
                    f"{r['default_branch']!r} แต่ของจริงคือ {branch!r}")


from .config import ROOT  # noqa: E402 — ต้องอยู่หลัง import yaml ด้านบน

DEFAULT_PATH = ROOT / "ecosystem.yaml"
SCHEMA_PATH = ROOT / "schema" / "ecosystem.schema.json"


def validate(doc: dict, *, check_remote: bool = False) -> Result:
    """ตรวจเอกสารที่โหลดมาแล้ว — ไม่แตะไฟล์ ไม่แตะ DB"""
    res = Result()
    check_schema(res, doc, SCHEMA_PATH)
    check_unique_ids(res, doc)

    ids = {s: {i["id"] for i in doc.get(s, [])}
           for s in ("contracts", "planes", "teams", "repositories", "components")}
    check_references(res, doc, ids)
    if res.ok:  # กฎเชิงความหมายจะอ่านผิดถ้า reference ยังพัง
        check_rules(res, doc, {x["id"]: x for x in doc["repositories"]})
    if check_remote:
        check_github(res, doc)
    return res


def load(path: Path | str | None = None, *, strict: bool = True,
         check_remote: bool = False) -> tuple[dict, Result]:
    """โหลด ecosystem.yaml แล้วตรวจ — strict=True จะโยน ValidationError ถ้าไม่ผ่าน

    importer ใช้ทางนี้ เพื่อให้ "ตรวจไม่ผ่าน = ไม่เขียนอะไรลง DB เลย" เป็นจริง
    """
    path = Path(path) if path else DEFAULT_PATH
    doc = normalize_dates(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    result = validate(doc, check_remote=check_remote)
    if strict and not result.ok:
        raise ValidationError(result)
    return doc, result


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    use_github = "--github" in argv
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT_PATH

    doc, result = load(path, strict=False, check_remote=use_github)

    for w in result.warnings:
        print(f"  warn  {w}")
    for e in result.errors:
        print(f"  ERROR {e}")

    counts = " · ".join(
        f"{len(doc.get(s, []))} {s}"
        for s in ("contracts", "planes", "teams", "repositories", "components")
    )
    print()
    if not result.ok:
        print(f"❌ {path.name}: {len(result.errors)} error, {len(result.warnings)} warning")
        return 1
    print(f"✅ {path.name}: {counts}")
    print(f"   ผ่านทั้งหมด — {len(result.warnings)} warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
