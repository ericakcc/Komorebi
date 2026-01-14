# Personal Agent MVP 規劃

## 專案目標

建立一個 CLI 個人助理 Agent，功能包含：
- 專案進度追蹤
- 每日工作規劃
- Google Calendar 整合

---

## 技術選型

| 項目 | 選擇 |
|------|------|
| Agent 框架 | Anthropic Agent SDK |
| 語言 | Python 3.11+ |
| 套件管理 | uv |
| 資料儲存 | 純 Markdown 檔案 |
| 行事曆 | gcalcli (之後可換 Google Calendar API) |
| 介面 | CLI (互動式) |

---

## 資料夾結構

```
personal-agent/
├── pyproject.toml
├── README.md
├── .python-version
│
├── src/
│   └── personal_agent/
│       ├── __init__.py
│       ├── main.py              # CLI 進入點
│       ├── agent.py             # Agent 定義
│       └── tools/
│           ├── __init__.py
│           ├── project.py       # 專案管理 tools
│           ├── planning.py      # 每日規劃 tools
│           └── calendar.py      # 行事曆 tools
│
├── data/                        # 資料儲存 (gitignore 或分開 repo)
│   ├── projects/
│   │   └── layerwise.md
│   ├── archive/                 # 未來: 舊專案知識庫
│   ├── knowledge/               # 未來: 萃取的知識
│   └── daily/
│       └── 2026-01-14.md
│
├── prompts/
│   └── system.md                # Agent 的 system prompt
│
└── config/
    └── settings.yaml            # 設定檔 (專案路徑等)
```

---

## 核心檔案內容

### pyproject.toml

```toml
[project]
name = "personal-agent"
version = "0.1.0"
description = "Personal AI assistant for project tracking and daily planning"
requires-python = ">=3.11"
dependencies = [
    "anthropic-agent-sdk",
    "rich",           # CLI 美化輸出
    "pyyaml",         # 讀設定檔
    "click",          # CLI 框架
]

[project.scripts]
pa = "personal_agent.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### config/settings.yaml

```yaml
# 專案設定
projects:
  layerwise:
    path: ~/projects/layerwise    # Git repo 路徑，用於掃描 commits
    active: true

# 資料路徑
data_dir: ./data

# Google Calendar
calendar:
  enabled: true
  default_calendar: "primary"
```

### prompts/system.md

```markdown
# Personal Agent System Prompt

你是 Eric 的個人執行助理。

## 你的角色
- 追蹤專案進度
- 規劃每日工作
- 管理行事曆

## 行為準則
1. 簡潔直接，不廢話
2. 主動提出建議，但讓 Eric 做最終決定
3. 使用繁體中文

## Eric 的背景
- Staff AI Engineer @ Softstargames Taiwan
- 管理 6 人 AI 團隊
- 目前專注: LayerWise 專案
- 學習方向: Agent, VLA, World Model, 自動交易

## 專案追蹤規則
- 每個專案記錄: 狀態、進度、技術棧、blockers
- 每日結束時掃描 git commits 更新進度

## 每日規劃規則
- 早上: 結合專案狀態 + 行事曆 → 產出今日計畫
- 識別最重要的 1 件事 (Highlight)
- 保留 30% 緩衝時間
```

### data/projects/layerwise.md (模板)

```markdown
---
name: LayerWise
status: active
priority: 1
started: 2026-01-xx
repo: ~/projects/layerwise
---

# LayerWise

## 目標
[專案目標描述]

## 技術棧
- Language: 
- Framework: 
- AI/ML: 
- Infra: 

## 當前進度
- [ ] [任務 1]
- [ ] [任務 2]
- [ ] [任務 3]

## Blockers
- (無)

## 進度日誌
### 2026-01-14
- 初始化專案追蹤
```

### data/daily/2026-01-14.md (模板)

```markdown
---
date: 2026-01-14
---

# 2026-01-14 週二

## 🎯 今日 Highlight
- [ ] [最重要的一件事]

## 📅 行程
| 時間 | 事項 | 類型 |
|------|------|------|
| 09:00 | ... | work |

## 📋 任務
### 工作
- [ ] 

### 學習
- [ ] 

## 📝 筆記
(今日紀錄)

