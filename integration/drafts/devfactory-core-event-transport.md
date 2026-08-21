<!-- ร่างสำหรับเปิดที่ monthop-gmail/devfactory-core — เปิดแล้วที่ https://github.com/monthop-gmail/devfactory-core/issues/32 เมื่อ 2026-08-22 -->
# ตกลงเรื่อง transport ของ event จาก `ecosystem-intelligence`

`ecosystem-intelligence` ปล่อย `event/v1` ที่ conform แล้ว แต่ยังไม่มีทางส่งถึงใคร

**ที่ตกลงกันแล้วโดยไม่ต้องคุย** — schema เป็น `event/v1` ที่ทั้งสองฝั่ง pin อยู่แล้ว
จึงไม่มีอะไรต้องออกแบบเพิ่มในส่วน payload

**ที่ยังต้องตกลง** — transport อย่างเดียว

| ทางเลือก | ข้อดี | ข้อเสีย |
| --- | --- | --- |
| webhook | ตรงไปตรงมา ไม่ต้องมี broker | ต้องมี endpoint และจัดการ retry เอง |
| ดึงจาก API | ฝั่งรับคุมจังหวะเอง ไม่ต้องเปิด endpoint | ต้อง poll และจำว่าอ่านถึงไหนแล้ว |
| ผ่าน broker ที่มีอยู่ | เข้ากับ observability plane ในอนาคต | ยังไม่มี broker กลางใน ecosystem |

**ตัวอย่าง payload จริง** (จาก `make emit TEAM=knowledge-team`)

```json
{
  "event_type": "ADVISORY_ISSUED",
  "tenant_id": "default",
  "subject_type": "record",
  "source": { "kind": "external", "system": "ecosystem-intelligence" },
  "metadata": {
    "record_type": "ecosystem_advisory",
    "team": "knowledge-team",
    "title": "ทำให้ enterprise-knowledge conform ตาม ADR-0006",
    "priority": 1,
    "references": ["enterprise-knowledge", "enterprise-knowledge#17", "conformance-provable"]
  }
}
```

RFC-0008 ครอบเคสนี้ไว้แล้ว — event ที่ไม่ได้เกิดจาก job มี `subject` แทน `job_id`
และเราไม่ปลอม `job_id` ตามที่ RFC ระบุว่าเป็นทางเลือกที่แย่ที่สุด
