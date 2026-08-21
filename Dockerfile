# Ecosystem Intelligence — API image
#
# ตั้งใจให้ image นี้ทำอย่างเดียวคือ "เสิร์ฟ API"
# การ migrate และ import เป็นคำสั่งแยก ไม่ทำอัตโนมัติตอนบูต เพราะ container
# ที่แก้ schema เองตอนสตาร์ตจะแข่งกันเองทันทีที่มีมากกว่าหนึ่ง replica
# (เปิดได้ด้วย RUN_MIGRATIONS=1 สำหรับ dev ที่รันตัวเดียว)

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ECOSYSTEM_ROOT=/app

WORKDIR /app

# ติดตั้ง dependency ก่อน copy source — layer นี้จะถูก cache ไว้
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# ไฟล์ที่ runtime ต้องอ่าน — แยก layer เพราะเปลี่ยนบ่อยกว่าโค้ด
COPY ecosystem.yaml guardian.yaml ./
COPY schema ./schema
COPY migrations ./migrations
COPY evaluation ./evaluation
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# ไม่รันด้วย root — ไม่มีเหตุผลที่ต้องใช้สิทธิ์นั้น
RUN useradd --create-home --uid 10001 ecosystem && chown -R ecosystem:ecosystem /app
USER ecosystem

EXPOSE 8000

# python -c แทน curl เพราะ slim ไม่มี curl และไม่คุ้มจะลงเพิ่มเพื่อ healthcheck
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "ecosystem_graph.api:app", "--host", "0.0.0.0", "--port", "8000"]
