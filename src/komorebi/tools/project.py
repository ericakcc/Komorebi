"""Project management tools for Komorebi.

精簡版專案工具：
- 只支援資料夾模式（project/project.md + tasks.md）
- generate_review 整合 weekly/monthly/daily review

工具清單：
- list_projects: 列出所有專案
- show_project: 顯示專案詳情
- get_today_tasks: 取得今日任務
- sync_project: 同步專案資訊
- generate_review: 統一的回顧報告生成（day/week/month）
"""

import calendar as cal_module
import logging
import re
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import ClaudeAgentOptions, query, tool
from claude_agent_sdk.types import ResultMessage
from pydantic import BaseModel, Field

from ..utils.git import get_commits_in_range, get_today_commits, run_git_command
from ..utils.markdown import load_frontmatter, read_file_safely, save_frontmatter

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Input Models
# ============================================================================


class ProjectStatus(str, Enum):
    """Valid project statuses."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ShowProjectInput(BaseModel):
    """Input schema for show_project tool."""

    name: str = Field(..., min_length=1, description="專案名稱")


class SyncProjectInput(BaseModel):
    """Input schema for sync_project tool."""

    name: str = Field(..., min_length=1, description="專案名稱")
    force: bool = Field(default=False, description="是否強制覆寫")


class ReviewPeriod(str, Enum):
    """Valid review periods."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class GenerateReviewInput(BaseModel):
    """Input schema for generate_review tool."""

    period: ReviewPeriod = Field(default=ReviewPeriod.DAY, description="回顧週期")
    date: str | None = Field(
        default=None,
        description="指定日期/週/月，格式：day=YYYY-MM-DD, week=YYYY-Www, month=YYYY-MM",
    )
    notes: str | None = Field(default=None, description="補充筆記（day 模式使用）")


# 專案資料目錄
_data_dir: Path = Path("data")


def set_data_dir(path: Path) -> None:
    """Set the data directory for project tools."""
    global _data_dir
    _data_dir = path


def _get_projects_dir() -> Path:
    """Get the projects directory path."""
    return _data_dir / "projects"


def _get_reviews_dir() -> Path:
    """Get the reviews directory path."""
    return _data_dir / "reviews"


def _get_daily_dir() -> Path:
    """Get the daily notes directory path."""
    return _data_dir / "daily"


# ============================================================================
# Project Path Helpers (Folder Mode Only)
# ============================================================================


def _get_project_path(project_name: str) -> Path | None:
    """Get the project.md path for a project (folder mode only).

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        Path to project.md or None if not found.
    """
    projects_dir = _get_projects_dir()
    folder_path = projects_dir / project_name.lower() / "project.md"
    return folder_path if folder_path.exists() else None


def _get_tasks_path(project_name: str) -> Path | None:
    """Get the tasks.md path for a project.

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        Path to tasks.md or None if not exists.
    """
    projects_dir = _get_projects_dir()
    tasks_path = projects_dir / project_name.lower() / "tasks.md"
    return tasks_path if tasks_path.exists() else None


def _iter_all_projects() -> list[tuple[str, Path]]:
    """Iterate over all projects (folder mode only).

    Returns:
        List of (project_name, project_md_path) tuples.
    """
    projects_dir = _get_projects_dir()
    results: list[tuple[str, Path]] = []

    if not projects_dir.exists():
        return results

    for item in projects_dir.iterdir():
        if item.is_dir():
            project_md = item / "project.md"
            if project_md.exists():
                results.append((item.name, project_md))

    return results


# ============================================================================
# Task Parsing Utilities
# ============================================================================


