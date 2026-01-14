# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 語言偏好

- **回答**：繁體中文
- **代碼/Commit**：英文

## 常用指令

```bash
# 安裝依賴
uv sync

# 執行 CLI
uv run komorebi
uv run komorebi -m haiku      # 用便宜的 haiku 模型
uv run komorebi --budget 0.5  # 設定預算上限

# Lint 和格式化
uv run ruff check . --fix && uv run ruff format .

# 執行測試
uv run pytest tests/ -v
```

## 架構概覽

這是一個基於 `claude-agent-sdk` 的個人助理 Agent，核心架構：

```
KomorebiAgent (agent.py)
    │
    ├── ClaudeSDKClient      # 多輪對話管理
    │
    ├── MCP Server           # 自訂工具容器
    │   └── project tools    # list_projects, show_project, update_project_status
    │
    └── UsageStats           # API 消耗追蹤
```

### 工具定義模式

使用 `@tool` decorator 定義工具，透過 `create_sdk_mcp_server()` 註冊：

```python
# tools/project.py
@tool(name="tool_name", description="...", input_schema={"param": str})
async def my_tool(args: dict) -> dict:
    return {"content": [{"type": "text", "text": "result"}]}

# agent.py
server = create_sdk_mcp_server(name="project", version="1.0.0", tools=all_tools)
options = ClaudeAgentOptions(
    mcp_servers={"project": server},
    allowed_tools=["mcp__project__tool_name"],  # 格式：mcp__<server>__<tool>
)
```

### 資料儲存

專案資料使用 Markdown + YAML frontmatter：
- `data/projects/*.md` - 專案追蹤檔案
- `data/daily/*.md` - 每日筆記（開發中）
- `prompts/system.md` - Agent 的 system prompt
- `config/settings.yaml` - 設定檔

## 開發注意事項

- 只用 `uv`，不用 `pip`
- 所有函數需要 type hints
- Docstrings 用 Google style
- 工具函數必須是 `async def`
- 工具回傳格式：`{"content": [{"type": "text", "text": "..."}], "is_error": bool}`
