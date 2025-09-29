import threading
import queue
import signal

from .cli import parse_args
from .viewer import Viewer
from .elf_reader import Reader as ElfReader
from .serial_reader import Reader as SerialReader


def main():
    args = parse_args()

    try:
        elf_reader = ElfReader(args, msg_queue)
        serial_reader = SerialReader(args, msg_queue, elf_reader.logs)
    except Exception as e:
        print(f"Error initializing components: {e}")
        return

    threads = []

    def run_elf():
        elf_reader.run()

    def run_serial():
        try:
            serial_reader.run()
        except Exception as e:
            print("Serial thread exception:", e)
            serial_reader.stop()
            elf_reader.stop()
            viewer.running = False

    def run_viewer():
        import curses
        def curses_main(stdscr):
            viewer.screen = stdscr
            viewer.run()  # viewer.run() should block until quit
        curses.wrapper(curses_main)

    def handle_sigint(signum, frame):
        print("\nCTRL-C received, shutting down...")
        viewer.running = False
        serial_reader.stop()
        elf_reader.stop()

    signal.signal(signal.SIGINT, handle_sigint)

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
    main()