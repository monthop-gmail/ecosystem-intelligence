"""Ecosystem Graph API (#6) — read-only

read-only ไม่ได้บังคับด้วยการ "ไม่เขียน route ที่เขียนข้อมูล" เฉย ๆ
ทุก request เปิดทรานแซกชันแบบ READ ONLY ที่ระดับ PostgreSQL
การเขียนทำได้ทางเดียวคือ import จาก ecosystem.yaml (#7)
"""
from __future__ import annotations

from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import advisor
from . import queries as q
from .db import connect
from .llm import LLMError, get_provider

app = FastAPI(
    title="Ecosystem Graph API",
    version="0.1.0",
    description=(
        "Query ecosystem — component, contract, dependency, ownership\n\n"
        "**ไม่มี endpoint ไหนเขียนข้อมูล** แหล่งความจริงคือ `ecosystem.yaml` "
        "การเปลี่ยนแปลงทำผ่าน import เท่านั้น (`/ask` เป็น POST เพราะต้องส่งคำถามใน body "
        "ไม่ใช่เพราะเขียนข้อมูล)"
    ),
)


def db() -> Iterator[Any]:
    with connect(readonly=True) as conn:
        yield conn


def _found(obj: Any, kind: str, ident: str) -> Any:
    if obj is None:
        raise HTTPException(status_code=404, detail=f"ไม่พบ {kind}: {ident}")
    return obj


@app.get("/health", tags=["meta"], summary="ระบบพร้อมไหม และข้อมูลเป็นของวันไหน")
def health(conn=Depends(db)) -> dict:
    meta = q.meta(conn)
    return {
        "status": "ok",
        "ecosystem": meta.get("name"),
        "updated": meta.get("updated"),
        "apiVersion": meta.get("apiVersion"),
        "components": len(q.list_components(conn)),
    }


@app.get("/architecture-rules", tags=["meta"],
         summary="กฎที่ทุก plane ต้องเคารพ — input ของ Architecture Guardian")
def architecture_rules(conn=Depends(db)) -> list[dict]:
    return q.architecture_rules(conn)


@app.get("/teams", tags=["team"], summary="ทีมทั้งหมด")
def list_teams(conn=Depends(db)) -> list[dict]:
    return q.list_teams(conn)


@app.get("/teams/{team_id}", tags=["team"], summary="ทีมหนึ่งทีม")
def get_team(team_id: str, conn=Depends(db)) -> dict:
    return _found(q.get_team(conn, team_id), "team", team_id)


@app.get("/teams/{team_id}/components", tags=["team"],
         summary="ทีมนี้เป็นเจ้าของ component อะไรบ้าง")
def team_components(team_id: str, conn=Depends(db)) -> list[dict]:
    _found(q.get_team(conn, team_id), "team", team_id)
    return q.list_components(conn, team=team_id)


@app.get("/components", tags=["component"], summary="component ทั้งหมด — กรองได้")
def list_components(
    conn=Depends(db),
    team: str | None = Query(None, description="กรองตามทีมเจ้าของ"),
    plane: str | None = Query(None, description="กรองตาม plane ที่ implement"),
    status: str | None = Query(None, description="active / in-development / scaffold / planned"),
) -> list[dict]:
    return q.list_components(conn, team=team, plane=plane, status=status)


@app.get("/components/{component_id}", tags=["component"], summary="component หนึ่งตัว")
def get_component(component_id: str, conn=Depends(db)) -> dict:
    return _found(q.get_component(conn, component_id), "component", component_id)


@app.get("/components/{component_id}/dependencies", tags=["graph"],
         summary="component นี้ขึ้นกับใครบ้าง (ขาขึ้น)")
def dependencies(component_id: str, depth: int = Query(q.MAX_DEPTH, ge=1, le=q.MAX_DEPTH),
                 conn=Depends(db)) -> dict:
    _found(q.get_component(conn, component_id), "component", component_id)
    return {"component": component_id, "direction": "dependencies",
            "results": q.dependencies_of(conn, component_id, depth)}


@app.get("/components/{component_id}/dependents", tags=["graph"],
         summary="ใครขึ้นกับ component นี้บ้าง (ขาลง)")
