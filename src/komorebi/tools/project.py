"""Project management tools for Komorebi.

學習重點：
- @tool decorator 定義工具的三個參數：name, description, input_schema
- 工具函數必須是 async def
- 回傳格式：{"content": [{"type": "text", "text": "..."}]}
- 錯誤時加上 "is_error": True
- 使用 Pydantic BaseModel 驗證工具輸入

這些工具支援雙模式專案結構：
- 檔案模式：data/projects/komorebi.md（舊版）
- 資料夾模式：data/projects/komorebi/project.md + tasks.md（新版）
"""

import asyncio
import logging
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import frontmatter
from claude_agent_sdk import ClaudeAgentOptions, query, tool
from claude_agent_sdk.types import ResultMessage
from pydantic import BaseModel, Field

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


class UpdateStatusInput(BaseModel):
    """Input schema for update_project_status tool."""

    name: str = Field(..., min_length=1, description="專案名稱")
    status: ProjectStatus = Field(..., description="新狀態")


class UpdateProgressInput(BaseModel):
    """Input schema for update_project_progress tool."""

    name: str = Field(..., min_length=1, description="專案名稱")
    days: int = Field(default=1, ge=1, le=30, description="分析最近幾天的變更")


class SyncProjectInput(BaseModel):
    """Input schema for sync_project tool."""

    name: str = Field(..., min_length=1, description="專案名稱")
    force: bool = Field(default=False, description="是否強制覆寫")


# 專案資料目錄，由 agent 設定
_data_dir: Path = Path("data")


def set_data_dir(path: Path) -> None:
    """Set the data directory for project tools.

    Args:
        path: Path to the data directory containing projects/.
    """
    global _data_dir
    _data_dir = path


def _get_projects_dir() -> Path:
    """Get the projects directory path."""
    return _data_dir / "projects"


# ============================================================================
# Dual-Mode Path Helpers
# ============================================================================


def _is_folder_mode(project_name: str) -> bool:
    """Check if a project uses folder mode.

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        True if project uses folder mode (has project.md inside folder).
    """
    projects_dir = _get_projects_dir()

    # Check for folder mode: projects/komorebi/project.md
    folder_path = projects_dir / project_name.lower()
    if folder_path.is_dir() and (folder_path / "project.md").exists():
        return True

    return False


def _get_project_path(project_name: str) -> Path | None:
    """Get the project.md path for a project (supports both modes).

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        Path to project.md or None if not found.
    """
    projects_dir = _get_projects_dir()
    name_lower = project_name.lower()

    # Priority 1: Folder mode (projects/komorebi/project.md)
    folder_path = projects_dir / name_lower / "project.md"
    if folder_path.exists():
        return folder_path

    # Priority 2: File mode (projects/komorebi.md)
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() == name_lower:
            return md_file

    return None


def _get_tasks_path(project_name: str) -> Path | None:
    """Get the tasks.md path for a project (folder mode only).

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        Path to tasks.md or None if not in folder mode.
    """
    projects_dir = _get_projects_dir()
    tasks_path = projects_dir / project_name.lower() / "tasks.md"
    return tasks_path if tasks_path.exists() else None


def _get_project_folder(project_name: str) -> Path | None:
    """Get the project folder path (folder mode only).

    Args:
        project_name: Project name (case-insensitive).

    Returns:
        Path to project folder or None if not in folder mode.
    """
    projects_dir = _get_projects_dir()
    folder_path = projects_dir / project_name.lower()
    return folder_path if folder_path.is_dir() else None


def _iter_all_projects() -> list[tuple[str, Path, bool]]:
    """Iterate over all projects, both file and folder mode.

    Returns:
        List of (project_name, project_md_path, is_folder_mode) tuples.
    """
    projects_dir = _get_projects_dir()
    results: list[tuple[str, Path, bool]] = []

    if not projects_dir.exists():
        return results

    # Collect folder mode projects
    for item in projects_dir.iterdir():
        if item.is_dir():
            project_md = item / "project.md"
            if project_md.exists():
                results.append((item.name, project_md, True))

    # Collect file mode projects (exclude those already in folder mode)
    folder_names = {r[0] for r in results}
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() not in folder_names:
            results.append((md_file.stem, md_file, False))

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

    # Parse task line: - [ ] task text #tag @today (2026-01-18)
    task_pattern = re.compile(
        r"^-\s*\[([ xX])\]\s*"  # checkbox
        r"(.+?)"  # task text
        r"(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$"  # optional date
    )

    for line in tasks_content.split("\n"):
        line = line.strip()

        # Check for section headers
        if line.startswith("## "):
            section_name = line[3:].strip().lower()
            if section_name in section_map:
                current_section = section_map[section_name]
            continue

        # Check for task lines
        match = task_pattern.match(line)
        if match:
            checked = match.group(1).lower() == "x"
            text = match.group(2).strip()
            completed_date = match.group(3)

            # Extract tags (#tag)
            tags = re.findall(r"#(\S+)", text)
            text_clean = re.sub(r"\s*#\S+", "", text).strip()

            # Check for @today marker
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

            # Put in appropriate section based on checkbox state
            if checked:
                result["completed"].append(task)
            else:
                result[current_section].append(task)

    return result


