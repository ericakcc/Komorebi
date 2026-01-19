"""Daily planning tools for Komorebi.

精簡版每日規劃工具：
- plan_today: 建立今日工作計畫
- get_today: 讀取今日計畫
- log_event: 記錄重要事件

注意：end_of_day 已整合到 project.py 的 generate_review(period="day")
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import frontmatter
from claude_agent_sdk import tool

# 資料目錄，由 agent 設定
_data_dir: Path = Path("data")


def set_data_dir(path: Path) -> None:
    """Set the data directory for planning tools.

    Args:
        path: Path to the data directory containing daily/.
    """
    global _data_dir
    _data_dir = path


def _get_daily_dir() -> Path:
    """Get the daily notes directory path."""
    return _data_dir / "daily"


def _get_projects_dir() -> Path:
    """Get the projects directory path."""
    return _data_dir / "projects"


def _get_today_file() -> Path:
    """Get today's daily note file path."""
    today = datetime.now().strftime("%Y-%m-%d")
    return _get_daily_dir() / f"{today}.md"


def _get_weekday_name(date: datetime) -> str:
    """Get Chinese weekday name.

    Args:
        date: The datetime object.

    Returns:
        Chinese weekday character (一 to 日).
    """
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return weekdays[date.weekday()]


@tool(
    name="plan_today",
    description="建立今日工作計畫。結合專案狀態，識別最重要的 Highlight，產出時間分配建議。",
    input_schema={
        "highlight": str,
        "tasks": list,
    },
)
async def plan_today(args: dict[str, Any]) -> dict[str, Any]:
    """Create today's work plan.

    Args:
        args: Dictionary containing:
            - highlight: 今日最重要的一件事 (必填)
            - tasks: 預計任務列表 (選填)

    Returns:
        Tool response with created plan summary.
    """
    highlight = args.get("highlight", "")
    tasks = args.get("tasks", [])

    if not highlight:
        return {
            "content": [{"type": "text", "text": "請提供今日的 Highlight（最重要的一件事）。"}],
            "is_error": True,
        }

    daily_dir = _get_daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)

    today_file = _get_today_file()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    weekday = _get_weekday_name(now)

    if today_file.exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"今日計畫已存在：{today_file}\n使用 get_today 查看，或手動刪除後重新建立。",
                }
            ],
            "is_error": True,
        }

    # 讀取 active 專案（只支援 folder mode）
    projects_dir = _get_projects_dir()
    active_projects: list[dict[str, Any]] = []
    if projects_dir.exists():
        for folder in projects_dir.iterdir():
            if folder.is_dir():
                project_md = folder / "project.md"
                if project_md.exists():
                    try:
                        post = frontmatter.load(project_md)
                        if post.get("status") == "active":
                            active_projects.append(
                                {
                                    "name": post.get("name", folder.name),
                                    "priority": post.get("priority", 999),
                                }
                            )
                    except Exception:
                        pass
        active_projects.sort(key=lambda p: p["priority"])

    # 建立任務清單 (Markdown)
    task_lines: list[str] = []
    for task in tasks:
        task_lines.append(f"- [ ] {task}")
    if not task_lines:
        task_lines.append("- [ ] (待填寫)")

    # 建立專案進度區塊
    project_lines: list[str] = []
    for proj in active_projects:
        project_lines.append(f"### {proj['name']}")
        project_lines.append("- 狀態: active")
        project_lines.append("- 預計: (待填寫)")
        project_lines.append("")

    # 查詢今日行程 (如果 calendar 已設定)
    calendar_section = "(行事曆未設定)"
    try:
        from . import calendar as cal

        events_result = await cal.list_events.handler({"date": date_str})
        if not events_result.get("is_error"):
            calendar_section = events_result["content"][0]["text"]
    except Exception:
        pass

    # 組合完整內容
    content = f"""---
date: {date_str}
highlight: "{highlight}"
created_at: "{now.isoformat()}"
updated_at: "{now.isoformat()}"
---

# {date_str} ({weekday})

## 今日行程
{calendar_section}

## Highlight
{highlight}

## 今日計畫
{chr(10).join(task_lines)}

## 專案進度
{chr(10).join(project_lines) if project_lines else "(無 active 專案)"}

## 時間建議
- 深度工作: 約 5-6 小時
- 緩衝時間: 約 2 小時 (30%)
- 專注於 Highlight，其他任務為次要

## 日終回顧
(使用 generate_review period=day 來填寫)
"""

    # 寫入檔案
    today_file.write_text(content, encoding="utf-8")

    return {
        "content": [
            {
                "type": "text",
                "text": f"""## 今日計畫已建立

**日期**: {date_str} ({weekday})
**Highlight**: {highlight}
**Active 專案**: {len(active_projects)} 個
**檔案**: {today_file}

記得專注於 Highlight，保持 30% 緩衝時間！""",
            }
        ],
    }


