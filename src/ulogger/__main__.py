import threading
import queue
import signal
from pathlib import Path

from .cli import parse_args
from .viewer_textual import LogViewer
from .settings import get_settings


def start_readers(args, msg_queue, viewer):
    """Start ELF and Serial readers in background threads."""
    from .elf_reader import Reader as ElfReader
    from .serial_reader import Reader as SerialReader

    try:
        elf_reader = ElfReader(args, msg_queue)
        serial_reader = SerialReader(args, msg_queue, elf_reader.logs)

        # Give viewer references to readers for cleanup
        viewer.elf_reader = elf_reader
        viewer.serial_reader = serial_reader
    except Exception as e:
        print(f"Error initializing components: {e}")
        return False

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

    # Start background threads
    threading.Thread(target=run_elf, daemon=True).start()
    threading.Thread(target=run_serial, daemon=True).start()

    return True


def main():
    args = parse_args()

    # If ELF file provided, validate and remember it
    if args.elf:
        elf_path = Path(args.elf)
        if not elf_path.exists():
            print(f"Error: ELF file not found: {args.elf}")
            return

        # Add to recent files
        settings = get_settings()
        settings.add_recent_file(str(elf_path.resolve()))

    # If COM port provided on command line, save it to settings
    if args.comm:
        settings = get_settings()
        settings.set_com_port(args.comm)

    msg_queue = queue.Queue()
    viewer = LogViewer(msg_queue, args, start_readers_callback=start_readers if not args.elf else None)

    # If ELF provided on command line, start readers immediately
    if args.elf:
        if not start_readers(args, msg_queue, viewer):
            return

    def handle_sigint(signum, frame):
        print("\nCTRL-C received, shutting down...")
        viewer.running = False
        if viewer.serial_reader:
            viewer.serial_reader.stop()
        if viewer.elf_reader:
            viewer.elf_reader.stop()
        viewer.exit()

    signal.signal(signal.SIGINT, handle_sigint)

    # Run the Textual app (blocks until exit)
    viewer.run()

    # Clean up
    if viewer.serial_reader:
        viewer.serial_reader.stop()
    if viewer.elf_reader:
        viewer.elf_reader.stop()


if __name__ == "__main__":
    main()