def dependents(component_id: str, depth: int = Query(q.MAX_DEPTH, ge=1, le=q.MAX_DEPTH),
               conn=Depends(db)) -> dict:
    _found(q.get_component(conn, component_id), "component", component_id)
    return {"component": component_id, "direction": "dependents",
            "results": q.dependents_of(conn, component_id, depth)}


@app.get("/contracts", tags=["contract"], summary="contract ทั้งหมดพร้อมผู้ใช้")
def list_contracts(conn=Depends(db)) -> list[dict]:
    return q.list_contracts(conn)


@app.get("/contracts/{contract_name}/v{version}", tags=["contract"], summary="contract หนึ่งตัว")
def get_contract(contract_name: str, version: int, conn=Depends(db)) -> dict:
    cid = f"{contract_name}/v{version}"
    return _found(q.get_contract(conn, cid), "contract", cid)


@app.get("/contracts/{contract_name}/v{version}/impact", tags=["graph"],
         summary="เปลี่ยน contract นี้แล้วกระทบใคร")
def contract_impact(contract_name: str, version: int, conn=Depends(db)) -> dict:
    cid = f"{contract_name}/v{version}"
    _found(q.get_contract(conn, cid), "contract", cid)
    return q.contract_impact(conn, cid)


@app.get("/planes", tags=["plane"], summary="plane ทั้ง 11 ตัว")
def list_planes(conn=Depends(db)) -> list[dict]:
    return q.list_planes(conn)


@app.get("/planes/{plane_id}", tags=["plane"], summary="plane หนึ่งตัว")
def get_plane(plane_id: str, conn=Depends(db)) -> dict:
    return _found(q.get_plane(conn, plane_id), "plane", plane_id)


@app.get("/repositories", tags=["repository"], summary="ทะเบียน repository")
def list_repositories(conn=Depends(db)) -> list[dict]:
    return q.list_repositories(conn)


@app.get("/repositories/{repo_id}", tags=["repository"], summary="repository หนึ่งตัว")
def get_repository(repo_id: str, conn=Depends(db)) -> dict:
    return _found(q.get_repository(conn, repo_id), "repository", repo_id)


@app.get("/graph/cycles", tags=["graph"], summary="circular dependency ที่ตรวจพบ")
def cycles(conn=Depends(db)) -> dict:
    found = q.cycles(conn)
    return {"count": len(found), "cycles": found}


# ─────────────────────────────────────────────────────────────────────────
# Team Advisor (#10)
#
# /ask เป็น POST เพราะคำถามต้องอยู่ใน body — ไม่ได้เขียนอะไรลง DB
# connection ยังเป็น READ ONLY เหมือน endpoint อื่นทุกตัว
# ─────────────────────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    team: str = Field(description="id ของทีมที่ถาม เช่น delivery-team")
    question: str = Field(min_length=3, description="คำถามภาษาธรรมชาติ")
    provider: str | None = Field(
        default=None, description="claude | chatgpt | offline — ไม่ใส่ = ตามค่า config")
    effort: str = Field(default="high", pattern="^(low|medium|high|xhigh|max)$")


@app.post("/ask", tags=["advisor"], summary="ถามจากมุมของทีม — ไม่เขียนข้อมูลใด ๆ")
def ask(req: AskRequest, conn=Depends(db)) -> dict:
    try:
        provider = get_provider(req.provider)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        result = advisor.ask(conn, req.team, req.question,
                             provider=provider, effort=req.effort)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"provider ตอบไม่ได้: {e}") from e
    return _found(result, "team", req.team)


@app.get("/contracts/{contract_name}/v{version}/coordination", tags=["advisor"],
         summary="เปลี่ยน contract นี้ — ความเสี่ยงและลำดับการประสานงาน")
def coordination(contract_name: str, version: int,
                 provider: str | None = Query(None, description="claude | chatgpt | offline"),
                 conn=Depends(db)) -> dict:
    cid = f"{contract_name}/v{version}"
    try:
        result = advisor.impact(conn, cid, provider=get_provider(provider))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"provider ตอบไม่ได้: {e}") from e
    return _found(result, "contract", cid)


@app.get("/advisor/provider", tags=["advisor"], summary="ตอนนี้ใช้ provider ตัวไหนอยู่")
def current_provider() -> dict:
    try:
        p = get_provider()
        return {"provider": p.name, "model": p.model, "configured": True}
    except LLMError as e:
        return {"provider": None, "model": None, "configured": False, "reason": str(e)}