def _parse_tasks(tasks_content: str) -> dict[str, list[dict[str, Any]]]:
    """Parse tasks.md content into structured data.

    Args:
        tasks_content: Content of tasks.md file.

    Returns:
        Dictionary with 'in_progress', 'pending', 'completed' lists.
    """
    result: dict[str, list[dict[str, Any]]] = {
        "in_progress": [],
        "pending": [],
        "completed": [],
    }

    current_section = "pending"
    section_map = {
        "進行中": "in_progress",
        "in progress": "in_progress",
        "待處理": "pending",
        "pending": "pending",
        "todo": "pending",
        "已完成": "completed",
        "completed": "completed",
        "done": "completed",
    }

    task_pattern = re.compile(
        r"^-\s*\[([ xX])\]\s*"  # checkbox
        r"(.+?)"  # task text
        r"(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$"  # optional date
    )

    for line in tasks_content.split("\n"):
        line = line.strip()

        if line.startswith("## "):
            section_name = line[3:].strip().lower()
            if section_name in section_map:
                current_section = section_map[section_name]
            continue

        match = task_pattern.match(line)
        if match:
            checked = match.group(1).lower() == "x"
            text = match.group(2).strip()
            completed_date = match.group(3)

            tags = re.findall(r"#(\S+)", text)
            text_clean = re.sub(r"\s*#\S+", "", text).strip()

            is_today = "@today" in text
            text_clean = text_clean.replace("@today", "").strip()

            task = {
                "text": text_clean,
                "completed": checked,
                "tags": tags,
                "is_today": is_today,
            }
            if completed_date:
                task["completed_date"] = completed_date

            if checked:
                result["completed"].append(task)
            else:
                result[current_section].append(task)

    return result


def _count_tasks(project_path: Path) -> dict[str, int]:
    """Count tasks for a project.

    Args:
        project_path: Path to project.md file.

    Returns:
        Dictionary with task counts.
    """
    counts = {"total": 0, "completed": 0, "in_progress": 0, "pending": 0}

    tasks_path = project_path.parent / "tasks.md"
    if tasks_path.exists():
        tasks = _parse_tasks(tasks_path.read_text(encoding="utf-8"))
        counts["in_progress"] = len(tasks["in_progress"])
        counts["pending"] = len(tasks["pending"])
        counts["completed"] = len(tasks["completed"])
        counts["total"] = counts["in_progress"] + counts["pending"] + counts["completed"]

    return counts


def _calculate_progress(project_path: Path) -> int:
    """Calculate progress percentage for a project.

    Args:
        project_path: Path to project.md file.

    Returns:
        Progress percentage (0-100).
    """
    counts = _count_tasks(project_path)
    if counts["total"] == 0:
        return 0
    return int((counts["completed"] / counts["total"]) * 100)


# ============================================================================
# Project Tools
# ============================================================================


@tool(
    name="list_projects",
    description="列出所有專案及其狀態、進度統計。回傳專案名稱、狀態、優先順序、任務完成率等摘要資訊。",
    input_schema={},
)
async def list_projects(args: dict[str, Any]) -> dict[str, Any]:
    """List all projects with statistics."""
    projects_dir = _get_projects_dir()

    if not projects_dir.exists():
        return {
            "content": [
                {"type": "text", "text": "專案資料夾不存在。請先建立 data/projects/ 目錄。"}
            ],
            "is_error": True,
        }

    projects: list[dict[str, Any]] = []

    for name, project_path in _iter_all_projects():
        try:
            post = load_frontmatter(project_path)
            task_counts = _count_tasks(project_path)

            projects.append(
                {
                    "name": post.get("name", name),
                    "type": post.get("type", "software"),
                    "status": post.get("status", "unknown"),
                    "priority": post.get("priority", 999),
                    "progress": post.get("progress", _calculate_progress(project_path)),
                    "tasks": task_counts,
                }
            )
        except (OSError, IOError) as e:
            logger.warning(f"Failed to read {project_path}: {e}")
            projects.append(
                {
                    "name": name,
                    "type": "unknown",
                    "status": "error: file read failed",
                    "priority": 999,
                    "progress": 0,
                    "tasks": {"total": 0, "completed": 0},
                }
            )

    if not projects:
        return {
            "content": [{"type": "text", "text": "目前沒有任何專案。"}],
        }

    projects.sort(key=lambda p: p["priority"])

    lines = ["## 專案列表\n"]
    for p in projects:
        status_emoji = {
            "active": "🟢",
            "paused": "⏸️",
            "completed": "✅",
            "archived": "📦",
        }.get(p["status"], "❓")

        stats_parts = []
        if p["tasks"]["total"] > 0:
            stats_parts.append(f"{p['tasks']['completed']}/{p['tasks']['total']} tasks")
        if p["progress"] > 0:
            stats_parts.append(f"{p['progress']}%")
        stats = f" | {', '.join(stats_parts)}" if stats_parts else ""

        lines.append(f"- {status_emoji} **{p['name']}** ({p['status']}){stats}")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
    }


