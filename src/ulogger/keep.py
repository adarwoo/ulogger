import curses

from .logs import LOG_LEVELS

LEVEL_COLOR = {
    "error": curses.COLOR_RED,
    "warn": 208,  # orange-ish
    "mile": curses.COLOR_YELLOW,
    "trace": curses.COLOR_GREEN,
    "info": curses.COLOR_BLUE,
    "debug": 8    # gray
}

import asyncio
import curses
from queue import Queue

class Viewer:
    def __init__(self, stdscr=None):
        self.stdscr = stdscr
        self.queue = Queue()
        self.running = True

    def display(self):
        curses.start_color()
        curses.use_default_colors()
        curses.noecho()
        curses.cbreak()
        self.stdscr.keypad(True)

        for i, (lvl, col) in enumerate(LEVEL_COLOR.items(), 1):
            curses.init_pair(i, col, -1)

        self.stdscr.clear()

        while self.running:
            if not self.queue.empty():
                log = self.queue.get()
                if log.level < 0 or log.level >= len(LOG_LEVELS):
                    continue

                level = LOG_LEVELS[log.level]
                filename, line, fmt = log.filename, log.line, log.fmt

                color_idx = next((i+1 for i, k in enumerate(LEVEL_COLOR) if k in level or level.startswith(k)), 0)
                attr = curses.color_pair(color_idx)

                self.stdscr.addstr(f"[{log.timestamp}] ", curses.A_DIM)
                self.stdscr.addstr(f"{level.upper():<7} ", attr | curses.A_BOLD)
                self.stdscr.addstr(f"{filename}:{line:<4} - {fmt} ", curses.A_NORMAL)

                if log.values:
                    self.stdscr.addstr(str(log.values), curses.A_BOLD)
                self.stdscr.addstr("\n")
                self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (ord('q'), ord('Q')):
                self.running = False

    async def produce_items(self):
        for i in range(100):
            await asyncio.sleep(0.5)  # Simulate delay
            await self.queue.put(f"Item {i}")

    async def display_items(self, stdscr):
        curses.curs_set(0)
        row = 0

        while True:
            item = await self.queue.get()
            stdscr.addstr(row, 0, item)
            stdscr.refresh()
            row += 1

    async def read_input(self, stdscr):
        stdscr.nodelay(True)

        while True:
            key = stdscr.getch()
            if key != -1:
                stdscr.addstr(20, 0, f"Key pressed: {chr(key)}   ")
                stdscr.refresh()
            await asyncio.sleep(0.1)

    async def main_curses(self):
        await asyncio.gather(
            self.curses_async_wrapper(self.display_items),
            self.curses_async_wrapper(self.read_input)
        )

    def curses_async_wrapper(self, coro_func):
        async def runner():
            curses.wrapper(lambda stdscr: asyncio.run(coro_func(stdscr)))
        return runner()

    asyncio.run(main_curses())

class LogViewer:
    def __init__(self, args, queue, stdscr=None):
        self.queue = queue
        self.level = args.level
        self.stdscr = stdscr
        self.running = True

    def display(self):
        curses.start_color()
        curses.use_default_colors()

        for i, (lvl, col) in enumerate(LEVEL_COLOR.items(), 1):
            curses.init_pair(i, col, -1)

        self.stdscr.clear()

        while self.running:
            log = self.queue.get()

            if log.level < self.level:
                continue

            level = LOG_LEVELS[log.level]
            filename, line, fmt = log.filename, log.line, log.fmt

            #color_idx = next((i+1 for i, k in enumerate(LEVEL_COLOR) if k in level or level.startswith(k)), 0)
            #attr = curses.color_pair(color_idx)

            #self.stdscr.addstr(f"[{ts}] ", curses.A_DIM)
            #self.stdscr.addstr(f"{level.upper():<7} ", attr | curses.A_BOLD)
            #self.stdscr.addstr(f"{filename}:{line:<4} - {fmt} ", curses.A_NORMAL)

            #if values:
            #    self.stdscr.addstr(str(values), curses.A_BOLD)
            #self.stdscr.addstr("\n")
            #self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord('q'), ord('Q')):
                self.running = False

