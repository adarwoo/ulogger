"""Textual-based TUI viewer for ulogger."""
from textual.app import App, ComposeResult
from textual.widgets import Footer, RichLog, Static, OptionList, Input
from textual.widgets.option_list import Option
from textual.screen import Screen, ModalScreen
from textual.reactive import reactive
from textual import work
from textual.message import Message
from rich.text import Text
from queue import Empty
import threading
from pathlib import Path
import time

from .buffer import PersistantIndexCircularBuffer as Buffer
from .messages import ControlMsg
from .logs import LogEntry
from .settings import get_settings

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


class LevelIndicatorHeader(Static):
    """Custom header showing active log levels."""

    active_levels = reactive(set())
    comm_port = reactive("")

    def render(self) -> Text:
        """Render the header with level indicators and version."""
        text = Text()
        text.append("uLogger v1.1.0", style="bold cyan")

        # Add COM port if available
        if self.comm_port:
            text.append(" | ", style="dim")
            text.append(f"Port: {self.comm_port}", style="green")

        text.append(" | Levels: ", style="dim")

        # Show each level with appropriate letter
        for i, level_name in enumerate(LOG_LEVELS):
            # Use digit for DEBUG levels, first letter for others
            if level_name.startswith("DEBUG"):
                display_char = level_name[-1]  # Get the digit (0, 1, 2, 3)
            else:
                display_char = level_name[0]  # E, W, M, I, T

            if i in self.active_levels:
                # Active - show in level color
                color = LEVEL_COLORS.get(i, "white")
                text.append(display_char, style=f"bold {color}")
            else:
                # Inactive - show in dark grey
                text.append(display_char, style="rgb(60,60,60)")

            # Add space between letters
            if i < len(LOG_LEVELS) - 1:
                text.append(" ", style="")

        return text


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


class ElfFileSelectionScreen(ModalScreen[str]):
    """Modal screen for selecting ELF file from recent files or file system."""

    CSS = """
    ElfFileSelectionScreen {
        align: center middle;
        background: $background 80%;
    }

    #selection_container {
        width: 80;
        height: 25;
        border: thick $primary;
        background: $panel;
        layout: vertical;
    }

    #selection_title {
        height: 1;
        content-align: center middle;
        background: $primary;
        color: $text;
    }

    #file_options {
        height: 1fr;
    }
    """

    def __init__(self):
        super().__init__()
        self.settings = get_settings()

    def compose(self) -> ComposeResult:
        """Create the file selection interface."""
        from textual.containers import Container

        with Container(id="selection_container"):
            yield Static("Select ELF File", id="selection_title")
            yield OptionList(id="file_options")

    def on_mount(self) -> None:
        """Populate the file list when mounted."""
        option_list = self.query_one("#file_options", OptionList)

        # Add "Browse for file..." option
        browse_text = Text()
        browse_text.append("📁 ", style="bold yellow")
        browse_text.append("Browse for new file...", style="bold cyan")
        option_list.add_option(Option(browse_text, id="__browse__"))

        # Add separator
        option_list.add_option(Option(Text("─" * 60, style="dim"), id="__separator__", disabled=True))

        # Add recent files
        recent_files = self.settings.get_recent_files()
        if recent_files:
            for filepath in recent_files:
                path = Path(filepath)
                text = Text()
                text.append("📄 ", style="bold green")
                text.append(path.name, style="white")
                text.append(f"\n   {path.parent}", style="dim")
                option_list.add_option(Option(text, id=filepath))
        else:
            option_list.add_option(Option(Text("No recent files", style="dim italic"), id="__none__", disabled=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle file selection."""
        if event.option.id == "__browse__":
            # Open file browser
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            filepath = filedialog.askopenfilename(
                title="Select ELF File",
                filetypes=[("ELF files", "*.elf"), ("All files", "*.*")]
            )
            root.destroy()

            if filepath:
                self.dismiss(filepath)
            else:
                # User cancelled, just close the dialog
                return
        elif event.option.id not in ["__separator__", "__none__"]:
            # Selected a recent file
            self.dismiss(event.option.id)

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss(None)


class ComPortSelectionScreen(ModalScreen[str]):
    """Modal screen for selecting COM port."""

    CSS = """
    ComPortSelectionScreen {
        align: center middle;
        background: $background 80%;
    }

    #comport_container {
        width: 60;
        height: 20;
        border: thick $primary;
        background: $panel;
        layout: vertical;
    }

    #comport_title {
        height: 1;
        content-align: center middle;
        background: $primary;
        color: $text;
    }

    #comport_options {
        height: 1fr;
    }
    """

    def __init__(self, current_port: str = None):
        super().__init__()
        self.current_port = current_port

    def compose(self) -> ComposeResult:
        """Create the COM port selection interface."""
        from textual.containers import Container

        with Container(id="comport_container"):
            yield Static("Select COM Port", id="comport_title")
            yield OptionList(id="comport_options")

    def on_mount(self) -> None:
        """Populate the COM port list when mounted."""
        option_list = self.query_one("#comport_options", OptionList)

        # Add "No COM port (offline mode)" option
        no_port_text = Text()
        no_port_text.append("⊗ ", style="bold yellow")
        no_port_text.append("No COM port (offline mode)", style="dim italic")
        option_list.add_option(Option(no_port_text, id="__none__"))

        # Add separator
        option_list.add_option(Option(Text("─" * 50, style="dim"), id="__separator__", disabled=True))

        # Add available COM ports
        from .settings import Settings
        ports = Settings.list_comports()

        if ports:
            for port in ports:
                text = Text()
                if port == self.current_port:
                    text.append("● ", style="bold green")
                    text.append(port, style="bold white")
                    text.append(" (current)", style="dim")
                else:
                    text.append("○ ", style="bold blue")
                    text.append(port, style="white")
                option_list.add_option(Option(text, id=port))
        else:
            option_list.add_option(Option(Text("No COM ports found", style="dim italic"), id="__empty__", disabled=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle COM port selection."""
        if event.option.id == "__none__":
            self.dismiss(None)
        elif event.option.id not in ["__separator__", "__empty__"]:
            self.dismiss(event.option.id)

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss(None)


