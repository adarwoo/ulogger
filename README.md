# ULog Console

The ULog console is as traces/logs viewer for AVR firmware using the ULog library.
For more on the ULog AVR logger - check the asx project.

It is required to view the traces of ULog - but conveniently also replaces your serial console viewer.

To run the viewer, you need to give the serial comm port and a path to the elf file of the AVR firmware.

```
$ ulog_console -p COM4 d:/modbus_relay/Debug/modbus_relay.elf
```

<img width="1083" height="574" alt="image" src="https://github.com/user-attachments/assets/684da355-d230-49f7-b86b-71cb45141704" />

## Usage

You install the viewer using pip install or build a windows executable with pyinstaller.

```
usage: ulog_console.exe [-h] [-l LEVEL] [-x] [-C COMM] [-b BUFFER_DEPTH] elf

ulog trace viewer (ncurses + live UART)

positional arguments:
  elf                   Path to ELF file with .logs section

options:
  -h, --help            show this help message and exit
  -l, --level LEVEL     Display log level threshold (0–8)
  -x, --clear           Clear screen on ELF reload
  -C, --comm COMM       UART serial port (e.g. /dev/ttyUSB0 or COM4)
  -b, --buffer-depth BUFFER_DEPTH
                        Internal buffer depth (e.g. 100k, 2M). Default: 100000
```

## Control keys:

| Key   | What it does  |
|:------:|---------------|
| Spacebar |Freeze the display on the screen. Note, the buffer is still filling up.<br/>Hit again, and it resumes to the latest logs.|
| Up and down arrow | Allow scrolling from the current position. The view gets frozen.<br/>Hit the spacebar to catchup|
| Page up and down |  Scroll one page at a time. Spacebar to resume |
| 0 to 8 |Set the minimum log level. Removes all log entry below that limit.<br/>Hit 0 to only show the errors. Hit 8 to see all.|
| q | Leave the application |

## Some of the key numbers

On the AVR, ULog is likely the smallest possible logger in every possible ways:

| Item | Size | Description |
|:----:|------|-------------|
|Library| **< 300 bytes** | This includes the UART handling, double buffer and API |
|Maximum throughput|**> 3000 messages / second**|Over a serial port at 115200|
|Single log text size|**8 bytes**|Every ULog add from 8 bytes of flash and no RAM|
|RAM | **from 30 bytes** | With a single buffer. or 100byes with 16|
|Single trace CPU cycles| **214** = 11us | Single trace with no arguments in the application |
|CPU load at 300 message/s|**<1%**|Includes ULog and sending|
|IDLE tasklet latency|**<23us**|Max additional latency to an reactor handler|

### Benefit

1. Work like normal. From the build to the execution!
The linker script may can be patched - but that's not event required.
2. 100 debug statement cost <1K! - that's less than 10 bytes per statement
3. The viewer know every possible trace before they are received - so a fully customer filtering is possible.

## What is the ULog library
The concept is very close to the excellent Trice library but has taken a different angle.
Where Trice does an extraction to a JSON and embedds the message ID in the code, ULog does not require any processing.
The traces and all the meta information are stored directly in the .elf file of the firmware.
<br/>
The following meta information is available:
 * Trace level : 8 Levels From ERROR to DEBUG4
 * Name of the file containing the statement
 * Line of the statement
 * Text associate with the trace
 * Type of the data attached to the text - size, type, sign etc. (no need to put formatters)
 * Double buffering - 1 for each ULog - 1 for sending over the UART
 * The second buffer is filled only when the reactor is idle
   

The meta information is added in the elf file in a non-mapped segment called .logs. This takes 0 flash.
When the trace is sent out, only the ID of the log and the raw data are sent with 2 extra characters for framing. (COBS Framing).
