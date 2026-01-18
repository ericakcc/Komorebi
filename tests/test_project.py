"""Tests for project management tools.

Tests the dual-mode (file and folder) project structure support.
"""

import tempfile
from pathlib import Path

import pytest

from komorebi.tools import project


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory with test projects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        projects_dir = data_dir / "projects"
        projects_dir.mkdir()

        # Create a folder mode project
        folder_project = projects_dir / "testproject"
        folder_project.mkdir()
        (folder_project / "project.md").write_text(
            """---
name: TestProject
type: software
status: active
priority: 1
repo: ~/TestProject
---

# TestProject

## Goals
Test project for unit tests.
"""
        )
        (folder_project / "tasks.md").write_text(
            """## In Progress
- [ ] Task in progress @today
- [ ] Another task #feature

## Pending
- [ ] Pending task

## Completed
- [x] Completed task (2026-01-14)
"""
        )

        # Create a file mode project (legacy)
        (projects_dir / "legacyproject.md").write_text(
            """---
name: LegacyProject
status: paused
priority: 2
---

# LegacyProject

Just a legacy file mode project.
"""
        )

        # Set the data directory
        project.set_data_dir(data_dir)

        yield data_dir


class TestPathHelpers:
    """Tests for dual-mode path helper functions."""

    def test_is_folder_mode_true(self, temp_data_dir: Path) -> None:
        """Test detection of folder mode project."""
        assert project._is_folder_mode("testproject") is True
        assert project._is_folder_mode("TestProject") is True  # Case insensitive

    def test_is_folder_mode_false(self, temp_data_dir: Path) -> None:
        """Test detection of file mode project."""
        assert project._is_folder_mode("legacyproject") is False
        assert project._is_folder_mode("nonexistent") is False

    def test_get_project_path_folder_mode(self, temp_data_dir: Path) -> None:
        """Test getting project path for folder mode."""
        path = project._get_project_path("testproject")
        assert path is not None
        assert path.name == "project.md"
        assert path.parent.name == "testproject"

    def test_get_project_path_file_mode(self, temp_data_dir: Path) -> None:
        """Test getting project path for file mode."""
        path = project._get_project_path("legacyproject")
        assert path is not None
        assert path.name == "legacyproject.md"

    def test_get_project_path_not_found(self, temp_data_dir: Path) -> None:
        """Test getting project path for non-existent project."""
        path = project._get_project_path("nonexistent")
        assert path is None

    def test_get_tasks_path_exists(self, temp_data_dir: Path) -> None:
        """Test getting tasks path for folder mode project."""
        path = project._get_tasks_path("testproject")
        assert path is not None
        assert path.name == "tasks.md"

    def test_get_tasks_path_not_folder_mode(self, temp_data_dir: Path) -> None:
        """Test getting tasks path for file mode project."""
        path = project._get_tasks_path("legacyproject")
        assert path is None

    def test_iter_all_projects(self, temp_data_dir: Path) -> None:
        """Test iterating over all projects."""
        projects = project._iter_all_projects()
        names = [p[0] for p in projects]
        assert "testproject" in names
        assert "legacyproject" in names
        assert len(projects) == 2


