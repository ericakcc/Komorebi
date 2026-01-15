"""Komorebi TUI Application.

Main Textual application for Komorebi personal assistant.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App
from textual.binding import Binding

from .screens import ChatScreen

if TYPE_CHECKING:
    from ..agent import KomorebiAgent


class KomorebiApp(App[None]):
    """Komorebi TUI Application.

    A Claude Code-like terminal interface for personal AI assistant.

    Args:
        config_path: Path to settings.yaml configuration file.
        model: Model name (opus/sonnet/haiku).
        max_budget: Maximum budget in USD.
    """

    TITLE = "Komorebi"
    SUB_TITLE = "Personal AI Assistant"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
    ]

    def __init__(
        self,
        config_path: Path | None = None,
        model: str = "sonnet",
        max_budget: float | None = None,
    ) -> None:
        """Initialize the TUI application.

        Args:
            config_path: Path to settings.yaml configuration file.
            model: Model name (opus/sonnet/haiku).
            max_budget: Maximum budget in USD.
        """
        super().__init__()
        self.config_path = config_path
        self.model = model
        self.max_budget = max_budget
        self._agent: "KomorebiAgent | None" = None

    @property
    def agent(self) -> "KomorebiAgent":
        """Get the agent instance."""
        if self._agent is None:
            raise RuntimeError("Agent not initialized")
        return self._agent

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.push_screen(ChatScreen())

    def action_clear(self) -> None:
        """Clear chat history."""
        screen = self.screen
        if isinstance(screen, ChatScreen):
            screen.clear_messages()

    def action_scroll_up(self) -> None:
        """Scroll chat history up."""
        screen = self.screen
        if isinstance(screen, ChatScreen):
            screen.scroll_up()

    def action_scroll_down(self) -> None:
        """Scroll chat history down."""
        screen = self.screen
        if isinstance(screen, ChatScreen):
            screen.scroll_down()
