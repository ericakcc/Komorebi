"""Thinking indicator widget for Komorebi TUI.

Shows an animated indicator while waiting for AI response.
"""

from textual.widgets import Static
from textual.reactive import reactive


class ThinkingIndicator(Static):
    """Animated thinking indicator.

    Displays a spinning symbol with "Thinking..." text.
    Similar to Claude Code's "Germinating..." indicator.
    """

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: auto;
        padding: 1;
        color: $warning;
    }
    """

    # Animation frames
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    MESSAGES = [
        "Thinking...",
        "Processing...",
        "Analyzing...",
        "Pondering...",
    ]

    frame_index: reactive[int] = reactive(0)

    def __init__(self) -> None:
        """Initialize thinking indicator."""
        super().__init__()
        self._timer = None
        self._message_index = 0

    def on_mount(self) -> None:
        """Start animation when mounted."""
        self._timer = self.set_interval(0.1, self._advance_frame)
        self._update_display()

    def on_unmount(self) -> None:
        """Stop animation when unmounted."""
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _advance_frame(self) -> None:
        """Advance to next animation frame."""
        self.frame_index = (self.frame_index + 1) % len(self.FRAMES)

    def watch_frame_index(self, _: int) -> None:
        """Update display when frame changes."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the display text."""
        frame = self.FRAMES[self.frame_index]
        message = self.MESSAGES[self._message_index]
        self.update(f"{frame} {message}")
