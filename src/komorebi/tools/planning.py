"""Daily planning tools for Komorebi.

提供每日規劃和回顧功能：
- plan_today: 結合專案狀態產出今日計畫
- get_today: 讀取今日的規劃筆記
- end_of_day: 掃描 git commits 更新進度

測試方式：
    @tool decorator 返回 SdkMcpTool 對象，可通過 .handler 屬性調用底層函數：
    >>> result = await planning.plan_today.handler({"highlight": "Test"})
"""

import subprocess
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


def _get_today_commits(repo_path: Path) -> list[str]:
    """Get today's git commits from a repository.

    Args:
        repo_path: Path to the git repository.

    Returns:
        List of commit messages (short format).
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--since=00:00",
                "--format=%s (%h)",
                "--no-merges",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return []


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

    工作流程：
    1. 讀取 data/projects/*.md 取得所有 active 專案
    2. 建立 data/daily/YYYY-MM-DD.md
    3. 填入 highlight 和任務清單
    4. 預留 30% 緩衝時間建議

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

    # 檢查檔案是否已存在
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

    # 讀取 active 專案
    projects_dir = _get_projects_dir()
    active_projects: list[dict[str, Any]] = []
    if projects_dir.exists():
        for md_file in projects_dir.glob("*.md"):
            try:
                post = frontmatter.load(md_file)
                if post.get("status") == "active":
                    active_projects.append(
                        {
                            "name": post.get("name", md_file.stem),
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

    # 組合完整內容
    content = f"""---
date: {date_str}
highlight: "{highlight}"
created_at: "{now.isoformat()}"
updated_at: "{now.isoformat()}"
---

# {date_str} ({weekday})

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
(待今日結束時填寫)
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
    name="end_of_day",
    description="結束今日工作。掃描 git commits 更新進度，產出日終回顧。",
    input_schema={
        "notes": str,
    },
)
async def end_of_day(args: dict[str, Any]) -> dict[str, Any]:
    """End of day review and git commit scanning.

    工作流程：
    1. 讀取 projects/*.md 中的專案路徑
    2. 對每個專案執行 git log --since="today 00:00"
    3. 彙整 commits 到今日筆記
    4. 更新 updated_at timestamp

    Args:
        args: Dictionary containing:
            - notes: 日終筆記 (選填)

    Returns:
        Tool response with end-of-day summary.
    """
    notes = args.get("notes", "")
    today_file = _get_today_file()

    if not today_file.exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": "今日尚未建立計畫。請先使用 plan_today。",
                }
            ],
            "is_error": True,
        }

    # 讀取今日筆記
    post = frontmatter.load(today_file)
    now = datetime.now()

    # 掃描 git commits
    commits_by_project: dict[str, list[str]] = {}

    # 從專案檔案讀取 repo 路徑
    projects_dir = _get_projects_dir()
    if projects_dir.exists():
        for md_file in projects_dir.glob("*.md"):
            try:
                proj_post = frontmatter.load(md_file)
                repo_path = proj_post.get("repo", "")
                proj_name = proj_post.get("name", md_file.stem)

                if repo_path:
                    # 展開 ~ 路徑
                    expanded_path = Path(repo_path).expanduser()
                    if expanded_path.exists():
                        commits = _get_today_commits(expanded_path)
                        if commits:
                            commits_by_project[proj_name] = commits
            except Exception:
                pass

    # 格式化 commits
    commit_lines: list[str] = []
    for proj_name, commits in commits_by_project.items():
        for commit in commits:
            commit_lines.append(f"- {proj_name}: {commit}")

    if not commit_lines:
        commit_lines.append("- (今日無 commits)")

    # 建立日終回顧區塊
    review_section = f"""## 日終回顧
### Git Commits
{chr(10).join(commit_lines)}

### 筆記
{notes if notes else "(無)"}

### 更新時間
{now.strftime("%H:%M")}
"""

    # 更新 frontmatter
    post["updated_at"] = now.isoformat()

    # 讀取原始內容，替換日終回顧區塊
    content = post.content
    if "## 日終回顧" in content:
        # 找到並替換
        parts = content.split("## 日終回顧")
        content = parts[0] + review_section
    else:
        content = content + "\n" + review_section

    post.content = content

    # 寫回檔案
    with open(today_file, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    total_commits = sum(len(c) for c in commits_by_project.values())

    return {
        "content": [
            {
                "type": "text",
                "text": f"""## 日終回顧完成

**專案 commits**: {len(commits_by_project)} 個專案
**總 commits**: {total_commits} 筆
**檔案已更新**: {today_file}

{chr(10).join(commit_lines)}

辛苦了，好好休息！""",
            }
        ],
    }


# 匯出所有工具，方便 agent.py 使用
all_tools = [plan_today, get_today, end_of_day]