@tool(
    name="get_today",
    description="讀取今日的工作計畫。",
    input_schema={},
)
async def get_today(args: dict[str, Any]) -> dict[str, Any]:
    """Read today's daily note.

    Args:
        args: Empty dictionary (no parameters required).

    Returns:
        Tool response with today's plan content.
    """
    today_file = _get_today_file()

    if not today_file.exists():
        date_str = datetime.now().strftime("%Y-%m-%d")
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"今日 ({date_str}) 尚未建立計畫。使用 plan_today 建立。",
                }
            ],
        }

    content = today_file.read_text(encoding="utf-8")
    return {
        "content": [{"type": "text", "text": content}],
    }


@tool(
    name="log_event",
    description="記錄重要事件或決策到今日筆記。用於記錄里程碑、重要決策、blockers 或洞見。",
    input_schema={
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "enum": ["decision", "milestone", "blocker", "insight"],
                "description": "事件類型：decision（決策）、milestone（里程碑）、blocker（阻礙）、insight（洞見）",
            },
            "summary": {
                "type": "string",
                "description": "事件摘要（簡短描述）",
            },
            "details": {
                "type": "string",
                "description": "詳細內容（可選，補充說明）",
            },
        },
        "required": ["event_type", "summary"],
    },
)
async def log_event(args: dict[str, Any]) -> dict[str, Any]:
    """記錄事件到每日筆記的重要事件區塊。

    Args:
        args: Dictionary containing:
            - event_type: 事件類型 (decision/milestone/blocker/insight)
            - summary: 事件摘要
            - details: 詳細內容（可選）

    Returns:
        Tool response confirming the event was logged.
    """
    event_type = args.get("event_type", "insight")
    summary = args.get("summary", "")
    details = args.get("details", "")

    if not summary:
        return {
            "content": [{"type": "text", "text": "請提供事件摘要。"}],
            "is_error": True,
        }

    # 取得今日筆記
    today = datetime.now()
    daily_dir = _get_daily_dir()
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_file = daily_dir / f"{today.strftime('%Y-%m-%d')}.md"

    # 讀取或建立基本結構
    if daily_file.exists():
        content = daily_file.read_text(encoding="utf-8")
    else:
        # 建立基本的每日筆記（僅包含 frontmatter 和事件區塊）
        content = f"""---
date: {today.strftime("%Y-%m-%d")}
created_at: "{today.isoformat()}"
---

# {today.strftime("%Y-%m-%d")} ({_get_weekday_name(today)})

"""

    # 新增事件區塊（如果不存在）
    if "## 重要事件" not in content:
        content += "\n## 重要事件\n"

    # 格式化事件
    time_str = today.strftime("%H:%M")
    type_emoji = {
        "decision": "**Decision**",
        "milestone": "**Milestone**",
        "blocker": "**Blocker**",
        "insight": "**Insight**",
    }
    event_label = type_emoji.get(event_type, "**Event**")

    event_entry = f"- [{time_str}] {event_label}: {summary}"
    if details:
        event_entry += f"\n  - {details}"
    event_entry += "\n"

    # 插入到事件區塊末尾
    if "## 重要事件\n" in content:
        events_start = content.find("## 重要事件\n") + len("## 重要事件\n")
        rest = content[events_start:]

        next_section = rest.find("\n## ")
        if next_section == -1:
            content = content.rstrip() + "\n" + event_entry
        else:
            insert_pos = events_start + next_section
            content = content[:insert_pos] + event_entry + content[insert_pos:]

    # 寫入檔案
    daily_file.write_text(content, encoding="utf-8")

    return {
        "content": [{"type": "text", "text": f"已記錄 {event_type}：{summary}"}],
    }


# 匯出所有工具（移除 end_of_day，現在使用 generate_review period=day）
all_tools = [plan_today, get_today, log_event]
