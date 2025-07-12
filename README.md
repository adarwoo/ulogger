# ULog Console

**NOTE** : This is work in progress right now

The ULog console is as traces/logs viewer for AVR firmware using the ULog library.
It is required to view the traces of ULog - but conveniently also replaces your serial console viewer.

To run the viewer, you need to give the serial comm port and a path to the elf file of the AVR firmware.

```
$ ulog_console -p COM4 d:/modbus_relay/Debug/modbus_relay.elf
```

## Some of the key numbers

1. Library size **< 300 bytes**
2. Maximum throughput over the serial port at 115200: **> 3000 messages / second**
3. Flash taken by a single log statement: ** 8 bytes **
4. Time taken by a single trace in the application: **< 2us**
5. CPU load to send the messages (only when no busy): **<1%**

### Benefit

1. Work like normal. From the build to the execution!
The linker script may can be patched - but that's not event required.
2. 100 debug statement cost <1K! - that's less than 10 bytes per statement
3. The viewer know every possible trace before they are received - so a fully customer filtering is possible.

## What is the ULog library
The concept is very close to the excellent Trice library but as taken a different angle.
Where Trice does an extraction to a JSON and embedded the message ID in the code, ULog does not require any processing.
The traces and all the meta information are stored directly in the .elf file of the firmware.
<br/>
The following meta information is available:
 * Trace level : 8 Levels From ERROR to DEBUG4
 * Name of the file containing the statement
 * Line of the statement
 * Text associate with the trace
 * Type of the data attached to the text - size, type, sign etc. (no need to put formatters)

The meta information is added in the elf file in a non-mapped segment called .logs. This takes 0 flash.
When the trace is sent out, only the ID of the log and the raw data are sent with 2 extra characters for framing. (COBS Framing).
