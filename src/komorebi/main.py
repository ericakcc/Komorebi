"""CLI entry point for Komorebi personal agent.

學習重點：
- 使用 click 建立 CLI 命令
- 使用 rich 美化輸出
- asyncio.run() 執行 async 函數

Usage:
    komorebi              # Start interactive session
    komorebi --help       # Show help
"""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import KomorebiAgent

console = Console()


async def run_repl(config_path: Path, model: str, max_budget: float | None) -> None:
    """Run the interactive REPL loop.

    REPL = Read-Eval-Print Loop
    1. Read: 讀取使用者輸入
    2. Eval: 發送給 Claude 處理
    3. Print: 顯示回應
    4. Loop: 重複直到使用者離開

    Args:
        config_path: Path to settings.yaml configuration file.
        model: 模型選擇 (sonnet/opus/haiku)
        max_budget: 預算上限（美元）
    """
    # 顯示歡迎訊息
    console.print(
        Panel.fit(
            "[bold blue]Komorebi[/bold blue] v0.1.0\n[dim]你的個人執行助理[/dim]",
            border_style="blue",
        )
    )
    console.print(f"[dim]模型: {model} | 輸入 /usage 查看消耗 | exit 離開[/dim]\n")

    # 使用 async with 確保正確管理連線
    async with KomorebiAgent(config_path, model=model, max_budget_usd=max_budget) as agent:
        while True:
            try:
                # Read: 取得使用者輸入
                user_input = Prompt.ask("[green]You[/green]")

                # 檢查特殊命令
                if user_input.lower() in ["exit", "quit", "q"]:
                    console.print(f"[dim]{agent.usage}[/dim]")
                    console.print("[dim]再見！[/dim]")
                    break

                if user_input.lower() in ["/usage", "/cost"]:
                    console.print(f"[yellow]{agent.usage}[/yellow]\n")
                    continue

                if user_input.lower() == "/help":
                    console.print(
                        "[dim]/usage - 查看 API 消耗\n/help  - 顯示幫助\nexit   - 離開[/dim]\n"
                    )
                    continue

                # 跳過空輸入
                if not user_input.strip():
                    continue

                # Eval & Print: 發送給 Claude 並顯示回應
                response_parts: list[str] = []
                async for chunk in agent.chat(user_input):
                    response_parts.append(chunk)

                # 組合並顯示完整回應
                full_response = "".join(response_parts)
                console.print(f"[blue]Komorebi[/blue]: {full_response}\n")

            except KeyboardInterrupt:
                console.print(f"\n[dim]{agent.usage}[/dim]")
                console.print("[dim]再見！[/dim]")
                break
            except Exception as e:
                console.print(f"[red]錯誤：{e}[/red]\n")


@click.command()
@click.option(
    "--config",
    default="config/settings.yaml",
    help="設定檔路徑",
    type=click.Path(),
)
@click.option(
    "--model",
    "-m",
    default="sonnet",
    type=click.Choice(["opus", "sonnet", "haiku"]),
    help="模型選擇：opus(最強)、sonnet(平衡)、haiku(最快)",
)
@click.option(
    "--budget",
    default=None,
    type=float,
    help="預算上限（美元），例如 --budget 1.0",
)
def cli(config: str, model: str, budget: float | None) -> None:
    """Komorebi - Personal AI Assistant.

    啟動互動式對話介面，協助管理專案與規劃工作。

    \b
    快速開始：
        komorebi                    # 使用預設設定 (sonnet)
        komorebi -m haiku           # 用便宜快速的 haiku
        komorebi -m opus            # 用最強的 opus
        komorebi --budget 0.5       # 設定預算上限 $0.5
    """
    config_path = Path(config)
    if not config_path.exists():
        console.print(f"[yellow]提示：設定檔 {config} 不存在，使用預設值[/yellow]\n")

    # asyncio.run() 是執行 async 函數的標準方式
    asyncio.run(run_repl(config_path, model, budget))


if __name__ == "__main__":
    cli()