class LogEntriesViewScreen(Screen):
    """Modal screen for displaying all log entry definitions from ELF."""

    CSS = """
    LogEntriesViewScreen {
        align: center middle;
        background: $background 20%;
    }

    #entries_container {
        width: 95%;
        height: 85%;
        border: thick $primary;
        background: $panel;
        layout: vertical;
    }

    #search_input {
        height: 1;
        border: none;
        background: $panel;
        margin: 0 1;
        display: none;
    }

    #entries_list {
        height: 1fr;
    }

    #entries_footer {
        height: 1;
        background: $panel;
        color: $text;
        dock: bottom;
    }
    """

    BINDINGS = [
        ("s", "cycle_sort", "Sort"),
        ("ctrl+f", "toggle_search", "Search"),
        ("escape", "close_or_clear", "Close"),
    ]

    sort_mode = reactive("none")  # "none", "level", "file"
    search_text = reactive("")

    def __init__(self, elf_reader, filename=None, level=None):
        super().__init__()
        self.elf_reader = elf_reader
        self.filename = filename
        self.level = level
        self.entries = []  # Store filtered entries for sorting/searching
        self.search_active = False

    def compose(self) -> ComposeResult:
        """Create the log entries display."""
        from textual.containers import Container

        with Container(id="entries_container"):
            yield Input(id="search_input", placeholder="Search in statements...")
            yield RichLog(id="entries_list", highlight=True, markup=True)

            # Add a custom footer inside the container
            footer_text = Static("S: Sort | Ctrl+F: Search | Esc: Close", id="entries_footer")
            yield footer_text

    def on_mount(self) -> None:
        """Populate the log entries list when mounted."""
        self._update_title()
        self._load_entries()
        self._refresh_display()

    def _update_title(self) -> None:
        """Update the title based on filters and sort mode."""
        title_parts = []

        if self.filename and self.level is not None:
            level_name = LOG_LEVELS[self.level] if self.level < len(LOG_LEVELS) else f"L{self.level}"
            title_parts.append(f"{self.filename} - {level_name}")
        elif self.filename:
            title_parts.append(self.filename)
        elif self.level is not None:
            level_name = LOG_LEVELS[self.level] if self.level < len(LOG_LEVELS) else f"L{self.level}"
            title_parts.append(level_name)
        else:
            title_parts.append("All Log Entry Definitions")

        # Add sort indicator
        if self.sort_mode == "level":
            title_parts.append("Sort: Level")
        elif self.sort_mode == "file":
            title_parts.append("Sort: File")

        container = self.query_one("#entries_container")
        container.border_title = " | ".join(title_parts)

    def _load_entries(self) -> None:
        """Load and filter entries from ELF."""
        self.entries = []

        if not self.elf_reader or not self.elf_reader.logs.elf_ready:
            return

        for entry in self.elf_reader.logs.entries:
            # Apply filters
            if self.filename and entry.filename != self.filename:
                continue
            if self.level is not None and entry.level != self.level:
                continue

            self.entries.append(entry)

    def _refresh_display(self) -> None:
        """Refresh the display with current sort and search."""
        log_widget = self.query_one("#entries_list", RichLog)
        log_widget.clear()

        if not self.elf_reader or not self.elf_reader.logs.elf_ready:
            log_widget.write(Text("No ELF file loaded", style="red bold"))
            return

        # Sort entries
        sorted_entries = self.entries.copy()
        if self.sort_mode == "level":
            sorted_entries.sort(key=lambda e: (e.level, e.filename, e.line))
        elif self.sort_mode == "file":
            sorted_entries.sort(key=lambda e: (e.filename, e.line, e.level))

        # Filter by search text
        if self.search_text:
            search_lower = self.search_text.lower()
            sorted_entries = [
                e for e in sorted_entries
                if search_lower in e.fmt.lower() or
                   search_lower in e.filename.lower()
            ]

        # Display entries
        if sorted_entries:
            for entry in sorted_entries:
                self._add_entry_line(log_widget, entry)
        else:
            if self.search_text:
                log_widget.write(Text(f"No entries matching '{self.search_text}'", style="dim italic"))
            else:
                log_widget.write(Text("No log entries found matching criteria", style="dim italic"))

    def _add_entry_line(self, log_widget: RichLog, entry) -> None:
        """Add a formatted log entry definition line."""
        level_str = LOG_LEVELS[entry.level] if entry.level < len(LOG_LEVELS) else f"L{entry.level}"
        level_color = LEVEL_COLORS.get(entry.level, "white")
        file_line = f"{entry.filename}:{entry.line}"

        # Format the variable types - convert type objects to strings
        if entry.types:
            type_names = [t.__name__ if hasattr(t, '__name__') else str(t) for t in entry.types]
            var_types = ', '.join(type_names)
        else:
            var_types = "none"

        line = Text()
        line.append(f"{level_str:8} ", style=level_color)
        line.append(f"{file_line:35} ", style="blue")
        line.append(f"{entry.fmt:60} ", style="white")
        line.append(f"[{var_types}]", style="dim cyan")

        log_widget.write(line)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        self.search_text = event.value
        self._refresh_display()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes (live search)."""
        self.search_text = event.value
        self._refresh_display()

    def action_cycle_sort(self) -> None:
        """Cycle through sort modes."""
        if self.sort_mode == "none":
            self.sort_mode = "level"
        elif self.sort_mode == "level":
            self.sort_mode = "file"
        else:
            self.sort_mode = "none"
        self._update_title()
        self._refresh_display()

    def action_toggle_search(self) -> None:
        """Toggle search input."""
        search_input = self.query_one("#search_input", Input)
        if self.search_active:
            search_input.display = False
            self.search_active = False
            self.search_text = ""
            self._refresh_display()
        else:
            search_input.display = True
            self.search_active = True
            search_input.focus()

    def action_close_or_clear(self) -> None:
        """Close search if active, otherwise close the screen."""
        if self.search_active:
            search_input = self.query_one("#search_input", Input)
            search_input.display = False
            self.search_active = False
            self.search_text = ""
            self._refresh_display()
        else:
            self.dismiss()

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        # Allow on_key as fallback for any keys not handled by actions
        pass


class LogLineListScreen(Screen):
    """Modal screen for displaying filtered log lines."""

    CSS = """
    LogLineListScreen {
        align: center middle;
        background: $background 20%;
    }

    LogLineListScreen > RichLog {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $panel;
    }
    """

    def __init__(self, log_buffer, buffer_lock, filename=None, level=None, parent_viewer=None):
        super().__init__()
        self.log_buffer = log_buffer
        self.buffer_lock = buffer_lock
        self.filename = filename
        self.level = level
        self.parent_viewer = parent_viewer

    def compose(self) -> ComposeResult:
        """Create the log display."""
        # Create title based on filters
        if self.filename and self.level is not None:
            level_name = LOG_LEVELS[self.level] if self.level < len(LOG_LEVELS) else f"L{self.level}"
            title = f"Logs: {self.filename} - {level_name}"
        elif self.filename:
            title = f"Logs: {self.filename}"
        elif self.level is not None:
            level_name = LOG_LEVELS[self.level] if self.level < len(LOG_LEVELS) else f"L{self.level}"
            title = f"Logs: {level_name}"
        else:
            title = "All Logs"

        log_widget = RichLog(id="line_list", highlight=True, markup=True)
        log_widget.border_title = title
        yield log_widget

    def on_mount(self) -> None:
        """Populate the log list when mounted."""
        log_widget = self.query_one("#line_list", RichLog)

        with self.buffer_lock:
            count = 0
            for entry in self.log_buffer.latest_slice(10000):
                # Apply filters
                if self.filename and entry.filename != self.filename:
                    continue
                if self.level is not None and entry.level != self.level:
                    continue

                # Format and add line
                self._add_log_line(log_widget, entry)
                count += 1

            if count == 0:
                log_widget.write(Text("No logs found matching criteria", style="dim italic"))

    def _add_log_line(self, log_widget: RichLog, entry: LogEntry) -> None:
        """Add a formatted log line."""
        if self.parent_viewer:
            # Use parent's formatting methods
            ts_str = self.parent_viewer.format_time(entry.timestamp)
            message = self.parent_viewer.format_message(entry.fmt, entry.data)
        else:
            ts_str = f"{entry.timestamp:.4f}"
            message = f"{entry.fmt} {entry.data}" if entry.data else entry.fmt

        level_str = LOG_LEVELS[entry.level] if entry.level < len(LOG_LEVELS) else f"L{entry.level}"
        level_color = LEVEL_COLORS.get(entry.level, "white")
        file_line = f"{entry.filename}:{entry.line}"

        line = Text()
        line.append(f"{ts_str} ", style="cyan")
        line.append(f"{level_str:8} ", style=level_color)
        line.append(f"{file_line:30} ", style="blue")
        line.append(message, style=level_color)

        log_widget.write(line)

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss()


class FileFilterScreen(Screen):
    """Modal screen for selecting file filter."""

    CSS = """
    FileFilterScreen {
        align: center middle;
        background: $background 20%;  /* Semi-transparent background */
    }

    FileFilterScreen > OptionList {
        width: 80;
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
        total_logs = sum(info['total'] for info in self.file_counts.values())

        # Add "None" option
        from rich.text import Text
        text = Text()
        text.append("[None]", style="bold red")
        text.append(" (hide all)", style="dim")
        option_list.add_option(Option(text, id="__none__"))

        # Add "Show all" option
        text = Text()
        text.append("[Show all]", style="bold cyan")
        text.append(f" ({total_logs} logs)", style="dim")
        option_list.add_option(Option(text, id="__all__"))

        # Add each file with tick/cross indicator and level breakdown
        for filename in sorted(self.file_counts.keys()):
            file_info = self.file_counts[filename]
            total_count = file_info['total']
            level_counts = file_info['levels']

            if filename in self.selected_files:
                indicator = "✓"
                indicator_color = "green"
            else:
                indicator = "✗"
                indicator_color = "red"

            # Truncate filename to 20 chars
            display_name = filename[:20] if len(filename) <= 20 else filename[:17] + "..."

            text = Text()
            text.append(indicator, style=f"bold {indicator_color}")
            text.append(f" {display_name:<20}", style="white")  # Left-aligned, padded to 20 chars
            text.append(f" ({total_count:4d}: ", style="dim")

            # Add color-coded counts in fixed order (E W M I D) for alignment, hide zeros
            for i, level_idx in enumerate(range(len(LOG_LEVELS))):
                if i > 0:
                    text.append(" ", style="dim")
                count = level_counts.get(level_idx, 0)
                level_color = LEVEL_COLORS.get(level_idx, "white")
                if count > 0:
                    text.append(f"{count:3d}", style=level_color)
                else:
                    text.append("   ", style="dim")  # Blank space for alignment

            text.append(")", style="dim")
            option_list.add_option(Option(text, id=filename))

        yield option_list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle file selection and apply immediately."""
        if event.option.id == "__none__":
            # Disable all files
            self.selected_files = set()
            if self.parent_viewer:
                self.parent_viewer.filter_files = set()  # Empty set means show nothing
                self.parent_viewer.post_message(self.parent_viewer.RefreshTable())
            # Don't dismiss - let user continue selecting
            return

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

        file_info = self.file_counts[filename]
        total_count = file_info['total']
        level_counts = file_info['levels']

        # Truncate filename to 20 chars
        display_name = filename[:20] if len(filename) <= 20 else filename[:17] + "..."

        from rich.text import Text
        text = Text()
        text.append(indicator, style=f"bold {indicator_color}")
        text.append(f" {display_name:<20}", style="white")  # Left-aligned, padded to 20 chars
        text.append(f" ({total_count:4d}: ", style="dim")

        # Add color-coded counts in fixed order (E W M I D) for alignment, hide zeros
        for i, level_idx in enumerate(range(len(LOG_LEVELS))):
            if i > 0:
                text.append(" ", style="dim")
            count = level_counts.get(level_idx, 0)
            level_color = LEVEL_COLORS.get(level_idx, "white")
            if count > 0:
                text.append(f"{count:3d}", style=level_color)
            else:
                text.append("   ", style="dim")  # Blank space for alignment

        text.append(")", style="dim")

        # Update the option in the list
        option_list.replace_option_prompt_at_index(
            event.option_index,
            text
        )
        event.stop()
        # Don't dismiss - let user continue selecting

    def on_key(self, event) -> None:
        """Handle keyboard events."""
        if event.key == "escape" or event.key == "q":
            event.prevent_default()
            event.stop()
            self.dismiss(self.selected_files)
        elif event.key == "enter":
            # Show all logs for currently highlighted file
            option_list = self.query_one("#file_list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None:
                option = option_list.get_option_at_index(highlighted)
                if option.id not in ["__none__", "__all__"]:
                    filename = option.id
                    if self.parent_viewer:
                        self.app.push_screen(
                            LogLineListScreen(
                                self.parent_viewer.log_buffer,
                                self.parent_viewer.buffer_lock,
                                filename=filename,
                                parent_viewer=self.parent_viewer
                            )
                        )
        elif event.key in "0123456789":
            # Show logs for currently highlighted file at specific level
            level_idx = int(event.key)
            if level_idx < len(LOG_LEVELS):
                option_list = self.query_one("#file_list", OptionList)
                highlighted = option_list.highlighted
                if highlighted is not None:
                    option = option_list.get_option_at_index(highlighted)
                    if option.id not in ["__none__", "__all__"]:
                        filename = option.id
                        if self.parent_viewer:
                            self.app.push_screen(
                                LogLineListScreen(
                                    self.parent_viewer.log_buffer,
                                    self.parent_viewer.buffer_lock,
                                    filename=filename,
                                    level=level_idx,
                                    parent_viewer=self.parent_viewer
                                )
                            )


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

    LevelIndicatorHeader {
        dock: top;
        height: 1;
        background: $panel;
        color: $text;
        content-align: center middle;
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
        ("space", "toggle_freeze", "Freeze/Unfreeze"),
        ("c", "clear", "Clear"),
        ("l", "show_level_filter", "Levels"),
        ("plus", "expand_level_filter", "More"),
        ("minus", "contract_level_filter", "Less"),
        ("f", "toggle_file_filter", "Files"),
        ("p", "select_com_port", "COM Port"),
        ("r", "reset_filters", "Reset Filters"),
        ("e", "view_log_entries", "View Log Entries"),
        ("v", "view_all_lines", "View All Lines"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("home", "scroll_home", "Top"),
        ("end", "scroll_end", "Bottom"),
    ]

    def __init__(self, queue, args, start_readers_callback=None):
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
        self.start_readers_callback = start_readers_callback

        # Filter settings
        self.filter_levels = set(range(len(LOG_LEVELS)))  # Set of level indices to show (default: all)
        self.filter_files = None  # None means show all files, otherwise set of filenames

        # Performance optimization: throttled refresh
        self.pending_refresh = False
        self.last_refresh_time = 0
        self.min_refresh_interval = 0.05  # 20 FPS max
        self.last_displayed_index = -1  # Track last rendered entry for incremental updates

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield LevelIndicatorHeader(id="level_header")
        yield RichLog(id="log_table", highlight=True, markup=True)
        yield StatusBar(id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the log widget when the app mounts."""
        log_widget = self.query_one("#log_table", RichLog)
        log_widget.can_focus = True

        # Load COM port from settings if not provided on command line
        settings = get_settings()
        if not self.comm_port:
            self.comm_port = settings.get_com_port()
        else:
            # Save command line COM port to settings
            settings.set_com_port(self.comm_port)

        # Update args
        self.args.comm = self.comm_port

        # Update status bar and title
        status = self.query_one("#status_bar", StatusBar)
        status.comm_port = self.comm_port or "No port"
        status.elf_file = Path(self.elf_file).name if self.elf_file else ""
        status.elf_status = self.elf_status

        # Update level indicator and header
        level_header = self.query_one("#level_header", LevelIndicatorHeader)
        level_header.comm_port = self.comm_port or "No port"
        self._update_level_indicator()

        # Update title to include COM port
        self.title = f"uLogger - {self.comm_port or 'No port'}"

        # Start background worker to poll queue (always needed)
        self.poll_queue()

        # If no COM port selected, show selection dialog first
        if not self.comm_port:
            self.show_com_port_selection()
        # If no ELF file provided, show selection dialog
        elif not self.args.elf:
            self.show_file_selection()

    def show_file_selection(self) -> None:
        """Show the ELF file selection dialog."""
        def handle_selection(filepath: str) -> None:
            if filepath:
                # Update args with selected file
                self.args.elf = filepath
                self.elf_file = filepath
                self.comm_port = self.args.comm or ""

                # Add to recent files
                from .settings import get_settings
                settings = get_settings()
                settings.add_recent_file(filepath)

                # Update status bar immediately
                status = self.query_one("#status_bar", StatusBar)
                status.elf_file = Path(filepath).name
                status.comm_port = self.comm_port

                # Use the callback to start readers (from main)
                if self.start_readers_callback:
                    success = self.start_readers_callback(self.args, self.queue, self)
                    if not success:
                        self.notify("Failed to start readers", severity="error", timeout=5)
                else:
                    self.notify("No reader callback available", severity="error", timeout=5)
            else:
                # User cancelled
                self.notify("No file selected. Exiting.", timeout=2)
                self.exit()

        self.push_screen(ElfFileSelectionScreen(), callback=handle_selection)

    def show_com_port_selection(self) -> None:
        """Show the COM port selection dialog."""
        def handle_selection(port: str | None) -> None:
            if port is not None:
                # Save to settings
                from .settings import get_settings
                settings = get_settings()
                settings.set_com_port(port)

                # Update local state
                old_port = self.comm_port
                self.comm_port = port
                self.args.comm = port

                # Update status bar and title
                status = self.query_one("#status_bar", StatusBar)
                status.comm_port = port or "No port"

                # Update header
                level_header = self.query_one("#level_header", LevelIndicatorHeader)
                level_header.comm_port = port or "No port"

                self.title = f"uLogger - {port or 'No port'}"

                # If port changed and we're already running, restart serial reader
                if old_port != port and self.elf_file:
                    self.restart_serial_reader()
                    self.notify(f"COM port changed to {port or 'offline mode'}", timeout=3)

                # After setting COM port, check if we need to select ELF file
                if not self.args.elf:
                    self.show_file_selection()

        self.push_screen(ComPortSelectionScreen(), callback=handle_selection)

    def restart_serial_reader(self) -> None:
        """Restart the serial reader with the new COM port."""
        # Stop the existing serial reader if it exists
        if hasattr(self, 'serial_reader_thread') and self.serial_reader_thread:
            if hasattr(self, 'serial_reader') and self.serial_reader:
                # Signal the reader to stop
                self.serial_reader.stop()
                # Wait for thread to finish
                self.serial_reader_thread.join(timeout=2)

        # Start new serial reader if we have a port
        if self.comm_port and self.elf_file:
            from .serial_reader import SerialReader
            import threading

            self.serial_reader = SerialReader(self.comm_port, self.elf_file, self.queue)
            self.serial_reader_thread = threading.Thread(target=self.serial_reader.read_loop, daemon=True)
            self.serial_reader_thread.start()
            self.notify(f"Serial reader started on {self.comm_port}", timeout=2)
        else:
            self.notify("Serial reader stopped (offline mode)", timeout=2)

    def action_select_com_port(self) -> None:
        """Show COM port selection dialog."""
        self.show_com_port_selection()

    def on_key(self, event) -> None:
        """Handle key presses at the app level."""
        if event.key == "q":
            event.prevent_default()
            event.stop()
            self.action_request_quit()
        elif event.key == "space":
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

    def _update_level_indicator(self) -> None:
        """Update the level indicator header with current active levels."""
        level_header = self.query_one("#level_header", LevelIndicatorHeader)
        level_header.active_levels = self.filter_levels.copy()

    def get_file_counts(self) -> dict:
        """Get dictionary of files with their log entry counts and level breakdown from ELF.

        Returns: dict[filename] = {'total': int, 'levels': {level_idx: count}}
        """
        if self.elf_reader and self.elf_reader.logs.elf_ready:
            counts = {}
            for entry in self.elf_reader.logs.entries:
                filename = entry.filename
                if filename not in counts:
                    counts[filename] = {'total': 0, 'levels': {}}

                counts[filename]['total'] += 1
                level = entry.level
                counts[filename]['levels'][level] = counts[filename]['levels'].get(level, 0) + 1
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
        """Add a log entry to the buffer and request refresh (throttled)."""
        with self.buffer_lock:
            self.log_buffer.append(entry)

            # Only update display if not frozen
            if not self.frozen:
                # Always request a refresh - the message system will handle throttling
                # by coalescing RefreshTable messages
                current_time = time.time()

                # Only post a new refresh message if enough time has passed since last refresh
                # OR if we don't have a pending refresh scheduled
                if (current_time - self.last_refresh_time) >= self.min_refresh_interval:
                    # Enough time has passed, trigger immediate refresh
                    self.last_refresh_time = current_time
                    self.post_message(self.RefreshTable())
                elif not self.pending_refresh:
                    # Schedule a delayed refresh for the next interval
                    self.pending_refresh = True
                    self.set_timer(self.min_refresh_interval, self._trigger_refresh)

    def _trigger_refresh(self) -> None:
        """Timer callback to trigger a refresh."""
        self.pending_refresh = False  # Clear flag before triggering
        current_time = time.time()
        self.last_refresh_time = current_time
        self.post_message(self.RefreshTable())

    def refresh_table(self) -> None:
        """Refresh the log widget - incrementally if possible, full rebuild if needed."""
        # Note: Don't clear pending_refresh here - it's cleared in _trigger_refresh
        log_widget = self.query_one("#log_table", RichLog)

        with self.buffer_lock:
            current_tail = self.log_buffer.tail_abs_index()

            # Determine if we can do incremental update or need full rebuild
            # Full rebuild needed if:
            # - We've never rendered before (last_displayed_index == -1)
            # - Buffer wrapped around and lost our last position
            # - There are more than 1000 new entries (simpler to rebuild)
            can_incremental = (
                self.last_displayed_index >= 0 and
                current_tail is not None and
                self.log_buffer.head_abs_index() <= self.last_displayed_index and
                (current_tail - self.last_displayed_index) < 1000
            )

            if can_incremental:
                # Incremental update: only add new entries
                new_entries_count = current_tail - self.last_displayed_index
                if new_entries_count > 0:
                    # Get only the new entries
                    new_entries = self.log_buffer.slice_by_abs_index(
                        self.last_displayed_index + 1,
                        new_entries_count
                    )

                    displayed = 0
                    for entry in new_entries:
                        if self.passes_filter(entry):
                            self.add_log_line(log_widget, entry)
                            displayed += 1

                    self.last_displayed_index = current_tail

                    # Update status
                    status = self.query_one("#status_bar", StatusBar)
                    status.log_count = len(self.log_buffer)
                    if displayed > 0:
                        # Only update filter info if we displayed something
                        # (to avoid recalculating total displayed count)
                        pass
            else:
                # Full rebuild needed
                log_widget.clear()
                self.last_displayed_index = -1

                displayed = 0
                for entry in self.log_buffer.latest_slice(1000):  # Show last 1000 entries
                    if self.passes_filter(entry):
                        self.add_log_line(log_widget, entry)
                        displayed += 1

                if current_tail is not None:
                    self.last_displayed_index = current_tail

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
        self._update_level_indicator()
        self.last_displayed_index = -1  # Force full rebuild
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
            self._update_level_indicator()
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
            self._update_level_indicator()

        self.last_displayed_index = -1  # Force full rebuild
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
        self._update_level_indicator()
        self.last_displayed_index = -1  # Force full rebuild
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
        self.last_displayed_index = -1  # Force full rebuild
        self.refresh_table()

    def action_reset_filters(self) -> None:
        """Reset all filters to default."""
        self.filter_levels = set(range(len(LOG_LEVELS)))  # Show all levels
        self.filter_files = None  # Show all files
        self._update_level_indicator()
        self.last_displayed_index = -1  # Force full rebuild
        self.refresh_table()

    def action_view_log_entries(self) -> None:
        """Show all log entry definitions from ELF."""
        if not self.elf_reader or not self.elf_reader.logs.elf_ready:
            self.notify("No ELF file loaded yet", severity="warning", timeout=2)
            return

        self.push_screen(
            LogEntriesViewScreen(self.elf_reader)
        )

    def action_view_all_lines(self) -> None:
        """Show all log lines in a modal view."""
        self.push_screen(
            LogLineListScreen(
                self.log_buffer,
                self.buffer_lock,
                parent_viewer=self
            )
        )

    def action_toggle_freeze(self) -> None:
        """Toggle freeze state."""
        self.frozen = not self.frozen
        if not self.frozen:
            self.last_displayed_index = -1  # Force full rebuild when unfreezing
            self.refresh_table()

    def action_clear(self) -> None:
        """Clear all logs."""
        self.clear_logs()

    def clear_logs(self) -> None:
        """Clear the log buffer and widget."""
        with self.buffer_lock:
            self.log_buffer = Buffer(maxlen=self.args.buffer_depth)
            self.log_start = None
            self.last_displayed_index = -1  # Reset display tracking

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
