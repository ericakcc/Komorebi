"""Chat screen for Komorebi TUI.

Main conversation interface with message history, input, and status bar.
"""

import asyncio
from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from textual.reactive import reactive

from ..commands import handle_command, is_command
from ..widgets import (
    ChatInput,
    CommandPalette,
    MessageView,
    PlanInputModal,
    ThinkingIndicator,
    ToolPanel,
)
from ...agent import (
    DoneEvent,
    KomorebiAgent,
    TextEvent,
    ToolEndEvent,
    ToolStartEvent,
    format_tool_name,
)

if TYPE_CHECKING:
    from ..app import KomorebiApp


class SmoothScroll(VerticalScroll):
    """VerticalScroll with aggressive throttling for Mac trackpad.

    Mac trackpads generate 40+ events per gesture with momentum scrolling.
    This class uses throttling (250ms) to make scrolling controllable.
    """

    SCROLL_AMOUNT = 1  # Lines per scroll event
    SCROLL_THROTTLE = 0.25  # 250ms between scroll events

    def __init__(self, *args, **kwargs) -> None:
        """Initialize with scroll throttle tracking."""
        super().__init__(*args, **kwargs)
        self._last_scroll_time: float = 0.0

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Handle scroll down with aggressive throttling."""
        import time

        now = time.monotonic()
        if now - self._last_scroll_time < self.SCROLL_THROTTLE:
            event.stop()
            event.prevent_default()
            return

        self._last_scroll_time = now

        if self.allow_vertical_scroll:
            self.scroll_relative(y=self.SCROLL_AMOUNT, animate=False)
        event.stop()
        event.prevent_default()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Handle scroll up with aggressive throttling."""
        import time

        now = time.monotonic()
        if now - self._last_scroll_time < self.SCROLL_THROTTLE:
            event.stop()
            event.prevent_default()
            return

        self._last_scroll_time = now

        if self.allow_vertical_scroll:
            self.scroll_relative(y=-self.SCROLL_AMOUNT, animate=False)
        event.stop()
        event.prevent_default()


