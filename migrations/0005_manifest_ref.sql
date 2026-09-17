-- manifest ไม่จำเป็นต้องอยู่ branch หลัก
--
-- botforge วาง platform-contract.yaml ไว้ที่ branch v2 ขณะที่ default เป็น main
-- check ที่อ่านแค่ branch หลักแล้วสรุปว่า "อ่าน manifest ไม่ได้" คือการรายงานผิด
-- ซึ่งอันตรายกว่าไม่รายงาน เพราะมันดูเหมือน repo นั้นมีปัญหา
ALTER TABLE conformance ADD COLUMN manifest_ref text;

COMMENT ON COLUMN conformance.manifest_ref IS
  'branch/ref ที่ manifest อยู่ — NULL แปลว่า branch หลักของ repo';
