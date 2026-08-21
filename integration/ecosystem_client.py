# ไฟล์นี้สร้างจาก ecosystem-intelligence — อย่าแก้ที่ปลายทาง
# ต้นทาง: src/ecosystem_graph/integration/client.py
# วิธีอัปเดต: ก๊อปทับจาก https://github.com/monthop-gmail/ecosystem-intelligence/blob/main/integration/ecosystem_client.py

"""Client สำหรับ repo อื่นที่จะอ่าน Ecosystem Graph (#24)

**ไฟล์เดียว ใช้แต่ stdlib** — ตั้งใจให้ก๊อปไปวางใน repo ไหนก็ได้โดยไม่ต้องเพิ่ม
dependency ใหม่ ถ้าต้องลง package เพิ่มเพื่ออ่าน metadata ของ ecosystem
ก็จะไม่มีใครยอมต่อ

    from ecosystem_client import EcosystemClient
    eco = EcosystemClient("https://ecosystem.internal")
    ctx = eco.team("platform-team")
    for c in ctx["components"]:
        print(c["id"], c["conformance_status"])

ทุก method อ่านอย่างเดียว — API ไม่มี endpoint ที่เขียนข้อมูลอยู่แล้ว
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

__all__ = ["EcosystemClient", "EcosystemError"]

DEFAULT_TIMEOUT = 10


class EcosystemError(RuntimeError):
    """เรียก Ecosystem Graph ไม่สำเร็จ"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class EcosystemClient:
    def __init__(self, base_url: str = "http://localhost:8000", *,
                 timeout: int = DEFAULT_TIMEOUT, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = token

    def _get(self, path: str, **params: Any) -> Any:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise EcosystemError(f"{path} ตอบ {e.code}", status=e.code) from e
        except urllib.error.URLError as e:
            raise EcosystemError(f"ต่อ {self.base_url} ไม่ได้: {e.reason}") from e

    # ── สถานะระบบ ──────────────────────────────────────────────────────
    def health(self) -> dict:
        return self._get("/health")

    # ── ทีม ────────────────────────────────────────────────────────────
    def teams(self) -> list[dict]:
        return self._get("/teams")

    def team(self, team_id: str) -> dict:
        """ทีมนี้ดูแลอะไร — รวม component ที่เป็นเจ้าของ"""
        return {**self._get(f"/teams/{team_id}"),
                "components": self._get(f"/teams/{team_id}/components")}

    # ── component ──────────────────────────────────────────────────────
    def components(self, *, team: str | None = None, plane: str | None = None,
                   status: str | None = None) -> list[dict]:
        return self._get("/components", team=team, plane=plane, status=status)

    def component(self, component_id: str) -> dict:
        return self._get(f"/components/{component_id}")

    def dependencies(self, component_id: str, depth: int | None = None) -> dict:
        """component นี้ขึ้นกับใคร"""
        return self._get(f"/components/{component_id}/dependencies", depth=depth)

    def dependents(self, component_id: str, depth: int | None = None) -> dict:
        """ใครขึ้นกับ component นี้ — ใช้ก่อนเปลี่ยนอะไรที่คนอื่นใช้อยู่"""
        return self._get(f"/components/{component_id}/dependents", depth=depth)

    # ── contract ───────────────────────────────────────────────────────
    def contracts(self) -> list[dict]:
        return self._get("/contracts")

    def contract(self, contract_id: str) -> dict:
        return self._get(f"/contracts/{contract_id}")

    def impact(self, contract_id: str, level: str = "unsure") -> dict:
        """เปลี่ยน contract นี้แล้วกระทบใคร พร้อมลำดับการประสานและร่าง issue"""
        return self._get(f"/contracts/{contract_id}/cross-team", level=level)

    # ── งานจริง ────────────────────────────────────────────────────────
    def current_work(self, *, team: str | None = None, state: str | None = None) -> dict:
        return self._get("/work/current", team=team, state=state)

    def duplicate_work(self) -> dict:
        """งานที่คนละทีมกำลังทำเรื่องเดียวกันอยู่"""
        return self._get("/work/duplicates")

    # ── advisor ────────────────────────────────────────────────────────
    def ask(self, team: str, question: str, *, provider: str | None = None) -> dict:
        """ถามจากมุมของทีม — POST เพราะคำถามอยู่ใน body ไม่ได้เขียนข้อมูล"""
        payload = json.dumps({k: v for k, v in
                              {"team": team, "question": question,
                               "provider": provider}.items() if v is not None}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/ask", data=payload, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise EcosystemError(f"/ask ตอบ {e.code}", status=e.code) from e
        except urllib.error.URLError as e:
            raise EcosystemError(f"ต่อ {self.base_url} ไม่ได้: {e.reason}") from e

    # ── guardian ───────────────────────────────────────────────────────
    def guardian_report(self, *, remote: bool = False) -> dict:
        return self._get("/guardian/report", remote=str(remote).lower())
