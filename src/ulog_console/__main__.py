import threading
import queue

from .cli import parse_args
from .viewer import Viewer
from .elf_reader import Reader as ElfReader
from .serial_reader import Reader as SerialReader


def main(args):
    msg_queue = queue.Queue()
    elf_reader = ElfReader(args, msg_queue)
    serial_reader = SerialReader(args, msg_queue, elf_reader.logs)
    viewer = Viewer(msg_queue, args)

    threads = []

    def run_elf():
        elf_reader.run()

    def run_serial():
        serial_reader.run()

    def run_viewer():
        import curses
        def curses_main(stdscr):
            viewer.screen = stdscr
            viewer.run()  # viewer.run() should block until quit
        curses.wrapper(curses_main)

    threads.append(threading.Thread(target=run_elf, daemon=True))
    threads.append(threading.Thread(target=run_serial, daemon=True))
    threads.append(threading.Thread(target=run_viewer, daemon=True))

    for t in threads:
        t.start()

    # Wait for viewer to finish, then stop others
    threads[2].join()
    serial_reader.stop()
    elf_reader.stop()

if __name__ == "__main__":
    main(parse_args())