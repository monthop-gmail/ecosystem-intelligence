# Deploy

```bash
cp .env.example .env
docker compose --profile app up -d --build     # db + api
curl localhost:8000/health
```

`make up` ยกแค่ PostgreSQL (สำหรับ dev ที่รัน API จาก source)
ส่วน `--profile app` ยกทั้ง DB และ API ในคอนเทนเนอร์

| | |
| --- | --- |
| base image | `python:3.12-slim` · ขนาด ~184 MB |
| user | `ecosystem` (uid 10001) — ไม่รันด้วย root |
| healthcheck | เรียก `/health` ด้วย `python -c` (slim ไม่มี curl และไม่คุ้มจะลงเพิ่ม) |
| migration | **ไม่รันอัตโนมัติ** เว้นแต่ตั้ง `RUN_MIGRATIONS=1` |

## ทำไม migration ไม่รันเองตอนบูต

container ที่แก้ schema เองตอนสตาร์ต จะแข่งกันเองทันทีที่มีมากกว่าหนึ่ง replica
`RUN_MIGRATIONS=1` มีไว้สำหรับ dev ที่รันตัวเดียว — บน production ให้รันเป็นขั้นแยก

```bash
docker compose run --rm api python -m ecosystem_graph.migrate
docker compose run --rm api python -m ecosystem_graph.importer
```

## บั๊กที่เจอตอนทำ image นี้ — และทำไมมันอันตราย

path ของไฟล์ข้อมูลเคยคำนวณจาก `__file__` ขึ้นไปสามชั้น ซึ่งถูกเฉพาะตอนรันจาก
`src/` layout พอ `pip install` จริง โมดูลไปอยู่ใน `site-packages` แล้วสามชั้นขึ้นไป
กลายเป็น `/usr/local/lib/python3.12`

ผลคือ `migrate` glob ไม่เจอไฟล์ `.sql` สักไฟล์ แล้ว **รายงานว่า "ไม่มีอะไรใหม่"**
— สำเร็จทั้งที่ไม่ได้สร้างตารางอะไรเลย app จึงไปพังทีหลังในที่ที่หาสาเหตุยากกว่ามาก

แก้สองชั้น
1. หา root ตามลำดับ `ECOSYSTEM_ROOT` → layout ของ repo → cwd
2. **ไม่เจอไฟล์ migration เลย = error** ไม่ใช่ "ไม่มีอะไรใหม่"

ข้อ 2 สำคัญกว่า — การเดา path ผิดยังพอแก้ได้ แต่การรายงานว่าสำเร็จทั้งที่ไม่ได้ทำ
คือสิ่งที่ทำให้ไม่มีใครรู้ว่าพัง

## ตรวจสภาพ

```bash
make health            # รายงาน markdown
make health REMOTE=1   # ตรวจ manifest drift + registry ด้วย
```

CI รัน `ecosystem health` ทุกวันตอน 01:00 UTC — sync จาก GitHub จริง แล้วเขียน
รายงานลง job summary และ **ตกถ้า Guardian เจอ error**

DB ของ job นั้นเป็นของชั่วคราว สร้างใหม่ทุกครั้ง สิ่งที่เก็บคือรายงาน ไม่ใช่ข้อมูล
— ถ้าต้องการ state ที่อยู่ข้ามรอบต้อง deploy จริง
