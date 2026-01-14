"""Test custom tools integration.

學習重點：
- Claude 會自動呼叫適當的工具
- 工具執行結果會整合到對話中
- 可以連續使用多個工具
"""

import asyncio
from pathlib import Path

from komorebi.agent import KomorebiAgent


async def main() -> None:
    """Test project management tools."""
    print("Testing custom tools integration...")
    print("=" * 50)

    async with KomorebiAgent(Path("config/settings.yaml")) as agent:
        # 測試 1: 列出專案
        print("\n[Test 1] 列出所有專案")
        print("-" * 30)
        async for chunk in agent.chat("列出我的專案"):
            print(chunk, end="")
        print("\n")

        # 測試 2: 顯示專案詳情
        print("\n[Test 2] 顯示 LayerWise 專案詳情")
        print("-" * 30)
        async for chunk in agent.chat("顯示 LayerWise 的詳細資訊"):
            print(chunk, end="")
        print("\n")

    print("=" * 50)
    print("Tools test completed!")


if __name__ == "__main__":
    asyncio.run(main())
