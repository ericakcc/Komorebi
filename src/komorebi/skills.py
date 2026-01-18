"""Skill management system for Komorebi.

學習重點：
- Skill 是一種按需載入的指引，讓 LLM 在需要時才載入完整內容
- SkillManager 掃描 .claude/skills/ 目錄，只讀取 frontmatter 作為摘要
- load_skill 工具讓 LLM 可以載入完整的 SKILL.md 內容

設計理念（參考 Claude Code）：
- System Prompt 中只列出 skill 清單（name + description）
- LLM 根據對話內容自主判斷是否需要載入某個 skill
- 透過 load_skill 工具載入完整內容作為上下文
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from claude_agent_sdk import tool


@dataclass
class SkillInfo:
    """Skill 摘要資訊（用於 system prompt）。

    只包含 frontmatter 中的 name 和 description，
    完整內容在需要時才透過 load_skill 載入。
    """

    name: str
    description: str
    path: Path


class SkillManager:
    """管理 Skill 的發現與載入。

    Skill 檔案結構：
    ```
    .claude/skills/
    ├── project-manager/
    │   └── SKILL.md          # frontmatter + 完整指引
    ├── daily-planner/
    │   └── SKILL.md
    ```

    SKILL.md 格式：
    ```yaml
    ---
    name: project-manager
    description: |
      專案管理與任務追蹤技能。...
    ---

    # Project Manager Skill
    [完整指引內容]
    ```
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        """Initialize SkillManager.

        Args:
            skills_dir: Path to skills directory. Defaults to .claude/skills.
        """
        self._skills_dir = skills_dir or Path(".claude/skills")
        self._skills: dict[str, SkillInfo] = {}

    def discover(self) -> list[SkillInfo]:
        """掃描 skills 目錄，只讀取 frontmatter（name + description）。

        只在啟動時執行一次，避免每次對話都重新掃描。

        Returns:
            List of discovered SkillInfo objects.
        """
        if not self._skills_dir.exists():
            return []

        for skill_dir in self._skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    try:
                        post = frontmatter.load(skill_file)
                        name = post.get("name", skill_dir.name)
                        self._skills[name] = SkillInfo(
                            name=name,
                            description=post.get("description", ""),
                            path=skill_file,
                        )
                    except Exception:
                        # 忽略無法解析的 SKILL.md
                        pass

        return list(self._skills.values())

    def get_skill_list_prompt(self) -> str:
        """生成 skill 清單 prompt，嵌入 system prompt。

        Returns:
            Markdown 格式的 skill 清單，如果沒有 skill 則回傳空字串。
        """
        if not self._skills:
            return ""

        lines = [
            "## 可用技能",
            "",
            "| 技能 | 說明 |",
            "|------|------|",
        ]

        for skill in self._skills.values():
            # 取 description 第一行作為摘要，限制 100 字元
            desc_lines = skill.description.strip().split("\n")
            desc = desc_lines[0].strip()[:100] if desc_lines else ""
            lines.append(f"| `{skill.name}` | {desc} |")

        lines.append("")
        lines.append("當對話涉及上述主題時，請呼叫 `load_skill` 工具載入詳細指引。")
        return "\n".join(lines)

    def load_skill_content(self, name: str) -> str | None:
        """載入完整 SKILL.md 內容。

        Args:
            name: Skill 名稱。

        Returns:
            完整的 SKILL.md 內容，如果找不到則回傳 None。
        """
        skill = self._skills.get(name)
        if not skill:
            return None
        return skill.path.read_text(encoding="utf-8")

    def list_available_skills(self) -> list[str]:
        """取得可用的 skill 名稱清單。

        Returns:
            Skill 名稱列表。
        """
        return list(self._skills.keys())


# ============================================================================
# Global SkillManager Instance
# ============================================================================

_skill_manager: SkillManager | None = None


def set_skill_manager(manager: SkillManager) -> None:
    """設定全域 SkillManager 實例。

    Args:
        manager: SkillManager 實例。
    """
    global _skill_manager
    _skill_manager = manager


def get_skill_manager() -> SkillManager | None:
    """取得全域 SkillManager 實例。

    Returns:
        SkillManager 實例，如果未設定則回傳 None。
    """
    return _skill_manager


# ============================================================================
# MCP Tool: load_skill
# ============================================================================


@tool(
    name="load_skill",
    description="載入技能指引。當需要執行特定任務（如專案管理、任務追蹤）時，先載入對應 skill 獲取詳細指引。",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "要載入的技能名稱",
            },
        },
        "required": ["name"],
    },
)
async def load_skill(args: dict[str, Any]) -> dict[str, Any]:
    """載入指定 skill 的完整內容。

    Args:
        args: 包含 "name" 欄位的字典。

    Returns:
        包含 skill 內容的回應字典。
    """
    name = args.get("name", "")

    if not _skill_manager:
        return {
            "content": [{"type": "text", "text": "Skill 系統未初始化"}],
            "is_error": True,
        }

    content = _skill_manager.load_skill_content(name)
    if not content:
        available = _skill_manager.list_available_skills()
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"找不到 skill: {name}\n可用: {', '.join(available)}",
                }
            ],
            "is_error": True,
        }

    return {"content": [{"type": "text", "text": content}]}


# 匯出的工具列表
all_tools = [load_skill]
