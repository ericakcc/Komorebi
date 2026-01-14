# Komorebi

> 木漏れ日 - 陽光穿過樹葉間隙灑落的光影

基於 [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) 的個人執行助理。

## 功能

- **專案追蹤** - 管理專案狀態、進度、blockers
- **每日規劃** - 結合專案狀態產生今日計畫（開發中）
- **行事曆整合** - Google Calendar 整合（開發中）
- **消耗監控** - 即時追蹤 API token 使用量和費用

---

## 快速開始

### 安裝

```bash
# 確保有 uv 套件管理器
# macOS: brew install uv
# 其他: https://docs.astral.sh/uv/getting-started/installation/

# Clone 並安裝
git clone https://github.com/your-username/komorebi.git
cd komorebi
uv sync
```

### 設定 API Key

```bash
# 設定 Anthropic API Key
export ANTHROPIC_API_KEY="your-api-key"

# 或加到 ~/.zshrc / ~/.bashrc
echo 'export ANTHROPIC_API_KEY="your-api-key"' >> ~/.zshrc
```

### 啟動

```bash
uv run komorebi
```

---

## 使用教學

### CLI 選項

```bash
# 基本使用（預設 Sonnet 模型）
uv run komorebi

# 選擇模型
uv run komorebi -m haiku    # 最快最便宜
uv run komorebi -m sonnet   # 平衡（推薦）
uv run komorebi -m opus     # 最強

# 設定預算上限
uv run komorebi --budget 0.5   # 上限 $0.5

# 指定設定檔
uv run komorebi --config path/to/settings.yaml

# 查看所有選項
uv run komorebi --help
```

### 互動指令

在 CLI 中可使用以下指令：

| 指令 | 說明 |
|------|------|
| `/usage` | 查看當前 session 的 API 消耗 |
| `/help` | 顯示可用指令 |
| `exit` | 離開（會顯示總消耗） |

### 使用範例

```
$ uv run komorebi -m sonnet

╭─────────────────────────╮
│ Komorebi v0.1.0         │
│ 你的個人執行助理         │
╰─────────────────────────╯
模型: sonnet | 輸入 /usage 查看消耗 | exit 離開

You: 列出我的專案
Komorebi: [使用工具: mcp__project__list_projects]
## 你目前有 2 個專案：
- 🟢 LayerWise (active)
- 🟢 Komorebi (active)

You: 顯示 Komorebi 的詳細資訊
Komorebi: [使用工具: mcp__project__show_project]
# Komorebi
## 目標
基於 Claude Agent SDK 的個人執行助理...

You: /usage
💰 $0.0523 | 📥 1,234 in | 📤 567 out | 🔄 2 turns

You: exit
💰 $0.0523 | 📥 1,234 in | 📤 567 out | 🔄 2 turns
再見！
```

---

## 模型與定價

| 模型 | API ID | 定價 (per MTok) | 特點 |
|------|--------|-----------------|------|
| **Haiku 4.5** | `claude-haiku-4-5-20251001` | $1 in / $5 out | 最快、最便宜 |
| **Sonnet 4.5** | `claude-sonnet-4-5-20250929` | $3 in / $15 out | 平衡（推薦） |
| **Opus 4.5** | `claude-opus-4-5-20251101` | $5 in / $25 out | 最強推理能力 |

> 💡 **建議**：日常使用選 Sonnet，簡單查詢用 Haiku 省錢

---

## 專案管理

### 新增專案

在 `data/projects/` 建立 markdown 檔案：

```markdown
---
name: MyProject
status: active
priority: 1
started: 2026-01-15
repo: ~/projects/my-project
---

# MyProject

## 目標
專案目標描述

## 技術棧
- Language: Python
- Framework: FastAPI

## 當前進度
- [ ] 任務 1
- [ ] 任務 2

## Blockers
- (無)
```

### 可用狀態

| 狀態 | 說明 |
|------|------|
| `active` | 進行中 🟢 |
| `paused` | 暫停 ⏸️ |
| `completed` | 已完成 ✅ |
| `archived` | 已歸檔 📦 |

---

## 設定檔

`config/settings.yaml`:

```yaml
# 專案設定
projects:
  layerwise:
    path: ~/projects/layerwise
    active: true

# 資料目錄
data_dir: ./data

# Google Calendar（開發中）
calendar:
  enabled: true
  default_calendar: primary
```

---

## 開發進度

| 階段 | 狀態 | 說明 |
|------|------|------|
| MVP-0 | ✅ | Hello World - SDK 連線驗證 |
| MVP-1 | ✅ | 多輪對話 - ClaudeSDKClient |
| MVP-2 | ✅ | 自訂工具 - @tool + MCP |
| MVP-3 | ⏳ | 每日規劃 - planning tools |
| MVP-4 | ⏳ | 行事曆 - gcalcli 整合 |
| MVP-5 | ⏳ | Hooks - 安全機制 |

---

## 專案結構

```
Komorebi/
├── pyproject.toml          # 專案配置
├── src/komorebi/
│   ├── __init__.py
│   ├── agent.py            # Agent 核心 (ClaudeSDKClient)
│   ├── main.py             # CLI 進入點
│   ├── config.py           # 設定載入
│   └── tools/
│       ├── __init__.py
│       └── project.py      # 專案管理工具
├── data/
│   ├── projects/           # 專案 Markdown 檔案
│   │   ├── komorebi.md
│   │   └── layerwise.md
│   └── daily/              # 每日筆記（開發中）
├── prompts/
│   └── system.md           # System Prompt
├── config/
│   └── settings.yaml       # 設定檔
└── tests/                  # 測試（開發中）
```

---

## 技術棧

| 項目 | 選擇 |
|------|------|
| Agent 框架 | [claude-agent-sdk](https://pypi.org/project/claude-agent-sdk/) 0.1.19 |
| 語言 | Python 3.12 |
| CLI | click + rich |
| 資料儲存 | Markdown + YAML |
| 套件管理 | uv |

---

## SDK 學習筆記

這個專案同時也是學習 Claude Agent SDK 的實作練習：

### 核心概念

| 概念 | 檔案 | 說明 |
|------|------|------|
| `query()` | `hello.py` | 單次無狀態查詢 |
| `ClaudeSDKClient` | `agent.py` | 多輪對話，自動管理上下文 |
| `@tool` | `tools/project.py` | 定義自訂工具 |
| `create_sdk_mcp_server()` | `agent.py` | 建立 in-process MCP server |
| `ClaudeAgentOptions` | `agent.py` | 配置選項（model, budget, tools） |

### 程式碼範例

**定義工具**:
```python
from claude_agent_sdk import tool

@tool(
    name="list_projects",
    description="列出所有專案",
    input_schema={},
)
async def list_projects(args: dict) -> dict:
    return {"content": [{"type": "text", "text": "..."}]}
```

**建立 Agent**:
```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, create_sdk_mcp_server

# 建立 MCP Server
server = create_sdk_mcp_server(name="project", version="1.0.0", tools=[list_projects])

# 配置選項
options = ClaudeAgentOptions(
    model="claude-sonnet-4-5-20250929",
    mcp_servers={"project": server},
    allowed_tools=["mcp__project__list_projects"],
)

# 多輪對話
async with ClaudeSDKClient(options) as client:
    await client.query("列出專案")
    async for msg in client.receive_response():
        print(msg)
```

---

## License

MIT
