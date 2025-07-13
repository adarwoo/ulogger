import curses
import threading
from queue import Empty

from .messages import ControlMsg
from .logs import Log

LOG_LEVELS = [
    "ERROR", "WARN", "MILE", "TRACE", "INFO", "DEBUG0", "DEBUG1", "DEBUG2", "DEBUG3"
]

# Define the color pairs for log levels
LEVEL_COLOR = {
    0: curses.COLOR_RED,
    1: 208,  # orange-ish
    2: curses.COLOR_YELLOW,
    3: curses.COLOR_GREEN,
    4: curses.COLOR_BLUE,
    5: 8,    # gray
    6: 8,    # gray
    7: 8,    # gray
    8: 8,    # gray
}


class Viewer:
    def __init__(self, queue, args):
        self.screen = None
        self.running = True
        self.queue = queue
        self.comm_port = args.comm
        self.elf_file = args.elf
        self.elf_status = "?"
        self.pad = None
        self.pad_row = 0
        self.view_row = 0  # Top row of pad currently displayed
        self.logging_active = True  # Track logging state

    def render_header(self):
        max_y, max_x = self.screen.getmaxyx()
        run_status = "RUNNING" if self.logging_active else "STOPPED"
        header = (
            f"Comm Port: {self.comm_port} "
            f"Elf file: {self.elf_file} / Status: {self.elf_status} / Logging: {run_status}"
        )
        self.screen.attron(curses.A_REVERSE)
        self.screen.addstr(0, 0, header[:max_x-2])
        self.screen.attroff(curses.A_REVERSE)
        self.screen.refresh()

    def render_log_to_pad(self, log, row):
        level = LOG_LEVELS[log.level]
        color_idx = LEVEL_COLOR[log.level]
        attr = curses.color_pair(color_idx)
        self.pad.addstr(row, 0, f"{level:<7} ", attr | curses.A_BOLD)
        self.pad.addstr(row, 8, f"{log.filename}:{log.line:<4} - ", curses.A_NORMAL)
        self.pad.addstr(row, 30, log.fmt, attr | curses.A_BOLD)

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
                    self.elf_status = "No ELF"
                elif item == ControlMsg.ELF_OK:
                    self.elf_status = "OK"
                elif item == ControlMsg.FAILED_TO_READ_ELF:
                    self.elf_status = "BAD"
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
            display_thread = threading.Thread(target=self.display_items, daemon=True)
            input_thread = threading.Thread(target=self.read_input, daemon=True)
            display_thread.start()
            input_thread.start()
            display_thread.join()
            input_thread.join()
        curses.wrapper(curses_main)
