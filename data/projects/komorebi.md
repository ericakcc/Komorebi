---
name: Komorebi
priority: 1
repo: ~/Komorebi
started: 2026-01-14
status: active
---

# Komorebi

## 目標
基於 Claude Agent SDK 的個人執行助理，提供專案追蹤、每日規劃、行事曆整合功能。

## 技術棧
- Language: Python 3.12
- Framework: claude-agent-sdk 0.1.19
- CLI: click + rich
- Data: Markdown + YAML
- Package: uv

## 開發階段

### ✅ 階段一：Hello World (MVP-0)
- [x] 專案初始化 (uv init, pyproject.toml)
- [x] 資料夾結構建立
- [x] 驗證 SDK 連線 (query())

### ✅ 階段二：多輪對話 (MVP-1)
- [x] agent.py - ClaudeSDKClient 封裝
- [x] main.py - CLI REPL 介面
- [x] 多輪對話上下文測試

### ✅ 階段三：自訂工具 (MVP-2)
- [x] tools/project.py - @tool decorator
- [x] create_sdk_mcp_server() 整合
- [x] list_projects, show_project, update_project_status

### ✅ 階段四：每日規劃 (MVP-3)
- [x] tools/planning.py - plan_today, get_today, end_of_day
- [x] data/daily/*.md 格式設計
- [x] 單元測試 (16 tests, 使用 .handler 模式)

### ⏳ 階段五：行事曆整合 (MVP-4)
- [ ] tools/calendar.py
- [ ] gcalcli 整合
- [ ] list_events, add_event 工具

### ⏳ 階段六：Hooks (MVP-5)
- [ ] PreToolUse hook 實作
- [ ] 危險操作確認機制
- [ ] 操作日誌記錄

## Blockers
- (無)

## 學習筆記

### SDK 核心概念
| 概念 | 用途 |
|------|------|
| `query()` | 單次無狀態查詢 |
| `ClaudeSDKClient` | 多輪對話管理 |
| `@tool` | 定義自訂工具 |
| `create_sdk_mcp_server()` | 建立 MCP server |
| `mcp__<server>__<tool>` | 工具命名規則 |

### @tool 測試方式
`@tool` decorator 返回 `SdkMcpTool` 對象，不是函數。測試時使用 `.handler` 屬性：
```python
# ❌ 錯誤：TypeError: 'SdkMcpTool' object is not callable
result = await planning.plan_today(args)

# ✅ 正確：通過 .handler 調用底層函數
result = await planning.plan_today.handler(args)
```

## 進度日誌

### 2026-01-15
- **MVP-3 每日規劃功能已完成**：實作 `plan_today`、`get_today`、`end_of_day` 三個工具，並建立 `data/daily/*.md` 格式設計，16 個單元測試全數通過

- **@tool decorator 測試模式確立**：研究並採用 `.handler` 屬性調用方式進行單元測試，解決 `SdkMcpTool` 對象不可直接調用的問題

- **專案管理工具持續擴充**：新增 `update_project_progress` 工具，`tools/project.py` 大幅擴充 275 行程式碼（+312/-37）

- **開發環境優化**：新增 pytest、pytest-asyncio、ruff 等開發依賴，並對 `main.py` 和 `project.py` 套用 ruff 格式化

- **文件與指引完善**：新增 `CLAUDE.md` Claude Code 使用指引、SDK 測試腳本，並在專案文件中記錄 @tool 測試最佳實踐

### 2026-01-15
- 完成 MVP-3 每日規劃工具
- 實作 plan_today, get_today, end_of_day 三個工具
- 研究 @tool decorator 測試模式，採用 .handler 方式
- 撰寫 16 個單元測試，100% 通過
- 新增 dev dependencies (pytest, pytest-asyncio, ruff)

### 2026-01-14
- 專案初始化，建立完整資料夾結構
- 完成階段一至三
- 實作專案管理工具 (list/show/update)
- 驗證多輪對話和工具呼叫功能