def _count_tasks(project_path: Path) -> dict[str, int]:
    """Count tasks for a project (supports both modes).

    Args:
        project_path: Path to project.md file.

    Returns:
        Dictionary with task counts.
    """
    counts = {"total": 0, "completed": 0, "in_progress": 0, "pending": 0}

    # Check if this is folder mode
    if project_path.name == "project.md":
        tasks_path = project_path.parent / "tasks.md"
        if tasks_path.exists():
            tasks = _parse_tasks(tasks_path.read_text(encoding="utf-8"))
            counts["in_progress"] = len(tasks["in_progress"])
            counts["pending"] = len(tasks["pending"])
            counts["completed"] = len(tasks["completed"])
            counts["total"] = sum(counts.values()) - counts["completed"]
            counts["total"] += counts["completed"]

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


@tool(
    name="list_projects",
    description="列出所有專案及其狀態、進度統計。回傳專案名稱、狀態、優先順序、任務完成率等摘要資訊。",
    input_schema={},  # 無參數
)
async def list_projects(args: dict[str, Any]) -> dict[str, Any]:
    """List all projects with statistics (supports both file and folder mode).

    讀取每個專案的 frontmatter 和任務統計資訊。

    Returns:
        Tool response with formatted project list and statistics.
    """
    projects_dir = _get_projects_dir()

    if not projects_dir.exists():
        return {
            "content": [
                {"type": "text", "text": "專案資料夾不存在。請先建立 data/projects/ 目錄。"}
            ],
            "is_error": True,
        }

    projects: list[dict[str, Any]] = []

    for name, project_path, is_folder in _iter_all_projects():
        try:
            post = frontmatter.load(project_path)
            task_counts = _count_tasks(project_path)

            projects.append(
                {
                    "name": post.get("name", name),
                    "type": post.get("type", "software"),
                    "status": post.get("status", "unknown"),
                    "priority": post.get("priority", 999),
                    "progress": post.get("progress", _calculate_progress(project_path)),
                    "is_folder": is_folder,
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
                    "is_folder": is_folder,
                    "tasks": {"total": 0, "completed": 0},
                }
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse frontmatter in {project_path}: {e}")
            projects.append(
                {
                    "name": name,
                    "type": "unknown",
                    "status": "error: invalid format",
                    "priority": 999,
                    "progress": 0,
                    "is_folder": is_folder,
                    "tasks": {"total": 0, "completed": 0},
                }
            )

    if not projects:
        return {
            "content": [{"type": "text", "text": "目前沒有任何專案。"}],
        }

    # 按優先順序排序
    projects.sort(key=lambda p: p["priority"])

    # 格式化輸出
    lines = ["## 專案列表\n"]
    for p in projects:
        status_emoji = {
            "active": "🟢",
            "paused": "⏸️",
            "completed": "✅",
            "archived": "📦",
        }.get(p["status"], "❓")

        # Build stats string
        stats_parts = []
        if p["tasks"]["total"] > 0:
            stats_parts.append(f"{p['tasks']['completed']}/{p['tasks']['total']} tasks")
        if p["progress"] > 0:
            stats_parts.append(f"{p['progress']}%")
        stats = f" | {', '.join(stats_parts)}" if stats_parts else ""

        # Mode indicator
        mode = "📁" if p["is_folder"] else "📄"

        lines.append(f"- {status_emoji} {mode} **{p['name']}** ({p['status']}){stats}")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
    }


