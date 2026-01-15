"""Chat input widget for Komorebi TUI.

Multi-line input with Shift+Enter for newlines and Enter for submit.
"""

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import TextArea


class ChatInput(TextArea):
    """Multi-line chat input widget.

    - Enter: Submit message (or select from command palette)
    - Shift+Enter: Insert newline
    - Up/Down: Navigate command palette when visible
    - Escape: Hide command palette
    """

    DEFAULT_CSS = """
    ChatInput {
        border: solid $primary;
        padding: 0 1;
    }

    ChatInput:focus {
        border: solid $accent;
    }
    """

    class Submitted(Message):
        """Posted when user submits input."""

        def __init__(self, value: str) -> None:
            """Initialize submitted message.

            Args:
                value: The submitted text.
            """
            self.value = value
            super().__init__()

    class SlashTyped(Message):
        """Posted when user types a slash command."""

        def __init__(self, text: str) -> None:
            """Initialize slash typed message.

            Args:
                text: Current input text starting with /.
            """
            self.text = text
            super().__init__()

    class SlashCleared(Message):
        """Posted when slash command input is cleared."""

        pass

    # Track if command palette is showing
    palette_visible: reactive[bool] = reactive(False)

    def __init__(
        self,
        id: str | None = None,
    ) -> None:
        """Initialize chat input.

        Args:
            id: Widget ID.
        """
        super().__init__(
            id=id,
            language=None,
            soft_wrap=True,
        )
        self.show_line_numbers = False
        self._last_text = ""

    def on_text_area_changed(self, event) -> None:
        """Handle text changes to detect slash commands."""
        text = self.text

        # Check if typing a slash command
        if text.startswith("/") and "\n" not in text:
            self.post_message(self.SlashTyped(text))
        elif self._last_text.startswith("/") and not text.startswith("/"):
            self.post_message(self.SlashCleared())

        self._last_text = text

    def _on_key(self, event) -> None:
        """Handle key events.

        Args:
            event: Key event.
        """
        # Normal enter = submit (only when palette not visible)
        if event.key == "enter" and not self.palette_visible:
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
            return

        # Shift+Enter falls through to default behavior (newline)

    def clear(self) -> None:
        """Clear the input text."""
        self.text = ""
        self._last_text = ""

    def set_text(self, text: str) -> None:
        """Set input text.

        Args:
            text: Text to set.
        """
        self.text = text
        self._last_text = text