@tool(
    name="show_project",
    description="顯示單一專案的完整資訊，包含目標、技術棧、進度、任務清單等詳細內容。",
    input_schema=ShowProjectInput.model_json_schema(),
)
async def show_project(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a specific project."""
    try:
        validated = ShowProjectInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    name = validated.name
    project_path = _get_project_path(name)

    if not project_path:
        available = [p[0] for p in _iter_all_projects()]
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"找不到專案：{name}\n可用的專案：{', '.join(available) if available else '(無)'}",
                }
            ],
            "is_error": True,
        }

    content = project_path.read_text(encoding="utf-8")

    tasks_path = project_path.parent / "tasks.md"
    if tasks_path.exists():
        tasks_content = tasks_path.read_text(encoding="utf-8")
        content += f"\n\n---\n\n# 任務清單 (tasks.md)\n\n{tasks_content}"

    folder_path = project_path.parent
    files = list(folder_path.iterdir())
    content += f"\n\n---\n\n**專案資料夾**: `{folder_path}`\n"
    content += f"**檔案**: {', '.join(f.name for f in files)}"

    return {
        "content": [{"type": "text", "text": content}],
    }


@tool(
    name="get_today_tasks",
    description="取得今日任務清單（跨所有專案）。掃描所有專案的 tasks.md，找出標記 @today 的任務和進行中的任務。",
    input_schema={},
)
async def get_today_tasks(args: dict[str, Any]) -> dict[str, Any]:
    """Get today's tasks across all projects."""
    today_tasks: list[dict[str, Any]] = []
    in_progress_tasks: list[dict[str, Any]] = []

    for name, project_path in _iter_all_projects():
        tasks_path = project_path.parent / "tasks.md"
        if not tasks_path.exists():
            continue

        try:
            tasks_content = tasks_path.read_text(encoding="utf-8")
            parsed = _parse_tasks(tasks_content)

            for task in parsed["pending"] + parsed["in_progress"]:
                if task.get("is_today"):
                    today_tasks.append(
                        {
                            "project": name,
                            "text": task["text"],
                            "tags": task.get("tags", []),
                            "section": "in_progress"
                            if task in parsed["in_progress"]
                            else "pending",
                        }
                    )

            for task in parsed["in_progress"]:
                if not task.get("is_today"):
                    in_progress_tasks.append(
                        {
                            "project": name,
                            "text": task["text"],
                            "tags": task.get("tags", []),
                        }
                    )

        except (OSError, IOError) as e:
            logger.warning(f"Failed to read tasks for {name}: {e}")

    lines = ["## 今日任務\n"]

    if today_tasks:
        lines.append("### @today 標記\n")
        for t in today_tasks:
            tags = " ".join(f"#{tag}" for tag in t["tags"]) if t["tags"] else ""
            lines.append(f"- [ ] **{t['project']}**: {t['text']} {tags}")
    else:
        lines.append("_沒有標記 @today 的任務_\n")

    if in_progress_tasks:
        lines.append("\n### 進行中\n")
        for t in in_progress_tasks:
            tags = " ".join(f"#{tag}" for tag in t["tags"]) if t["tags"] else ""
            lines.append(f"- [ ] **{t['project']}**: {t['text']} {tags}")

    if not today_tasks and not in_progress_tasks:
        lines.append("\n_目前沒有任何進行中或今日待辦的任務。_")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
    }


# ============================================================================
# Project Sync Tool
# ============================================================================


