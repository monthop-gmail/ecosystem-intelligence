# ชั้น LLM ของ Team Advisor

> ปิด issue #11 — เอกสารนี้อธิบายว่าทำไมชั้นนี้ถูกออกแบบแบบนี้

## Provider

| ค่า `ECOSYSTEM_LLM_PROVIDER` | ใช้อะไร | ต้องมีอะไร |
| --- | --- | --- |
| `offline` **(default)** | rule engine ในเครื่อง ไม่เรียกเน็ต | ไม่ต้องมีอะไร |
| `claude` | Anthropic SDK · default model `claude-opus-5` | `ANTHROPIC_API_KEY` |
| `chatgpt` | OpenAI SDK (Responses API) | `OPENAI_API_KEY` + **`ECOSYSTEM_OPENAI_MODEL`** |

```bash
make provider                                    # ดูว่าตอนนี้ใช้ตัวไหน
make ask TEAM=delivery-team Q="ทีมเราควรทำอะไรต่อ?"
curl localhost:8000/ask -H 'content-type: application/json' \
  -d '{"team":"knowledge-team","question":"ทีมเราควรทำอะไรต่อ?","provider":"claude"}'
```

## สี่ข้อที่ตั้งใจให้เป็นแบบนี้

### 1. default เป็น `offline` ไม่ใช่ `claude`

ระบบต้องรันและเทสต์ได้โดยไม่ต้องมี API key และต้องไม่มีทางเผลอยิง API จริงเพราะลืมตั้งค่า
CI จึงรันทั้งชุดได้โดยไม่เสียเงินและไม่ต้องเก็บ secret

`offline` **ไม่ใช่ LLM และไม่แกล้งเป็น** — เป็น rule engine ที่อ่าน context แล้วสรุปตามกฎตรง ๆ
คำตอบถูก mark `generated_by.provider = "offline"` เสมอ

มันมีอีกหน้าที่ที่สำคัญกว่า: **เป็น baseline** ถ้า LLM ตอบแย่กว่า rule engine
แปลว่าปัญหาอยู่ที่ prompt หรือ context ไม่ใช่ที่ model

### 2. ฝั่ง OpenAI ไม่มี model default

`ECOSYSTEM_OPENAI_MODEL` ต้องตั้งเอง ไม่งั้น provider ปฏิเสธตั้งแต่ตอนสร้าง
เพราะ model id ของ OpenAI ต่างกันตามบัญชีและเปลี่ยนบ่อย — การเดา id ไว้แล้วให้มัน 404
ตอน runtime แย่กว่าการบอกตั้งแต่ตอนตั้งค่า

ฝั่ง Anthropic มี default ได้เพราะ `claude-opus-5` เป็น id ที่ยืนยันได้

### 3. prompt เรียงจากนิ่งไปหาผันผวน — เพื่อ cache

```text
stable_system     ecosystem truth      ~6 KB   เหมือนกันทุกทีม ทุกคำถาม   ← cache ตรงนี้
volatile_context  team context         ~2 KB   เปลี่ยนตามทีม
question          คำถาม                 <1 KB   เปลี่ยนทุกครั้ง
```

prompt cache ของทั้งสองเจ้าเป็น **prefix match** — ของนิ่งต้องมาก่อนเสมอ
ฝั่ง Claude ใส่ `cache_control` ที่ท้าย system block · ฝั่ง OpenAI ใช้ `prompt_cache_key`

ecosystem truth ถูก serialize ด้วย `sort_keys=True` เพื่อให้ไบต์เดิมทุกครั้ง — ถ้าไม่เรียง key
dict ที่มีลำดับต่างกันจะทำให้ cache miss เงียบ ๆ

### 4. schema เดียว ใช้ได้ทุก provider

`RECOMMENDATION_SCHEMA` เป็น JSON Schema ธรรมดา ส่งเข้า
`output_config.format` ของ Anthropic และ `text.format` ของ OpenAI ได้ตรง ๆ
เปลี่ยน provider จึงไม่ต้องแก้ logic — ตามที่ #11 กำหนด

## Grounding — จุดที่ทำให้ต่างจาก "ถาม LLM เฉย ๆ"

model เห็นเฉพาะสิ่งที่ query มาให้ และคำตอบถูกตรวจย้อนว่าอ้าง id ที่มีจริงหรือไม่

| ระดับ | ตรวจอะไร | ไม่ผ่านแล้วยังไง |
| --- | --- | --- |
| strict | `references`, `dependencies`, `affected_components`, `team` | `grounding.ok = false` พร้อมรายชื่อ id ที่แต่งขึ้น |
| loose | token หน้าตาเหมือน contract (`xxx/vN`) ในข้อความอิสระ | `suspicious_mentions` — เตือน ไม่ใช่ error |

loose เป็นแค่ warning เพราะข้อความภาษาไทยมีคำที่หน้าตาเหมือน id ได้

คำตอบไม่ถูกแก้หรือถูกซ่อน — เรารายงานตามจริงว่ามันแต่ง แล้วให้คนตัดสิน

## ชุดคำถามทดสอบ

[`evaluation/questions.yaml`](../evaluation/questions.yaml) — เกณฑ์เป็น **ข้อเท็จจริงที่ต้องมี**
ไม่ใช่การเทียบข้อความคำต่อคำ เพราะภาษาที่ LLM เขียนต่างกันได้ แต่ข้อเท็จจริงต้องตรงเสมอ

```yaml
must_reference:    id ที่คำตอบต้องอ้างถึง
must_not_mention:  id ที่ห้ามอ้าง (ของทีมอื่น หรือไม่มีอยู่จริง)
expect_answerable: ข้อมูลพอตอบไหม
```

รันกับ provider ไหนก็ได้ — `ECOSYSTEM_LLM_PROVIDER=claude pytest tests/test_advisor.py`
ใช้เทียบว่าเปลี่ยน prompt แล้วดีขึ้นหรือแย่ลง และเทียบ provider กันตรง ๆ

## เพิ่ม provider ใหม่

implement `LLMProvider` protocol ใน [`llm/base.py`](../src/ecosystem_graph/llm/base.py)
แล้วลงทะเบียนใน `llm/__init__.py` — ไม่ต้องแตะ `advisor.py` เลย
