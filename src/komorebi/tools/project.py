"""Project management tools for Komorebi.

學習重點：
- @tool decorator 定義工具的三個參數：name, description, input_schema
- 工具函數必須是 async def
- 回傳格式：{"content": [{"type": "text", "text": "..."}]}
- 錯誤時加上 "is_error": True
- 使用 Pydantic BaseModel 驗證工具輸入

這些工具用於讀寫 data/projects/*.md 檔案。
"""

import asyncio
import logging
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


@tool(
    name="list_projects",
    description="列出所有專案及其狀態。回傳專案名稱、狀態、優先順序等摘要資訊。",
    input_schema={},  # 無參數
)
async def list_projects(args: dict[str, Any]) -> dict[str, Any]:
    """List all projects from data/projects/*.md files.

    讀取每個 markdown 檔案的 frontmatter 來取得專案資訊。

    Returns:
        Tool response with formatted project list.
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

    for md_file in projects_dir.glob("*.md"):
        try:
            post = frontmatter.load(md_file)
            projects.append(
                {
                    "name": post.get("name", md_file.stem),
                    "status": post.get("status", "unknown"),
                    "priority": post.get("priority", 999),
                    "file": md_file.name,
                }
            )
        except (OSError, IOError) as e:
            logger.warning(f"Failed to read {md_file}: {e}")
            projects.append(
                {
                    "name": md_file.stem,
                    "status": "error: file read failed",
                    "priority": 999,
                    "file": md_file.name,
                }
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse frontmatter in {md_file}: {e}")
            projects.append(
                {
                    "name": md_file.stem,
                    "status": "error: invalid format",
                    "priority": 999,
                    "file": md_file.name,
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

        lines.append(f"- {status_emoji} **{p['name']}** ({p['status']})")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
    }


@tool(
    name="show_project",
    description="顯示單一專案的完整資訊，包含目標、技術棧、進度、blockers 等詳細內容。",
    input_schema=ShowProjectInput.model_json_schema(),
)
async def show_project(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a specific project.

    讀取並回傳完整的專案 markdown 檔案內容。

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

    projects_dir = _get_projects_dir()

    # 嘗試找到匹配的檔案（不分大小寫）
    project_file = None
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() == name.lower():
            project_file = md_file
            break

    if not project_file or not project_file.exists():
        # 列出可用的專案
        available = [f.stem for f in projects_dir.glob("*.md")]
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"找不到專案：{name}\n可用的專案：{', '.join(available) if available else '(無)'}",
                }
            ],
            "is_error": True,
        }

    content = project_file.read_text(encoding="utf-8")
    return {
        "content": [{"type": "text", "text": content}],
    }


@tool(
    name="update_project_status",
    description="更新專案的狀態（active, paused, completed, archived）。",
    input_schema=UpdateStatusInput.model_json_schema(),
)
async def update_project_status(args: dict[str, Any]) -> dict[str, Any]:
    """Update the status of a project.

    修改專案 markdown 檔案的 frontmatter 中的 status 欄位。

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

    projects_dir = _get_projects_dir()

    # 找到檔案
    project_file = None
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() == name.lower():
            project_file = md_file
            break

    if not project_file or not project_file.exists():
        return {
            "content": [{"type": "text", "text": f"找不到專案：{name}"}],
            "is_error": True,
        }

    # 讀取並更新
    try:
        post = frontmatter.load(project_file)
        old_status = post.get("status", "unknown")
        post["status"] = new_status

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

    # 找到專案檔案
    projects_dir = _get_projects_dir()
    project_file = None
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() == name.lower():
            project_file = md_file
            break

    if not project_file:
        available = [f.stem for f in projects_dir.glob("*.md")]
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

    # Find project file
    projects_dir = _get_projects_dir()
    project_file = None
    for md_file in projects_dir.glob("*.md"):
        if md_file.stem.lower() == name.lower():
            project_file = md_file
            break

    if not project_file:
        available = [f.stem for f in projects_dir.glob("*.md")]
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


# 匯出所有工具，方便 agent.py 使用
all_tools = [
    list_projects,
    show_project,
    update_project_status,
    update_project_progress,
    sync_project,
]
