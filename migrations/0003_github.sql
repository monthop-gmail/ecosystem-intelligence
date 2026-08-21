-- GitHub Intelligence (M3) — สถานะจริงจาก GitHub
--
-- ตารางกลุ่มนี้ **ไม่มี FK ไปหา repositories** โดยตั้งใจ
-- เพราะ import ของ M1 ลบ-เขียนตาราง ecosystem ใหม่ทั้งชุดทุกครั้ง
-- ถ้าผูก FK ไว้ ข้อมูล sync จะโดนลบทิ้งทุกครั้งที่ import (หรือ import จะพัง)
--
-- และมันควรเป็นอิสระอยู่แล้ว: ecosystem.yaml คือ "สิ่งที่เราตั้งใจ"
-- ส่วนตารางพวกนี้คือ "สิ่งที่เกิดขึ้นจริง" — ต้องเทียบกันได้ ไม่ใช่ผูกกันจนแยกไม่ออก

CREATE TABLE repo_sync_state (
    repository      text PRIMARY KEY,
    last_synced_at  timestamptz,
    last_ok         boolean NOT NULL DEFAULT false,
    last_error      text,
    default_branch  text,
    pushed_at       timestamptz,
    last_commit_sha text,
    last_commit_at  timestamptz,
    open_issues     integer,
    visibility      text,
    archived        boolean
);

CREATE TABLE issues (
    repository  text NOT NULL,
    number      integer NOT NULL,
    title       text NOT NULL,
    state       text NOT NULL,
    author      text,
    assignees   text[] NOT NULL DEFAULT '{}',
    labels      text[] NOT NULL DEFAULT '{}',
    milestone   text,
    created_at  timestamptz,
    updated_at  timestamptz,
    closed_at   timestamptz,
    url         text,
    PRIMARY KEY (repository, number)
);

CREATE TABLE pull_requests (
    repository      text NOT NULL,
    number          integer NOT NULL,
    title           text NOT NULL,
    state           text NOT NULL,          -- open | closed | merged
    author          text,
    draft           boolean NOT NULL DEFAULT false,
    review_decision text,
    created_at      timestamptz,
    updated_at      timestamptz,
    merged_at       timestamptz,
    closed_at       timestamptz,
    url             text,
    files_synced    boolean NOT NULL DEFAULT false,
    PRIMARY KEY (repository, number)
);

CREATE TABLE pr_files (
    repository text NOT NULL,
    number     integer NOT NULL,
    path       text NOT NULL,
    status     text,
    changes    integer,
    PRIMARY KEY (repository, number, path)
);

CREATE INDEX issues_state_idx      ON issues (state, updated_at DESC);
CREATE INDEX pull_requests_state_idx ON pull_requests (state, updated_at DESC);
CREATE INDEX pr_files_path_idx     ON pr_files (path);

-- ─────────────────────────────────────────────────────────────────────────
-- PR ที่แตะไฟล์ซึ่งเป็น contract หรือ manifest
--
-- นี่คือสัญญาณที่มีค่าที่สุดจาก GitHub — การเปลี่ยน contract คือจุดที่
-- ecosystem พังได้ง่ายที่สุด และเป็น input ตรงของ M5 Architecture Guardian
-- ─────────────────────────────────────────────────────────────────────────
CREATE VIEW contract_touching_prs AS
    SELECT DISTINCT p.repository, p.number, p.title, p.state, p.author,
           p.updated_at, p.url, f.path,
           CASE
               WHEN f.path LIKE 'contracts/%'          THEN 'contract-schema'
               WHEN f.path = 'platform-contract.yaml'  THEN 'consumer-manifest'
               WHEN f.path = 'contract-semantics.yaml' THEN 'contract-semantics'
               WHEN f.path LIKE 'decisions/%'          THEN 'adr'
               WHEN f.path LIKE 'rfcs/%'               THEN 'rfc'
           END AS kind
      FROM pull_requests p
      JOIN pr_files f ON f.repository = p.repository AND f.number = p.number
     WHERE f.path LIKE 'contracts/%'
        OR f.path IN ('platform-contract.yaml', 'contract-semantics.yaml')
        OR f.path LIKE 'decisions/%'
        OR f.path LIKE 'rfcs/%';

-- งานที่เปิดค้างอยู่ ผูกกลับไปยัง component และทีมเจ้าของ
CREATE VIEW open_work AS
    SELECT 'issue' AS kind, i.repository, i.number, i.title, i.author,
           i.assignees, i.labels, i.updated_at, i.url,
           c.id AS component, c.owner AS team
      FROM issues i
      LEFT JOIN components c ON c.repository = i.repository
     WHERE i.state = 'open'
    UNION ALL
    SELECT 'pr', p.repository, p.number, p.title, p.author,
           ARRAY[]::text[], ARRAY[]::text[], p.updated_at, p.url,
           c.id, c.owner
      FROM pull_requests p
      LEFT JOIN components c ON c.repository = p.repository
     WHERE p.state = 'open';
