"""Textual-based TUI viewer for ulogger."""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, RichLog, Static, OptionList
from textual.widgets.option_list import Option
from textual.screen import Screen
from textual.reactive import reactive
from textual import work
from textual.message import Message
from rich.text import Text
from queue import Empty
import threading

from .buffer import PersistantIndexCircularBuffer as Buffer
from .messages import ControlMsg
from .logs import LogEntry

# Log levels
LOG_LEVELS = [
    "ERROR", "WARN", "MILE", "INFO", "TRACE", "DEBUG0", "DEBUG1", "DEBUG2", "DEBUG3"
]

DEFAULT_LOG_LEVEL = 8  # Show all levels by default

# Color mapping for log levels
LEVEL_COLORS = {
    0: "red",           # ERROR
    1: "yellow",        # WARN
    2: "bright_yellow", # MILE
    3: "green",         # TRACE
    4: "blue",          # INFO
    5: "white",         # DEBUG0
    6: "bright_black",  # DEBUG1
    7: "dim white",     # DEBUG2
    8: "dim",           # DEBUG3
}


class StatusBar(Static):
    """Custom status bar widget."""

    elf_status = reactive("NO_ELF")
    comm_port = reactive("")
    elf_file = reactive("")
    log_count = reactive(0)
    filter_info = reactive("")

    def render(self) -> Text:
        """Render the status bar."""
        status_color = {
            "NO_ELF": "yellow",
            "OK": "green",
            "BAD": "red"
        }.get(self.elf_status, "white")

        text = Text()
        text.append(f" ELF: ", style="bold")
        text.append(f"{self.elf_status} ", style=f"bold {status_color}")
        text.append(f"| Port: {self.comm_port} ", style="dim")
        text.append(f"| File: {self.elf_file} ", style="dim")
        text.append(f"| Logs: {self.log_count}", style="bold cyan")
        if self.filter_info:
            text.append(f" | ", style="dim")
            text.append(self.filter_info, style="bold yellow")
        return text


class FileFilterScreen(Screen):
    """Modal screen for selecting file filter."""

    CSS = """
    FileFilterScreen {
        align: center middle;
        background: $background 20%;  /* Semi-transparent background */
    }

    FileFilterScreen > OptionList {
        width: 70;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $panel;
    }
    """

    def __init__(self, file_counts: dict, selected_files: set = None, parent_viewer=None):
        super().__init__()
        self.file_counts = file_counts
        self.selected_files = selected_files.copy() if selected_files else set(file_counts.keys())
        self.parent_viewer = parent_viewer

    def compose(self) -> ComposeResult:
        """Create the file selection list."""
        option_list = OptionList(id="file_list")

        # Calculate total logs
        total_logs = sum(self.file_counts.values())

        # Add "Show all" option
        from rich.text import Text
        text = Text()
        text.append("[Show all]", style="bold cyan")
        text.append(f" ({total_logs} logs)", style="dim")
        option_list.add_option(Option(text, id="__all__"))

        # Add each file with tick/cross indicator
        for filename in sorted(self.file_counts.keys()):
            count = self.file_counts[filename]

            if filename in self.selected_files:
                indicator = "✓"
                indicator_color = "green"
            else:
                indicator = "✗"
                indicator_color = "red"

            text = Text()
            text.append(indicator, style=f"bold {indicator_color}")
            text.append(f" {filename}", style="white")
            text.append(f" ({count} logs)", style="dim")
            option_list.add_option(Option(text, id=filename))

        yield option_list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle file selection and apply immediately."""
        if event.option.id == "__all__":
            # Enable all files
            self.selected_files = set(self.file_counts.keys())
            if self.parent_viewer:
                self.parent_viewer.filter_files = None  # None means show all
                self.parent_viewer.post_message(self.parent_viewer.RefreshTable())
            # Don't dismiss - let user continue selecting
            return

        filename = event.option.id

        # Toggle the file
        if filename in self.selected_files:
            self.selected_files.discard(filename)
        else:
            self.selected_files.add(filename)

        # Update parent immediately
        if self.parent_viewer:
            if len(self.selected_files) == len(self.file_counts):
                # All files selected = show all
                self.parent_viewer.filter_files = None
            else:
                self.parent_viewer.filter_files = self.selected_files.copy()
            self.parent_viewer.post_message(self.parent_viewer.RefreshTable())

        # Refresh the option text
        option_list = self.query_one("#file_list", OptionList)

        if filename in self.selected_files:
            indicator = "✓"
            indicator_color = "green"
        else:
            indicator = "✗"
            indicator_color = "red"

        count = self.file_counts[filename]
        from rich.text import Text
        text = Text()
        text.append(indicator, style=f"bold {indicator_color}")
        text.append(f" {filename}", style="white")
        text.append(f" ({count} logs)", style="dim")

        option_list.replace_option_prompt_at_index(
            event.option_index,
            text
        )

    def on_key(self, event) -> None:
        """Handle escape key to cancel."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss(self.selected_files)


