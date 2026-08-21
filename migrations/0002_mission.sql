-- เป้าหมายระดับ ecosystem — advisor ใช้ตอบว่า "ทำไมต้องทำสิ่งนี้"
-- M0 เลื่อนไว้เพราะยังไม่รู้รูปแบบที่ต้องใช้ · M2 รู้แล้วจึงเพิ่มตรงนี้
CREATE TABLE ecosystem_goals (
    id     text PRIMARY KEY,
    goal   text NOT NULL,
    source text NOT NULL
);
