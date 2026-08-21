"""Query ของ Ecosystem Graph — ชั้นเดียวที่แตะ SQL

ทุกอย่างที่อยู่เหนือขึ้นไป (API, Team Advisor, Impact Analyzer) เรียกผ่านที่นี่
ไม่ต่อ DB เอง (#6)
"""
from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one

MAX_DEPTH = 10


def meta(conn) -> dict[str, str]:
    return {r["key"]: r["value"] for r in fetch_all(conn, "SELECT key, value FROM ecosystem_meta")}


def goals(conn) -> list[dict]:
    """เป้าหมายระดับ ecosystem — decided_by บอกว่าใครตัดสิน ไม่ใช่อ้างมาจากไหน"""
    return fetch_all(conn, "SELECT id, goal, decided_by, decided_at "
                           "FROM ecosystem_goals ORDER BY id")


def architecture_rules(conn) -> list[dict]:
    return fetch_all(conn, "SELECT id, rule FROM architecture_rules ORDER BY id")


def list_teams(conn) -> list[dict]:
    return fetch_all(conn, "SELECT * FROM teams ORDER BY id")


def get_team(conn, team_id: str) -> dict | None:
    return fetch_one(conn, "SELECT * FROM teams WHERE id = %s", (team_id,))


def list_planes(conn) -> list[dict]:
    return fetch_all(conn, """
        SELECT p.*,
               COALESCE(pc.contracts, '{}') AS contracts,
               COALESCE(cp.implemented_by, '{}') AS implemented_by
          FROM planes p
          LEFT JOIN (SELECT plane_id, array_agg(contract_id ORDER BY contract_id) AS contracts
                       FROM plane_contracts GROUP BY plane_id) pc ON pc.plane_id = p.id
          LEFT JOIN (SELECT plane_id, array_agg(component_id ORDER BY component_id) AS implemented_by
                       FROM component_planes GROUP BY plane_id) cp ON cp.plane_id = p.id
         ORDER BY p.id
    """)


def get_plane(conn, plane_id: str) -> dict | None:
    rows = [p for p in list_planes(conn) if p["id"] == plane_id]
    return rows[0] if rows else None


def list_repositories(conn) -> list[dict]:
    return fetch_all(conn, """
        SELECT r.*, COALESCE(c.components, '{}') AS components
          FROM repositories r
          LEFT JOIN (SELECT repository, array_agg(id ORDER BY id) AS components
                       FROM components WHERE repository IS NOT NULL
                      GROUP BY repository) c ON c.repository = r.id
         ORDER BY r.does_exist DESC, r.id
    """)


def get_repository(conn, repo_id: str) -> dict | None:
    rows = [r for r in list_repositories(conn) if r["id"] == repo_id]
    return rows[0] if rows else None


def list_contracts(conn) -> list[dict]:
    return fetch_all(conn, """
        SELECT c.*,
               (SELECT component_id FROM component_contracts
                 WHERE contract_id = c.id AND relation = 'exposes') AS exposed_by,
               COALESCE((SELECT array_agg(component_id ORDER BY component_id)
                           FROM component_contracts
                          WHERE contract_id = c.id AND relation = 'consumes'), '{}') AS consumers,
               COALESCE((SELECT array_agg(component_id ORDER BY component_id)
                           FROM component_contracts
                          WHERE contract_id = c.id AND relation = 'expected'), '{}') AS expected_by
          FROM contracts c
         ORDER BY c.id
    """)


def get_contract(conn, contract_id: str) -> dict | None:
    rows = [c for c in list_contracts(conn) if c["id"] == contract_id]
    return rows[0] if rows else None


_COMPONENT_SELECT = """
    SELECT c.*,
           COALESCE(cp.planes, '{}')     AS implements,
           COALESCE(ex.contracts, '{}')  AS exposes,
           COALESCE(co.contracts, '{}')  AS consumes,
           COALESCE(xp.contracts, '{}')  AS expected_contracts,
           ce.status          AS conformance_status,
           ce.declared_status AS conformance_declared,
           ce.last_verified   AS conformance_last_verified,
           ce.age_days        AS conformance_age_days,
           ce.manifest, ce.pinned_commit, ce.evidence, ce.note
      FROM components c
      LEFT JOIN (SELECT component_id, array_agg(plane_id ORDER BY plane_id) AS planes
                   FROM component_planes GROUP BY component_id) cp ON cp.component_id = c.id
      LEFT JOIN (SELECT component_id, array_agg(contract_id ORDER BY contract_id) AS contracts
                   FROM component_contracts WHERE relation = 'exposes'
                  GROUP BY component_id) ex ON ex.component_id = c.id
      LEFT JOIN (SELECT component_id, array_agg(contract_id ORDER BY contract_id) AS contracts
                   FROM component_contracts WHERE relation = 'consumes'
                  GROUP BY component_id) co ON co.component_id = c.id
      LEFT JOIN (SELECT component_id, array_agg(contract_id ORDER BY contract_id) AS contracts
                   FROM component_contracts WHERE relation = 'expected'
                  GROUP BY component_id) xp ON xp.component_id = c.id
      LEFT JOIN conformance_effective ce ON ce.component_id = c.id
"""


