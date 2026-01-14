"""Hello World test for Claude Agent SDK.

This script verifies that the SDK is properly installed and can connect to Claude.

學習重點：
- query() 是無狀態的單次查詢
- 使用 async for 來接收串流回應
- ClaudeAgentOptions 用於配置 system prompt 等選項
"""

import asyncio

from claude_agent_sdk import query, ClaudeAgentOptions


async def main() -> None:
    """Test basic SDK connectivity with a simple query."""
    print("Testing Claude Agent SDK connection...")
    print("-" * 40)

    options = ClaudeAgentOptions(
        system_prompt="你是 Komorebi，Eric 的個人助理。請用繁體中文回答。",
    )

    # query() 回傳一個 async generator，yield 各種 Message 類型
    async for message in query(
        prompt="你好！請簡單介紹一下你自己。",
        options=options,
    ):
        # message 可能是 AssistantMessage, ResultMessage 等
        print(message)

    print("-" * 40)
    print("SDK test completed!")


if __name__ == "__main__":
    asyncio.run(main())