## ✅ 完成回顧
(晚上填寫)
```

---

## Agent Tools 設計

### tools/project.py

```python
"""專案管理 Tools"""

from pathlib import Path
import yaml

def list_projects(data_dir: Path) -> str:
    """列出所有進行中的專案"""
    projects_dir = data_dir / "projects"
    projects = []
    for f in projects_dir.glob("*.md"):
        # 讀取 frontmatter 取得狀態
        content = f.read_text()
        # 解析並回傳摘要
        projects.append(f.stem)
    return projects

def show_project(name: str, data_dir: Path) -> str:
    """顯示單一專案詳情"""
    project_file = data_dir / "projects" / f"{name}.md"
    if not project_file.exists():
        return f"專案 {name} 不存在"
    return project_file.read_text()

def update_project(name: str, section: str, content: str, data_dir: Path) -> str:
    """更新專案的特定區塊"""
    # 實作更新邏輯
    pass

def scan_git_commits(repo_path: Path, since: str = "yesterday") -> str:
    """掃描 Git commits"""
    import subprocess
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--oneline"],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    return result.stdout
```

### tools/planning.py

```python
"""每日規劃 Tools"""

from datetime import date
from pathlib import Path

def plan_today(data_dir: Path) -> str:
    """
    產生今日計畫
    1. 讀取所有 active 專案的狀態
    2. 讀取今日行事曆
    3. 產生今日計畫
    """
    pass

def get_today_file(data_dir: Path) -> Path:
    """取得今日的 daily note 路徑"""
    today = date.today().isoformat()
    return data_dir / "daily" / f"{today}.md"

def end_of_day(data_dir: Path, settings: dict) -> str:
    """
    每日結束
    1. 掃描各專案的 git commits
    2. 更新專案進度
    3. 產生今日回顧
    """
    pass
```

### tools/calendar.py

```python
"""Google Calendar Tools (使用 gcalcli)"""

import subprocess
from datetime import date

def list_events(target_date: str = None) -> str:
    """列出某天的行程"""
    if target_date is None:
        target_date = date.today().isoformat()
    
    result = subprocess.run(
        ["gcalcli", "agenda", target_date, target_date],
        capture_output=True,
        text=True
    )
    return result.stdout

def add_event(title: str, start: str, end: str, calendar: str = "primary") -> str:
    """新增行事曆事件"""
    result = subprocess.run(
        [
            "gcalcli", "add",
            "--calendar", calendar,
            "--title", title,
            "--when", start,
            "--duration", "60",  # 預設 1 小時
            "--noprompt"
        ],
        capture_output=True,
        text=True
    )
    return "已新增" if result.returncode == 0 else f"失敗: {result.stderr}"
```

### agent.py

```python
"""Agent 定義"""

from anthropic import Anthropic
from pathlib import Path

from .tools import project, planning, calendar

class PersonalAgent:
    def __init__(self, config_path: Path):
        self.client = Anthropic()
        self.config = self._load_config(config_path)
        self.data_dir = Path(self.config["data_dir"])
        self.system_prompt = self._load_system_prompt()
        
        # 定義 tools
        self.tools = [
            {
                "name": "list_projects",
                "description": "列出所有進行中的專案",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "show_project", 
                "description": "顯示單一專案的詳細資訊",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "專案名稱"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "update_project",
                "description": "更新專案進度或狀態",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "section": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["name", "section", "content"]
                }
            },
            {
                "name": "plan_today",
                "description": "產生今日工作計畫",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "list_calendar",
                "description": "列出行事曆事件",
                "input_schema": {
                    "type": "object", 
                    "properties": {
                        "date": {"type": "string", "description": "日期 YYYY-MM-DD"}
                    }
                }
            },
            {
                "name": "add_calendar",
                "description": "新增行事曆事件",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string", "description": "開始時間"},
                        "end": {"type": "string", "description": "結束時間"}
                    },
                    "required": ["title", "start"]
                }
            }
        ]
    
    def _load_config(self, path: Path) -> dict:
        import yaml
        return yaml.safe_load(path.read_text())
    
    def _load_system_prompt(self) -> str:
        prompt_file = Path("prompts/system.md")
        return prompt_file.read_text()
    
    def _execute_tool(self, name: str, input: dict) -> str:
        """執行 tool 並回傳結果"""
        if name == "list_projects":
            return project.list_projects(self.data_dir)
        elif name == "show_project":
            return project.show_project(input["name"], self.data_dir)
        elif name == "update_project":
            return project.update_project(
                input["name"], input["section"], input["content"], self.data_dir
            )
        elif name == "plan_today":
            return planning.plan_today(self.data_dir)
        elif name == "list_calendar":
            return calendar.list_events(input.get("date"))
        elif name == "add_calendar":
            return calendar.add_event(
                input["title"], input["start"], input.get("end", "")
            )
        return "Unknown tool"

    def chat(self, user_message: str, history: list = None) -> str:
        """處理使用者訊息"""
        if history is None:
            history = []
        
        messages = history + [{"role": "user", "content": user_message}]
        
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=self.system_prompt,
            tools=self.tools,
            messages=messages
        )
        
        # 處理 tool use
        while response.stop_reason == "tool_use":
            tool_use = next(b for b in response.content if b.type == "tool_use")
            tool_result = self._execute_tool(tool_use.name, tool_use.input)
            
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": tool_result
                }]
            })
            
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages
            )
        
        # 回傳最終文字回應
        return next(b.text for b in response.content if hasattr(b, "text"))
