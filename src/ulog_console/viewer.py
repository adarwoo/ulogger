import curses
import threading
import string
from queue import Empty
from enum import Enum, auto

from .messages import ControlMsg
from .logs import Log

LOG_LEVELS = [
    "ERROR", "WARN", "MILE", "TRACE", "INFO", "DEBUG0", "DEBUG1", "DEBUG2", "DEBUG3"
]

LEVEL_COLOR = {
    0: curses.COLOR_RED,
    1: 208,
    2: curses.COLOR_YELLOW,
    3: curses.COLOR_GREEN,
    4: curses.COLOR_BLUE,
    5: 8,
    6: 8,
    7: 8,
    8: 8,
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
        self.logging_active = True

    def render_header(self):
        max_y, max_x = self.screen.getmaxyx()
        run_status = "RUNNING" if self.logging_active else "STOPPED"
        status_attr = curses.A_REVERSE | (curses.A_BLINK if not self.logging_active else 0)

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
        # Use the same color as the log level, but bold
        arg_highlight = curses.color_pair(log.level + 1) | curses.A_BOLD
        curses.init_pair(30, curses.COLOR_WHITE, curses.COLOR_RED)

        # Parse the format string
        parsed = list(formatter.parse(fmt_str))
        arg_index = 0
        start_col = 30

        try:
            for literal_text, field_name, format_spec, _ in parsed:
                # Print literal text
                if literal_text:
                    self.pad.addstr(row, start_col, literal_text, attr)
                    start_col += len(literal_text)
                if field_name is not None:
                    # Try to get the argument
                    try:
                        value = args[arg_index]
                        formatted_arg = formatter.format_field(value, format_spec)
                        self.pad.addstr(row, start_col, formatted_arg, arg_highlight)
                        start_col += len(str(formatted_arg))
                        arg_index += 1
                    except Exception:
                        # Formatting error, highlight in red
                        self.pad.addstr(row, start_col, f"<ERR>", curses.color_pair(30) | curses.A_BOLD)
                        start_col += 5

            # If there are leftover args, print them comma separated at the end
            if arg_index < len(args):
                leftovers = ", ".join(str(a) for a in args[arg_index:])
                self.pad.addstr(row, start_col, " " + leftovers, arg_highlight)
                start_col += len(leftovers) + 1
        except Exception:
            # General formatting error
            self.pad.addstr(row, start_col, fmt_str, curses.color_pair(30) | curses.A_BOLD)

        # Print level
        self.pad.addstr(row, 0, f"{level:<7} ", attr)
        # Print file:line
        self.pad.addstr(row, 8, f"{log.filename}:{log.line:<4} - ", curses.A_NORMAL)


    def draw_scrollbar(self, max_y, max_x):
        # Draw a simple vertical scrollbar on the right edge
        pad_lines = self.pad_row
        visible_lines = max_y - 2
        if pad_lines <= visible_lines:
            return
        bar_height = max(1, visible_lines * visible_lines // pad_lines)
        bar_top = int(self.view_row * visible_lines / pad_lines)
        for i in range(visible_lines):
            ch = '|' if bar_top <= i < bar_top + bar_height else ' '
            self.screen.addstr(i + 1, max_x - 1, ch, curses.A_REVERSE)

    def display_items(self):
        curses.curs_set(0)
        self.screen.scrollok(True)
        max_y, max_x = self.screen.getmaxyx()
        pad_height = 10000
        pad_width = max_x - 1  # Leave space for scrollbar
        self.pad = curses.newpad(pad_height, pad_width)
        self.pad_row = 0
        self.view_row = 0

        while self.running:
            self.render_header()
            self.draw_scrollbar(max_y, max_x)
            try:
                if self.queue.qsize() > 5000:
                    while not self.queue.empty():
                        self.queue.get_nowait()
                    self.pad.addstr(self.pad_row, 0, "Queue flushed (over 5000 items)")
                    self.pad_row += 1

                item = self.queue.get(timeout=0.1)
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
                    self.pad.erase()
                    self.pad_row = 0
                    self.view_row = 0
                self.render_header()
            elif isinstance(item, Log):
                if self.logging_active:
                    if self.pad_row >= pad_height - 1:
                        self.pad_row = pad_height - 2
                    self.pad.move(self.pad_row, 0)
                    self.pad.clrtoeol()
                    self.render_log_to_pad(item, self.pad_row)
                    self.pad_row += 1
                    # Always scroll to bottom when new log arrives
                    self.view_row = max(0, self.pad_row - (max_y - 2))

            # Display pad below header
            self.pad.refresh(
                self.view_row, 0, 1, 0, max_y - 1, max_x - 2
            )
            self.draw_scrollbar(max_y, max_x)

    def read_input(self):
        self.screen.timeout(100)
        max_y, max_x = self.screen.getmaxyx()
        while self.running:
            key = self.screen.getch()
            if key != -1:
                if key in (curses.KEY_UP, ord('k')):
                    self.view_row = max(0, self.view_row - 1)
                elif key in (curses.KEY_DOWN, ord('j')):
                    self.view_row = min(max(0, self.pad_row - (max_y - 2)), self.view_row + 1)
                elif key == curses.KEY_NPAGE:  # Page Down
                    self.view_row = min(max(0, self.pad_row - (max_y - 2)), self.view_row + (max_y - 2))
                elif key == curses.KEY_PPAGE:  # Page Up
                    self.view_row = max(0, self.view_row - (max_y - 2))
                elif key == ord(' '):  # Spacebar toggles logging
                    self.logging_active = not self.logging_active
                    self.render_header()
                elif key == ord('q'):
                    self.running = False
                    break
                self.pad.refresh(
                    self.view_row, 0, 1, 0, max_y - 1, max_x - 2
                )
                self.draw_scrollbar(max_y, max_x)

    def run(self):
        def curses_main(stdscr):
            self.screen = stdscr

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

            # Initialize color pairs for log levels
            display_thread = threading.Thread(target=self.display_items, daemon=True)
            input_thread = threading.Thread(target=self.read_input, daemon=True)
            display_thread.start()
            input_thread.start()
            display_thread.join()
            input_thread.join()
        curses.wrapper(curses_main)
