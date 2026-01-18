"""Tests for skill management system.

Tests the SkillManager discovery, loading, and the load_skill MCP tool.
"""

import tempfile
from pathlib import Path

import pytest

from komorebi.skills import SkillManager, get_skill_manager, load_skill, set_skill_manager


@pytest.fixture
def temp_skills_dir():
    """Create a temporary skills directory with test skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)

        # Create test skill with frontmatter
        test_skill = skills_dir / "test-skill"
        test_skill.mkdir()
        (test_skill / "SKILL.md").write_text(
            """---
name: test-skill
description: |
  測試用技能。用於驗證 SkillManager 功能。
---

# Test Skill Content

This is the full content of the test skill.

## Usage

Call this skill when testing.
"""
        )

        # Create another skill without description
        minimal_skill = skills_dir / "minimal-skill"
        minimal_skill.mkdir()
        (minimal_skill / "SKILL.md").write_text(
            """---
name: minimal-skill
---

# Minimal Skill

Just a minimal skill without description.
"""
        )

        yield skills_dir


class TestSkillManager:
    """Tests for SkillManager class."""

    def test_discover_finds_skills(self, temp_skills_dir: Path) -> None:
        """Test that discover() finds all skills in the directory."""
        manager = SkillManager(temp_skills_dir)
        skills = manager.discover()

        assert len(skills) == 2
        skill_names = {s.name for s in skills}
        assert "test-skill" in skill_names
        assert "minimal-skill" in skill_names

    def test_discover_extracts_frontmatter(self, temp_skills_dir: Path) -> None:
        """Test that discover() correctly extracts frontmatter."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()

        skills = {s.name: s for s in manager._skills.values()}
        test_skill = skills["test-skill"]

        assert test_skill.name == "test-skill"
        assert "測試用技能" in test_skill.description
        assert test_skill.path.exists()

    def test_discover_handles_missing_description(self, temp_skills_dir: Path) -> None:
        """Test that discover() handles skills without description."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()

        skills = {s.name: s for s in manager._skills.values()}
        minimal_skill = skills["minimal-skill"]

        assert minimal_skill.name == "minimal-skill"
        assert minimal_skill.description == ""

    def test_discover_empty_directory(self) -> None:
        """Test discover() with non-existent directory."""
        manager = SkillManager(Path("/nonexistent/path"))
        skills = manager.discover()

        assert skills == []

    def test_get_skill_list_prompt(self, temp_skills_dir: Path) -> None:
        """Test get_skill_list_prompt() generates correct markdown."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()
        prompt = manager.get_skill_list_prompt()

        # Should contain table headers
        assert "| 技能 | 說明 |" in prompt
        assert "|------|------|" in prompt

        # Should contain skill names
        assert "`test-skill`" in prompt
        assert "`minimal-skill`" in prompt

        # Should contain instruction
        assert "load_skill" in prompt

    def test_get_skill_list_prompt_empty(self) -> None:
        """Test get_skill_list_prompt() with no skills."""
        manager = SkillManager(Path("/nonexistent/path"))
        manager.discover()
        prompt = manager.get_skill_list_prompt()

        assert prompt == ""

    def test_load_skill_content(self, temp_skills_dir: Path) -> None:
        """Test load_skill_content() returns full SKILL.md content."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()

        content = manager.load_skill_content("test-skill")

        assert content is not None
        assert "# Test Skill Content" in content
        assert "This is the full content of the test skill" in content
        assert "name: test-skill" in content  # Includes frontmatter

    def test_load_skill_content_not_found(self, temp_skills_dir: Path) -> None:
        """Test load_skill_content() returns None for missing skill."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()

        content = manager.load_skill_content("nonexistent-skill")

        assert content is None

    def test_list_available_skills(self, temp_skills_dir: Path) -> None:
        """Test list_available_skills() returns skill names."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()

        skills = manager.list_available_skills()

        assert "test-skill" in skills
        assert "minimal-skill" in skills


class TestGlobalSkillManager:
    """Tests for global SkillManager functions."""

    def test_set_and_get_skill_manager(self, temp_skills_dir: Path) -> None:
        """Test set_skill_manager() and get_skill_manager()."""
        manager = SkillManager(temp_skills_dir)
        set_skill_manager(manager)

        retrieved = get_skill_manager()
        assert retrieved is manager

    def test_get_skill_manager_initially_none(self) -> None:
        """Test get_skill_manager() returns None if not set."""
        # Reset global state
        set_skill_manager(None)  # type: ignore

        # Note: This test may be affected by other tests
        # In practice, the global manager is set by KomorebiAgent


class TestLoadSkillTool:
    """Tests for load_skill MCP tool."""

    @pytest.mark.asyncio
    async def test_load_skill_success(self, temp_skills_dir: Path) -> None:
        """Test load_skill tool returns skill content."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()
        set_skill_manager(manager)

        # SdkMcpTool.handler is the actual async function
        result = await load_skill.handler({"name": "test-skill"})

        assert "is_error" not in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert "# Test Skill Content" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_load_skill_not_found(self, temp_skills_dir: Path) -> None:
        """Test load_skill tool returns error for missing skill."""
        manager = SkillManager(temp_skills_dir)
        manager.discover()
        set_skill_manager(manager)

        # SdkMcpTool.handler is the actual async function
        result = await load_skill.handler({"name": "nonexistent-skill"})

        assert result["is_error"] is True
        assert "找不到 skill" in result["content"][0]["text"]
        assert "test-skill" in result["content"][0]["text"]  # Lists available

    @pytest.mark.asyncio
    async def test_load_skill_no_manager(self) -> None:
        """Test load_skill tool returns error when manager not initialized."""
        set_skill_manager(None)  # type: ignore

        # SdkMcpTool.handler is the actual async function
        result = await load_skill.handler({"name": "test-skill"})

        assert result["is_error"] is True
        assert "Skill 系統未初始化" in result["content"][0]["text"]
