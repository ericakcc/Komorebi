"""Memory tools for semantic memory management.

提供語意記憶功能：
- get_memory: 讀取用戶偏好和專案事實
- remember: 記住重要資訊

資料儲存在 data/memory/facts.yaml。

測試方式：
    >>> memory.set_memory_file(Path("data/memory/facts.yaml"))
    >>> result = await memory.remember.handler({"category": "user", "key": "style", "value": "簡潔直接"})
"""

from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import tool

# 記憶檔案路徑，由 agent 設定
_MEMORY_FILE: Path | None = None


def set_memory_file(path: Path) -> None:
    """Set the memory file path.

    Args:
        path: Path to the memory YAML file (e.g., data/memory/facts.yaml)
    """
    global _MEMORY_FILE
    _MEMORY_FILE = path


def _load_memory() -> dict[str, Any]:
    """Load memory from YAML file.

    Returns:
        Memory dictionary with user and projects sections.
    """
    if not _MEMORY_FILE or not _MEMORY_FILE.exists():
        return {"user": {}, "projects": {}}

    try:
        content = _MEMORY_FILE.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return data if isinstance(data, dict) else {"user": {}, "projects": {}}
    except (yaml.YAMLError, OSError):
        return {"user": {}, "projects": {}}


def _save_memory(data: dict[str, Any]) -> None:
    """Save memory to YAML file.

    Args:
        data: Memory dictionary to save.
    """
    if not _MEMORY_FILE:
        return

    _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MEMORY_FILE.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


@tool(
    name="get_memory",
    description="讀取記憶中的用戶偏好或專案事實。用於回顧 Eric 的偏好設定或專案相關資訊。",
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["user", "projects"],
                "description": "記憶類別：user（用戶偏好）或 projects（專案事實）",
            },
            "key": {
                "type": "string",
                "description": "可選，特定的 key（如專案名稱或偏好項目）。不指定則返回整個類別。",
            },
        },
    },
)
async def get_memory(args: dict[str, Any]) -> dict[str, Any]:
    """讀取語意記憶。

    Args:
        args: Dictionary containing:
            - category: 記憶類別 (user/projects)，預設 user
            - key: 特定 key（可選）

    Returns:
        Tool response with memory content in YAML format.
    """
    if not _MEMORY_FILE:
        return {
            "content": [{"type": "text", "text": "記憶系統尚未設定。"}],
            "is_error": True,
        }

    data = _load_memory()
    category = args.get("category", "user")
    key = args.get("key")

    result = data.get(category, {})
    if key:
        result = result.get(key, {})

    if not result:
        if key:
            return {
                "content": [{"type": "text", "text": f"找不到記憶：{category}/{key}"}],
            }
        return {
            "content": [{"type": "text", "text": f"類別 {category} 中沒有記憶。"}],
        }

    formatted = yaml.dump(result, allow_unicode=True, default_flow_style=False)
    return {
        "content": [
            {
                "type": "text",
                "text": f"## {category}"
                + (f"/{key}" if key else "")
                + "\n\n```yaml\n"
                + formatted
                + "```",
            }
        ],
    }


@tool(
    name="remember",
    description="記住重要的用戶偏好或專案事實。當 Eric 提到偏好（如「我喜歡...」）或重要專案資訊時使用。",
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["user", "projects"],
                "description": "類別：user（用戶偏好）或 projects（專案事實）",
            },
            "key": {
                "type": "string",
                "description": "key 名稱（如 work_style, coding_preference, 或專案名稱）",
            },
            "value": {
                "type": "string",
                "description": "要記住的內容",
            },
        },
        "required": ["category", "key", "value"],
    },
)
async def remember(args: dict[str, Any]) -> dict[str, Any]:
    """儲存到語意記憶。

    Args:
        args: Dictionary containing:
            - category: 類別 (user/projects)
            - key: key 名稱
            - value: 要記住的內容

    Returns:
        Tool response confirming the memory was saved.
    """
    if not _MEMORY_FILE:
        return {
            "content": [{"type": "text", "text": "記憶系統尚未設定。"}],
            "is_error": True,
        }

    category = args.get("category", "user")
    key = args.get("key", "")
    value = args.get("value", "")

    if not key or not value:
        return {
            "content": [{"type": "text", "text": "請提供 key 和 value。"}],
            "is_error": True,
        }

    # 載入現有記憶
    data = _load_memory()

    # 確保類別存在
    if category not in data:
        data[category] = {}

    # 更新記憶
    data[category][key] = value

    # 儲存
    _save_memory(data)

    return {
        "content": [{"type": "text", "text": f"已記住：[{category}] {key} = {value}"}],
    }


# 匯出所有工具，方便 agent.py 使用
all_tools = [get_memory, remember]
