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

from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)

from .config import Config, load_config
from .tools import project


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
        "opus": "claude-opus-4-5-20251101",      # $5/$25 per MTok - 最強
        "sonnet": "claude-sonnet-4-5-20250929",  # $3/$15 per MTok - 平衡（推薦）
        "haiku": "claude-haiku-4-5-20251001",    # $1/$5 per MTok - 最快最便宜
    }

    def __init__(
        self,
        config_path: Path | None = None,
        model: str = "sonnet",
        max_budget_usd: float | None = None,
    ) -> None:
        """Initialize agent with configuration.

        Args:
            config_path: Optional path to settings.yaml. Uses defaults if None.
            model: 模型簡稱 (opus/sonnet/haiku) 或完整名稱
            max_budget_usd: 預算上限，超過會拒絕請求
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

        # 建立專案管理 MCP Server
        # create_sdk_mcp_server() 把 @tool 裝飾的函數包裝成 MCP server
        project_server = create_sdk_mcp_server(
            name="project",
            version="1.0.0",
            tools=project.all_tools,  # [list_projects, show_project, update_project_status]
        )

        return ClaudeAgentOptions(
            system_prompt=self._load_system_prompt(),
            # 模型設定
            model=self.model,
            # 預算限制
            max_budget_usd=self.max_budget_usd,
            # 註冊 MCP servers
            mcp_servers={
                "project": project_server,
            },
            # 允許使用的工具（格式：mcp__<server>__<tool>）
            allowed_tools=[
                "mcp__project__list_projects",
                "mcp__project__show_project",
                "mcp__project__update_project_status",
            ],
        )

    def _load_system_prompt(self) -> str:
        """Load system prompt from prompts/system.md.

        Returns:
            System prompt string, or default if file not found.
        """
        prompt_file = Path("prompts/system.md")
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return "你是 Komorebi，Eric 的個人執行助理。請用繁體中文回答。"

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

    async def chat(self, message: str) -> AsyncIterator[str]:
        """Send a message and yield response text.

        這是主要的對話介面。使用 query() 發送訊息，
        然後用 receive_response() 接收回應。

        ClaudeSDKClient 會自動管理對話歷史，
        所以後續的 chat() 呼叫會記得之前的對話。

        Args:
            message: User message to send.

        Yields:
            Response text chunks as they arrive.

        Raises:
            RuntimeError: If agent is not connected (not in async with context).
        """
        if not self._client:
            raise RuntimeError("Agent not connected. Use 'async with' context.")

        # 發送使用者訊息
        await self._client.query(message)

        # 接收並處理回應
        async for msg in self._client.receive_response():
            # SystemMessage: 初始化資訊，通常可以忽略
            if isinstance(msg, SystemMessage):
                continue

            # AssistantMessage: Claude 的回應
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        yield block.text
                    elif isinstance(block, ToolUseBlock):
                        # 階段三會實作工具呼叫
                        yield f"\n[使用工具: {block.name}]\n"

            # ResultMessage: 最終結果，包含統計資訊
            if isinstance(msg, ResultMessage):
                # 更新使用量統計
                self.usage.update(msg)
                if msg.is_error:
                    yield f"\n[錯誤: {msg.result}]\n"
