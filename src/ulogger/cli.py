import argparse

def parse_args():
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(description="ulog trace viewer (ncurses + live UART)")

    parser.add_argument("elf", help="Path to ELF file with .logs section")
    parser.add_argument("-l", "--level", type=int, default=4, help="Display log level threshold (0–8)")
    parser.add_argument("-x", "--clear", action="store_true", help="Clear screen on ELF reload")
    parser.add_argument("-C", "--comm", default=None, help="UART serial port (e.g. /dev/ttyUSB0 or COM4)")
    parser.add_argument(
        "-b", "--buffer-depth",
        type=str,
        default="100000",
        help="Internal buffer depth (e.g. 100k, 2M). Default: 100000"
    )

    def parse_buffer_depth(value):
        value = value.strip().lower()
        if value.endswith('k'):
            return int(float(value[:-1]) * 1000)
        elif value.endswith('m'):
            return int(float(value[:-1]) * 1000000)
        else:
            return int(value)

    # After parsing, convert buffer_depth to int
    args = parser.parse_args()
    args.buffer_depth = parse_buffer_depth(args.buffer_depth)

    return args
