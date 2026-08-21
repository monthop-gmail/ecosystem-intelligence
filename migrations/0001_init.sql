-- Ecosystem Graph — schema ตั้งต้น
-- entity และ relationship ทั้งหมดตาม docs/entities.md
--
-- หลัก: ecosystem.yaml เป็นแหล่งความจริง DB เป็นสำเนาที่ query ได้
-- ทุกตารางจึงถูกเขียนใหม่ทั้งหมดตอน import (ดู src/ecosystem_graph/importer.py)

CREATE TABLE ecosystem_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

CREATE TABLE architecture_rules (
    id   text PRIMARY KEY,
    rule text NOT NULL
);

CREATE TABLE sources (
    name  text PRIMARY KEY,
    owner text NOT NULL,
    url   text NOT NULL,
    rule  text,
    note  text
);

CREATE TABLE teams (
    id               text PRIMARY KEY,
    name             text NOT NULL,
    responsibilities text[] NOT NULL DEFAULT '{}',
    members          text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE repositories (
    id             text PRIMARY KEY,
    url            text,
    visibility     text,
    default_branch text,
    does_exist     boolean NOT NULL,
    manifest       text,
    CONSTRAINT repositories_visibility_ck
        CHECK (visibility IS NULL OR visibility IN ('public', 'private', 'unknown'))
);

CREATE TABLE planes (
    id             text PRIMARY KEY,
    name           text NOT NULL,
    responsibility text NOT NULL,
    must_not       text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE contracts (
    id              text PRIMARY KEY,
    authority       text NOT NULL REFERENCES repositories(id),
    semantics_owner text REFERENCES repositories(id),
    derived         boolean NOT NULL DEFAULT false,
    status          text NOT NULL,
    -- derived กับ semantics_owner ต้องมาคู่กันเสมอ (docs/entities.md §1.3)
    CONSTRAINT contracts_derived_ck
        CHECK (derived = (semantics_owner IS NOT NULL))
);

CREATE TABLE components (
    id                   text PRIMARY KEY,
    name                 text NOT NULL,
    owner                text NOT NULL REFERENCES teams(id),
    repository           text REFERENCES repositories(id),
    status               text NOT NULL,
    outside_plane_model  boolean NOT NULL DEFAULT false,
    outside_plane_reason text,
    implements_note      text,
    CONSTRAINT components_status_ck
        CHECK (status IN ('active', 'in-development', 'scaffold', 'planned', 'deprecated')),
    -- อยู่นอก plane model ต้องบอกเหตุผล ห้ามปล่อยว่างเงียบ ๆ
    CONSTRAINT components_outside_reason_ck
        CHECK (NOT outside_plane_model OR outside_plane_reason IS NOT NULL)
);

-- Plane governed_by Contract
CREATE TABLE plane_contracts (
    plane_id    text NOT NULL REFERENCES planes(id) ON DELETE CASCADE,
    contract_id text NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    PRIMARY KEY (plane_id, contract_id)
);

-- Component implements Plane  (N:M — agent-backend-os กินสอง plane)
CREATE TABLE component_planes (
    component_id text NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    plane_id     text NOT NULL REFERENCES planes(id) ON DELETE CASCADE,
    PRIMARY KEY (component_id, plane_id)
);

-- Component exposes / consumes / expects Contract
--   exposes  = เป็นเจ้าของ contract นั้น
--   consumes = pin ไว้จริงใน platform-contract.yaml (มีหลักฐาน — ใช้คำนวณ impact ได้)
--   expected = ควรใช้ตาม plane/roadmap (ความตั้งใจ — ห้ามใช้คำนวณ impact)
CREATE TABLE component_contracts (
    component_id text NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    contract_id  text NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    relation     text NOT NULL,
    PRIMARY KEY (component_id, contract_id, relation),
    CONSTRAINT component_contracts_relation_ck
        CHECK (relation IN ('exposes', 'consumes', 'expected'))
);

-- contract หนึ่งตัวมีผู้ expose ได้รายเดียว
CREATE UNIQUE INDEX component_contracts_one_exposer
    ON component_contracts (contract_id) WHERE relation = 'exposes';

-- dependency ที่ไม่ผ่าน contract — ต้องมีเหตุผลกำกับเสมอ
CREATE TABLE component_deps (
    component_id text NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    depends_on   text NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    reason       text NOT NULL,
    PRIMARY KEY (component_id, depends_on),
    CONSTRAINT component_deps_no_self CHECK (component_id <> depends_on)
);

CREATE TABLE conformance (
    component_id  text PRIMARY KEY REFERENCES components(id) ON DELETE CASCADE,
    status        text NOT NULL,
    manifest      text,
    pinned_commit text,
    last_verified date,
    evidence      text,
    note          text,
    waived_until  date,
    waiver_ref    text,
    CONSTRAINT conformance_status_ck
        CHECK (status IN ('passing', 'failing', 'unknown', 'waived', 'not-applicable')),
    CONSTRAINT conformance_passing_ck
        CHECK (status <> 'passing' OR (last_verified IS NOT NULL AND manifest IS NOT NULL)),
    CONSTRAINT conformance_waived_ck
        CHECK (status <> 'waived' OR (waived_until IS NOT NULL AND waiver_ref IS NOT NULL))
);

CREATE INDEX components_owner_idx        ON components (owner);
CREATE INDEX components_repository_idx   ON components (repository);
CREATE INDEX component_contracts_cid_idx ON component_contracts (contract_id, relation);

-- ─────────────────────────────────────────────────────────────────────────
-- เส้นเชื่อมของ graph
--
-- A ขึ้นกับ B เมื่อ A consumes contract ที่ B expose อยู่
-- ใช้เฉพาะ relation='consumes' — 'expected' เป็นความตั้งใจ ไม่ใช่หลักฐาน
-- ─────────────────────────────────────────────────────────────────────────
CREATE VIEW component_edges AS
    SELECT c.component_id AS dependent,
           e.component_id AS dependency,
           c.contract_id  AS via,
           'contract'     AS kind
      FROM component_contracts c
      JOIN component_contracts e
        ON e.contract_id = c.contract_id AND e.relation = 'exposes'
     WHERE c.relation = 'consumes'
       AND c.component_id <> e.component_id
    UNION ALL
    SELECT component_id, depends_on, reason, 'explicit'
      FROM component_deps;

-- conformance ที่คำนวณกฎ 90 วันของ ADR-0006 แล้ว
-- passing ที่เก่ากว่า 90 วันคือ unknown ไม่ว่าไฟล์จะเขียนว่าอะไร
CREATE VIEW conformance_effective AS
    SELECT component_id,
           status AS declared_status,
           CASE
               WHEN status = 'passing'
                    AND last_verified < CURRENT_DATE - INTERVAL '90 days' THEN 'unknown'
               WHEN status = 'waived'
                    AND waived_until < CURRENT_DATE THEN 'unknown'
               ELSE status
           END AS status,
           last_verified,
           CURRENT_DATE - last_verified AS age_days,
           manifest, pinned_commit, evidence, note, waived_until, waiver_ref
      FROM conformance;