class LevelFilterScreen(Screen):
    """Modal screen for selecting log levels to display."""

    CSS = """
    LevelFilterScreen {
        align: center middle;
        background: $background 20%;  /* Semi-transparent background */
    }

    LevelFilterScreen > OptionList {
        width: 50;
        height: auto;
        max-height: 15;
        border: thick $primary;
        background: $panel;
    }
    """

    def __init__(self, selected_levels: set, parent_viewer=None):
        super().__init__()
        self.selected_levels = selected_levels.copy()
        self.parent_viewer = parent_viewer

    def compose(self) -> ComposeResult:
        """Create the level selection list."""
        option_list = OptionList(id="level_list")

        # Add each level with colored tick/cross indicator
        for i, level_name in enumerate(LOG_LEVELS):
            if i in self.selected_levels:
                indicator = "✓"
                indicator_color = "green"
            else:
                indicator = "✗"
                indicator_color = "red"

            level_color = LEVEL_COLORS.get(i, "white")
            # Create rich text for the option
            from rich.text import Text
            text = Text()
            text.append(indicator, style=f"bold {indicator_color}")
            text.append(f" {level_name}", style=level_color)
            option_list.add_option(Option(text, id=str(i)))

        yield option_list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Toggle level selection and apply immediately."""
        level_idx = int(event.option.id)

        # Toggle the level
        if level_idx in self.selected_levels:
            self.selected_levels.discard(level_idx)
        else:
            self.selected_levels.add(level_idx)

        # Update parent immediately if available
        if self.parent_viewer:
            self.parent_viewer.filter_levels = self.selected_levels.copy()
            self.parent_viewer.post_message(self.parent_viewer.RefreshTable())

        # Refresh the option text with colored indicator
        option_list = self.query_one("#level_list", OptionList)
        if level_idx in self.selected_levels:
            indicator = "✓"
            indicator_color = "green"
        else:
            indicator = "✗"
            indicator_color = "red"

        level_name = LOG_LEVELS[level_idx]
        level_color = LEVEL_COLORS.get(level_idx, "white")

        from rich.text import Text
        text = Text()
        text.append(indicator, style=f"bold {indicator_color}")
        text.append(f" {level_name}", style=level_color)

        option_list.replace_option_prompt_at_index(
            event.option_index,
            text
        )

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss(self.selected_levels)
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            self.dismiss(self.selected_levels)


class LogViewer(App):
    """A Textual app for viewing ulogger output."""

    class RefreshTable(Message):
        """Message to trigger table refresh."""
        pass

    CSS = """
    Screen {
        background: $surface;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
    }

    RichLog {
        height: 1fr;
        background: $surface;
    }
    """

    BINDINGS = [
        ("q", "request_quit", "Quit"),
        ("ctrl+c", "request_quit", "Quit"),
        ("z", "toggle_freeze", "Freeze/Unfreeze"),
        ("c", "clear", "Clear"),
        ("l", "show_level_filter", "Level Filter"),
        ("plus", "expand_level_filter", "Add Level"),
        ("minus", "contract_level_filter", "Remove Level"),
        ("f", "toggle_file_filter", "File Filter"),
        ("r", "reset_filters", "Reset Filters"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("home", "scroll_home", "Top"),
        ("end", "scroll_end", "Bottom"),
    ]

    def __init__(self, queue, args):
        super().__init__()
        self.queue = queue
        self.args = args
        self.comm_port = args.comm
        self.elf_file = args.elf
        self.log_buffer = Buffer(maxlen=args.buffer_depth)
        self.log_start = None
        self.buffer_lock = threading.RLock()
        self.frozen = False
        self.frozen_index = None
        self.display_log_level = DEFAULT_LOG_LEVEL
        self.elf_status = "NO_ELF"
        self.running = True
        self.serial_reader = None
        self.elf_reader = None

        # Filter settings
        self.filter_levels = set(range(len(LOG_LEVELS)))  # Set of level indices to show (default: all)
        self.filter_files = None  # None means show all files, otherwise set of filenames

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield RichLog(id="log_table", highlight=True, markup=True)
        yield StatusBar(id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the log widget when the app mounts."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.can_focus = True

        # Update status bar
        status = self.query_one("#status_bar", StatusBar)
        status.comm_port = self.comm_port
        status.elf_file = self.elf_file
        status.elf_status = self.elf_status

        # Start background worker to poll queue
        self.poll_queue()

    def on_key(self, event) -> None:
        """Handle key presses at the app level."""
        if event.key == "q":
            event.prevent_default()
            event.stop()
            self.action_request_quit()
        elif event.key == "z":
            event.prevent_default()
            event.stop()
            self.action_toggle_freeze()
        elif event.key == "c":
            event.prevent_default()
            event.stop()
            self.action_clear()

    def on_log_viewer_refresh_table(self, message: RefreshTable) -> None:
        """Handle refresh table message."""
        self.refresh_table()

    @work(exclusive=True, thread=True)
    def poll_queue(self) -> None:
        """Background worker to poll the message queue."""
        while self.running:
            try:
                msg = self.queue.get(timeout=0.1)
                self.handle_message(msg)
            except Empty:
                continue
            except Exception as e:
                self.log(f"Error in poll_queue: {e}")

    def handle_message(self, msg) -> None:
        """Handle a message from the queue."""
        if isinstance(msg, ControlMsg):
            if msg == ControlMsg.QUIT:
                self.running = False
                self.exit()
            elif msg == ControlMsg.WAIT_FOR_ELF:
                self.elf_status = "NO_ELF"
                self.update_status()
            elif msg == ControlMsg.ELF_OK:
                self.elf_status = "OK"
                self.update_status()
            elif msg == ControlMsg.FAILED_TO_READ_ELF:
                self.elf_status = "BAD"
                self.update_status()
            elif msg == ControlMsg.RELOADED_ELF:
                self.elf_status = "OK"
                self.update_status()
                self.call_from_thread(self.clear_logs)
            elif msg == ControlMsg.BAD_DATA:
                # Could show an error message
                pass
        elif isinstance(msg, LogEntry):
            self.add_log_entry(msg)

    def update_status(self) -> None:
        """Update the status bar."""
        def _update():
            status = self.query_one("#status_bar", StatusBar)
            status.elf_status = self.elf_status
            with self.buffer_lock:
                status.log_count = len(self.log_buffer)

        self.call_from_thread(_update)

    def get_file_counts(self) -> dict:
        """Get dictionary of files with their log entry counts from ELF."""
        if self.elf_reader and self.elf_reader.logs.elf_ready:
            counts = {}
            for entry in self.elf_reader.logs.entries:
                filename = entry.filename
                counts[filename] = counts.get(filename, 0) + 1
            return counts
        return {}

    def passes_filter(self, entry: LogEntry) -> bool:
        """Check if log entry passes current filters."""
        # Check level filter - entry.level must be in the selected set
        if entry.level not in self.filter_levels:
            return False

        # Check file filter - if filter_files is None, show all files
        if self.filter_files is not None:
            if entry.filename not in self.filter_files:
                return False

        return True

    def add_log_entry(self, entry: LogEntry) -> None:
        """Add a log entry to the buffer and table."""
        with self.buffer_lock:


            self.log_buffer.append(entry)

            # Only update display if not frozen
            if not self.frozen:
                self.post_message(self.RefreshTable())

    def refresh_table(self) -> None:
        """Refresh the entire log widget from the buffer."""
        log_widget = self.query_one("#log_table", RichLog)

        with self.buffer_lock:
            # Clear and rebuild log
            log_widget.clear()

            displayed = 0
            for entry in self.log_buffer.latest_slice(1000):  # Show last 1000 entries
                if self.passes_filter(entry):
                    self.add_log_line(log_widget, entry)
                    displayed += 1

            # Update status
            status = self.query_one("#status_bar", StatusBar)
            status.log_count = len(self.log_buffer)
            status.filter_info = self._get_filter_info(displayed)

    def add_log_line(self, log_widget: RichLog, entry: LogEntry) -> None:
        """Add a single log line to the widget."""
        # Format timestamp
        ts_str = self.format_time(entry.timestamp)

        # Format level
        level_str = LOG_LEVELS[entry.level] if entry.level < len(LOG_LEVELS) else f"L{entry.level}"
        level_color = LEVEL_COLORS.get(entry.level, "white")

        # Format file:line
        file_line = f"{entry.filename}:{entry.line}"

        # Format message - check if format string has {} style formatters
        message = self.format_message(entry.fmt, entry.data)

        # Create formatted log line
        line = Text()
        line.append(f"{ts_str} ", style="cyan")
        line.append(f"{level_str:8} ", style=level_color)
        line.append(f"{file_line:30} ", style="blue")
        line.append(message, style=level_color)

        log_widget.write(line)

    def format_message(self, fmt: str, data: tuple) -> str:
        """Format message with proper handling of {} and {:02x} style formatters."""
        if not fmt:
            return str(data) if data else ""

        # Check if the format string contains {} style formatters
        if '{' in fmt and '}' in fmt:
            try:
                # New-style formatting with {} placeholders
                if isinstance(data, tuple):
                    return fmt.format(*data)
                else:
                    return fmt.format(data)
            except (IndexError, KeyError, ValueError) as e:
                # If formatting fails, show format string and data
                return f"{fmt} {data}"
        else:
            # No formatters - just append data naturally
            if data:
                data_str = ', '.join(str(d) for d in data) if isinstance(data, tuple) else str(data)
                return f"{fmt} [{data_str}]"
            else:
                return fmt

    def format_time(self, timestamp: float) -> str:
        """Format timestamp as elapsed time."""
        if self.log_start is None:
            self.log_start = timestamp

        elapsed = timestamp - self.log_start
        seconds = int(elapsed)
        ms = int((elapsed - seconds) * 10000)

        if seconds < 10000:
            return f"{seconds:04}.{ms:04}"
        else:
            return f"+{seconds:03}.{ms:04}"

    def _get_filter_info(self, displayed: int) -> str:
        """Get filter info string for status bar."""
        parts = []
        # Show level filter if not showing all levels
        if len(self.filter_levels) < len(LOG_LEVELS):
            if len(self.filter_levels) == 0:
                parts.append("Lvl:NONE")
            else:
                level_names = [LOG_LEVELS[i] for i in sorted(self.filter_levels) if i < len(LOG_LEVELS)]
                if len(level_names) <= 3:
                    parts.append(f"Lvl:{','.join(level_names)}")
                else:
                    parts.append(f"Lvl:{len(level_names)} selected")
        if self.filter_files is not None and len(self.filter_files) > 0:
            all_files = self.get_file_counts().keys()
            if len(self.filter_files) == len(all_files):
                # All files selected - don't show filter
                pass
            elif len(self.filter_files) == 1:
                parts.append(f"File:{list(self.filter_files)[0]}")
            else:
                parts.append(f"Files:{len(self.filter_files)} selected")

        if parts:
            filter_str = " & ".join(parts)
            return f"Filter: {filter_str} ({displayed} shown)"
        return ""

    def action_show_level_filter(self) -> None:
        """Show level filter selection dialog."""
        self.push_screen(
            LevelFilterScreen(self.filter_levels, parent_viewer=self),
            callback=self._on_levels_selected
        )

    def _on_levels_selected(self, selected_levels: set) -> None:
        """Handle level selection from modal."""
        self.filter_levels = selected_levels
        self.refresh_table()

    def action_expand_level_filter(self) -> None:
        """Expand filter to include the next disabled level and all levels up to it.

        If MILE and DEBUG0 are selected, pressing + will enable all levels from ERROR to DEBUG1.
        """
        if len(self.filter_levels) == len(LOG_LEVELS):
            # Already showing all levels
            return

        if len(self.filter_levels) == 0:
            # Start with ERROR only
            self.filter_levels = {0}
        else:
            # Find the highest enabled level
            max_enabled = max(self.filter_levels)

            # Find the next level to enable
            next_level = max_enabled + 1
            if next_level >= len(LOG_LEVELS):
                # No more levels to add
                return

            # Enable all levels from 0 to next_level (inclusive)
            self.filter_levels = set(range(next_level + 1))

        self.refresh_table()

    def action_contract_level_filter(self) -> None:
        """Contract filter by removing the highest enabled level.

        Maintains a continuous range from ERROR (0) to some max level.
        """
        if len(self.filter_levels) == 0:
            return

        # Find the highest enabled level
        max_enabled = max(self.filter_levels)

        if max_enabled == 0:
            # Can't contract below ERROR - would leave empty set
            return

        # Create range from 0 to (max_enabled - 1)
        self.filter_levels = set(range(max_enabled))
        self.refresh_table()

    def action_toggle_file_filter(self) -> None:
        """Show file filter selection dialog."""
        self.notify("File filter action triggered", timeout=1)
        file_counts = self.get_file_counts()
        self.notify(f"Got {len(file_counts)} files from ELF", timeout=2)
        if not file_counts:
            # No ELF loaded yet - can't show file filter
            self.notify("No ELF file loaded yet", severity="warning", timeout=2)
            return

        # Determine currently selected files
        if self.filter_files is None:
            selected_files = set(file_counts.keys())  # All files
        else:
            selected_files = self.filter_files

        self.notify("About to push screen", timeout=1)
        # Push the file filter screen
        self.push_screen(
            FileFilterScreen(file_counts, selected_files, parent_viewer=self),
            callback=self._on_file_selected
        )
        self.notify("Screen pushed", timeout=1)

    def _on_file_selected(self, selected_files: set) -> None:
        """Handle file selection from modal."""
        all_files = self.get_file_counts().keys()
        if len(selected_files) == len(all_files):
            self.filter_files = None  # All files = no filter
        else:
            self.filter_files = selected_files
        self.refresh_table()

    def action_reset_filters(self) -> None:
        """Reset all filters to default."""
        self.filter_levels = set(range(len(LOG_LEVELS)))  # Show all levels
        self.filter_files = None  # Show all files
        self.refresh_table()

    def action_toggle_freeze(self) -> None:
        """Toggle freeze state."""
        self.frozen = not self.frozen
        if not self.frozen:
            self.refresh_table()

    def action_clear(self) -> None:
        """Clear all logs."""
        self.clear_logs()

    def clear_logs(self) -> None:
        """Clear the log buffer and widget."""
        with self.buffer_lock:
            self.log_buffer = Buffer(maxlen=self.args.buffer_depth)
            self.log_start = None

        log_widget = self.query_one("#log_table", RichLog)
        log_widget.clear()

        status = self.query_one("#status_bar", StatusBar)
        status.log_count = 0

    def action_scroll_up(self) -> None:
        """Scroll up one row."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_up()

    def action_scroll_down(self) -> None:
        """Scroll down one row."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_down()

    def action_page_up(self) -> None:
        """Scroll up one page."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_page_up()

    def action_page_down(self) -> None:
        """Scroll down one page."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_page_down()

    def action_scroll_home(self) -> None:
        """Scroll to top."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_home()

    def action_scroll_end(self) -> None:
        """Scroll to bottom."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.scroll_end()

    def action_request_quit(self) -> None:
        """Quit the application and stop all threads."""
        # Stop background processing
        self.running = False

        # Exit the Textual app - this will trigger on_unmount
        self.exit()

    def on_unmount(self) -> None:
        """Clean up when the app is unmounting."""
        self.running = False

        # Ensure readers are stopped
        if self.serial_reader:
            self.serial_reader.stop()
        if self.elf_reader:
            self.elf_reader.stop()
