#!/bin/sh
# รอ DB พร้อมก่อนค่อยเริ่ม — compose healthcheck ครอบแค่ตอนสตาร์ต
# ส่วนการรีสตาร์ตของ DB ระหว่างทางต้องรอเองที่นี่
set -e

python - <<'PY'
import os, sys, time
import psycopg
dsn = os.environ.get("ECOSYSTEM_DSN", "")
if not dsn:
    sys.exit("ต้องตั้ง ECOSYSTEM_DSN")
for attempt in range(60):
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            print("db พร้อมแล้ว")
            break
    except Exception as e:
        if attempt == 0:
            print(f"รอ db… ({type(e).__name__})")
        time.sleep(2)
else:
    sys.exit("ต่อ db ไม่ได้ภายใน 120 วินาที")
PY

if [ "${RUN_MIGRATIONS}" = "1" ]; then
    echo "RUN_MIGRATIONS=1 — รัน migrate + import"
    python -m ecosystem_graph.migrate
    python -m ecosystem_graph.importer
fi

exec "$@"
