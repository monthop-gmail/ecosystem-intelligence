"""เลือก provider จาก config — logic ที่อยู่เหนือขึ้นไปไม่รู้ว่าใครตอบ

    ECOSYSTEM_LLM_PROVIDER = claude | chatgpt | offline   (ค่า default: offline)
    ECOSYSTEM_ANTHROPIC_MODEL                             (default: claude-opus-5)
    ECOSYSTEM_OPENAI_MODEL                                (ไม่มี default — ต้องตั้งเอง)

default เป็น offline โดยตั้งใจ — ระบบต้องรันและเทสต์ได้โดยไม่ต้องมี key
และไม่มีทางเผลอยิง API จริงเพราะลืมตั้งค่า
"""
from __future__ import annotations

import os

from ..config import _load_dotenv
from .base import LLMError, LLMProvider
from .offline import OfflineProvider

__all__ = ["LLMError", "LLMProvider", "get_provider", "available_providers"]

available_providers = ("claude", "chatgpt", "offline")


def get_provider(name: str | None = None) -> LLMProvider:
    _load_dotenv()
    name = (name or os.environ.get("ECOSYSTEM_LLM_PROVIDER") or "offline").lower()
    if name == "offline":
        return OfflineProvider()
    if name == "claude":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "chatgpt":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    raise LLMError(f"ไม่รู้จัก provider {name!r} — เลือกได้: {', '.join(available_providers)}")
