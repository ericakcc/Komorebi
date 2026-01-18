"""Plan input modal widget for Komorebi TUI.

Modal screen for entering a task description when entering Plan Mode.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class PlanInputModal(ModalScreen[str | None]):
    """Modal for entering plan mode task description.

    Returns the task string if submitted, or None if cancelled.
    """

    DEFAULT_CSS = """
    PlanInputModal {
        align: center middle;
    }

    PlanInputModal > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $warning;
        padding: 1 2;
    }

    PlanInputModal .modal-title {
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    PlanInputModal .modal-description {
        color: $text-muted;
        margin-bottom: 1;
    }

    PlanInputModal Input {
        width: 100%;
        margin-bottom: 1;
    }

    PlanInputModal Input:focus {
        border: solid $warning;
    }

    PlanInputModal .button-row {
        height: auto;
        width: 100%;
        align: center middle;
    }

    PlanInputModal Button {
        margin: 0 1;
    }

    PlanInputModal #btn-start {
        background: $warning;
        color: $text;
    }

    PlanInputModal #btn-cancel {
        background: $surface-darken-1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Vertical():
            yield Static("Enter Plan Mode", classes="modal-title")
            yield Label(
                "Describe what you want to plan. "
                "Write tools will be disabled until you approve the plan.",
                classes="modal-description",
            )
            yield Input(placeholder="What do you want to plan?", id="task-input")
            with Vertical(classes="button-row"):
                yield Button("Start Planning", id="btn-start", variant="warning")
                yield Button("Cancel", id="btn-cancel", variant="default")

    def on_mount(self) -> None:
        """Focus the input when modal mounts."""
        self.query_one("#task-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input.

        Args:
            event: The submitted event.
        """
        task = event.value.strip()
        if task:
            self.dismiss(task)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: The button pressed event.
        """
        if event.button.id == "btn-start":
            task = self.query_one("#task-input", Input).value.strip()
            if task:
                self.dismiss(task)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
