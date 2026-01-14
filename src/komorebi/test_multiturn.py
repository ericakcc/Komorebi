"""Test multi-turn conversation with ClaudeSDKClient.

學習重點：
- ClaudeSDKClient 會記住對話上下文
- 第二輪對話時，Claude 應該記得第一輪的內容
"""

import asyncio
from pathlib import Path

from komorebi.agent import KomorebiAgent


async def main() -> None:
    """Test multi-turn conversation."""
    print("Testing multi-turn conversation...")
    print("=" * 50)

    async with KomorebiAgent(Path("config/settings.yaml")) as agent:
        # 第一輪：告訴 Claude 一個資訊
        print("\n[Turn 1] You: 我的名字是 Eric，我正在開發一個叫 LayerWise 的專案")
        response1 = []
        async for chunk in agent.chat("我的名字是 Eric，我正在開發一個叫 LayerWise 的專案"):
            response1.append(chunk)
        print(f"[Turn 1] Komorebi: {''.join(response1)}")

        # 第二輪：測試 Claude 是否記得
        print("\n[Turn 2] You: 我叫什麼名字？我在做什麼專案？")
        response2 = []
        async for chunk in agent.chat("我叫什麼名字？我在做什麼專案？"):
            response2.append(chunk)
        print(f"[Turn 2] Komorebi: {''.join(response2)}")

    print("\n" + "=" * 50)
    print("Multi-turn test completed!")


if __name__ == "__main__":
    asyncio.run(main())
