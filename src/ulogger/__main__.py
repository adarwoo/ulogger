import threading
import queue
import signal

from .cli import parse_args
from .viewer_textual import LogViewer
from .elf_reader import Reader as ElfReader
from .serial_reader import Reader as SerialReader


def main():
    args = parse_args()
    msg_queue = queue.Queue()
    viewer = LogViewer(msg_queue, args)

    try:
        elf_reader = ElfReader(args, msg_queue)
        serial_reader = SerialReader(args, msg_queue, elf_reader.logs)

        # Give viewer references to readers for cleanup
        viewer.elf_reader = elf_reader
        viewer.serial_reader = serial_reader
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

    def handle_sigint(signum, frame):
        print("\nCTRL-C received, shutting down...")
        viewer.running = False
        serial_reader.stop()
        elf_reader.stop()
        viewer.exit()

    signal.signal(signal.SIGINT, handle_sigint)

    # Start background threads
    threads.append(threading.Thread(target=run_elf, daemon=True))
    threads.append(threading.Thread(target=run_serial, daemon=True))

    for t in threads:
        t.start()

    # Run the Textual app (blocks until exit)
    viewer.run()

    # Clean up
    serial_reader.stop()
    elf_reader.stop()

if __name__ == "__main__":
    main()