INIT_PROMPT = """你是專案分析助理。根據以下 repository 資訊，為這個成熟專案生成完整的專案文件。

## Repository 資訊

### README
{readme}

### 開發指南 (CLAUDE.md)
{claude_md}

### 其他文檔
{other_docs}

### 依賴配置
{dependencies}

### 目錄結構
{structure}

### Git 開發歷史
{git_log}

## 輸出格式 (YAML)

請用 YAML 格式輸出以下欄位（繁體中文）。直接輸出 YAML 內容，不要有 ```yaml 標記：

goal: |
  專案的核心目標與價值主張（2-3 句）

tech_stack:
  - "Language: Python 3.12"
  - "Framework: FastAPI"
  # 列出所有關鍵技術

current_progress:
  - "[x] 已完成的功能"
  - "[ ] 進行中或待辦的功能"

blockers:
  - "(無)"
"""


async def _collect_repo_info(repo_path: Path, full_analysis: bool = False) -> dict[str, str]:
    """Collect comprehensive repository information."""
    info: dict[str, str] = {}

    info["readme"] = read_file_safely(repo_path / "README.md")
    info["claude_md"] = read_file_safely(repo_path / "CLAUDE.md")

    deps_file = repo_path / "pyproject.toml"
    if not deps_file.exists():
        deps_file = repo_path / "package.json"
    info["dependencies"] = read_file_safely(deps_file, max_chars=2000)

    info["structure"] = await run_git_command(
        repo_path,
        ["-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD"],
    )

    if full_analysis:
        info["git_log"] = await run_git_command(repo_path, ["log", "--oneline", "-50"])
        other_docs = []
        for doc_name in ["TECHNICAL.md", "API_SPEC.md", "ARCHITECTURE.md"]:
            doc_content = read_file_safely(repo_path / doc_name, max_chars=2000)
            if doc_content:
                other_docs.append(f"### {doc_name}\n{doc_content}")
        info["other_docs"] = "\n\n".join(other_docs) if other_docs else "(無)"
    else:
        info["git_log"] = await run_git_command(
            repo_path, ["log", "--since=7 days ago", "--oneline"]
        )
        info["other_docs"] = "(sync mode: 略過)"

    return info


def _is_default_content(content: str) -> bool:
    """Check if project content contains default/placeholder values."""
    default_markers = [
        "待填寫",
        "TODO:",
        "(無內容)",
        "Description here",
        "Add description",
    ]
    return any(marker.lower() in content.lower() for marker in default_markers)


async def _analyze_repo_for_init(
    project_name: str,
    repo_info: dict[str, str],
) -> dict[str, Any]:
    """Use Sonnet to analyze repository for init mode."""
    prompt = INIT_PROMPT.format(
        readme=repo_info.get("readme", "(無)"),
        claude_md=repo_info.get("claude_md", "(無)"),
        other_docs=repo_info.get("other_docs", "(無)"),
        dependencies=repo_info.get("dependencies", "(無)"),
        structure=repo_info.get("structure", "(無)"),
        git_log=repo_info.get("git_log", "(無)"),
    )

    options = ClaudeAgentOptions(model="claude-sonnet-4-5-20250929")
    result_text = ""

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            if hasattr(message, "result") and message.result:
                result_text = message.result
                break

    try:
        result_text = result_text.strip()
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            result_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        return yaml.safe_load(result_text) or {}
    except Exception:
        return {"_raw": result_text}


