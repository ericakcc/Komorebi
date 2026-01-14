---
name: Komorebi
status: active
priority: 1
started: 2026-01-14
repo: ~/Komorebi
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

### ⏳ 階段四：每日規劃 (MVP-3)
- [ ] tools/planning.py
- [ ] data/daily/*.md 模板
- [ ] plan_today, end_of_day 工具

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

## 進度日誌

### 2026-01-14
- 專案初始化，建立完整資料夾結構
- 完成階段一至三
- 實作專案管理工具 (list/show/update)
- 驗證多輪對話和工具呼叫功能