```

### main.py

```python
"""CLI 進入點"""

import click
from rich.console import Console
from rich.prompt import Prompt
from pathlib import Path

from .agent import PersonalAgent

console = Console()

@click.command()
@click.option("--config", default="config/settings.yaml", help="設定檔路徑")
def cli(config):
    """Personal Agent CLI"""
    console.print("[bold blue]Personal Agent v0.1[/bold blue]")
    console.print("輸入 'exit' 或 'quit' 離開\n")
    
    agent = PersonalAgent(Path(config))
    history = []
    
    while True:
        try:
            user_input = Prompt.ask("[green]You[/green]")
            
            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[dim]再見！[/dim]")
                break
            
            response = agent.chat(user_input, history)
            console.print(f"[blue]Agent[/blue]: {response}\n")
            
            # 更新 history
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            
        except KeyboardInterrupt:
            console.print("\n[dim]再見！[/dim]")
            break

if __name__ == "__main__":
    cli()
```

---

## 開發步驟

### Step 1: 初始化專案
```bash
mkdir personal-agent && cd personal-agent
uv init
uv add anthropic rich pyyaml click
```

### Step 2: 建立資料夾結構
```bash
mkdir -p src/personal_agent/tools
mkdir -p data/{projects,archive,knowledge,daily}
mkdir -p prompts config
```

### Step 3: 建立檔案
依照上面的內容建立各檔案

### Step 4: 設定 gcalcli
```bash
# 安裝
pip install gcalcli

# 授權 (會開瀏覽器)
gcalcli list
```

### Step 5: 測試執行
```bash
uv run pa
```

---

## 使用範例

```
$ pa

Personal Agent v0.1
輸入 'exit' 或 'quit' 離開

You: 列出我的專案
Agent: 目前有 1 個進行中的專案：
- LayerWise (active)

You: 今天該做什麼？
Agent: 讓我看看你的行事曆和專案狀態...
[讀取 LayerWise 進度]
[讀取今日行事曆]

建議今日計畫：
🎯 Highlight: [LayerWise 的下一個重要任務]

09:00-11:00 深度工作: LayerWise
11:00-12:00 [行事曆上的會議]
14:00-16:00 深度工作: LayerWise
16:00-17:00 緩衝

要我建立今日的 daily note 嗎？

You: 幫我加一個明天早上 10 點的會議，主題是 Team Standup
Agent: 已新增行事曆事件：
- Team Standup
- 2026-01-15 10:00

You: exit
再見！
```

---

## 未來擴充 (v0.2+)

- [ ] `archive_project()` - 歸檔舊專案
- [ ] `extract_knowledge()` - 從專案萃取知識
- [ ] `search_knowledge()` - 搜尋知識庫
- [ ] `suggest_reading()` - 建議學習資源
- [ ] 改用 Google Calendar API (取代 gcalcli)
- [ ] 加入 MCP 支援
