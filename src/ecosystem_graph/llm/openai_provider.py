"""ChatGPT — ผ่าน OpenAI SDK อย่างเป็นทางการ (Responses API)

**ต้องตั้ง `ECOSYSTEM_OPENAI_MODEL` เอง ไม่มีค่า default**
จงใจไม่ใส่ default เพราะ model id ของ OpenAI เปลี่ยนบ่อยและต่างกันตามบัญชี
การเดา id แล้วให้มัน 404 ตอน runtime แย่กว่าการบอกตั้งแต่ตอนตั้งค่า

การเรียงพารามิเตอร์ตรงกับฝั่ง Claude
    instructions  ecosystem truth ก้อนนิ่ง
    input         team context + คำถาม
    prompt_cache_key  ให้ OpenAI จับ prefix เดียวกันซ้ำได้
"""
from __future__ import annotations

import json
import os
from typing import Any

from .base import LLMError

MAX_OUTPUT_TOKENS = 16000


class OpenAIProvider:
    name = "chatgpt"

    def __init__(self, model: str | None = None) -> None:
        try:
            import openai
        except ImportError as e:  # pragma: no cover
            raise LLMError("ต้องติดตั้ง openai — pip install openai") from e
        self._openai = openai
        self._client = openai.OpenAI()
        self.model = model or os.environ.get("ECOSYSTEM_OPENAI_MODEL", "")
        if not self.model:
            raise LLMError(
                "ต้องตั้ง ECOSYSTEM_OPENAI_MODEL — provider นี้ไม่มี default "
                "เพราะ model id ของ OpenAI ต่างกันตามบัญชีและเปลี่ยนบ่อย"
            )

    def complete_json(self, *, stable_system: str, volatile_context: str,
                      question: str, schema: dict[str, Any],
                      effort: str = "high") -> dict[str, Any]:
        o = self._openai
        try:
            response = self._client.responses.create(
                model=self.model,
                instructions=stable_system,
                input=(
                    f"<team_context>\n{volatile_context}\n</team_context>\n\n"
                    f"<question>\n{question}\n</question>"
                ),
                max_output_tokens=MAX_OUTPUT_TOKENS,
                reasoning={"effort": effort},
                prompt_cache_key="ecosystem-truth",
                text={"format": {
                    "type": "json_schema",
                    "name": "team_recommendation",
                    "schema": schema,
                    "strict": True,
                }},
            )
        except o.NotFoundError as e:
            raise LLMError(f"ไม่รู้จัก model {self.model!r} — ตั้ง ECOSYSTEM_OPENAI_MODEL ใหม่") from e
        except o.AuthenticationError as e:
            raise LLMError("OPENAI_API_KEY ไม่ถูกต้องหรือยังไม่ได้ตั้ง") from e
        except o.RateLimitError as e:
            raise LLMError("โดน rate limit ของ OpenAI — ลองใหม่ภายหลัง") from e
        except o.APIStatusError as e:
            raise LLMError(f"OpenAI ตอบ {e.status_code}") from e
        except o.APIConnectionError as e:
            raise LLMError("ต่อ OpenAI ไม่ได้ — ตรวจเน็ต") from e

        text = getattr(response, "output_text", None)
        if not text:
            raise LLMError("ไม่มีข้อความในคำตอบของ OpenAI")
        return json.loads(text)