def _update_project_sections(
    project_file: Path,
    updates: dict[str, Any],
    is_init: bool = False,
) -> list[str]:
    """Update project file sections with AI-generated content."""
    post = load_frontmatter(project_file)
    content = post.content
    updated_sections: list[str] = []

    if "goal" in updates and (is_init or "## 目標" not in content):
        goal_text = (
            updates["goal"].strip() if isinstance(updates["goal"], str) else str(updates["goal"])
        )
        if "## 目標" in content:
            parts = content.split("## 目標")
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section != -1:
                content = parts[0] + "## 目標\n" + goal_text + rest[next_section:]
            else:
                content = parts[0] + "## 目標\n" + goal_text
        else:
            lines = content.split("\n")
            insert_idx = 1 if lines[0].startswith("#") else 0
            lines.insert(insert_idx + 1, f"\n## 目標\n{goal_text}")
            content = "\n".join(lines)
        updated_sections.append("目標")

    if "tech_stack" in updates:
        tech_list = updates["tech_stack"]
        if isinstance(tech_list, list):
            tech_text = "\n".join(f"- {item}" for item in tech_list)
        else:
            tech_text = str(tech_list)

        if "## 技術棧" in content:
            parts = content.split("## 技術棧")
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section != -1:
                content = parts[0] + "## 技術棧\n" + tech_text + rest[next_section:]
            else:
                content = parts[0] + "## 技術棧\n" + tech_text
            updated_sections.append("技術棧")

    date_str = datetime.now().strftime("%Y-%m-%d")
    mode_str = "init (完整分析)" if is_init else "sync (增量更新)"
    sync_entry = f"\n- 🔄 [{mode_str}] 已同步: {', '.join(updated_sections)}"

    if "## 進度日誌" in content:
        if f"### {date_str}" in content:
            content = content.replace(f"### {date_str}\n", f"### {date_str}{sync_entry}\n")
        else:
            parts = content.split("## 進度日誌")
            new_entry = f"\n\n### {date_str}{sync_entry}"
            content = parts[0] + "## 進度日誌" + new_entry + parts[1]
    else:
        content += f"\n\n## 進度日誌\n\n### {date_str}{sync_entry}"

    post.content = content
    save_frontmatter(project_file, post)

    return updated_sections


@tool(
    name="sync_project",
    description="從 repo 內容同步專案資訊。分析 README、CLAUDE.md、程式碼結構等，用 AI 生成/更新專案描述、技術棧、進度。",
    input_schema=SyncProjectInput.model_json_schema(),
)
async def sync_project(args: dict[str, Any]) -> dict[str, Any]:
    """Sync project information from repository content."""
    try:
        validated = SyncProjectInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    name = validated.name
    force = validated.force

    project_file = _get_project_path(name)

    if not project_file:
        available = [p[0] for p in _iter_all_projects()]
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"找不到專案：{name}\n可用的專案：{', '.join(available) if available else '(無)'}",
                }
            ],
            "is_error": True,
        }

    post = load_frontmatter(project_file)
    repo_path = post.get("repo", "")

    if not repo_path:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"專案 {name} 沒有設定 repo 路徑。請在 frontmatter 中加入 repo 欄位。",
                }
            ],
            "is_error": True,
        }

    repo_path = Path(repo_path).expanduser()
    if not repo_path.exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"專案路徑不存在：{repo_path}",
                }
            ],
            "is_error": True,
        }

    is_init = force or _is_default_content(post.content)
    mode_name = "init (完整分析)" if is_init else "sync (增量更新)"

    repo_info = await _collect_repo_info(repo_path, full_analysis=is_init)

    if not repo_info.get("readme"):
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"專案 {name} 的 repo 中找不到 README.md。",
                }
            ],
            "is_error": True,
        }

    try:
        updates = await _analyze_repo_for_init(name, repo_info)
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"AI 分析失敗：{e}"}],
            "is_error": True,
        }

    if "_raw" in updates:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"AI 回應格式錯誤，請手動更新。\n\n原始回應：\n{updates['_raw'][:1000]}",
                }
            ],
            "is_error": True,
        }

    updated_sections = _update_project_sections(project_file, updates, is_init=is_init)

    summary_lines = [
        f"## 已同步 {name}",
        "",
        f"**模式**: {mode_name}",
        f"**更新區塊**: {', '.join(updated_sections) if updated_sections else '(無變更)'}",
        "",
    ]

    if "goal" in updates:
        goal = updates["goal"].strip() if isinstance(updates["goal"], str) else str(updates["goal"])
        summary_lines.append(f"### 目標\n{goal}\n")

    summary_lines.append(f"已寫入 {project_file}")

    return {
        "content": [{"type": "text", "text": "\n".join(summary_lines)}],
    }


