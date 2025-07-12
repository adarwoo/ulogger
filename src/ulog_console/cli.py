import argparse

def parse_args():
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(description="ulog trace viewer (ncurses + live UART)")

    parser.add_argument("elf", help="Path to ELF file with .logs section")
    parser.add_argument("-l", "--level", type=int, default=4, help="Display log level threshold (0–8)")
    parser.add_argument("-x", "--clear", action="store_true", help="Clear screen on ELF reload")
    parser.add_argument("-C", "--comm", default=None, help="UART serial port (e.g. /dev/ttyUSB0 or COM4)")

    return parser.parse_args()
