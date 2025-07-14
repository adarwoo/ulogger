import curses
import time
import threading
import string
import collections
from queue import Empty
from enum import Enum, auto

from .buffer import PersistantIndexCircularBuffer as Buffer
from .messages import ControlMsg
from .logs import LogEntry
import datetime

#
# Constants
#

# Maximum length of the filename to be printed in the viewer
MAX_PRINTED_FILENAME_LENGTH = 20

LOG_LEVELS = [
    "ERROR", "WARN", "MILE", "TRACE", "INFO", "DEBUG0", "DEBUG1", "DEBUG2", "DEBUG3"
]

DEBUG_COLOR = curses.COLOR_WHITE

DEFAULT_LOG_LEVEL = 8  # Show all levels by default

LEVEL_COLOR = {
    0: curses.COLOR_RED,      # ERROR
    1: 208,                   # WARN (orange-ish)
    2: curses.COLOR_YELLOW,   # MILE
    3: curses.COLOR_GREEN,    # TRACE
    4: curses.COLOR_BLUE,     # INFO
    5: 252,                   # DEBUG0 - light gray
    6: 244,                   # DEBUG1 - medium gray
    7: 240,                   # DEBUG2 - darker gray
    8: 236,                   # DEBUG3 - dark gray
}

class ElfStatus(Enum):
    NO_ELF = auto()
    OK = auto()
    BAD = auto()