@tool(
    name="show_project",
    description="顯示單一專案的完整資訊，包含目標、技術棧、進度、任務清單等詳細內容。支援檔案和資料夾兩種模式。",
    input_schema=ShowProjectInput.model_json_schema(),
)
async def show_project(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a specific project.

    支援雙模式：
    - 檔案模式：回傳 project.md 內容
    - 資料夾模式：回傳 project.md + tasks.md 內容

    Args:
        args: Dictionary containing 'name' - the project name (case-insensitive).

    Returns:
        Tool response with project details.
    """
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
        # 列出可用的專案
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

    # Read project.md
    content = project_path.read_text(encoding="utf-8")

    # Check if folder mode - include tasks.md if exists
    is_folder = project_path.name == "project.md"
    if is_folder:
        tasks_path = project_path.parent / "tasks.md"
        if tasks_path.exists():
            tasks_content = tasks_path.read_text(encoding="utf-8")
            content += f"\n\n---\n\n# 任務清單 (tasks.md)\n\n{tasks_content}"

        # Add folder info
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
    input_schema={},  # 無參數
)
async def get_today_tasks(args: dict[str, Any]) -> dict[str, Any]:
    """Get today's tasks across all projects.

    掃描所有專案（folder mode）的 tasks.md，找出：
    1. 標記 @today 的任務
    2. 進行中的任務

    Returns:
        Tool response with today's task list.
    """
    today_tasks: list[dict[str, Any]] = []
    in_progress_tasks: list[dict[str, Any]] = []

    for name, project_path, is_folder in _iter_all_projects():
        if not is_folder:
            continue  # Only check folder mode projects

        tasks_path = project_path.parent / "tasks.md"
        if not tasks_path.exists():
            continue

        try:
            tasks_content = tasks_path.read_text(encoding="utf-8")
            parsed = _parse_tasks(tasks_content)

            # Collect @today tasks
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

            # Collect all in-progress tasks
            for task in parsed["in_progress"]:
                if not task.get("is_today"):  # Avoid duplicates
                    in_progress_tasks.append(
                        {
                            "project": name,
                            "text": task["text"],
                            "tags": task.get("tags", []),
                        }
                    )

        except (OSError, IOError) as e:
            logger.warning(f"Failed to read tasks for {name}: {e}")

    # Format output
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


@tool(
    name="update_project_status",
    description="更新專案的狀態（active, paused, completed, archived）。支援檔案和資料夾兩種模式。",
    input_schema=UpdateStatusInput.model_json_schema(),
)
async def update_project_status(args: dict[str, Any]) -> dict[str, Any]:
    """Update the status of a project.

    修改專案 markdown 檔案的 frontmatter 中的 status 欄位。
    支援檔案和資料夾兩種模式。

    Args:
        args: Dictionary containing 'name' and 'status'.

    Returns:
        Tool response confirming the update.
    """
    try:
        validated = UpdateStatusInput(**args)
    except ValueError as e:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"輸入驗證失敗：{e}\n有效狀態：active, paused, completed, archived",
                }
            ],
            "is_error": True,
        }

    name = validated.name
    new_status = validated.status.value

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

    # 讀取並更新
    try:
        post = frontmatter.load(project_file)
        old_status = post.get("status", "unknown")
        post["status"] = new_status
        post["updated"] = datetime.now().strftime("%Y-%m-%d")

        project_file.write_text(frontmatter.dumps(post), encoding="utf-8")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"已更新 **{name}** 狀態：{old_status} → {new_status}",
                }
            ],
        }
    except (OSError, IOError) as e:
        logger.error(f"Failed to write project file {project_file}: {e}")
        return {
            "content": [{"type": "text", "text": f"寫入檔案失敗：{e}"}],
            "is_error": True,
        }
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse frontmatter in {project_file}: {e}")
        return {
            "content": [{"type": "text", "text": f"檔案格式錯誤：{e}"}],
            "is_error": True,
        }


# ============================================================================
# Progress Analysis Tool
# ============================================================================


async def _run_git_command(repo_path: Path, args: list[str]) -> str:
    """Run a git command asynchronously and return output.

    Args:
        repo_path: Path to the git repository.
        args: Git command arguments.

    Returns:
        Command output or empty string on error.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode == 0:
            return stdout.decode().strip()
    except asyncio.TimeoutError:
        logger.warning(f"Git command timed out: git {' '.join(args)}")
    except FileNotFoundError:
        logger.warning("Git executable not found")
    except OSError as e:
        logger.warning(f"Git command failed: {e}")
    return ""


async def _collect_git_info(repo_path: Path, days: int = 1) -> dict[str, str]:
    """Collect git log and diff information asynchronously.

    Args:
        repo_path: Path to the git repository.
        days: Number of days to look back.

    Returns:
        Dictionary with log, diff, and changed_files.
    """
    # Run git commands in parallel for better performance
    log_task = _run_git_command(repo_path, ["log", f"--since={days} days ago", "--oneline"])
    diff_task = _run_git_command(repo_path, ["diff", f"HEAD~{days}", "--stat"])
    diff_content_task = _run_git_command(repo_path, ["diff", f"HEAD~{days}"])
    changed_files_task = _run_git_command(repo_path, ["diff", "--name-only", f"HEAD~{days}"])

    log, diff, diff_content, changed_files = await asyncio.gather(
        log_task, diff_task, diff_content_task, changed_files_task
    )

    return {
        "log": log,
        "diff": diff,
        "diff_content": diff_content,
        "changed_files": changed_files,
    }


async def _analyze_with_sonnet(project_name: str, git_info: dict[str, str]) -> str:
    """Use Sonnet to analyze project progress.

    Args:
        project_name: Name of the project.
        git_info: Dictionary with git information.

    Returns:
        Progress summary in Traditional Chinese.
    """
    # 限制 diff 長度避免 token 過多
    diff_content = git_info["diff_content"][:4000] if git_info["diff_content"] else "(無變更)"

    prompt = f"""分析以下專案的進度，用繁體中文撰寫簡潔的進度摘要（3-5 個 bullet points）。

## 專案：{project_name}

## Git Commits
{git_info["log"] or "(無 commits)"}

## 檔案變更統計
{git_info["diff"] or "(無變更)"}

## 程式碼變更內容
{diff_content}

請直接輸出進度摘要，不要有開頭語或結尾語。格式：
- 第一項進度
- 第二項進度
..."""

    options = ClaudeAgentOptions(model="claude-sonnet-4-5-20250929")
    result_text = ""

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            # 從 ResultMessage 中提取文字
            if hasattr(message, "result") and message.result:
                result_text = message.result
                break

    return result_text


def _append_progress_log(project_file: Path, date_str: str, summary: str) -> None:
    """Append progress summary to project's progress log.

    Args:
        project_file: Path to the project markdown file.
        date_str: Date string (YYYY-MM-DD).
        summary: Progress summary to append.
    """
    post = frontmatter.load(project_file)
    content = post.content

    # 找到 "## 進度日誌" 區塊
    if "## 進度日誌" in content:
        # 在 "## 進度日誌" 後插入新日誌
        parts = content.split("## 進度日誌")
        new_entry = f"\n\n### {date_str}\n{summary}"
        content = parts[0] + "## 進度日誌" + new_entry + parts[1]
    else:
        # 如果沒有進度日誌區塊，在最後加上
        content += f"\n\n## 進度日誌\n\n### {date_str}\n{summary}"

    post.content = content

    project_file.write_text(frontmatter.dumps(post), encoding="utf-8")


@tool(
    name="update_project_progress",
    description="用 AI 分析專案的 git 變更，自動撰寫進度日誌。會研究 commits 和程式碼變更後生成摘要。",
    input_schema=UpdateProgressInput.model_json_schema(),
)
async def update_project_progress(args: dict[str, Any]) -> dict[str, Any]:
    """Analyze project git changes and update progress log.

    使用 Sonnet 分析專案的 git commits 和程式碼變更，
    自動生成進度摘要並寫入專案的進度日誌。

    Args:
        args: Dictionary containing:
            - name: 專案名稱
            - days: 分析最近幾天的變更（預設 1）

    Returns:
        Tool response with generated progress summary.
    """
    try:
        validated = UpdateProgressInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    name = validated.name
    days = validated.days

    # 找到專案檔案（支援檔案和資料夾兩種模式）
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

    # 讀取專案的 repo 路徑
    post = frontmatter.load(project_file)
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

    # 展開路徑
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

    # 收集 git 資訊
    git_info = await _collect_git_info(repo_path, days)

    if not git_info["log"]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"專案 {name} 在最近 {days} 天內沒有 commits。",
                }
            ],
        }

    # 用 Sonnet 分析
    try:
        summary = await _analyze_with_sonnet(name, git_info)
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"AI 分析失敗：{e}"}],
            "is_error": True,
        }

    # 更新進度日誌
    date_str = datetime.now().strftime("%Y-%m-%d")
    _append_progress_log(project_file, date_str, summary)

    return {
        "content": [
            {
                "type": "text",
                "text": f"""## 已更新 {name} 的進度日誌

**日期**: {date_str}
**分析範圍**: 最近 {days} 天
**Commits**: {len(git_info["log"].splitlines())} 筆

### 進度摘要
{summary}

已寫入 {project_file}""",
            }
        ],
    }


