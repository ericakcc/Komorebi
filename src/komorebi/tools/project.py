"""Project management tools for Komorebi.

學習重點：
- @tool decorator 定義工具的三個參數：name, description, input_schema
- 工具函數必須是 async def
- 回傳格式：{"content": [{"type": "text", "text": "..."}]}
- 錯誤時加上 "is_error": True

這些工具用於讀寫 data/projects/*.md 檔案。
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter
from claude_agent_sdk import ClaudeAgentOptions, query, tool
from claude_agent_sdk.types import ResultMessage

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
        except Exception as e:
            # 跳過無法解析的檔案，但記錄警告
            projects.append(
                {
                    "name": md_file.stem,
                    "status": f"error: {e}",
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
    input_schema={"name": str},  # 參數：專案名稱
)
async def show_project(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a specific project.

    讀取並回傳完整的專案 markdown 檔案內容。

    Args:
        args: Dictionary containing 'name' - the project name (case-insensitive).

    Returns:
        Tool response with project details.
    """
    name = args.get("name", "")
    if not name:
        return {
            "content": [{"type": "text", "text": "請提供專案名稱。"}],
            "is_error": True,
        }

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
    input_schema={
        "name": str,
        "status": str,  # active, paused, completed, archived
    },
)
async def update_project_status(args: dict[str, Any]) -> dict[str, Any]:
    """Update the status of a project.

    修改專案 markdown 檔案的 frontmatter 中的 status 欄位。

    Args:
        args: Dictionary containing 'name' and 'status'.

    Returns:
        Tool response confirming the update.
    """
    name = args.get("name", "")
    new_status = args.get("status", "")

    valid_statuses = ["active", "paused", "completed", "archived"]
    if new_status not in valid_statuses:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"無效的狀態：{new_status}\n有效狀態：{', '.join(valid_statuses)}",
                }
            ],
            "is_error": True,
        }

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

        with open(project_file, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"已更新 **{name}** 狀態：{old_status} → {new_status}",
                }
            ],
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"更新失敗：{e}"}],
            "is_error": True,
        }


# ============================================================================
# Progress Analysis Tool
# ============================================================================


def _run_git_command(repo_path: Path, args: list[str]) -> str:
    """Run a git command and return output.

    Args:
        repo_path: Path to the git repository.
        args: Git command arguments.

    Returns:
        Command output or empty string on error.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def _collect_git_info(repo_path: Path, days: int = 1) -> dict[str, str]:
    """Collect git log and diff information.

    Args:
        repo_path: Path to the git repository.
        days: Number of days to look back.

    Returns:
        Dictionary with log, diff, and changed_files.
    """
    return {
        "log": _run_git_command(repo_path, ["log", f"--since={days} days ago", "--oneline"]),
        "diff": _run_git_command(repo_path, ["diff", f"HEAD~{days}", "--stat"]),
        "diff_content": _run_git_command(repo_path, ["diff", f"HEAD~{days}"]),
        "changed_files": _run_git_command(repo_path, ["diff", "--name-only", f"HEAD~{days}"]),
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

    with open(project_file, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


@tool(
    name="update_project_progress",
    description="用 AI 分析專案的 git 變更，自動撰寫進度日誌。會研究 commits 和程式碼變更後生成摘要。",
    input_schema={
        "name": str,
        "days": int,
    },
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
    name = args.get("name", "")
    days = args.get("days", 1)

    if not name:
        return {
            "content": [{"type": "text", "text": "請提供專案名稱。"}],
            "is_error": True,
        }

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
    git_info = _collect_git_info(repo_path, days)

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


# 匯出所有工具，方便 agent.py 使用
all_tools = [list_projects, show_project, update_project_status, update_project_progress]