# ============================================================================
# Unified Review Tool
# ============================================================================


def _get_date_range(period: ReviewPeriod, date_str: str | None) -> tuple[datetime, datetime, str]:
    """Get start/end dates and label for a review period.

    Args:
        period: Review period (day/week/month).
        date_str: Optional date string.

    Returns:
        Tuple of (start_date, end_date, label).
    """
    today = datetime.now()

    if period == ReviewPeriod.DAY:
        if date_str:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            target = today
        start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = target.strftime("%Y-%m-%d")

    elif period == ReviewPeriod.WEEK:
        if date_str:
            year = int(date_str[:4])
            week = int(date_str[6:])
            start = datetime.strptime(f"{year}-W{week:02d}-1", "%Y-W%W-%w")
        else:
            start = today - timedelta(days=today.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=6)
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = start.strftime("%Y-W%W")

    else:  # MONTH
        if date_str:
            year = int(date_str[:4])
            month = int(date_str[5:7])
        else:
            year = today.year
            month = today.month
        start = datetime(year, month, 1)
        _, last_day = cal_module.monthrange(year, month)
        end = datetime(year, month, last_day, 23, 59, 59, 999999)
        label = start.strftime("%Y-%m")

    return start, end, label


async def _collect_completed_tasks_in_range(
    start_date: datetime, end_date: datetime
) -> dict[str, list[dict[str, Any]]]:
    """Collect completed tasks within a date range."""
    results: dict[str, list[dict[str, Any]]] = {}

    for name, project_path in _iter_all_projects():
        tasks_path = project_path.parent / "tasks.md"
        if not tasks_path.exists():
            continue

        try:
            tasks_content = tasks_path.read_text(encoding="utf-8")
            parsed = _parse_tasks(tasks_content)

            completed_in_range = []
            for task in parsed["completed"]:
                if "completed_date" in task:
                    task_date = datetime.strptime(task["completed_date"], "%Y-%m-%d")
                    if start_date <= task_date <= end_date:
                        completed_in_range.append(task)

            if completed_in_range:
                results[name] = completed_in_range

        except (OSError, IOError) as e:
            logger.warning(f"Failed to read tasks for {name}: {e}")

    return results


async def _collect_all_commits_in_range(
    start_date: datetime, end_date: datetime
) -> dict[str, list[str]]:
    """Collect git commits for all projects within a date range."""
    commits_summary: dict[str, list[str]] = {}

    for name, project_path in _iter_all_projects():
        post = load_frontmatter(project_path)
        repo_path_str = post.get("repo", "")
        if repo_path_str:
            repo_path = Path(repo_path_str).expanduser()
            if repo_path.exists():
                commits = await get_commits_in_range(repo_path, start_date, end_date)
                if commits and commits[0]:  # Filter empty results
                    commits_summary[name] = commits

    return commits_summary


async def _generate_reflection_questions(
    completed_tasks: dict[str, list[dict[str, Any]]],
    commits_summary: dict[str, list[str]],
) -> str:
    """Use AI to generate reflection questions."""
    summary_parts = []
    for project, tasks in completed_tasks.items():
        task_texts = [t["text"] for t in tasks]
        summary_parts.append(f"**{project}** 完成任務: {', '.join(task_texts)}")

    for project, commits in commits_summary.items():
        if commits:
            summary_parts.append(f"**{project}** commits: {len(commits)} 筆")

    if not summary_parts:
        return "- 本週沒有完成的任務，下週有什麼想要達成的目標？"

    prompt = f"""根據以下本週完成的工作，生成 3-5 個反思問題。

本週工作摘要：
{chr(10).join(summary_parts)}

請直接輸出問題，每個問題一行，用 "- " 開頭。繁體中文。"""

    options = ClaudeAgentOptions(model="claude-haiku-3-5-20241022")
    result_text = ""

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            if hasattr(message, "result") and message.result:
                result_text = message.result
                break

    return result_text or "- 本週有什麼讓你感到自豪的成就？\n- 下週最重要的一件事是什麼？"


