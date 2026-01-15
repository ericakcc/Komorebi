"""Message view widget for Komorebi TUI.

Displays chat messages with Markdown rendering.
"""

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static


RoleType = Literal["user", "assistant", "system", "error"]


class MessageView(Vertical):
    """Message view widget.

    Displays a chat message with role label and Markdown content.
    Supports streaming append for assistant messages.
    """

    DEFAULT_CSS = """
    MessageView {
        height: auto;
        margin-bottom: 0;
        padding: 0 1;
    }

    MessageView.error {
        color: $error;
    }

    MessageView .role-label {
        color: $text-muted;
        text-style: bold;
        margin-bottom: 0;
    }

    MessageView .role-label.user {
        color: $primary;
    }

    MessageView .role-label.assistant {
        color: $secondary;
    }

    MessageView .role-label.system {
        color: $warning;
    }

    MessageView .role-label.error {
        color: $error;
    }

    MessageView Markdown {
        padding: 0;
        margin: 0 0 1 2;
    }
    """

    ROLE_LABELS = {
        "user": "> You",
        "assistant": "> Komorebi",
        "system": "> System",
        "error": "> Error",
    }

    def __init__(
        self,
        role: RoleType,
        content: str = "",
    ) -> None:
        """Initialize message view.

        Args:
            role: Message role (user/assistant/system/error).
            content: Initial message content.
        """
        super().__init__(classes=role)
        self._role = role
        self._content = content
        self._markdown: Markdown | None = None

    def compose(self) -> ComposeResult:
        """Compose the message layout."""
        label = self.ROLE_LABELS.get(self._role, self._role)
        yield Static(label, classes=f"role-label {self._role}")
        self._markdown = Markdown(self._content)
        yield self._markdown

    def append_text(self, text: str) -> None:
        """Append text to the message (for streaming).

        Args:
            text: Text to append.
        """
        self._content += text
        if self._markdown:
            # Use update() for streaming - Textual v7 doesn't have append()
            self._markdown.update(self._content)
