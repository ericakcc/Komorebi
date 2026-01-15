"""Command palette widget for slash command autocomplete.

Shows available commands when user types '/'.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import OptionList
from textual.widgets.option_list import Option


# Available slash commands with descriptions
COMMANDS = [
    ("/help", "Show available commands and keyboard shortcuts"),
    ("/usage", "Show API usage statistics (tokens and cost)"),
    ("/clear", "Clear chat history"),
    ("/projects", "List all tracked projects"),
    ("/sync", "Sync project info from repo (usage: /sync <name>)"),
    ("/today", "Show today's plan"),
    ("/exit", "Exit application"),
]


class CommandPalette(Vertical):
    """Command palette for slash command autocomplete.

    Shows a filterable list of commands when user types '/'.
    """

    DEFAULT_CSS = """
    CommandPalette {
        dock: bottom;
        height: auto;
        max-height: 12;
        margin: 0 1 5 1;
        background: $surface;
        border: solid $primary;
        display: none;
        layer: above;
    }

    CommandPalette.visible {
        display: block;
    }

    CommandPalette OptionList {
        height: auto;
        max-height: 10;
        background: $surface;
        padding: 0;
    }

    CommandPalette OptionList > .option-list--option-highlighted {
        background: $primary-darken-2;
    }
    """

    # Prevent OptionList from receiving focus
    can_focus = False

    class CommandSelected(Message):
        """Posted when a command is selected."""

        def __init__(self, command: str) -> None:
            """Initialize message.

            Args:
                command: The selected command.
            """
            self.command = command
            super().__init__()

    filter_text: reactive[str] = reactive("")

    def __init__(self) -> None:
        """Initialize command palette."""
        super().__init__()
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        """Compose the palette layout."""
        self._option_list = OptionList()
        yield self._option_list

    def on_mount(self) -> None:
        """Initialize on mount - palette starts hidden."""
        pass  # Don't initialize options here, wait for show()

    def show(self, filter_text: str = "") -> None:
        """Show the command palette.

        Args:
            filter_text: Initial filter text (e.g., "/he" to filter for /help).
        """
        self.filter_text = filter_text
        self.add_class("visible")
        self._update_options()
        # Don't focus OptionList - we handle keys manually

    def hide(self) -> None:
        """Hide the command palette."""
        self.remove_class("visible")

    @property
    def is_visible(self) -> bool:
        """Check if palette is visible."""
        return self.has_class("visible")

    def watch_filter_text(self, value: str) -> None:
        """Update options when filter changes."""
        # Only update if visible (avoid initialization issues)
        if self.is_visible:
            self._update_options()

    def _update_options(self) -> None:
        """Update the option list based on filter."""
        if not self._option_list:
            return

        self._option_list.clear_options()

        # Filter commands based on input
        filter_lower = self.filter_text.lower()
        for cmd, desc in COMMANDS:
            if filter_lower in cmd.lower() or filter_lower.lstrip("/") in cmd.lower():
                # Format: "/command  Description"
                label = f"{cmd:<12} [dim]{desc}[/dim]"
                self._option_list.add_option(Option(label, id=cmd))

        # Highlight first option
        if self._option_list.option_count > 0:
            self._option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection.

        Args:
            event: The selection event.
        """
        if event.option.id:
            self.post_message(self.CommandSelected(event.option.id))
        self.hide()

    def select_highlighted(self) -> None:
        """Select the currently highlighted option."""
        if self._option_list and self._option_list.highlighted is not None:
            option = self._option_list.get_option_at_index(self._option_list.highlighted)
            if option and option.id:
                self.post_message(self.CommandSelected(option.id))
        self.hide()

    def move_up(self) -> None:
        """Move highlight up."""
        if self._option_list and self._option_list.option_count > 0:
            self._option_list.action_cursor_up()

    def move_down(self) -> None:
        """Move highlight down."""
        if self._option_list and self._option_list.option_count > 0:
            self._option_list.action_cursor_down()
