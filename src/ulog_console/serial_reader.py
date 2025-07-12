import asyncio
import serial
import threading

from ulog_console.logs import ApplicationLogs, ElfNotReady

from .messages import ControlMsg

EOF = 0xA6  # COBS end of frame marker

def cobs_decode(encoded: bytearray) -> bytearray:
    if not encoded or encoded[-1] != EOF:
        raise ValueError("Missing or invalid 0xAA frame terminator")

    decoded = bytearray()
    index = 0
    end = len(encoded) - 1  # Exclude the final EOF

    while index < end:
        code = encoded[index]
        if code == 0 or index + code > end + 1:
            raise ValueError("Invalid COBS code byte")

        index += 1
        decoded.extend(encoded[index:index + code - 1])

        # Insert a EOF if code < 0xFF and not at the end
        if code != 0xFF and index + code - 1 < end:
            decoded.append(EOF)

        index += code - 1

    return decoded
 

class Reader:
    def __init__(self, args, queue, app_logs):
        self.queue = queue
        self.app_logs = app_logs
        self.bad_data = False
        self.serial = serial.Serial(
            args.comm,
            baudrate=115200,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=1,
            xonxoff=0,
            rtscts=0
        )
        self._stop_event = threading.Event()

    async def run(self):
        if not self.serial.is_open:
            raise RuntimeError("Serial port is not open")

        loop = asyncio.get_running_loop()
        thread = threading.Thread(target=self.thread_loop, args=(loop,))
        thread.start()

        # Wait until stop is called
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        thread.join()

    def stop(self):
        if self.serial:
            self.serial.close()
        self._stop_event.set()

    def thread_loop(self, loop):
        while self.serial and not self._stop_event.is_set():
            # Read a whole COBS packet
            # Allow for up to 1 second of data
            b = self.serial.read_until(EOF.to_bytes(), size=11520)
            print(b)

            try:
                if len(b) < 2:
                    raise ValueError("Invalid COBS packet size")

                # Decode the COBS packet - remove the framing character
                decoded = cobs_decode(b)

                # Decode the log ID and data
                log = self.app_logs.decode_frame(decoded)
            except ElfNotReady as e:
                continue
            except Exception as e:
                if not self.bad_data:
                    loop.call_soon_threadsafe(self.queue.put_nowait, ControlMsg.BAD_DATA)
                    self.bad_data = True
            else:
                self.bad_data = False
                loop.call_soon_threadsafe(self.queue.put_nowait, log)
