"""Slash command handling for Komorebi TUI.

Implements /help, /usage, /clear, /exit, /sync, /projects, /today commands.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .screens.chat import ChatScreen


def is_command(message: str) -> bool:
    """Check if a message is a slash command.

    Args:
        message: Message to check.

    Returns:
        True if message starts with /.
    """
    return message.startswith("/")


async def handle_command(screen: "ChatScreen", message: str) -> None:
    """Handle a slash command.

    Args:
        screen: Chat screen instance.
        message: Command message (e.g., "/help", "/sync LayerWise").
    """
    parts = message.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handlers = {
        "/help": _handle_help,
        "/usage": _handle_usage,
        "/clear": _handle_clear,
        "/exit": _handle_exit,
        "/quit": _handle_exit,
        "/q": _handle_exit,
        "/sync": _handle_sync,
        "/projects": _handle_projects,
        "/today": _handle_today,
        "/plan": _handle_plan,
        "/approve": _handle_approve,
        "/reject": _handle_reject,
        "/mode": _handle_mode,
    }

    handler = handlers.get(command)
    if handler:
        await handler(screen, args)
    else:
        screen._add_error_message(f"Unknown command: {command}\nType /help for available commands.")


async def _handle_help(screen: "ChatScreen", args: str) -> None:
    """Show help message."""
    help_text = """## Available Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help message |
| `/usage` | Show API usage statistics |
| `/clear` | Clear chat history |
| `/exit`, `/quit`, `/q` | Exit application |
| `/sync <project>` | Sync project information |
| `/projects` | List all projects |
| `/today` | Show today's plan |
| `/plan <task>` | Enter Plan Mode (or use Shift+Tab) |
| `/approve` | Approve plan and execute |
| `/reject` | Reject plan and exit Plan Mode |
| `/mode` | Show current mode status |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Shift+Enter` | Insert newline |
| `Shift+Tab` | Enter Plan Mode |
| `Ctrl+C` | Quit |
| `Ctrl+L` | Clear chat |
| `PageUp/PageDown` | Scroll history |
"""
    screen._add_system_message(help_text)


async def _handle_usage(screen: "ChatScreen", args: str) -> None:
    """Show API usage statistics."""
    screen.show_usage()


async def _handle_clear(screen: "ChatScreen", args: str) -> None:
    """Clear chat history."""
    screen.clear_messages()


async def _handle_exit(screen: "ChatScreen", args: str) -> None:
    """Exit application."""
    screen.app.exit()


async def _handle_sync(screen: "ChatScreen", args: str) -> None:
    """Sync a project."""
    project_name = args.strip()
    if not project_name:
        screen._add_error_message("Usage: /sync <project_name>")
        return

    # Convert to natural language and send to agent (non-blocking)
    screen._add_user_message(f"/sync {project_name}")
    screen.run_worker(
        screen._process_chat(f"Please sync the {project_name} project information"),
        exclusive=True,
    )


async def _handle_projects(screen: "ChatScreen", args: str) -> None:
    """List all projects."""
    screen._add_user_message("/projects")
    screen.run_worker(screen._process_chat("List all my projects"), exclusive=True)


async def _handle_today(screen: "ChatScreen", args: str) -> None:
    """Show today's plan."""
    screen._add_user_message("/today")
    screen.run_worker(screen._process_chat("Show me today's plan"), exclusive=True)


async def _handle_plan(screen: "ChatScreen", args: str) -> None:
    """Enter Plan Mode."""
    task = args.strip()
    if not task:
        # No task provided, show modal
        from .widgets import PlanInputModal

        screen.app.push_screen(PlanInputModal(), screen._on_plan_task_entered)
    else:
        # Task provided directly
        screen.enter_plan_mode(task)


async def _handle_approve(screen: "ChatScreen", args: str) -> None:
    """Approve plan and execute."""
    if not screen.plan_mode:
        screen._add_error_message(
            "Not in Plan Mode. Use `/plan` or Shift+Tab to enter Plan Mode first."
        )
        return

    screen.exit_plan_mode(approved=True)


async def _handle_reject(screen: "ChatScreen", args: str) -> None:
    """Reject plan and exit Plan Mode."""
    if not screen.plan_mode:
        screen._add_error_message("Not in Plan Mode. Nothing to reject.")
        return

    screen.exit_plan_mode(approved=False)


async def _handle_mode(screen: "ChatScreen", args: str) -> None:
    """Show current mode status."""
    screen.show_mode_status()