# ============================================================================
# Project Sync Tool
# ============================================================================


def _read_file_safely(file_path: Path, max_chars: int = 4000) -> str:
    """Read file content with size limit.

    Args:
        file_path: Path to file.
        max_chars: Maximum characters to read.

    Returns:
        File content (truncated if needed) or empty string.
    """
    if not file_path.exists():
        return ""
    try:
        content = file_path.read_text(encoding="utf-8")
        if len(content) > max_chars:
            return content[:max_chars] + "\n...(truncated)"
        return content
    except Exception:
        return ""


async def _collect_repo_info_full(repo_path: Path, full_analysis: bool = False) -> dict[str, str]:
    """Collect comprehensive repository information asynchronously.

    Args:
        repo_path: Path to the repository.
        full_analysis: If True, collect more data for init mode.

    Returns:
        Dictionary with readme, claude_md, other_docs, dependencies,
        structure, git_log.
    """
    info: dict[str, str] = {}

    # README
    info["readme"] = _read_file_safely(repo_path / "README.md")

    # CLAUDE.md (if exists)
    info["claude_md"] = _read_file_safely(repo_path / "CLAUDE.md")

    # Dependencies (pyproject.toml or package.json)
    deps_file = repo_path / "pyproject.toml"
    if not deps_file.exists():
        deps_file = repo_path / "package.json"
    info["dependencies"] = _read_file_safely(deps_file, max_chars=2000)

    # Directory structure
    info["structure"] = await _run_git_command(
        repo_path,
        ["-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD"],
    )
    if not info["structure"]:
        # Fallback: use find command asynchronously
        try:
            process = await asyncio.create_subprocess_exec(
                "find",
                ".",
                "-maxdepth",
                "3",
                "-type",
                "f",
                "-name",
                "*.py",
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            info["structure"] = stdout.decode().strip()
        except (asyncio.TimeoutError, OSError) as e:
            logger.warning(f"Failed to get directory structure: {e}")
            info["structure"] = "(無法取得目錄結構)"

    # Git log
    if full_analysis:
        # Full history for init mode
        info["git_log"] = await _run_git_command(repo_path, ["log", "--oneline", "-50"])
        # Other docs
        other_docs = []
        for doc_name in ["TECHNICAL.md", "API_SPEC.md", "ARCHITECTURE.md"]:
            doc_content = _read_file_safely(repo_path / doc_name, max_chars=2000)
            if doc_content:
                other_docs.append(f"### {doc_name}\n{doc_content}")
        info["other_docs"] = "\n\n".join(other_docs) if other_docs else "(無)"
    else:
        # Recent history for sync mode
        info["git_log"] = await _run_git_command(
            repo_path, ["log", "--since=7 days ago", "--oneline"]
        )
        info["other_docs"] = "(sync mode: 略過)"

    return info


def _is_default_content(content: str) -> bool:
    """Check if project content contains default/placeholder values.

    Args:
        content: Project markdown content.

    Returns:
        True if content appears to be default/placeholder.
    """
    default_markers = [
        "Layer-wise training framework",  # LayerWise 的錯誤預設描述
        "待填寫",
        "TODO:",
        "(無內容)",
        "Description here",
        "Add description",
    ]
    return any(marker.lower() in content.lower() for marker in default_markers)


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
  - "Core: pypotrace (向量描摹)"
  # 列出所有關鍵技術，附上用途說明

current_progress:
  - "[x] 已完成的功能"
  - "[ ] 進行中或待辦的功能"
  # 根據程式碼結構和 git history 推測

blockers:
  - "(無)"
  # 或描述發現的潛在問題

注意：
1. goal 要精確描述專案目的和核心價值
2. tech_stack 要完整，每項附上用途
3. current_progress 根據程式碼結構推測完成度
4. 直接輸出 YAML，開頭是 goal:
"""


async def _analyze_repo_for_init(
    project_name: str,
    repo_info: dict[str, str],
) -> dict[str, Any]:
    """Use Sonnet to analyze repository for init mode.

    Args:
        project_name: Name of the project.
        repo_info: Collected repository information.

    Returns:
        Parsed YAML as dictionary, or empty dict on error.
    """
    import yaml

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

    # Parse YAML response
    try:
        # Remove potential markdown code block markers
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
    """Update project file sections with AI-generated content.

    Args:
        project_file: Path to project markdown file.
        updates: Dictionary with goal, tech_stack, current_progress, blockers.
        is_init: If True, overwrite all sections (init mode).

    Returns:
        List of updated section names.
    """
    post = frontmatter.load(project_file)
    content = post.content
    updated_sections: list[str] = []

    # Update goal section
    if "goal" in updates and (is_init or "## 目標" not in content):
        goal_text = (
            updates["goal"].strip() if isinstance(updates["goal"], str) else str(updates["goal"])
        )
        if "## 目標" in content:
            parts = content.split("## 目標")
            # Find the next section
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section != -1:
                content = parts[0] + "## 目標\n" + goal_text + rest[next_section:]
            else:
                content = parts[0] + "## 目標\n" + goal_text
        else:
            # Add after title
            lines = content.split("\n")
            insert_idx = 1 if lines[0].startswith("#") else 0
            lines.insert(insert_idx + 1, f"\n## 目標\n{goal_text}")
            content = "\n".join(lines)
        updated_sections.append("目標")

    # Update tech_stack section
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

    # Update current_progress section
    if "current_progress" in updates and is_init:
        progress_list = updates["current_progress"]
        if isinstance(progress_list, list):
            progress_text = "\n".join(f"- {item}" for item in progress_list)
        else:
            progress_text = str(progress_list)

        if "## 當前進度" in content:
            parts = content.split("## 當前進度")
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section != -1:
                content = parts[0] + "## 當前進度\n" + progress_text + rest[next_section:]
            else:
                content = parts[0] + "## 當前進度\n" + progress_text
            updated_sections.append("當前進度")

    # Update blockers section (only in init mode)
    if "blockers" in updates and is_init:
        blockers_list = updates["blockers"]
        if isinstance(blockers_list, list):
            blockers_text = "\n".join(f"- {item}" for item in blockers_list)
        else:
            blockers_text = str(blockers_list)

        if "## Blockers" in content:
            parts = content.split("## Blockers")
            rest = parts[1]
            next_section = rest.find("\n## ")
            if next_section != -1:
                content = parts[0] + "## Blockers\n" + blockers_text + rest[next_section:]
            else:
                content = parts[0] + "## Blockers\n" + blockers_text
            updated_sections.append("Blockers")

    # Add sync log entry
    date_str = datetime.now().strftime("%Y-%m-%d")
    mode_str = "init (完整分析)" if is_init else "sync (增量更新)"
    sync_entry = f"\n- 🔄 [{mode_str}] 已同步: {', '.join(updated_sections)}"

    if "## 進度日誌" in content:
        # Check if today's entry already exists
        if f"### {date_str}" in content:
            # Append to existing date entry
            content = content.replace(f"### {date_str}\n", f"### {date_str}{sync_entry}\n")
        else:
            # Add new date entry
            parts = content.split("## 進度日誌")
            new_entry = f"\n\n### {date_str}{sync_entry}"
            content = parts[0] + "## 進度日誌" + new_entry + parts[1]
    else:
        content += f"\n\n## 進度日誌\n\n### {date_str}{sync_entry}"

    post.content = content

    project_file.write_text(frontmatter.dumps(post), encoding="utf-8")

    return updated_sections


@tool(
    name="sync_project",
    description="從 repo 內容同步專案資訊。分析 README、CLAUDE.md、程式碼結構等，用 AI 生成/更新專案描述、技術棧、進度。初次使用會進行完整分析。",
    input_schema=SyncProjectInput.model_json_schema(),
)
async def sync_project(args: dict[str, Any]) -> dict[str, Any]:
    """Sync project information from repository content.

    分析 repo 的 README、CLAUDE.md、程式碼結構等，
    用 AI 生成/更新專案的目標、技術棧、進度等資訊。

    支援兩種模式：
    - init: 專案內容為預設值時，進行完整分析
    - sync: 專案已有內容時，進行增量更新

    Args:
        args: Dictionary containing:
            - name: 專案名稱
            - force: 是否強制覆寫（預設 False）

    Returns:
        Tool response with sync summary.
    """
    try:
        validated = SyncProjectInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    name = validated.name
    force = validated.force

    # Find project file (supports both file and folder mode)
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

    # Read project and get repo path
    post = frontmatter.load(project_file)
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

    # Determine mode: init or sync
    is_init = force or _is_default_content(post.content)
    mode_name = "init (完整分析)" if is_init else "sync (增量更新)"

    # Collect repo info
    repo_info = await _collect_repo_info_full(repo_path, full_analysis=is_init)

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

    # Analyze with AI
    try:
        updates = await _analyze_repo_for_init(name, repo_info)
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"AI 分析失敗：{e}"}],
            "is_error": True,
        }

    if "_raw" in updates:
        # Failed to parse YAML
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"AI 回應格式錯誤，請手動更新。\n\n原始回應：\n{updates['_raw'][:1000]}",
                }
            ],
            "is_error": True,
        }

    # Update project file
    updated_sections = _update_project_sections(project_file, updates, is_init=is_init)

    # Build summary
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

    if "tech_stack" in updates:
        tech = updates["tech_stack"]
        if isinstance(tech, list):
            summary_lines.append("### 技術棧")
            for item in tech[:5]:  # Show first 5
                summary_lines.append(f"- {item}")
            if len(tech) > 5:
                summary_lines.append(f"- ... 共 {len(tech)} 項")
            summary_lines.append("")

    summary_lines.append(f"已寫入 {project_file}")

    return {
        "content": [{"type": "text", "text": "\n".join(summary_lines)}],
    }


# ============================================================================
# Review Tools
# ============================================================================


class WeeklyReviewInput(BaseModel):
    """Input schema for weekly_review tool."""

    week: str | None = Field(
        default=None,
        description="週次 (格式: 2026-W03)，預設為本週",
    )


class MonthlyReviewInput(BaseModel):
    """Input schema for monthly_review tool."""

    month: str | None = Field(
        default=None,
        description="月份 (格式: 2026-01)，預設為本月",
    )


def _get_reviews_dir() -> Path:
    """Get the reviews directory path."""
    return _data_dir / "reviews"


def _get_week_range(week_str: str) -> tuple[datetime, datetime]:
    """Get start and end dates for a week string (YYYY-Www).

    Args:
        week_str: Week string like '2026-W03'.

    Returns:
        Tuple of (start_date, end_date) as datetime objects.
    """
    # Parse week string
    year = int(week_str[:4])
    week = int(week_str[6:])

    # Get first day of the week (Monday)
    start = datetime.strptime(f"{year}-W{week:02d}-1", "%Y-W%W-%w")
    end = start + __import__("datetime").timedelta(days=6)

    return start, end


def _get_month_range(month_str: str) -> tuple[datetime, datetime]:
    """Get start and end dates for a month string (YYYY-MM).

    Args:
        month_str: Month string like '2026-01'.

    Returns:
        Tuple of (start_date, end_date) as datetime objects.
    """
    import calendar

    year = int(month_str[:4])
    month = int(month_str[5:7])

    start = datetime(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    end = datetime(year, month, last_day)

    return start, end


async def _collect_completed_tasks_in_range(
    start_date: datetime, end_date: datetime
) -> dict[str, list[dict[str, Any]]]:
    """Collect completed tasks within a date range across all projects.

    Args:
        start_date: Start of the range.
        end_date: End of the range.

    Returns:
        Dictionary mapping project name to list of completed tasks.
    """
    results: dict[str, list[dict[str, Any]]] = {}

    for name, project_path, is_folder in _iter_all_projects():
        if not is_folder:
            continue

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


async def _collect_git_commits_in_range(
    repo_path: Path, start_date: datetime, end_date: datetime
) -> list[str]:
    """Collect git commits within a date range.

    Args:
        repo_path: Path to the repository.
        start_date: Start of the range.
        end_date: End of the range.

    Returns:
        List of commit lines (hash + message).
    """
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    log = await _run_git_command(
        repo_path,
        ["log", f"--since={start_str}", f"--until={end_str}", "--oneline"],
    )

    return log.split("\n") if log else []


async def _generate_reflection_questions(
    completed_tasks: dict[str, list[dict[str, Any]]],
    commits_summary: dict[str, list[str]],
) -> str:
    """Use AI to generate reflection questions based on completed work.

    Args:
        completed_tasks: Completed tasks by project.
        commits_summary: Git commits by project.

    Returns:
        AI-generated reflection questions in Traditional Chinese.
    """
    # Build summary for AI
    summary_parts = []
    for project, tasks in completed_tasks.items():
        task_texts = [t["text"] for t in tasks]
        summary_parts.append(f"**{project}** 完成任務: {', '.join(task_texts)}")

    for project, commits in commits_summary.items():
        if commits:
            summary_parts.append(f"**{project}** commits: {len(commits)} 筆")

    if not summary_parts:
        return "- 本週沒有完成的任務，下週有什麼想要達成的目標？"

    prompt = f"""根據以下本週完成的工作，生成 3-5 個反思問題。問題應該幫助使用者：
1. 回顧本週的成就
2. 識別學習和成長
3. 思考下週的優先事項

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


@tool(
    name="weekly_review",
    description="生成週回顧報告。統計本週完成的任務、git commits，並生成 AI 反思問題。輸出到 data/reviews/weekly/YYYY-Www.md。",
    input_schema=WeeklyReviewInput.model_json_schema(),
)
async def weekly_review(args: dict[str, Any]) -> dict[str, Any]:
    """Generate weekly review report.

    統計本週完成的任務、各專案 git commits，
    並使用 AI 生成反思問題。

    Args:
        args: Dictionary containing optional 'week' (format: 2026-W03).

    Returns:
        Tool response with review summary and file path.
    """
    try:
        validated = WeeklyReviewInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    # Determine week
    if validated.week:
        week_str = validated.week
    else:
        today = datetime.now()
        week_str = today.strftime("%Y-W%W")

    # Get week range
    try:
        start_date, end_date = _get_week_range(week_str)
    except ValueError:
        return {
            "content": [
                {"type": "text", "text": f"無效的週次格式：{week_str}，請使用 YYYY-Www 格式"}
            ],
            "is_error": True,
        }

    # Collect completed tasks
    completed_tasks = await _collect_completed_tasks_in_range(start_date, end_date)

    # Collect git commits for each project
    commits_summary: dict[str, list[str]] = {}
    for name, project_path, is_folder in _iter_all_projects():
        post = frontmatter.load(project_path)
        repo_path_str = post.get("repo", "")
        if repo_path_str:
            repo_path = Path(repo_path_str).expanduser()
            if repo_path.exists():
                commits = await _collect_git_commits_in_range(repo_path, start_date, end_date)
                if commits:
                    commits_summary[name] = commits

    # Generate reflection questions
    reflection = await _generate_reflection_questions(completed_tasks, commits_summary)

    # Build review content
    lines = [
        f"# 週回顧 {week_str}",
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
            for commit in commits[:10]:  # Show first 10
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

    # Save to file
    reviews_dir = _get_reviews_dir() / "weekly"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_file = reviews_dir / f"{week_str}.md"
    review_content = "\n".join(lines)
    review_file.write_text(review_content, encoding="utf-8")

    # Summary for response
    total_tasks = sum(len(tasks) for tasks in completed_tasks.values())
    total_commits = sum(len(commits) for commits in commits_summary.values())

    return {
        "content": [
            {
                "type": "text",
                "text": f"""## 週回顧 {week_str} 已生成

**統計**:
- 完成任務: {total_tasks} 項
- Git commits: {total_commits} 筆
- 涵蓋專案: {len(completed_tasks) + len(commits_summary)} 個

**檔案**: `{review_file}`

{reflection}""",
            }
        ],
    }


@tool(
    name="monthly_review",
    description="生成月回顧報告。統計本月專案進度、成就清單、學習紀錄。輸出到 data/reviews/monthly/YYYY-MM.md。",
    input_schema=MonthlyReviewInput.model_json_schema(),
)
async def monthly_review(args: dict[str, Any]) -> dict[str, Any]:
    """Generate monthly review report.

    統計本月專案進度總覽、月度成就清單、學習與成長紀錄。

    Args:
        args: Dictionary containing optional 'month' (format: 2026-01).

    Returns:
        Tool response with review summary and file path.
    """
    try:
        validated = MonthlyReviewInput(**args)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"輸入驗證失敗：{e}"}],
            "is_error": True,
        }

    # Determine month
    if validated.month:
        month_str = validated.month
    else:
        today = datetime.now()
        month_str = today.strftime("%Y-%m")

    # Get month range
    try:
        start_date, end_date = _get_month_range(month_str)
    except ValueError:
        return {
            "content": [
                {"type": "text", "text": f"無效的月份格式：{month_str}，請使用 YYYY-MM 格式"}
            ],
            "is_error": True,
        }

    # Collect completed tasks
    completed_tasks = await _collect_completed_tasks_in_range(start_date, end_date)

    # Collect project progress
    project_progress: list[dict[str, Any]] = []
    commits_summary: dict[str, list[str]] = {}

    for name, project_path, is_folder in _iter_all_projects():
        post = frontmatter.load(project_path)
        task_counts = _count_tasks(project_path)

        project_info = {
            "name": post.get("name", name),
            "status": post.get("status", "unknown"),
            "progress": post.get("progress", _calculate_progress(project_path)),
            "tasks": task_counts,
        }
        project_progress.append(project_info)

        # Collect git commits
        repo_path_str = post.get("repo", "")
        if repo_path_str:
            repo_path = Path(repo_path_str).expanduser()
            if repo_path.exists():
                commits = await _collect_git_commits_in_range(repo_path, start_date, end_date)
                if commits:
                    commits_summary[name] = commits

    # Build review content
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

    # Save to file
    reviews_dir = _get_reviews_dir() / "monthly"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_file = reviews_dir / f"{month_str}.md"
    review_content = "\n".join(lines)
    review_file.write_text(review_content, encoding="utf-8")

    # Summary for response
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


# 匯出所有工具，方便 agent.py 使用
all_tools = [
    list_projects,
    show_project,
    get_today_tasks,
    sync_project,
    weekly_review,
    monthly_review,
]

# 保留但不預設啟用的工具（可由 agent 按需加入）
optional_tools = [
    update_project_status,
    update_project_progress,
]
