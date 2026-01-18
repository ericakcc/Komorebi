"""Session management for cross-session conversation persistence.

提供 Session 持久化功能：
- 保存當前會話 ID
- 恢復上次會話
- 清除會話（開始新對話）

Session 資料儲存在 data/session.json。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class SessionManager:
    """管理 Komorebi 的對話會話。

    會話資料包含：
    - session_id: Claude SDK 的會話 ID
    - updated: 最後更新時間
    - summary: 對話摘要（可選）

    Example:
        >>> manager = SessionManager(Path("data"))
        >>> manager.save("abc123", "討論了專案進度")
        >>> session_id = manager.load()
        >>> manager.clear()  # 開始新對話
    """

    def __init__(self, data_dir: Path) -> None:
        """Initialize session manager.

        Args:
            data_dir: Path to data directory (e.g., ./data)
        """
        self.session_file = data_dir / "session.json"

    def save(self, session_id: str, summary: str = "") -> None:
        """保存當前會話。

        Args:
            session_id: Claude SDK 的會話 ID
            summary: 對話摘要（可選）
        """
        data: dict[str, Any] = {
            "session_id": session_id,
            "updated": datetime.now().isoformat(),
            "summary": summary,
        }
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.session_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> str | None:
        """載入上次的會話 ID。

        Returns:
            上次的 session_id，若無則返回 None
        """
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text())
                return data.get("session_id")
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def get_info(self) -> dict[str, Any] | None:
        """取得完整的會話資訊。

        Returns:
            包含 session_id, updated, summary 的 dict，若無則返回 None
        """
        if self.session_file.exists():
            try:
                return json.loads(self.session_file.read_text())
            except json.JSONDecodeError:
                return None
        return None

    def clear(self) -> None:
        """清除會話（開始新對話）。"""
        if self.session_file.exists():
            self.session_file.unlink()
