import asyncio

from .cli import parse_args
from .viewer import Viewer
from .elf_reader import Reader as ElfReader
from .serial_reader import Reader as SerialReader


def main(args):
    queue = asyncio.Queue()
    elf_reader = ElfReader(args, queue)
    serial_reader = SerialReader(args, queue, elf_reader.logs)
    viewer = Viewer(queue, args)

    def curses_main(stdscr):
        viewer.screen = stdscr
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(
                asyncio.gather(
                    elf_reader.run(),
                    serial_reader.run(),
                    viewer.gather()  # viewer.gather() should be your async display logic
                )
            )
        finally:
            serial_reader.stop()
            elf_reader.stop()

    import curses
    curses.wrapper(curses_main)

if __name__ == "__main__":
    main(parse_args())