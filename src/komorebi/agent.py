"""Komorebi Agent - Personal Assistant powered by Claude Agent SDK.

學習重點：
- ClaudeSDKClient 維護多輪對話的上下文
- 使用 async context manager (async with) 管理連線
- receive_response() 回傳 async generator，yield 各種 Message 類型
- create_sdk_mcp_server() 建立 in-process MCP server
- 工具命名規則：mcp__<server_name>__<tool_name>

與 query() 的差異：
- query(): 單次查詢，無狀態，每次都是新對話
- ClaudeSDKClient: 多輪對話，記住上下文，適合互動式應用
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from rich.console import Console
from rich.prompt import Confirm

from .config import Config, load_config
from .planner import PlanManager
from .session import SessionManager
from .skills import SkillManager, all_tools as skill_tools, set_skill_manager
from .tools import calendar, memory, planning, project

# Komorebi 專案根目錄（由 KomorebiAgent.__init__ 設置）
_komorebi_root: Path | None = None


def set_komorebi_root(root: Path) -> None:
    """設定 Komorebi 專案根目錄。"""
    global _komorebi_root
    _komorebi_root = root


# Console for tool confirmation prompts
_console = Console()

# Logger for audit trail
logger = logging.getLogger(__name__)

# 模組級 PlanManager 引用（用於權限檢查）
_plan_manager: PlanManager | None = None


def set_plan_manager(manager: PlanManager) -> None:
    """設定模組級的 PlanManager 引用。"""
    global _plan_manager
    _plan_manager = manager


# ============================================================================
# Chat Event Types
# ============================================================================


@dataclass
class TextEvent:
    """文字輸出事件"""

    text: str


@dataclass
class ToolStartEvent:
    """工具開始執行事件"""

    tool_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class ToolEndEvent:
    """工具執行完成事件"""

    tool_id: str
    result: str
    is_error: bool


@dataclass
class DoneEvent:
    """對話完成事件"""

    cost_usd: float
    input_tokens: int
    output_tokens: int


ChatEvent = TextEvent | ToolStartEvent | ToolEndEvent | DoneEvent


def format_tool_name(tool_name: str) -> str:
    """格式化工具名稱：mcp__project__list_projects → list_projects"""
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        return parts[-1] if len(parts) >= 3 else tool_name
    return tool_name


# 需要確認的工具（寫入操作）
_CONFIRM_TOOLS = {
    "mcp__project__sync_project",
    "mcp__project__generate_review",
    "mcp__planning__plan_today",
    "mcp__calendar__add_event",
}


async def _check_tool_permission(
    tool_name: str,
    input: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """SDK 層級的權限檢查。

    確保 agent 不會修改其他專案資料夾。
    所有寫入操作只能在 Komorebi 專案內進行。
    在 Plan Mode 下禁止所有寫入工具。

    Args:
        tool_name: 工具名稱
        input: 工具輸入參數
        context: 權限上下文

    Returns:
        允許或拒絕的結果
    """
    # 審計日誌：記錄所有工具調用
    input_summary = {k: str(v)[:100] for k, v in input.items()}
    logger.info(f"Tool call: {tool_name} | Input: {input_summary}")

    # Plan Mode 檢查：禁止寫入工具
    if _plan_manager and _plan_manager.is_active:
        if not _plan_manager.is_tool_allowed(tool_name):
            return PermissionResultDeny(
                behavior="deny",
                message=_plan_manager.get_denial_message(tool_name),
            )

    # MCP 工具：需要確認的工具先詢問用戶
    if tool_name.startswith("mcp__"):
        if tool_name in _CONFIRM_TOOLS:
            # 顯示工具資訊
            tool_display = format_tool_name(tool_name)
            _console.print(f"\n[yellow]要執行 {tool_display} 嗎？[/yellow]")

            # 顯示參數
            for key, value in input.items():
                value_str = str(value)[:80]
                if len(str(value)) > 80:
                    value_str += "..."
                _console.print(f"  [dim]{key}:[/dim] {value_str}")

            # 詢問確認
            if not Confirm.ask("確認執行", default=True):
                return PermissionResultDeny(
                    behavior="deny",
                    message="用戶取消執行",
                )

        return PermissionResultAllow(behavior="allow")

    # Bash 指令檢查
    if tool_name == "Bash":
        cmd = input.get("command", "")

        # 禁止切換目錄到其他專案
        other_project_paths = ["~/LayerWise", "~/projects", "/Users/eric_tsou/LayerWise"]
        if "cd " in cmd:
            for proj in other_project_paths:
                if proj in cmd:
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"禁止切換到其他專案目錄（{proj}）。請使用 sync_project 工具來同步專案資訊。",
                    )

        # 禁止在其他專案執行寫入操作
        write_patterns = ["mkdir", "touch", "rm ", "mv ", "cp ", " > ", " >> "]
        if any(p in cmd for p in write_patterns):
            for proj in other_project_paths:
                if proj in cmd:
                    return PermissionResultDeny(
                        behavior="deny",
                        message=f"禁止在其他專案資料夾（{proj}）執行寫入操作。",
                    )

    # Edit/Write 工具路徑檢查
    if tool_name in ["Edit", "Write"]:
        file_path = input.get("file_path", "")

        # 如果沒有設定根目錄，允許所有操作（避免意外阻擋）
        if not _komorebi_root:
            return PermissionResultAllow(behavior="allow")

        # 只允許編輯 Komorebi 專案內的檔案
        allowed_prefixes = [
            str(_komorebi_root) + "/",
        ]

        path_allowed = any(file_path.startswith(p) for p in allowed_prefixes)
        if not path_allowed:
            return PermissionResultDeny(
                behavior="deny",
                message=f"只允許編輯 Komorebi 專案內的檔案。嘗試編輯：{file_path}",
            )

    # 其他工具（如 Read）允許
    return PermissionResultAllow(behavior="allow")


class UsageStats:
    """追蹤 API 使用量和費用。"""

    def __init__(self) -> None:
        self.total_cost_usd: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.turn_count: int = 0

    def update(self, result: ResultMessage) -> None:
        """從 ResultMessage 更新統計。"""
        self.total_cost_usd += result.total_cost_usd or 0.0
        self.turn_count += result.num_turns or 1
        if result.usage:
            self.total_input_tokens += result.usage.get("input_tokens", 0)
            self.total_output_tokens += result.usage.get("output_tokens", 0)

    def __str__(self) -> str:
        return (
            f"💰 ${self.total_cost_usd:.4f} | "
            f"📥 {self.total_input_tokens:,} in | "
            f"📤 {self.total_output_tokens:,} out | "
            f"🔄 {self.turn_count} turns"
        )


class KomorebiAgent:
    """Personal assistant agent with multi-turn conversation support.

    使用 ClaudeSDKClient 實現多輪對話，讓 Claude 記住對話上下文。

    Args:
        config_path: Path to settings.yaml configuration file.
        model: 模型選擇 (sonnet/opus/haiku)，預設 sonnet
        max_budget_usd: 最大預算限制（美元），超過會停止

    Example:
        >>> agent = KomorebiAgent(Path("config/settings.yaml"))
        >>> async with agent:
        ...     async for text in agent.chat("你好"):
        ...         print(text)
        ...     print(agent.usage)  # 查看消耗
    """

    # 模型對照表（2025-01 最新）
    # 參考: https://platform.claude.com/docs/en/about-claude/models/overview
    MODELS = {
        "opus": "claude-opus-4-5-20251101",  # $5/$25 per MTok - 最強
        "sonnet": "claude-sonnet-4-5-20250929",  # $3/$15 per MTok - 平衡（推薦）
        "haiku": "claude-haiku-4-5-20251001",  # $1/$5 per MTok - 最快最便宜
    }

    def __init__(
        self,
        config_path: Path | None = None,
        model: str = "sonnet",
        max_budget_usd: float | None = None,
        resume_session: bool = True,
    ) -> None:
        """Initialize agent with configuration.

        Args:
            config_path: Optional path to settings.yaml. Uses defaults if None.
            model: 模型簡稱 (opus/sonnet/haiku) 或完整名稱
            max_budget_usd: 預算上限，超過會拒絕請求
            resume_session: 是否恢復上次的對話會話
        """
        if config_path and config_path.exists():
            self.config: Config = load_config(config_path)
        else:
            self.config = Config()

        # 模型設定
        self.model = self.MODELS.get(model, model)
        self.max_budget_usd = max_budget_usd

        # 使用量追蹤
        self.usage = UsageStats()

        # Session 管理
        self._session_manager = SessionManager(self.config.data_dir)
        self._resume_session = resume_session
        self._session_id: str | None = None

        # 如果要恢復，載入上次的 session_id
        if resume_session:
            self._session_id = self._session_manager.load()

        # 初始化 SkillManager
        self._skill_manager = SkillManager(Path(".claude/skills"))
        self._skill_manager.discover()
        set_skill_manager(self._skill_manager)

        # 初始化 PlanManager
        self._plan_manager = PlanManager(self.config.data_dir)
        set_plan_manager(self._plan_manager)

        # 設定 Komorebi 專案根目錄（用於權限檢查）
        # data_dir 是 data/，其 parent 就是專案根目錄
        set_komorebi_root(self.config.data_dir.parent)

        self._client: ClaudeSDKClient | None = None
        self._options: ClaudeAgentOptions = self._build_options()

    def _build_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions with system prompt and custom tools.

        學習重點：
        - create_sdk_mcp_server() 建立 in-process MCP server
        - 工具在 mcp_servers dict 中註冊
        - allowed_tools 使用格式：mcp__<server_name>__<tool_name>

        Returns:
            Configured options for the SDK client.
        """
        # 設定工具的資料目錄
        project.set_data_dir(self.config.data_dir)
        planning.set_data_dir(self.config.data_dir)
        memory.set_memory_file(self.config.data_dir / "memory" / "facts.yaml")

        # 設定 calendar 工具
        if self.config.calendar.enabled:
            calendar.set_config(
                {
                    "credentials_path": str(self.config.calendar.credentials_path.expanduser()),
                    "token_path": str(self.config.calendar.token_path.expanduser()),
                    "default_calendar": self.config.calendar.default_calendar,
                }
            )

        # 建立專案管理 MCP Server
        # create_sdk_mcp_server() 把 @tool 裝飾的函數包裝成 MCP server
        project_server = create_sdk_mcp_server(
            name="project",
            version="1.0.0",
            tools=project.all_tools,  # [list_projects, show_project, update_project_status]
        )

        # 建立每日規劃 MCP Server
        planning_server = create_sdk_mcp_server(
            name="planning",
            version="1.0.0",
            tools=planning.all_tools,  # [plan_today, get_today, end_of_day]
        )

        # 建立行事曆 MCP Server (如果啟用)
        calendar_server = None
        if self.config.calendar.enabled:
            calendar_server = create_sdk_mcp_server(
                name="calendar",
                version="1.0.0",
                tools=calendar.all_tools,  # [list_events, add_event]
            )

        # 建立 Skill MCP Server
        skill_server = create_sdk_mcp_server(
            name="skill",
            version="1.0.0",
            tools=skill_tools,  # [load_skill]
        )

        # 建立 Memory MCP Server
        memory_server = create_sdk_mcp_server(
            name="memory",
            version="1.0.0",
            tools=memory.all_tools,  # [get_memory, remember]
        )

        # 組合 MCP servers
        mcp_servers = {
            "project": project_server,
            "planning": planning_server,
            "skill": skill_server,
            "memory": memory_server,
        }
        if calendar_server:
            mcp_servers["calendar"] = calendar_server

        # 組合 allowed tools（精簡版：只註冊核心工具）
        # 任務管理（add/complete/update）改由 Skill 指引直接編輯 tasks.md
        allowed_tools = [
            # 專案工具（精簡版）
            "mcp__project__list_projects",
            "mcp__project__show_project",
            "mcp__project__get_today_tasks",
            "mcp__project__sync_project",
            # 回顧系統（統一工具：day/week/month）
            "mcp__project__generate_review",
            # 每日規劃（移除 end_of_day，改用 generate_review period=day）
            "mcp__planning__plan_today",
            "mcp__planning__get_today",
            "mcp__planning__log_event",
            # Skill 系統（LLM 自主判斷載入）
            "mcp__skill__load_skill",
            # Memory 系統（語意記憶）
            "mcp__memory__get_memory",
            "mcp__memory__remember",
            # 檔案操作（用於 Skill 指引的任務編輯）
            "Read",
            "Edit",
            # 網路搜尋（SDK 內建工具）
            "WebSearch",
            "WebFetch",
        ]
        if self.config.calendar.enabled:
            allowed_tools.extend(
                [
                    "mcp__calendar__list_events",
                    "mcp__calendar__add_event",
                ]
            )

        return ClaudeAgentOptions(
            system_prompt=self._load_system_prompt(),
            # 模型設定
            model=self.model,
            # 預算限制
            max_budget_usd=self.max_budget_usd,
            # 恢復上次的對話會話
            resume=self._session_id,
            # 註冊 MCP servers
            mcp_servers=mcp_servers,
            # 允許使用的工具（格式：mcp__<server>__<tool>）
            allowed_tools=allowed_tools,
            # SDK 層級權限檢查：確保不會修改其他專案
            can_use_tool=_check_tool_permission,
        )

    def _load_system_prompt(self) -> str:
        """Load system prompt from prompts/system.md.

        會自動注入可用的 skill 清單到 system prompt 結尾。

        Returns:
            System prompt string, or default if file not found.
        """
        prompt_file = Path("prompts/system.md")
        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding="utf-8")
        else:
            prompt = "你是 Komorebi，Eric 的個人執行助理。請用繁體中文回答。"

        # 注入 skill 清單
        skill_list = self._skill_manager.get_skill_list_prompt()
        if skill_list:
            prompt += f"\n\n{skill_list}"

        return prompt

    async def __aenter__(self) -> "KomorebiAgent":
        """Enter async context and create client.

        ClaudeSDKClient 需要在 async context 中使用。
        connect() 會啟動與 Claude 的連線。

        Returns:
            Self for use in async with statement.
        """
        self._client = ClaudeSDKClient(self._options)
        await self._client.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context and disconnect.

        確保連線正確關閉，釋放資源。
        """
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def chat(self, message: str) -> AsyncIterator[ChatEvent]:
        """Send a message and yield structured events.

        這是主要的對話介面。使用 query() 發送訊息，
        然後用 receive_response() 接收回應。

        ClaudeSDKClient 會自動管理對話歷史，
        所以後續的 chat() 呼叫會記得之前的對話。

        Args:
            message: User message to send.

        Yields:
            ChatEvent: 結構化事件（TextEvent, ToolStartEvent, ToolEndEvent, DoneEvent）

        Raises:
            RuntimeError: If agent is not connected (not in async with context).
        """
        if not self._client:
            raise RuntimeError("Agent not connected. Use 'async with' context.")

        # 發送使用者訊息
        await self._client.query(message)

        # 接收並處理回應
        async for msg in self._client.receive_response():
            # SystemMessage: 初始化資訊，擷取 session_id
            if isinstance(msg, SystemMessage):
                # 首次取得 session_id
                if not self._session_id and hasattr(msg, "session_id"):
                    self._session_id = msg.session_id
                continue

            # AssistantMessage: Claude 的回應
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        yield TextEvent(text=block.text)
                    elif isinstance(block, ToolUseBlock):
                        yield ToolStartEvent(
                            tool_id=block.id,
                            tool_name=block.name,
                            tool_input=block.input,
                        )
                    elif isinstance(block, ToolResultBlock):
                        yield ToolEndEvent(
                            tool_id=block.tool_use_id,
                            result=str(block.content)[:200] if block.content else "",
                            is_error=block.is_error or False,
                        )

            # UserMessage: SDK 可能將 ToolResultBlock 包含在 UserMessage 中
            if isinstance(msg, UserMessage):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        yield ToolEndEvent(
                            tool_id=block.tool_use_id,
                            result=str(block.content)[:200] if block.content else "",
                            is_error=block.is_error or False,
                        )

            # ResultMessage: 最終結果，包含統計資訊
            if isinstance(msg, ResultMessage):
                # 更新使用量統計
                self.usage.update(msg)

                # 保存會話（用於下次恢復）
                if self._session_id:
                    self._session_manager.save(self._session_id)

                yield DoneEvent(
                    cost_usd=msg.total_cost_usd or 0,
                    input_tokens=msg.usage.get("input_tokens", 0) if msg.usage else 0,
                    output_tokens=msg.usage.get("output_tokens", 0) if msg.usage else 0,
                )

    def new_session(self) -> None:
        """開始新的對話會話。

        清除已保存的 session_id，下次 chat() 時會建立新會話。
        """
        self._session_manager.clear()
        self._session_id = None

    @property
    def session_info(self) -> dict[str, Any] | None:
        """取得當前會話資訊。

        Returns:
            包含 session_id, updated, summary 的 dict，若無則返回 None
        """
        return self._session_manager.get_info()

    @property
    def is_resumed(self) -> bool:
        """檢查是否為恢復的會話。

        Returns:
            True 如果是恢復上次的會話
        """
        return self._resume_session and self._session_id is not None

    # ========================================================================
    # Plan Mode
    # ========================================================================

    @property
    def plan_mode(self) -> bool:
        """檢查是否在 Plan Mode 中。"""
        return self._plan_manager.is_active

    @property
    def plan_task(self) -> str | None:
        """取得當前計劃的任務描述。"""
        return self._plan_manager.current_task

    @property
    def plan_path(self) -> Path | None:
        """取得當前計劃檔案路徑。"""
        return self._plan_manager.current_plan_path

    def enter_plan_mode(self, task: str) -> Path:
        """進入 Plan Mode。

        Args:
            task: 任務描述

        Returns:
            計劃檔案路徑
        """
        return self._plan_manager.enter(task)

    def approve_plan(self) -> str:
        """批准計劃並退出 Plan Mode。

        Returns:
            結果訊息
        """
        return self._plan_manager.exit(approved=True)

    def reject_plan(self) -> str:
        """拒絕計劃並退出 Plan Mode。

        Returns:
            結果訊息
        """
        return self._plan_manager.exit(approved=False)
