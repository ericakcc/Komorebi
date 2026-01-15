"""Tool panel widget for Komorebi TUI.

Collapsible panel showing tool execution status and output.
"""

from typing import Any

from textual.app import ComposeResult
from textual.widgets import Collapsible, Static


class ToolPanel(Collapsible):
    """Collapsible tool execution panel.

    Shows tool name, status indicator, and output.
    Starts expanded, auto-collapses after completion.
    """

    DEFAULT_CSS = """
    ToolPanel {
        margin: 0 2 1 2;
        padding: 0;
    }

    ToolPanel.running {
        border: round $secondary;
    }

    ToolPanel.success {
        border: round $success;
    }

    ToolPanel.error {
        border: round $error;
    }

    ToolPanel .tool-status {
        height: auto;
        padding: 1;
    }

    ToolPanel .tool-input {
        color: $text-muted;
        padding: 0 1;
    }

    ToolPanel .tool-result {
        padding: 1;
        background: $surface-darken-1;
    }

    ToolPanel .tool-result.error {
        background: $error-darken-3;
        color: $error-lighten-1;
    }
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
    ) -> None:
        """Initialize tool panel.

        Args:
            tool_name: Name of the tool being executed.
            tool_input: Tool input parameters.
        """
        # Format title with running indicator
        title = f" {tool_name}..."
        super().__init__(title=title, collapsed=False)
        self.add_class("running")

        self._tool_name = tool_name
        self._tool_input = tool_input or {}
        self._result: str | None = None
        self._is_error: bool = False
        self._result_widget: Static | None = None

    def compose(self) -> ComposeResult:
        """Compose the panel content."""
        # Show input parameters
        if self._tool_input:
            input_lines = []
            for key, value in self._tool_input.items():
                value_str = str(value)[:60]
                if len(str(value)) > 60:
                    value_str += "..."
                input_lines.append(f"  {key}: {value_str}")
            yield Static("\n".join(input_lines), classes="tool-input")

        # Placeholder for result
        self._result_widget = Static("", classes="tool-result")
        yield self._result_widget

    def set_result(self, result: str, is_error: bool = False) -> None:
        """Set the tool execution result.

        Args:
            result: Result text to display.
            is_error: Whether the result is an error.
        """
        self._result = result
        self._is_error = is_error

        # Update status
        self.remove_class("running")
        if is_error:
            self.add_class("error")
            self.title = f" {self._tool_name}"
        else:
            self.add_class("success")
            self.title = f" {self._tool_name}"

        # Update result widget
        if self._result_widget:
            if result:
                self._result_widget.update(result)
                if is_error:
                    self._result_widget.add_class("error")
            else:
                self._result_widget.display = False

        # Auto-collapse on success
        if not is_error:
            self.collapsed = True
