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

LOG_LEVELS = [
    "ERROR", "WARN", "MILE", "TRACE", "INFO", "DEBUG0", "DEBUG1", "DEBUG2", "DEBUG3"
]

DEBUG_COLOR = curses.COLOR_WHITE

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
        level = LOG_LEVELS[log.level]
        attr = curses.color_pair(log.level + 1) | curses.A_BOLD

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
        self.pad.addstr(row, 20, f"{log.filename}:{log.line:<4}: - ", curses.A_NORMAL)

        # Start formatting message after column 36
        start_col = 36

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
            # No need for a scrollbar
            for i in range(visible_lines):
                self.screen.addstr(i + 1, max_x - 1, ' ', curses.A_REVERSE)
            return

        # Calculate the scroll position and bar size
        start_idx = max(0, total_lines - visible_lines - self.view_row)
        bar_height = max(1, visible_lines * visible_lines // total_lines)
        # Bar position: where the visible window starts in the buffer
        bar_top = int(start_idx * visible_lines / total_lines)

        for i in range(visible_lines):
            ch = '|' if bar_top <= i < bar_top + bar_height else ' '
            self.screen.addstr(i + 1, max_x - 1, ch, curses.A_REVERSE)

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
                elif item == ControlMsg.ELF_OK:
                    self.elf_status = ElfStatus.OK
                elif item == ControlMsg.FAILED_TO_READ_ELF:
                    self.elf_status = ElfStatus.BAD
                elif item == ControlMsg.RELOADED_ELF:
                    self.log_buffer = Buffer(maxlen=self.log_buffer.maxlen)
                    self.log_start = None
            elif isinstance(item, LogEntry):
                with self.buffer_lock:
                    self.log_buffer.append(item)

    def refresh_pad(self):
        max_y, max_x = self.screen.getmaxyx()
        visible_lines = max_y - 1

        if not self.frozen_index:  # Not frozen
            logs_to_display = self.log_buffer.latest_slice(visible_lines)
        else:  # Frozen
            logs_to_display = self.log_buffer.slice_by_abs_index(self.frozen_index - visible_lines, visible_lines)
            # If frozen_index is out of range, show the latest logs
            if not logs_to_display:
                logs_to_display = self.log_buffer.latest_slice(visible_lines)
                self.frozen_index = None

        for row, log in enumerate(logs_to_display):
            self.pad.move(row, 0)
            self.pad.clrtoeol()
            self.render_log_to_pad(log, row)

        self.pad.refresh(0, 0, 1, 0, max_y - 1, max_x - 2)

    def refresh_loop(self):
        self.screen.timeout(100)
        frozen = False

        while self.running:
            max_y, max_x = self.screen.getmaxyx()
            visible_lines = max_y - 1

            key = self.screen.getch()

            with self.buffer_lock:
                head_idx = self.log_buffer.head_abs_index()
                tail_idx = self.log_buffer.tail_abs_index()

                if key != -1:
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
                    elif key == ord('q'):
                        self.running = False
                        break

                self.render_header()
                self.refresh_pad()

            self.screen.refresh()

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
            self.pad = curses.newpad(visible_lines, max_x - 1)

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
