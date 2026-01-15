"""CLI entry point for Komorebi personal agent.

學習重點：
- 使用 click 建立 CLI 命令
- 使用 Textual 實現 TUI 介面
- 保留 --classic 選項用於舊版 REPL

Usage:
    komorebi              # Start TUI interface
    komorebi --classic    # Start classic REPL
    komorebi --help       # Show help
"""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import (
    DoneEvent,
    KomorebiAgent,
    TextEvent,
    ToolEndEvent,
    ToolStartEvent,
    format_tool_name,
)
from .ui import KomorebiApp

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

                # Eval & Print: 發送給 Claude 並處理結構化事件
                console.print("[blue]Komorebi[/blue]: ", end="")
                has_text = False

                async for event in agent.chat(user_input):
                    if isinstance(event, TextEvent):
                        # 串流輸出文字
                        console.print(event.text, end="")
                        has_text = True

                    elif isinstance(event, ToolStartEvent):
                        # 工具開始執行
                        if has_text:
                            console.print()  # 換行
                            has_text = False
                        tool_display = format_tool_name(event.tool_name)
                        console.print(f"  [dim]→ {tool_display}[/dim]", end="")

                    elif isinstance(event, ToolEndEvent):
                        # 工具執行完成
                        if event.is_error:
                            console.print(" [red]✗[/red]")
                        else:
                            console.print(" [green]✓[/green]")

                    elif isinstance(event, DoneEvent):
                        # 對話完成，顯示統計
                        if has_text:
                            console.print()  # 換行
                        console.print(
                            f"[dim]💰 ${event.cost_usd:.4f} | "
                            f"📥 {event.input_tokens:,} | "
                            f"📤 {event.output_tokens:,}[/dim]"
                        )

                console.print()  # 空行分隔

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
@click.option(
    "--classic",
    is_flag=True,
    default=False,
    help="使用傳統 REPL 介面（非 TUI）",
)
def cli(config: str, model: str, budget: float | None, classic: bool) -> None:
    """Komorebi - Personal AI Assistant.

    啟動互動式對話介面，協助管理專案與規劃工作。

    \b
    快速開始：
        komorebi                    # 使用 TUI 介面 (預設)
        komorebi --classic          # 使用傳統 REPL 介面
        komorebi -m haiku           # 用便宜快速的 haiku
        komorebi -m opus            # 用最強的 opus
        komorebi --budget 0.5       # 設定預算上限 $0.5
    """
    config_path = Path(config)
    if not config_path.exists():
        console.print(f"[yellow]提示：設定檔 {config} 不存在，使用預設值[/yellow]\n")

    if classic:
        # 傳統 REPL 模式
        asyncio.run(run_repl(config_path, model, budget))
    else:
        # TUI 模式
        app = KomorebiApp(
            config_path=config_path,
            model=model,
            max_budget=budget,
        )
        app.run()


if __name__ == "__main__":
    cli()
