"""Textual-based TUI viewer for ulogger."""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, RichLog, Static
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
        return text


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
        ("f", "toggle_freeze", "Freeze/Unfreeze"),
        ("c", "clear", "Clear"),
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
        elif event.key == "f":
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

    def add_log_entry(self, entry: LogEntry) -> None:
        """Add a log entry to the buffer and table."""
        with self.buffer_lock:
            # Filter by log level
            if entry.level > self.display_log_level:
                return

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

            for entry in self.log_buffer.latest_slice(1000):  # Show last 1000 entries
                self.add_log_line(log_widget, entry)

            # Update status
            status = self.query_one("#status_bar", StatusBar)
            status.log_count = len(self.log_buffer)

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