class TestTaskParsing:
    """Tests for task parsing utilities."""

    def test_parse_tasks_basic(self, temp_data_dir: Path) -> None:
        """Test parsing tasks from content."""
        content = """## In Progress
- [ ] Task A @today
- [ ] Task B #feature

## Pending
- [ ] Task C

## Completed
- [x] Task D (2026-01-14)
"""
        result = project._parse_tasks(content)

        assert len(result["in_progress"]) == 2
        assert len(result["pending"]) == 1
        assert len(result["completed"]) == 1

        # Check @today detection
        assert result["in_progress"][0]["is_today"] is True
        assert result["in_progress"][1]["is_today"] is False

        # Check tag extraction
        assert "feature" in result["in_progress"][1]["tags"]

    def test_parse_tasks_empty(self) -> None:
        """Test parsing empty content."""
        result = project._parse_tasks("")
        assert result["in_progress"] == []
        assert result["pending"] == []
        assert result["completed"] == []

    def test_count_tasks(self, temp_data_dir: Path) -> None:
        """Test counting tasks for a project."""
        project_path = project._get_project_path("testproject")
        counts = project._count_tasks(project_path)

        assert counts["in_progress"] == 2
        assert counts["pending"] == 1
        assert counts["completed"] == 1
        assert counts["total"] == 4

    def test_calculate_progress(self, temp_data_dir: Path) -> None:
        """Test progress calculation."""
        project_path = project._get_project_path("testproject")
        progress = project._calculate_progress(project_path)
        # 1 completed out of 4 total = 25%
        assert progress == 25


class TestListProjects:
    """Tests for list_projects tool."""

    @pytest.mark.asyncio
    async def test_list_projects_both_modes(self, temp_data_dir: Path) -> None:
        """Test listing projects in both modes."""
        result = await project.list_projects.handler({})

        assert "is_error" not in result or result["is_error"] is False
        text = result["content"][0]["text"]

        # Should list both projects
        assert "TestProject" in text
        assert "LegacyProject" in text

        # Should show mode indicators
        assert "📁" in text  # Folder mode
        assert "📄" in text  # File mode

    @pytest.mark.asyncio
    async def test_list_projects_shows_stats(self, temp_data_dir: Path) -> None:
        """Test that list_projects shows task statistics."""
        result = await project.list_projects.handler({})
        text = result["content"][0]["text"]

        # Should show task count for folder mode project
        assert "tasks" in text or "%" in text


class TestShowProject:
    """Tests for show_project tool."""

    @pytest.mark.asyncio
    async def test_show_project_folder_mode(self, temp_data_dir: Path) -> None:
        """Test showing folder mode project."""
        result = await project.show_project.handler({"name": "testproject"})

        assert "is_error" not in result or result["is_error"] is False
        text = result["content"][0]["text"]

        # Should include project.md content
        assert "TestProject" in text
        assert "Goals" in text

        # Should include tasks.md content
        assert "tasks.md" in text
        assert "Task in progress" in text

    @pytest.mark.asyncio
    async def test_show_project_file_mode(self, temp_data_dir: Path) -> None:
        """Test showing file mode project."""
        result = await project.show_project.handler({"name": "legacyproject"})

        assert "is_error" not in result or result["is_error"] is False
        text = result["content"][0]["text"]

        assert "LegacyProject" in text
        # Should not include tasks.md reference
        assert "tasks.md" not in text

    @pytest.mark.asyncio
    async def test_show_project_not_found(self, temp_data_dir: Path) -> None:
        """Test showing non-existent project."""
        result = await project.show_project.handler({"name": "nonexistent"})

        assert result["is_error"] is True
        assert "找不到" in result["content"][0]["text"]


class TestGetTodayTasks:
    """Tests for get_today_tasks tool."""

    @pytest.mark.asyncio
    async def test_get_today_tasks_finds_today(self, temp_data_dir: Path) -> None:
        """Test finding @today marked tasks."""
        result = await project.get_today_tasks.handler({})

        assert "is_error" not in result or result["is_error"] is False
        text = result["content"][0]["text"]

        # Should find the @today task
        assert "Task in progress" in text
        assert "testproject" in text

    @pytest.mark.asyncio
    async def test_get_today_tasks_empty(self, temp_data_dir: Path) -> None:
        """Test when no @today tasks exist."""
        # Remove @today from tasks
        tasks_path = temp_data_dir / "projects" / "testproject" / "tasks.md"
        content = tasks_path.read_text().replace("@today", "")
        tasks_path.write_text(content)

        result = await project.get_today_tasks.handler({})
        text = result["content"][0]["text"]

        # Should indicate no @today tasks
        assert "沒有標記" in text or "沒有任何" in text