class Viewer:
    def __init__(self, queue, args):
        self.screen = None
        self.args = args
        self.running = True
        self.queue = queue
        self.comm_port = args.comm
        self.elf_file = args.elf
        self.elf_status = ElfStatus.NO_ELF
        self.pad = None
        self.pad_row = 0
        self.view_row = 0
        self.log_buffer = Buffer(maxlen=args.buffer_depth)
        self.log_start = None
        # Prevent race conditions when accessing the log buffer
        self.buffer_lock = threading.RLock()
        self.frozen_index = None
        self.display_log_level = DEFAULT_LOG_LEVEL  # Default: show all levels
        # Signalling between threads for input handling
        self.input_condition = threading.Condition()
        self.input_waiting = False

    def signal_input(self):
        """ Signal that input is available, allowing the viewer to refresh immediately."""
        with self.input_condition:
            # Temporarily set non-blocking mode
            self.screen.nodelay(True)
            pending_key = self.screen.getch()
            self.screen.nodelay(False)
            # Only signal if no key is pending
            if pending_key == -1 and self.input_waiting:
                curses.ungetch(-1)

    def format_time(self, timestamp):
        if self.log_start is None:
            self.log_start = timestamp

        elapsed = timestamp - self.log_start
        seconds = int(elapsed)
        ms = int((elapsed - seconds) * 10000)

        if seconds < 10000:
            ts_str = f"{seconds:04}.{ms:04}"
        else:
            ts_str = f"+{seconds:03}.{ms:04}"

        return ts_str

    def render_header(self):
        max_y, max_x = self.screen.getmaxyx()
        run_status = "RUNNING"
        status_attr = curses.A_REVERSE

        # Left part
        left = f"Comm Port: {self.comm_port}"
        left_width = len(left) + 2

        # Right part (run status), right justified
        status_str = f"{run_status:<8}"
        status_width = len(status_str) + 2

        # Center part (elf file name only, centered)
        center_start = left_width
        center_end = max_x - status_width
        elf_file_max = center_end - center_start - 4  # 2 spaces each side
        elf_file = self.elf_file
        if len(elf_file) > elf_file_max:
            elf_file = elf_file[:max(0, elf_file_max - 3)] + "..."
        center = f"  {elf_file}  "
        center_pos = center_start + (center_end - center_start - len(center)) // 2

        # Clear header line
        self.screen.move(0, 0)
        self.screen.clrtoeol()

        # Draw left
        self.screen.attron(curses.A_REVERSE)
        self.screen.addstr(0, 0, left)
        self.screen.attroff(curses.A_REVERSE)

        # Draw center (elf file) with color based on elf_status
        if self.elf_status == ElfStatus.NO_ELF:
            # Black on red
            curses.init_pair(20, curses.COLOR_BLACK, curses.COLOR_RED)
            self.screen.attron(curses.color_pair(20))
            self.screen.addstr(0, center_pos, center[:center_end - center_pos])
            self.screen.attroff(curses.color_pair(20))
        elif self.elf_status == ElfStatus.OK:
            # Inverted grey
            curses.init_pair(21, 8, -1)
            self.screen.attron(curses.color_pair(21) | curses.A_REVERSE)
            self.screen.addstr(0, center_pos, center[:center_end - center_pos])
            self.screen.attroff(curses.color_pair(21) | curses.A_REVERSE)
        elif self.elf_status == ElfStatus.BAD:
            # Blink background grey, text red
            curses.init_pair(22, curses.COLOR_RED, 8)
            self.screen.attron(curses.color_pair(22) | curses.A_BLINK)
            self.screen.addstr(0, center_pos, center[:center_end - center_pos])
            self.screen.attroff(curses.color_pair(22) | curses.A_BLINK)

        # Draw right (status)
        self.screen.attron(status_attr)
        self.screen.addstr(0, max_x - status_width, status_str)
        self.screen.attroff(status_attr)

    def render_log_to_pad(self, log, row):
        # Log could be a string or a LogEntry object
        if isinstance(log, str):
            # If it's a string, treat it as a log message
            attr = curses.color_pair(20) | curses.A_BOLD
            self.pad.addstr(row, 0, log, attr)
            return

        attr = curses.color_pair(log.level + 1) | curses.A_BOLD
        level = LOG_LEVELS[log.level]
        formatter = string.Formatter()
        fmt_str = log.fmt
        args = getattr(log, "data", ())
        arg_highlight = curses.color_pair(log.level + 1) | curses.A_BOLD

        # Print timestamp (same color as file:line, i.e. curses.A_NORMAL)
        timestamp = self.format_time(log.timestamp)
        self.pad.addstr(row, 0, f"{timestamp:<11} ", curses.A_NORMAL)

        # Print level
        self.pad.addstr(row, 12, f"{level:<7} ", attr)

        # Print file:line

        filename = log.filename
        if len(filename) > MAX_PRINTED_FILENAME_LENGTH:
            filename = "..." + filename[-(MAX_PRINTED_FILENAME_LENGTH - 3):]

        self.pad.addstr(
            row,
            20,
            f"{filename:>{MAX_PRINTED_FILENAME_LENGTH}}:{log.line:<4} ",
            curses.A_NORMAL
        )

        # Start formatting message after column 36
        start_col = MAX_PRINTED_FILENAME_LENGTH + 20 + 1 + 4 + 1

        # Parse the format string
        parsed = list(formatter.parse(fmt_str))
        arg_index = 0

        try:
            for literal_text, field_name, format_spec, _ in parsed:
                if literal_text:
                    self.pad.addstr(row, start_col, literal_text, attr)
                    start_col += len(literal_text)
                if field_name is not None:
                    try:
                        value = args[arg_index]
                        formatted_arg = formatter.format_field(value, format_spec)
                        self.pad.addstr(row, start_col, formatted_arg, arg_highlight)
                        start_col += len(str(formatted_arg))
                        arg_index += 1
                    except Exception:
                        self.pad.addstr(row, start_col, f"<ERR>", curses.color_pair(30) | curses.A_BOLD)
                        start_col += 5

            if arg_index < len(args):
                leftovers = ", ".join(str(a) for a in args[arg_index:])
                self.pad.addstr(row, start_col, " " + leftovers, arg_highlight)
                start_col += len(leftovers) + 1
        except Exception:
            self.pad.addstr(row, start_col, fmt_str, curses.color_pair(30) | curses.A_BOLD)

    def draw_scrollbar(self, max_y, max_x):
            # Draw a simple vertical scrollbar on the right edge
            visible_lines = max_y - 1
            total_lines = len(self.log_buffer)

            if total_lines <= visible_lines:
                # No need for a scrollbar, wipe the previous one
                for i in range(1, visible_lines):
                    self.screen.addstr(i, max_x - 1, ' ', curses.A_REVERSE)
                return

            # Determine the start index for the scrollbar
            if self.frozen_index is not None:
                # When frozen, show the scrollbar relative to frozen_index
                start_idx = max(0, self.frozen_index - visible_lines + 1)
            else:
                # When live, show the latest logs
                start_idx = max(0, total_lines - visible_lines)

            bar_height = max(1, visible_lines * visible_lines // total_lines)
            # Bar position: where the visible window starts in the buffer
            bar_top = int(start_idx * visible_lines / total_lines)

            for i in range(1, visible_lines):
                ch = '|' if bar_top <= i < bar_top + bar_height else ' '
                self.screen.addstr(i, max_x - 1, ch, curses.A_REVERSE)

    def process_queue(self):
        while self.running:
            try:
                if self.queue.qsize() > 5000:
                    while not self.queue.empty():
                        self.queue.get_nowait()
                        with self.buffer_lock:
                            self.log_buffer.append("Buffer overrun - flushed 5000 items")
                item = self.queue.get(timeout=1)
            except Empty:
                continue

            if isinstance(item, ControlMsg):
                if item == ControlMsg.QUIT:
                    self.running = False
                elif item == ControlMsg.WAIT_FOR_ELF:
                    self.elf_status = ElfStatus.NO_ELF
                elif item == ControlMsg.FAILED_TO_READ_ELF:
                    self.elf_status = ElfStatus.BAD
                elif item in (ControlMsg.ELF_OK, ControlMsg.RELOADED_ELF):
                    self.elf_status = ElfStatus.OK

                    with self.buffer_lock:
                        if item == ControlMsg.RELOADED_ELF and self.args.clear:
                            # Create a new log buffer (discard old logs or create a new one)
                            self.log_buffer = Buffer(maxlen=self.log_buffer.maxlen)

                        # Add a log entry with datetime and sha256 of the new elf file
                        dt_str = datetime.datetime.now().strftime("%Y%m%d %H:%M")

                        status = "reloaded" if item == ControlMsg.RELOADED_ELF else "loaded"
                        self.log_buffer.append(f"[{dt_str}] ELF {status}, sha256={item.sha256}")

                        # Used to determine the time of the first log entry
                        # Reset since we've yet to receive any logs
                        self.log_start = None
            elif isinstance(item, LogEntry):
                with self.buffer_lock:
                    self.log_buffer.append(item)

            # Signal the input thread that new work has arrived
            with self.input_condition:
                self.input_condition.notify()

    def refresh_pad(self):
        max_y, max_x = self.screen.getmaxyx()
        visible_lines = max_y - 1

        # Collect logs to display, applying log level filter
        logs_to_display = []
        count = 0

        with self.buffer_lock:
            if not self.frozen_index:  # Not frozen
                # Iterate from the newest backwards
                for log in reversed(self.log_buffer):
                    if isinstance(log, str) or log.level <= self.display_log_level:
                        # If it's a string, treat it as a log message
                        logs_to_display.append(log)
                        count += 1
                        if count >= visible_lines:
                            break
            else:  # Frozen
                head_index = self.log_buffer.head_abs_index()
                index = max(head_index, self.frozen_index)

                while index is not None and index >= head_index and len(logs_to_display) < visible_lines:
                    log = self.log_buffer[index]

                    if isinstance(log, str) or log.level <= self.display_log_level:
                        logs_to_display.append(log)

                    if index == head_index:
                        break  # Prevent going below the first entry

                    index -= 1

            # If still not enough logs, pad with empty lines
            logs_to_display.reverse()  # So newest is at the bottom
            while len(logs_to_display) < visible_lines:
                logs_to_display.insert(0, None)

        for row, log in enumerate(logs_to_display):
            self.pad.move(row, 0)
            self.pad.clrtoeol()
            if log is not None:
                self.render_log_to_pad(log, row)

        self.pad.refresh(0, 0, 1, 0, max_y - 1, max_x - 2)

    def refresh_loop(self):
        self.screen.nodelay(True)  # Non-blocking input

        def screen_refresh():
            max_y, max_x = self.screen.getmaxyx()
            self.render_header()
            self.refresh_pad()
            self.draw_scrollbar(max_y, max_x)
            self.screen.refresh()

        while self.running:
            # Allow for the screen to be resized
            max_y, max_x = self.screen.getmaxyx()
            visible_lines = max_y - 1

            key = self.screen.getch()

            if key != -1:
                # Get the current head and tail indexes of the log buffer
                with self.buffer_lock:
                    head_idx = self.log_buffer.head_abs_index()
                    tail_idx = self.log_buffer.tail_abs_index()

                    if key == ord(' '):
                        if self.frozen_index is None:
                            self.frozen_index = tail_idx
                        else:
                            self.frozen_index = None
                    elif key in (curses.KEY_UP, ord('k')):
                        if self.frozen_index is None:
                            self.frozen_index = tail_idx
                        self.frozen_index = max(head_idx, self.frozen_index - 1)
                    elif key in (curses.KEY_DOWN, ord('j')):
                        if self.frozen_index is None:
                            self.frozen_index = tail_idx
                        self.frozen_index = min(tail_idx, self.frozen_index + 1)
                    elif key == curses.KEY_NPAGE:
                        if self.frozen_index is None:
                            self.frozen_index = tail_idx
                        self.frozen_index = min(tail_idx, self.frozen_index + visible_lines)
                    elif key == curses.KEY_PPAGE:
                        if self.frozen_index is None:
                            self.frozen_index = tail_idx
                        self.frozen_index = max(head_idx, self.frozen_index - visible_lines)
                    # Handle log level keys 0-8
                    elif key - ord('0') in LEVEL_COLOR.keys():
                        self.display_log_level = int(chr(key))
                    elif key == ord('q'):
                        self.running = False
                        break

                    screen_refresh()
            else:
                # Wait for signal or timeout - so we have a 20ms latency in key handling
                with self.input_condition:
                    if self.input_condition.wait(timeout=0.02):  # 20ms
                        with self.buffer_lock:
                            screen_refresh()

    def run(self):
        def curses_main(stdscr):
            self.screen = stdscr
            self.screen.scrollok(True)

            # Don't echo input, hide cursor
            curses.curs_set(0)
            curses.noecho()
            curses.cbreak()

            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                # Initialize color pairs for log levels
                for level, color in LEVEL_COLOR.items():
                    curses.init_pair(level + 1, color, curses.COLOR_BLACK)

            # Initialize color pairs for header
            curses.init_pair(20, curses.COLOR_BLACK, curses.COLOR_RED)
            curses.init_pair(31, curses.COLOR_YELLOW, -1)
            curses.init_pair(30, curses.COLOR_WHITE, curses.COLOR_RED)

            # Create a pad for scrolling logs
            max_y, max_x = self.screen.getmaxyx()
            visible_lines = max_y - 1
            self.pad = curses.newpad(visible_lines, max_x - 2)

            try:
                # Initialize color pairs for log levels
                display_thread = threading.Thread(target=self.process_queue, daemon=True)
                input_thread = threading.Thread(target=self.refresh_loop, daemon=True)

                display_thread.start()
                input_thread.start()
            except Exception as e:
                print(f"Error starting threads: {e}")
                return

            display_thread.join()
            input_thread.join()
        curses.wrapper(curses_main)
