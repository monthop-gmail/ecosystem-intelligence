-- เป้าหมายต้องบอกได้ว่า "ใครตัดสิน" ไม่ใช่ "อ้างมาจากเอกสารไหน"
--
-- รอบแรกเก็บ source เพราะสมมติว่าเป้าหมาย derive มาจากเอกสารได้ — ซึ่งผิด
-- ไม่มีเอกสารไหนใน ecosystem เขียนเป้าหมายไว้เลย (ค้น 3 repo ได้ 0 ผลลัพธ์)
-- สิ่งที่ derive ได้คือกติกา ส่วนเป้าหมายต้องมีคนตัดสิน และต้องรู้ว่าใคร

ALTER TABLE ecosystem_goals DROP COLUMN source;
ALTER TABLE ecosystem_goals ADD COLUMN decided_by text NOT NULL DEFAULT 'unknown';
ALTER TABLE ecosystem_goals ADD COLUMN decided_at date;
ALTER TABLE ecosystem_goals ALTER COLUMN decided_by DROP DEFAULT;