class StatusBar(Static):
    """Bottom status bar showing token statistics and mode indicator."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        padding: 0 1;
    }

    StatusBar.plan-mode {
        background: $warning;
        color: $text;
    }
    """

    def __init__(self) -> None:
        """Initialize status bar."""
        super().__init__()
        self._cost: float = 0.0
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._plan_mode: bool = False
        self._plan_task: str = ""

    def update_stats(self, cost: float, input_tokens: int, output_tokens: int) -> None:
        """Update statistics display.

        Args:
            cost: Total cost in USD.
            input_tokens: Total input tokens.
            output_tokens: Total output tokens.
        """
        self._cost += cost
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._refresh_display()

    def set_plan_mode(self, active: bool, task: str = "") -> None:
        """Set plan mode state.

        Args:
            active: Whether plan mode is active.
            task: The task description for plan mode.
        """
        self._plan_mode = active
        self._plan_task = task
        if active:
            self.add_class("plan-mode")
        else:
            self.remove_class("plan-mode")
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the status bar text."""
        if self._plan_mode:
            # Truncate task if too long
            task_display = (
                self._plan_task[:40] + "..." if len(self._plan_task) > 40 else self._plan_task
            )
            self.update(f" PLAN MODE | {task_display} | ${self._cost:.4f} | /approve or /reject")
        else:
            self.update(
                f" ${self._cost:.4f} | "
                f" {self._input_tokens:,} | "
                f" {self._output_tokens:,} | "
                "/help for commands"
            )


class ChatScreen(Screen):
    """Main chat screen.

    Contains:
    - Header with app title
    - Scrollable message container
    - Input field
    - Status bar with token statistics
    """

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
    }

    #chat-container {
        height: 1fr;
        padding: 1;
        scrollbar-gutter: stable;
    }

    #chat-input {
        dock: bottom;
        height: auto;
        max-height: 8;
        min-height: 3;
        margin: 0 1 1 1;
    }

    #chat-input.plan-mode {
        border: solid $warning;
    }

    .message-container {
        margin-bottom: 1;
    }
    """

    # Plan mode state
    plan_mode: reactive[bool] = reactive(False)
    plan_task: reactive[str] = reactive("")

    def __init__(self) -> None:
        """Initialize chat screen."""
        super().__init__()
        self._agent: KomorebiAgent | None = None
        self._current_message: MessageView | None = None
        # Use dict to track all tool panels by tool_id
        self._tool_panels: dict[str, ToolPanel] = {}

    @property
    def komorebi_app(self) -> "KomorebiApp":
        """Get the app instance."""
        from ..app import KomorebiApp

        app = self.app
        if not isinstance(app, KomorebiApp):
            raise RuntimeError("Invalid app type")
        return app

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        yield Header()
        yield SmoothScroll(id="chat-container")
        yield CommandPalette()
        yield ChatInput(id="chat-input")
        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Called when screen is mounted."""
        # Initialize agent
        app = self.komorebi_app
        self._agent = KomorebiAgent(
            config_path=app.config_path,
            model=app.model,
            max_budget_usd=app.max_budget,
        )
        # Enter async context
        await self._agent.__aenter__()

        # Focus input
        self.query_one("#chat-input", ChatInput).focus()

        # Welcome message
        self._add_system_message(
            f"Komorebi v0.1.0 | Model: {app.model}\nType /help for available commands."
        )

    async def on_unmount(self) -> None:
        """Called when screen is unmounted."""
        if self._agent:
            await self._agent.__aexit__(None, None, None)
            self._agent = None

    def on_chat_input_slash_typed(self, event: ChatInput.SlashTyped) -> None:
        """Handle slash command typing.

        Args:
            event: The slash typed event.
        """
        palette = self.query_one(CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)

        # Update filter and show if not already visible
        if not palette.is_visible:
            palette.show(event.text)
            chat_input.palette_visible = True
        else:
            # Just update filter text
            palette.filter_text = event.text
            palette._update_options()

    def on_chat_input_slash_cleared(self, event: ChatInput.SlashCleared) -> None:
        """Handle slash command cleared."""
        palette = self.query_one(CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)

        palette.hide()
        chat_input.palette_visible = False

    def on_command_palette_command_selected(self, event: CommandPalette.CommandSelected) -> None:
        """Handle command selection from palette.

        Args:
            event: The command selected event.
        """
        chat_input = self.query_one("#chat-input", ChatInput)
        palette = self.query_one(CommandPalette)

        # Preserve user's full input if it starts with the selected command
        # e.g., "/sync layerwise" should not become just "/sync"
        current_text = chat_input.text.strip()
        if current_text.startswith(event.command):
            final_text = current_text
        else:
            final_text = event.command

        chat_input.set_text(final_text)
        chat_input.palette_visible = False
        palette.hide()

        # Submit the command
        chat_input.post_message(ChatInput.Submitted(final_text))

    def key_up(self, event) -> None:
        """Handle up key for command palette navigation."""
        chat_input = self.query_one("#chat-input", ChatInput)
        if chat_input.palette_visible:
            palette = self.query_one(CommandPalette)
            palette.move_up()
            event.stop()
            event.prevent_default()

    def key_down(self, event) -> None:
        """Handle down key for command palette navigation."""
        chat_input = self.query_one("#chat-input", ChatInput)
        if chat_input.palette_visible:
            palette = self.query_one(CommandPalette)
            palette.move_down()
            event.stop()
            event.prevent_default()

    def key_escape(self, event) -> None:
        """Handle escape key to hide command palette."""
        chat_input = self.query_one("#chat-input", ChatInput)
        if chat_input.palette_visible:
            palette = self.query_one(CommandPalette)
            palette.hide()
            chat_input.palette_visible = False
            event.stop()
            event.prevent_default()

    def on_chat_input_plan_mode_requested(self, event: ChatInput.PlanModeRequested) -> None:
        """Handle Shift+Tab to enter plan mode.

        Args:
            event: The plan mode requested event.
        """
        # Show modal to get task description
        self.app.push_screen(PlanInputModal(), self._on_plan_task_entered)

    def _on_plan_task_entered(self, task: str | None) -> None:
        """Callback when plan task is entered from modal.

        Args:
            task: The task description, or None if cancelled.
        """
        if task:
            self.enter_plan_mode(task)
        # Refocus input
        self.query_one("#chat-input", ChatInput).focus()

    def on_chat_input_enter_pressed(self, event: ChatInput.EnterPressed) -> None:
        """Handle Enter key when palette is visible."""
        palette = self.query_one(CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)

        # If palette has highlighted option, select it
        # Otherwise, submit the current input directly
        if palette.is_visible and palette.has_highlighted():
            palette.select_highlighted()
        else:
            # No matching command, submit as-is
            palette.hide()
            chat_input.palette_visible = False
            text = chat_input.text.strip()
            if text:
                chat_input.post_message(ChatInput.Submitted(text))

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle user input submission.

        Args:
            event: The submitted event with message content.
        """
        message = event.value.strip()
        if not message:
            return

        # Hide palette if visible
        palette = self.query_one(CommandPalette)
        chat_input = self.query_one("#chat-input", ChatInput)
        if palette.is_visible:
            palette.hide()
            chat_input.palette_visible = False

        # Clear input
        chat_input.clear()

        # Check for slash commands
        if is_command(message):
            await handle_command(self, message)
            return

        # Add user message to chat
        self._add_user_message(message)

        # Run chat processing in background worker to keep UI responsive
        self.run_worker(self._process_chat(message), exclusive=True)

    async def _process_chat(self, message: str) -> None:
        """Process a chat message through the agent.

        Args:
            message: User message to send.
        """
        if not self._agent:
            return

        container = self.query_one("#chat-container")

        # Show thinking indicator
        thinking = ThinkingIndicator()
        await container.mount(thinking)
        self.call_after_refresh(container.scroll_end, animate=False)

        # Track if we've received first response
        first_response = True

        try:
            async for event in self._agent.chat(message):
                # Remove thinking indicator on first response
                if first_response:
                    first_response = False
                    await thinking.remove()
                    # Create assistant message container
                    self._current_message = self._add_assistant_message()

                if isinstance(event, TextEvent):
                    # Append text to current message
                    if self._current_message:
                        self._current_message.append_text(event.text)
                        # Scroll to show new content
                        self.call_after_refresh(container.scroll_end, animate=False)

                elif isinstance(event, ToolStartEvent):
                    # Add tool panel, track by tool_id
                    tool_name = format_tool_name(event.tool_name)
                    panel = ToolPanel(
                        tool_name=tool_name,
                        tool_input=event.tool_input,
                    )
                    self._tool_panels[event.tool_id] = panel
                    await container.mount(panel)
                    panel.refresh()  # Force refresh to ensure immediate rendering
                    self.call_after_refresh(container.scroll_end, animate=False)
                    # Wait for mount and initial render to complete
                    await asyncio.sleep(0.1)

                elif isinstance(event, ToolEndEvent):
                    # Find panel by tool_id and update status
                    panel = self._tool_panels.pop(event.tool_id, None)
                    if panel:
                        panel.set_result(event.result, event.is_error)
                        # Remove panel on success, keep on error for visibility
                        if not event.is_error:
                            await asyncio.sleep(0.5)  # Delay to ensure user sees the result
                            await panel.remove()

                elif isinstance(event, DoneEvent):
                    # Update status bar
                    status_bar = self.query_one(StatusBar)
                    status_bar.update_stats(
                        event.cost_usd,
                        event.input_tokens,
                        event.output_tokens,
                    )

        except Exception as e:
            # Remove thinking indicator if still present
            if first_response:
                await thinking.remove()
            self._add_error_message(str(e))

        finally:
            self._current_message = None
            # Scroll to bottom
            self.call_after_refresh(container.scroll_end, animate=False)

    def _add_user_message(self, content: str) -> MessageView:
        """Add a user message to the chat.

        Args:
            content: Message content.

        Returns:
            The created MessageView widget.
        """
        msg = MessageView(role="user", content=content)
        container = self.query_one("#chat-container")
        container.mount(msg)
        self.call_after_refresh(container.scroll_end, animate=False)
        return msg

    def _add_assistant_message(self, content: str = "") -> MessageView:
        """Add an assistant message to the chat.

        Args:
            content: Initial message content.

        Returns:
            The created MessageView widget.
        """
        msg = MessageView(role="assistant", content=content)
        container = self.query_one("#chat-container")
        container.mount(msg)
        self.call_after_refresh(container.scroll_end, animate=False)
        return msg

    def _add_system_message(self, content: str) -> None:
        """Add a system message to the chat.

        Args:
            content: Message content.
        """
        msg = MessageView(role="system", content=content)
        container = self.query_one("#chat-container")
        container.mount(msg)

    def _add_error_message(self, content: str) -> None:
        """Add an error message to the chat.

        Args:
            content: Error message content.
        """
        msg = MessageView(role="error", content=f"Error: {content}")
        container = self.query_one("#chat-container")
        container.mount(msg)
        self.call_after_refresh(container.scroll_end, animate=False)

    def clear_messages(self) -> None:
        """Clear all messages from the chat."""
        container = self.query_one("#chat-container")
        container.remove_children()
        self._add_system_message("Chat cleared. Type /help for commands.")

    def scroll_up(self) -> None:
        """Scroll chat container up."""
        container = self.query_one("#chat-container")
        # Scroll by 5 lines instead of full page
        container.scroll_relative(y=-5, animate=False)

    def scroll_down(self) -> None:
        """Scroll chat container down."""
        container = self.query_one("#chat-container")
        # Scroll by 5 lines instead of full page
        container.scroll_relative(y=5, animate=False)

    def show_usage(self) -> None:
        """Show API usage statistics."""
        if self._agent:
            self._add_system_message(str(self._agent.usage))

    def enter_plan_mode(self, task: str) -> None:
        """Enter plan mode with the given task.

        Args:
            task: The task to plan for.
        """
        self.plan_mode = True
        self.plan_task = task

        # Update UI
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.add_class("plan-mode")

        status_bar = self.query_one(StatusBar)
        status_bar.set_plan_mode(True, task)

        self._add_system_message(
            f"**Entered Plan Mode**\n\n"
            f"Task: {task}\n\n"
            f"Write tools are disabled. Use `/approve` to execute the plan or `/reject` to cancel."
        )

        # Send initial planning message to agent
        self.run_worker(
            self._process_chat(
                f"[Plan Mode] Task: {task}\n\nPlease create a detailed plan for this task. Do NOT make any changes yet - only provide a plan."
            ),
            exclusive=True,
        )

    def exit_plan_mode(self, approved: bool = False) -> None:
        """Exit plan mode.

        Args:
            approved: Whether the plan was approved (True) or rejected (False).
        """
        task = self.plan_task
        self.plan_mode = False
        self.plan_task = ""

        # Update UI
        chat_input = self.query_one("#chat-input", ChatInput)
        chat_input.remove_class("plan-mode")

        status_bar = self.query_one(StatusBar)
        status_bar.set_plan_mode(False)

        if approved:
            self._add_system_message("**Plan Approved** - Switching to Execute Mode.")
            # Send approval message to agent
            self.run_worker(
                self._process_chat(
                    f"[Execute Mode] The plan for '{task}' has been approved. Please proceed with the implementation."
                ),
                exclusive=True,
            )
        else:
            self._add_system_message("**Plan Rejected** - Exited Plan Mode.")

    def show_mode_status(self) -> None:
        """Show current mode status."""
        if self.plan_mode:
            self._add_system_message(
                f"**Current Mode:** Plan Mode\n"
                f"**Task:** {self.plan_task}\n\n"
                f"Use `/approve` to execute or `/reject` to cancel."
            )
        else:
            self._add_system_message("**Current Mode:** Normal Mode")
