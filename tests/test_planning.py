"""Tests for planning tools.

## 測試 @tool 函數的方式

claude-agent-sdk 的 @tool decorator 會將函數轉換為 SdkMcpTool 對象，
而不是返回原始函數。因此無法直接調用：

    # ❌ 這樣會報錯：TypeError: 'SdkMcpTool' object is not callable
    result = await planning.plan_today({"highlight": "Test"})

SdkMcpTool 的結構：

    @dataclass
    class SdkMcpTool:
        name: str
        description: str
        input_schema: dict
        handler: Callable  # 原始的 async 函數保存在這裡

正確的測試方式是通過 .handler 屬性調用底層函數：

    # ✅ 正確方式
    result = await planning.plan_today.handler({"highlight": "Test"})

這樣可以直接測試業務邏輯，不需要啟動 MCP server。
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from komorebi.tools import planning


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create temporary data directory structure."""
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # 建立測試專案
    (projects_dir / "test-project.md").write_text(
        """---
name: Test Project
status: active
priority: 1
repo: ~/test-repo
---
# Test Project
""",
        encoding="utf-8",
    )

    planning.set_data_dir(tmp_path)
    return tmp_path


class TestPlanToday:
    """Tests for plan_today tool."""

    @pytest.mark.asyncio
    async def test_plan_today_creates_file(self, temp_data_dir: Path) -> None:
        """plan_today should create daily note file."""
        result = await planning.plan_today.handler(
            {
                "highlight": "Test highlight",
                "tasks": ["Task 1", "Task 2"],
            }
        )

        assert result.get("is_error") is not True
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = temp_data_dir / "daily" / f"{today}.md"
        assert daily_file.exists()

        content = daily_file.read_text(encoding="utf-8")
        assert "Test highlight" in content
        assert "Task 1" in content
        assert "Task 2" in content

    @pytest.mark.asyncio
    async def test_plan_today_requires_highlight(self, temp_data_dir: Path) -> None:
        """plan_today should fail without highlight."""
        result = await planning.plan_today.handler({})

        assert result.get("is_error") is True
        assert "Highlight" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_plan_today_prevents_overwrite(self, temp_data_dir: Path) -> None:
        """plan_today should not overwrite existing file."""
        # 先建立一個
        await planning.plan_today.handler({"highlight": "First"})
        # 再試一次
        result = await planning.plan_today.handler({"highlight": "Second"})

        assert result.get("is_error") is True
        assert "已存在" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_plan_today_includes_active_projects(self, temp_data_dir: Path) -> None:
        """plan_today should include active projects in the plan."""
        result = await planning.plan_today.handler({"highlight": "Test"})

        assert result.get("is_error") is not True
        # 檢查回應中有 active 專案數量
        response_text = result["content"][0]["text"]
        assert "Active 專案" in response_text

    @pytest.mark.asyncio
    async def test_plan_today_handles_empty_tasks(self, temp_data_dir: Path) -> None:
        """plan_today should handle missing tasks parameter."""
        result = await planning.plan_today.handler({"highlight": "Test"})

        assert result.get("is_error") is not True
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = temp_data_dir / "daily" / f"{today}.md"
        content = daily_file.read_text(encoding="utf-8")
        assert "待填寫" in content


class TestGetToday:
    """Tests for get_today tool."""

    @pytest.mark.asyncio
    async def test_get_today_returns_content(self, temp_data_dir: Path) -> None:
        """get_today should return existing plan."""
        await planning.plan_today.handler({"highlight": "Test highlight"})
        result = await planning.get_today.handler({})

        content = result["content"][0]["text"]
        assert "Test highlight" in content
        assert result.get("is_error") is not True

    @pytest.mark.asyncio
    async def test_get_today_handles_no_file(self, temp_data_dir: Path) -> None:
        """get_today should handle missing file gracefully."""
        result = await planning.get_today.handler({})

        content = result["content"][0]["text"]
        assert "尚未建立" in content
        assert result.get("is_error") is not True


class TestEndOfDay:
    """Tests for end_of_day tool."""

    @pytest.mark.asyncio
    async def test_end_of_day_requires_plan(self, temp_data_dir: Path) -> None:
        """end_of_day should fail without existing plan."""
        result = await planning.end_of_day.handler({})

        assert result.get("is_error") is True
        assert "plan_today" in result["content"][0]["text"]

    @pytest.mark.asyncio
    @patch("komorebi.tools.planning._get_today_commits")
    async def test_end_of_day_scans_commits(
        self, mock_commits: MagicMock, temp_data_dir: Path
    ) -> None:
        """end_of_day should scan git commits."""
        mock_commits.return_value = ["feat: add feature (abc123)"]

        await planning.plan_today.handler({"highlight": "Test"})
        result = await planning.end_of_day.handler({"notes": "Good day"})

        assert result.get("is_error") is not True
        response_text = result["content"][0]["text"]
        assert "日終回顧完成" in response_text

    @pytest.mark.asyncio
    async def test_end_of_day_updates_file(self, temp_data_dir: Path) -> None:
        """end_of_day should update the daily note file."""
        await planning.plan_today.handler({"highlight": "Test"})
        await planning.end_of_day.handler({"notes": "Test note"})

        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = temp_data_dir / "daily" / f"{today}.md"
        content = daily_file.read_text(encoding="utf-8")

        assert "Test note" in content
        assert "Git Commits" in content


class TestGetTodayCommits:
    """Tests for _get_today_commits helper."""

    @patch("subprocess.run")
    def test_returns_commits(self, mock_run: MagicMock) -> None:
        """Should return commit list from git log."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="feat: add feature (abc123)\nfix: bug fix (def456)",
        )

        commits = planning._get_today_commits(Path("/fake/repo"))

        assert len(commits) == 2
        assert "abc123" in commits[0]
        assert "def456" in commits[1]

    @patch("subprocess.run")
    def test_handles_empty_repo(self, mock_run: MagicMock) -> None:
        """Should handle repo with no commits."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        commits = planning._get_today_commits(Path("/fake/repo"))

        assert commits == []

    @patch("subprocess.run")
    def test_handles_git_error(self, mock_run: MagicMock) -> None:
        """Should handle git command failure gracefully."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

        commits = planning._get_today_commits(Path("/fake/repo"))

        assert commits == []

    @patch("subprocess.run")
    def test_handles_timeout(self, mock_run: MagicMock) -> None:
        """Should handle subprocess timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=10)

        commits = planning._get_today_commits(Path("/fake/repo"))

        assert commits == []


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_weekday_name(self) -> None:
        """Should return correct Chinese weekday names."""
        # Monday = 0
        monday = datetime(2026, 1, 12)  # Monday
        assert planning._get_weekday_name(monday) == "一"

        # Sunday = 6
        sunday = datetime(2026, 1, 18)  # Sunday
        assert planning._get_weekday_name(sunday) == "日"

    def test_get_today_file_format(self, temp_data_dir: Path) -> None:
        """Should return correct file path format."""
        today_file = planning._get_today_file()
        today = datetime.now().strftime("%Y-%m-%d")

        assert today_file.name == f"{today}.md"
        assert today_file.parent.name == "daily"
