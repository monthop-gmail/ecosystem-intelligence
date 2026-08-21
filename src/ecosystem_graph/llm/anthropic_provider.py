"""Claude — ผ่าน Anthropic SDK อย่างเป็นทางการ

ทำไมเรียงพารามิเตอร์แบบนี้
    system      ecosystem truth ก้อนนิ่ง + cache_control → cache hit ข้ามทุกคำถามของทุกทีม
    messages    team context แล้วตามด้วยคำถาม — ผันผวนกว่า จึงอยู่หลัง breakpoint
    thinking    adaptive — งานนี้ต้องเชื่อม dependency หลายชั้น ไม่ใช่ classification
    output_config.format  บังคับให้ตอบตรง schema เดียวกับที่ provider อื่นใช้
"""
from __future__ import annotations

import json
import os
from typing import Any

from .base import LLMError

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000


class AnthropicProvider:
    name = "claude"

    def __init__(self, model: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("ต้องติดตั้ง anthropic — pip install anthropic") from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("ECOSYSTEM_ANTHROPIC_MODEL", DEFAULT_MODEL)

    def complete_json(self, *, stable_system: str, volatile_context: str,
                      question: str, schema: dict[str, Any],
                      effort: str = "high") -> dict[str, Any]:
        a = self._anthropic
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=[{
                    "type": "text",
                    "text": stable_system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": (
                        f"<team_context>\n{volatile_context}\n</team_context>\n\n"
                        f"<question>\n{question}\n</question>"
                    ),
                }],
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except a.NotFoundError as e:
            raise LLMError(f"ไม่รู้จัก model {self.model!r} — ตั้ง ECOSYSTEM_ANTHROPIC_MODEL ใหม่") from e
        except a.AuthenticationError as e:
            raise LLMError("ANTHROPIC_API_KEY ไม่ถูกต้องหรือยังไม่ได้ตั้ง") from e
        except a.RateLimitError as e:
            raise LLMError("โดน rate limit ของ Anthropic — ลองใหม่ภายหลัง") from e
        except a.APIStatusError as e:
            raise LLMError(f"Anthropic ตอบ {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("ต่อ Anthropic ไม่ได้ — ตรวจเน็ต") from e

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "category", None)
            raise LLMError(f"Claude ปฏิเสธคำขอ (category={detail})")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise LLMError("ไม่มี text block ในคำตอบ")
        return json.loads(text)
