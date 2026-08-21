"""ห่อ gh CLI — ใช้ auth เดิมของเครื่อง ไม่ต้องจัดการ token เอง

ทำไมไม่ใช้ REST library: registry ของ M1 ใช้ gh อยู่แล้ว และ gh จัดการ auth,
pagination, retry ให้ครบ การเพิ่ม dependency ใหม่เพื่อทำสิ่งเดียวกันไม่คุ้ม
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any


class GitHubError(RuntimeError):
    """เรียก gh ไม่สำเร็จ — แยกจาก error ของ logic ฝั่งเรา

    `status` สำคัญกว่าที่คิด: 404 แปลว่า "ไม่มีอยู่จริง" ซึ่งเป็นคำตอบ
    ส่วนต่อไม่ติดแปลว่า "ตอบไม่ได้" ซึ่งไม่ใช่คำตอบ — ปนกันเมื่อไหร่
    รายงานจะบอกว่า repo ที่ตั้งใจไม่ให้มี "ตรวจไม่ได้"
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def not_found(self) -> bool:
        return self.status == 404


class GitHubClient:
    def __init__(self, owner: str = "monthop-gmail") -> None:
        self.owner = owner
        # นับเอง — rate_limit ของ GitHub ไม่ขยับทันทีและบางบัญชีใช้คนละ bucket
        # ตัวเลขที่รายงานต้องเป็นของจริง ไม่ใช่ผลลบของค่าที่อาจไม่อัปเดต
        self.calls = 0

    def _run(self, args: list[str], *, timeout: int = 120) -> str:
        try:
            proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as e:
            raise GitHubError("ไม่มี gh CLI ในเครื่อง") from e
        except subprocess.TimeoutExpired as e:
            raise GitHubError(f"gh {' '.join(args[:3])} หมดเวลา") from e
        if proc.returncode != 0:
            text = (proc.stderr or proc.stdout).strip()
            last = text.splitlines()[-1][:300] if text else "gh ล้มเหลวโดยไม่มีข้อความ"
            match = re.search(r"HTTP (\d{3})", text)
            raise GitHubError(last, status=int(match.group(1)) if match else None)
        return proc.stdout

    def api(self, path: str, *, paginate: bool = False, timeout: int = 120) -> Any:
        self.calls += 1
        args = ["api", path]
        if paginate:
            args += ["--paginate", "--slurp"]
        out = self._run(args, timeout=timeout)
        if not out.strip():
            return None
        data = json.loads(out)
        # --slurp ห่อผลแต่ละหน้าเป็น list ซ้อน — แบนให้เหลือชั้นเดียว
        if paginate and isinstance(data, list) and data and isinstance(data[0], list):
            return [item for page in data for item in page]
        return data

    def rate_limit(self) -> dict[str, Any]:
        data = self.api("rate_limit")
        core = data["resources"]["core"]
        return {"limit": core["limit"], "remaining": core["remaining"], "reset": core["reset"]}

    def available(self) -> bool:
        try:
            self._run(["auth", "status"], timeout=30)
            return True
        except GitHubError:
            return False

    # ── endpoints ที่ sync ใช้ ──────────────────────────────────────────
    def repo(self, name: str) -> dict[str, Any]:
        return self.api(f"repos/{self.owner}/{name}")

    def latest_commit(self, name: str, branch: str) -> dict[str, Any] | None:
        try:
            data = self.api(f"repos/{self.owner}/{name}/commits/{branch}")
        except GitHubError:
            return None
        return data

    def issues(self, name: str, since: str | None = None) -> list[dict[str, Any]]:
        path = f"repos/{self.owner}/{name}/issues?state=all&per_page=100"
        if since:
            path += f"&since={since}"
        return self.api(path, paginate=True) or []

    def pulls(self, name: str) -> list[dict[str, Any]]:
        path = (f"repos/{self.owner}/{name}/pulls"
                f"?state=all&per_page=100&sort=updated&direction=desc")
        return self.api(path, paginate=True) or []

    def pull_files(self, name: str, number: int) -> list[dict[str, Any]]:
        return self.api(f"repos/{self.owner}/{name}/pulls/{number}/files?per_page=100",
                        paginate=True) or []