def _update_daily_note_review(
    daily_file: Path,
    commits_by_project: dict[str, list[str]],
    notes: str | None,
) -> None:
    """Update daily note with end-of-day review section."""
    post = load_frontmatter(daily_file)
    now = datetime.now()

    commit_lines: list[str] = []
    for proj_name, commits in commits_by_project.items():
        for commit in commits:
            commit_lines.append(f"- {proj_name}: {commit}")

    if not commit_lines:
        commit_lines.append("- (今日無 commits)")

    review_section = f"""## 日終回顧
### Git Commits
{chr(10).join(commit_lines)}

### 筆記
{notes if notes else "(無)"}

### 更新時間
{now.strftime("%H:%M")}
"""

    post["updated_at"] = now.isoformat()

    content = post.content
    if "## 日終回顧" in content:
        parts = content.split("## 日終回顧")
        content = parts[0] + review_section
    else:
        content = content + "\n" + review_section

    post.content = content
    save_frontmatter(daily_file, post)


@tool(
    name="generate_review",
    description="生成回顧報告。支援三種模式：day（日終回顧，掃描今日 commits）、week（週回顧）、month（月回顧）。",
    input_schema=GenerateReviewInput.model_json_schema(),
)
async def generate_review(args: dict[str, Any]) -> dict[str, Any]:
    """Generate review report for day/week/month.

    - day: 更新今日筆記的日終回顧區塊（等同原 end_of_day）
    - week: 生成週回顧報告到 data/reviews/weekly/
    - month: 生成月回顧報告到 data/reviews/monthly/
    """
    try:
        validated = GenerateReviewInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    period = validated.period
    start_date, end_date, label = _get_date_range(period, validated.date)

    # ========== Day Review (end_of_day) ==========
    if period == ReviewPeriod.DAY:
        daily_dir = _get_daily_dir()
        daily_file = daily_dir / f"{label}.md"

        if not daily_file.exists():
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"找不到 {label} 的每日筆記。請先使用 plan_today 建立。",
                    }
                ],
                "is_error": True,
            }

        # Collect today's commits
        commits_by_project: dict[str, list[str]] = {}
        for name, project_path in _iter_all_projects():
            post = load_frontmatter(project_path)
            repo_path_str = post.get("repo", "")
            if repo_path_str:
                repo_path = Path(repo_path_str).expanduser()
                if repo_path.exists():
                    commits = await get_today_commits(repo_path)
                    if commits and commits[0]:
                        commits_by_project[name] = commits

        _update_daily_note_review(daily_file, commits_by_project, validated.notes)

        total_commits = sum(len(c) for c in commits_by_project.values())
        commit_lines = []
        for proj_name, commits in commits_by_project.items():
            for commit in commits:
                commit_lines.append(f"- {proj_name}: {commit}")
        if not commit_lines:
            commit_lines.append("- (今日無 commits)")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"""## 日終回顧完成

**專案 commits**: {len(commits_by_project)} 個專案
**總 commits**: {total_commits} 筆
**檔案已更新**: {daily_file}

{chr(10).join(commit_lines)}

辛苦了，好好休息！""",
                }
            ],
        }

    # ========== Week / Month Review ==========
    completed_tasks = await _collect_completed_tasks_in_range(start_date, end_date)
    commits_summary = await _collect_all_commits_in_range(start_date, end_date)

    if period == ReviewPeriod.WEEK:
        reflection = await _generate_reflection_questions(completed_tasks, commits_summary)

        lines = [
            f"# 週回顧 {label}",
            "",
            f"**期間**: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            f"**生成時間**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 完成的任務",
            "",
        ]

        if completed_tasks:
            for project, tasks in completed_tasks.items():
                lines.append(f"### {project}")
                for task in tasks:
                    date_str = task.get("completed_date", "")
                    lines.append(f"- [x] {task['text']} ({date_str})")
                lines.append("")
        else:
            lines.append("_本週沒有標記完成的任務_")
            lines.append("")

        lines.append("## Git Commits 摘要")
        lines.append("")

        if commits_summary:
            for project, commits in commits_summary.items():
                lines.append(f"### {project} ({len(commits)} commits)")
                for commit in commits[:10]:
                    lines.append(f"- {commit}")
                if len(commits) > 10:
                    lines.append(f"- ... 共 {len(commits)} 筆")
                lines.append("")
        else:
            lines.append("_本週沒有 commits_")
            lines.append("")

        lines.append("## 反思問題")
        lines.append("")
        lines.append(reflection)
        lines.append("")

        reviews_dir = _get_reviews_dir() / "weekly"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        review_file = reviews_dir / f"{label}.md"
        review_file.write_text("\n".join(lines), encoding="utf-8")

        total_tasks = sum(len(tasks) for tasks in completed_tasks.values())
        total_commits = sum(len(commits) for commits in commits_summary.values())

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"""## 週回顧 {label} 已生成

**統計**:
- 完成任務: {total_tasks} 項
- Git commits: {total_commits} 筆
- 涵蓋專案: {len(completed_tasks) + len(commits_summary)} 個

**檔案**: `{review_file}`

{reflection}""",
                }
            ],
        }

    else:  # MONTH
        project_progress: list[dict[str, Any]] = []

        for name, project_path in _iter_all_projects():
            post = load_frontmatter(project_path)
            task_counts = _count_tasks(project_path)

            project_info = {
                "name": post.get("name", name),
                "status": post.get("status", "unknown"),
                "progress": post.get("progress", _calculate_progress(project_path)),
                "tasks": task_counts,
            }
            project_progress.append(project_info)

        month_name = start_date.strftime("%Y 年 %m 月")
        lines = [
            f"# 月回顧 {month_name}",
            "",
            f"**期間**: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            f"**生成時間**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 專案進度總覽",
            "",
        ]

        for proj in project_progress:
            status_emoji = {
                "active": "🟢",
                "paused": "⏸️",
                "completed": "✅",
                "archived": "📦",
            }.get(proj["status"], "❓")

            tasks = proj["tasks"]
            task_str = (
                f"{tasks['completed']}/{tasks['total']} tasks" if tasks["total"] > 0 else "0 tasks"
            )
            commits_count = len(commits_summary.get(proj["name"].lower(), []))
            commits_str = f", {commits_count} commits" if commits_count > 0 else ""

            lines.append(f"- {status_emoji} **{proj['name']}**: {task_str}{commits_str}")

        lines.append("")
        lines.append("## 月度成就清單")
        lines.append("")

        if completed_tasks:
            total_count = 0
            for project, tasks in completed_tasks.items():
                lines.append(f"### {project}")
                for task in tasks:
                    lines.append(f"- [x] {task['text']}")
                    total_count += 1
                lines.append("")
            lines.append(f"**共完成 {total_count} 項任務**")
        else:
            lines.append("_本月沒有標記完成的任務_")

        lines.append("")
        lines.append("## 學習與成長")
        lines.append("")
        lines.append("<!-- 手動填寫本月學到的新技術、概念或技能 -->")
        lines.append("- ")
        lines.append("")
        lines.append("## 下月目標")
        lines.append("")
        lines.append("<!-- 手動填寫下個月想要達成的目標 -->")
        lines.append("- ")
        lines.append("")

        reviews_dir = _get_reviews_dir() / "monthly"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        review_file = reviews_dir / f"{label}.md"
        review_file.write_text("\n".join(lines), encoding="utf-8")

        total_tasks = sum(len(tasks) for tasks in completed_tasks.values())
        total_commits = sum(len(commits) for commits in commits_summary.values())

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"""## 月回顧 {month_name} 已生成

**統計**:
- 追蹤專案: {len(project_progress)} 個
- 完成任務: {total_tasks} 項
- Git commits: {total_commits} 筆

**檔案**: `{review_file}`

請檢查並手動填寫「學習與成長」和「下月目標」區塊。""",
                }
            ],
        }


# ============================================================================
# Export
# ============================================================================

all_tools = [
    list_projects,
    show_project,
    get_today_tasks,
    sync_project,
    generate_review,
]
