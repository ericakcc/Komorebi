"""Project management tools for Komorebi.

學習重點：
- @tool decorator 定義工具的三個參數：name, description, input_schema
- 工具函數必須是 async def
- 回傳格式：{"content": [{"type": "text", "text": "..."}]}
- 錯誤時加上 "is_error": True

這些工具用於讀寫 data/projects/*.md 檔案。
"""

from pathlib import Path
from typing import Any

import frontmatter
from claude_agent_sdk import tool

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


# 匯出所有工具，方便 agent.py 使用
all_tools = [list_projects, show_project, update_project_status]