def list_components(conn, *, team: str | None = None, plane: str | None = None,
                    status: str | None = None) -> list[dict]:
    where, params = [], []
    if team:
        where.append("c.owner = %s")
        params.append(team)
    if status:
        where.append("c.status = %s")
        params.append(status)
    if plane:
        where.append("EXISTS (SELECT 1 FROM component_planes cpx "
                     "WHERE cpx.component_id = c.id AND cpx.plane_id = %s)")
        params.append(plane)
    sql = _COMPONENT_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.id"
    return fetch_all(conn, sql, tuple(params))


def get_component(conn, component_id: str) -> dict | None:
    return fetch_one(conn, _COMPONENT_SELECT + " WHERE c.id = %s", (component_id,))


# ─────────────────────────────────────────────────────────────────────────
# Graph traversal
#
# เดินบน component_edges ซึ่งนับเฉพาะ consumes (มีหลักฐาน) ไม่นับ expected
# path[] กันวนไม่รู้จบ และใช้รายงาน circular dependency ได้ด้วย
# ─────────────────────────────────────────────────────────────────────────
_TRAVERSE = """
WITH RECURSIVE walk(node, depth, via, path) AS (
    SELECT %(start)s::text, 0, NULL::text, ARRAY[%(start)s::text]
  UNION ALL
    SELECT e.{next}, w.depth + 1, e.via, w.path || e.{next}
      FROM walk w
      JOIN component_edges e ON e.{cur} = w.node
     WHERE w.depth < %(depth)s
       AND NOT e.{next} = ANY(w.path)
)
SELECT node AS component, min(depth) AS depth,
       array_agg(DISTINCT via) FILTER (WHERE via IS NOT NULL) AS via,
       (array_agg(path ORDER BY depth))[1] AS path
  FROM walk
 WHERE depth > 0
 GROUP BY node
 ORDER BY min(depth), node
"""


def _traverse(conn, component_id: str, depth: int, direction: str) -> list[dict]:
    cur, nxt = ("dependent", "dependency") if direction == "up" else ("dependency", "dependent")
    sql = _TRAVERSE.format(cur=cur, next=nxt)
    return fetch_all(conn, sql, {"start": component_id, "depth": min(depth, MAX_DEPTH)})


def dependencies_of(conn, component_id: str, depth: int = MAX_DEPTH) -> list[dict]:
    """component นี้ขึ้นกับใครบ้าง (ขาขึ้น)"""
    return _traverse(conn, component_id, depth, "up")


def dependents_of(conn, component_id: str, depth: int = MAX_DEPTH) -> list[dict]:
    """ใครขึ้นกับ component นี้บ้าง (ขาลง) — แกนของ impact analysis ใน M4"""
    return _traverse(conn, component_id, depth, "down")


def contract_impact(conn, contract_id: str) -> dict[str, Any]:
    """เปลี่ยน contract นี้แล้วกระทบใคร — ตอบจากหลักฐาน ไม่ใช่ความตั้งใจ"""
    consumers = fetch_all(conn, """
        SELECT cc.component_id AS component, c.owner AS team, c.repository,
               ce.status AS conformance, ce.pinned_commit
          FROM component_contracts cc
          JOIN components c ON c.id = cc.component_id
          LEFT JOIN conformance_effective ce ON ce.component_id = c.id
         WHERE cc.contract_id = %s AND cc.relation = 'consumes'
         ORDER BY cc.component_id
    """, (contract_id,))
    waiting = fetch_all(conn, """
        SELECT component_id AS component FROM component_contracts
         WHERE contract_id = %s AND relation = 'expected' ORDER BY component_id
    """, (contract_id,))
    contract = get_contract(conn, contract_id)
    return {
        "contract": contract_id,
        "authority": contract["authority"] if contract else None,
        "semantics_owner": contract["semantics_owner"] if contract else None,
        "affected_components": [c["component"] for c in consumers],
        "affected_teams": sorted({c["team"] for c in consumers}),
        "affected_repositories": sorted({c["repository"] for c in consumers if c["repository"]}),
        "consumers": consumers,
        "expected_by": [w["component"] for w in waiting],
        "closable": not consumers,
    }


def cycles(conn) -> list[list[str]]:
    """หา circular dependency — ต้องรายงาน ไม่ใช่วนไม่รู้จบ (#5)"""
    rows = fetch_all(conn, """
        WITH RECURSIVE walk(start, node, path) AS (
            SELECT id, id, ARRAY[id] FROM components
          UNION ALL
            SELECT w.start, e.dependency, w.path || e.dependency
              FROM walk w
              JOIN component_edges e ON e.dependent = w.node
             WHERE array_length(w.path, 1) < %s
               AND (e.dependency = w.start OR NOT e.dependency = ANY(w.path))
        )
        SELECT DISTINCT path FROM walk
         WHERE node = start AND array_length(path, 1) > 1
    """, (MAX_DEPTH,))
    seen, out = set(), []
    for r in rows:
        cycle = r["path"][:-1]
        key = frozenset(cycle)
        if key not in seen:
            seen.add(key)
            out.append(r["path"])
    return out
