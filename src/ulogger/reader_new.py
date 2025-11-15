#
# ulogger - Serial reader for ulog data
# Runs as a subprocess of ulogger to read from a serial port with a high
# priority thread and send log entries to the main process via a queue.
# The queue data is consumed by the Feeder class.
import serial
import threading
import time
import multiprocessing as mp
import signal
import sys
import atexit
import asyncio
import uuid

from collections import deque
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Any, Tuple


EOF = 0xA6  # COBS end of frame marker

class Command(Enum):
    """Commands that can be sent to the subprocess"""
    OPEN_PORT = auto()
    CLOSE_PORT = auto()
    QUIT = auto()

class Status(Enum):
    """Status messages from the subprocess"""
    PORT_OPENED = auto()
    PORT_CLOSED = auto()
    PORT_ERROR = auto()
    DATA_READY = auto()
    COMMAND_RESPONSE = auto()  # Response to synchronous commands
    PORT_RETRY = auto()  # Port retry attempt notification

@dataclass
class CommandMessage:
    """Command message structure"""
    command: Command
    data: Any = None
    request_id: Optional[str] = None  # For synchronous command responses

@dataclass
class StatusMessage:
    """Status message structure"""
    status: Status
    data: Any = None
    request_id: Optional[str] = None  # For matching responses to requests

@dataclass
class DroppedFrameInfo:
    """Information about a dropped frame"""
    timestamp_us: int  # Monotonic timestamp when frame was dropped
    reason: str = "buffer_overflow"

@dataclass
class FrameData:
    """Unified frame data structure for both valid and error frames"""
    timestamp_us: int  # Monotonic timestamp in microseconds
    frame_type: str  # "valid", "dropped", "error"
    data: Any = None  # FrameData for valid frames, None for others
    error_reason: Optional[str] = None  # Reason for dropped/error frames

class BufferedQueue:
    """Circular buffer queue that holds up to 10,000 messages (2 seconds at 5000 msgs/sec)"""

    def __init__(self, maxsize: int = 10000):
        self.maxsize = maxsize
        self.buffer = deque(maxlen=maxsize)
        self.lock = threading.Lock()

    def put_valid_frame(self, frame, timestamp_us: int):
        """Add a valid log entry frame to queue"""
        frame = FrameData(timestamp_us, "valid", frame)
        self._put_frame(frame, timestamp_us)

    def put_error_frame(self, timestamp_us: int, error_reason: str):
        """Add an error frame to queue"""
        frame = FrameData(timestamp_us, "error", None, error_reason)
        self._put_frame(frame, timestamp_us)

    def _put_frame(self, frame: FrameData, timestamp_us: int):
        """Internal method to add frame to queue, handling overflow"""
        with self.lock:
            if len(self.buffer) >= self.maxsize:
                # Record dropped frame due to buffer overflow
                dropped_frame = FrameData(timestamp_us, "dropped", None, "buffer_overflow")
                # Replace oldest item with dropped frame info
                if self.buffer:
                    self.buffer.popleft()
                self.buffer.append(dropped_frame)

            # Add the new frame
            if len(self.buffer) < self.maxsize:
                self.buffer.append(frame)

    def get_all_frames(self):
        """Get all frames in chronological order and clear buffer"""
        with self.lock:
            frames = list(self.buffer)
            self.buffer.clear()
            # Sort by timestamp to ensure chronological order
            frames.sort(key=lambda f: f.timestamp_us)
            return frames

    # Legacy method for backward compatibility
    def get_all(self):
        """Legacy method - separates frames into logs and dropped_frames lists"""
        frames = self.get_all_frames()
        logs = []
        dropped_frames = []

        for frame in frames:
            if frame.frame_type == "valid":
                logs.append(frame.data)
            elif frame.frame_type == "dropped":
                dropped_frames.append(DroppedFrameInfo(frame.timestamp_us, frame.error_reason))

        return logs, dropped_frames

    def size(self):
        """Get current queue size"""
        with self.lock:
            return len(self.buffer)

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
    def __init__(self, command_queue: mp.Queue, status_queue: mp.Queue, app_logs):
        self.command_queue = command_queue
        self.status_queue = status_queue
        self.app_logs = app_logs
        self.bad_data = False
        self.serial: Optional[serial.Serial] = None
        self.data_buffer = BufferedQueue()
        self._stop_event = threading.Event()
        self._thread = None
        self._command_thread = None

        # Monotonic timestamping
        self._first_timestamp: Optional[float] = None
        self._last_timestamp_us: int = 0
        self._timestamp_lock = threading.Lock()

        # Port retry mechanism
        self._retry_thread: Optional[threading.Thread] = None
        self._pending_port_open: Optional[dict] = None
        self._retry_lock = threading.Lock()

    def _get_monotonic_timestamp_us(self) -> int:
        """
        Get monotonic timestamp in microseconds since first valid data.
        Guarantees that timestamps are always incrementing.
        """
        with self._timestamp_lock:
            current_time = time.perf_counter()

            # Initialize first timestamp on first call
            if self._first_timestamp is None:
                self._first_timestamp = current_time
                self._last_timestamp_us = 0
                return 0

            # Calculate elapsed microseconds since first timestamp
            elapsed_us = int((current_time - self._first_timestamp) * 1_000_000)

            # Ensure monotonic condition - timestamp must always increment
            if elapsed_us <= self._last_timestamp_us:
                elapsed_us = self._last_timestamp_us + 1

            self._last_timestamp_us = elapsed_us
            return elapsed_us

    def _start_retry_timer(self, port_name: str, baudrate: int, request_id: Optional[str]):
        """Start a 2-second retry timer for port opening"""
        with self._retry_lock:
            # Cancel any existing retry
            self._cancel_retry()

            # Store pending port open parameters
            self._pending_port_open = {
                'port_name': port_name,
                'baudrate': baudrate,
                'request_id': request_id,
                'retry_count': getattr(self._pending_port_open, 'retry_count', 0) + 1 if self._pending_port_open else 1
            }

            # Start retry thread
            self._retry_thread = threading.Thread(target=self._retry_port_open, daemon=True)
            self._retry_thread.start()

    def _cancel_retry(self):
        """Cancel any pending port open retry"""
        with self._retry_lock:
            self._pending_port_open = None
            if self._retry_thread and self._retry_thread.is_alive():
                # Thread will check _pending_port_open and exit
                pass

    def _retry_port_open(self):
        """Background thread function to retry port opening after 2 seconds"""
        # Wait 2 seconds
        if self._stop_event.wait(2.0):
            return  # Subprocess is stopping

        with self._retry_lock:
            if self._pending_port_open is None:
                return  # Retry was cancelled

            retry_info = self._pending_port_open.copy()
            self._pending_port_open = None

        # Attempt to open port again
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()

            self.serial = serial.Serial(
                retry_info['port_name'],
                baudrate=retry_info['baudrate'],
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=1,
                xonxoff=0,
                rtscts=0
            )

            # Reset timestamping for new port
            with self._timestamp_lock:
                self._first_timestamp = None
                self._last_timestamp_us = 0

            # Start reading thread
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self.read_loop, daemon=True)
                self._thread.start()

            # Send success response
            self.status_queue.put(StatusMessage(Status.PORT_OPENED, retry_info['port_name']))

        except Exception as e:
            # Retry failed - start another retry timer (max 5 attempts)
            if retry_info['retry_count'] < 5:
                self._start_retry_timer(
                    retry_info['port_name'],
                    retry_info['baudrate'],
                    retry_info['request_id']
                )
                self.status_queue.put(StatusMessage(Status.PORT_RETRY, {
                    'attempt': retry_info['retry_count'],
                    'max_attempts': 5,
                    'port': retry_info['port_name'],
                    'error': str(e),
                    'next_retry_seconds': 2
                }))
            else:
                self.status_queue.put(StatusMessage(Status.PORT_ERROR,
                    f"Failed to open port {retry_info['port_name']} after 5 attempts: {str(e)}"))

    def open_port(self, port_name: str, baudrate: int = 115200, request_id: Optional[str] = None) -> bool:
        """Open serial port with specified parameters"""
        try:
            # Cancel any pending retry
            self._cancel_retry()

            if self.serial and self.serial.is_open:
                self.serial.close()

            self.serial = serial.Serial(
                port_name,
                baudrate=baudrate,
                bytesize=8,
                parity='N',
                stopbits=1,
                timeout=1,
                xonxoff=0,
                rtscts=0
            )

            # Reset timestamping for new port
            with self._timestamp_lock:
                self._first_timestamp = None
                self._last_timestamp_us = 0

            # Start reading thread
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self.read_loop, daemon=True)
                self._thread.start()

            # Send success response
            self.status_queue.put(StatusMessage(Status.COMMAND_RESPONSE, {
                'success': True,
                'port': port_name
            }, request_id))
            return True

        except Exception as e:
            # Start retry timer for failed port open
            self._start_retry_timer(port_name, baudrate, request_id)

            # Send error response with retry info
            self.status_queue.put(StatusMessage(Status.COMMAND_RESPONSE, {
                'success': False,
                'error': str(e),
                'retry_in_seconds': 2
            }, request_id))
            return False

    def close_port(self, request_id: Optional[str] = None):
        """Close serial port"""
        try:
            # Cancel any pending retry
            self._cancel_retry()

            if self.serial and self.serial.is_open:
                self.serial.close()
                # Reset timestamping state
                with self._timestamp_lock:
                    self._first_timestamp = None
                    self._last_timestamp_us = 0

            # Send success response
            self.status_queue.put(StatusMessage(Status.COMMAND_RESPONSE, {
                'success': True
            }, request_id))

        except Exception as e:
            # Send error response
            self.status_queue.put(StatusMessage(Status.COMMAND_RESPONSE, {
                'success': False,
                'error': str(e)
            }, request_id))

    def run(self):
        """Main subprocess loop"""
        # Start command processing thread
        self._command_thread = threading.Thread(target=self.command_loop, daemon=True)
        self._command_thread.start()

        # Main loop - periodically send buffered data
        while not self._stop_event.is_set():
            try:
                # Send buffered data every 100ms
                frames = self.data_buffer.get_all_frames()
                if frames:
                    # Separate for backward compatibility
                    logs = []
                    dropped_frames = []

                    for frame in frames:
                        if frame.frame_type == "valid":
                            logs.append(frame.data)
                        elif frame.frame_type in ["dropped", "error"]:
                            dropped_frames.append(DroppedFrameInfo(frame.timestamp_us, frame.error_reason))

                    self.status_queue.put(StatusMessage(Status.DATA_READY, {
                        'logs': logs,
                        'dropped_frames': dropped_frames,
                        'frames': frames  # New unified format
                    }))

                self._stop_event.wait(0.1)  # 100ms interval
            except KeyboardInterrupt:
                break

        # Cleanup
        self.stop()

    def stop(self):
        """Stop all threads and close port"""
        self._stop_event.set()

        # Cancel any pending retry
        self._cancel_retry()

        if self.serial and self.serial.is_open:
            self.serial.close()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._command_thread and self._command_thread.is_alive():
            self._command_thread.join(timeout=1.0)
        if self._retry_thread and self._retry_thread.is_alive():
            self._retry_thread.join(timeout=1.0)

    def command_loop(self):
        """Process commands from the main process"""
        while not self._stop_event.is_set():
            try:
                # Check for commands with timeout
                try:
                    cmd_msg = self.command_queue.get(timeout=0.1)
                except:
                    continue  # Timeout, continue loop

                if isinstance(cmd_msg, CommandMessage):
                    if cmd_msg.command == Command.OPEN_PORT:
                        if isinstance(cmd_msg.data, dict):
                            port_name = cmd_msg.data.get('port_name')
                            baudrate = cmd_msg.data.get('baudrate', 115200)
                            self.open_port(port_name, baudrate, cmd_msg.request_id)
                        else:
                            # Backward compatibility
                            self.open_port(cmd_msg.data, request_id=cmd_msg.request_id)
                    elif cmd_msg.command == Command.CLOSE_PORT:
                        self.close_port(cmd_msg.request_id)
                    elif cmd_msg.command == Command.QUIT:
                        self._stop_event.set()
                        break

            except Exception as e:
                self.status_queue.put(StatusMessage(Status.PORT_ERROR, f"Command error: {e}"))

    def read_loop(self):
        """Read data from serial port and buffer it"""
        while self.serial and self.serial.is_open and not self._stop_event.is_set():
            try:
                b = self.serial.read_until(EOF.to_bytes(), size=11520)
                if len(b) < 2:
                    raise ValueError("Invalid COBS packet size")

                decoded = cobs_decode(b)

                # Get monotonic timestamp in microseconds since first valid data
                timestamp_us = self._get_monotonic_timestamp_us()

                # Add valid frame to buffer
                self.data_buffer.put_valid_frame(decoded, timestamp_us)
                self.bad_data = False
            except Exception as e:
                # Get timestamp for error frame
                error_timestamp_us = self._get_monotonic_timestamp_us()

                # Add error frame to buffer
                self.data_buffer.put_error_frame(error_timestamp_us, f"Read error: {str(e)}")

                if not self.bad_data:
                    self.status_queue.put(StatusMessage(Status.PORT_ERROR, f"Read error: {e}"))
                    self.bad_data = True


def run_subprocess(command_queue: mp.Queue, status_queue: mp.Queue, app_logs):
    """Entry point for running the serial reader as a subprocess"""
    reader = Reader(command_queue, status_queue, app_logs)
    try:
        reader.run()
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()

class AsyncSerialReaderAPI:
    """
    Async API for serial reader that provides awaitable data reading
    with synchronous port operations for error handling.
    """

    def __init__(self, app_logs):
        self.app_logs = app_logs
        self._process: Optional[mp.Process] = None
        self._command_queue: Optional[mp.Queue] = None
        self._status_queue: Optional[mp.Queue] = None
        self._status_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False

        # Data queue for async operations
        self._data_queue = asyncio.Queue()
        self._pending_responses = {}  # Track synchronous command responses
        self._response_events = {}  # Events for waiting on responses

        # Register cleanup on application exit and signals
        atexit.register(self._cleanup)
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            asyncio.create_task(self.stop())
            sys.exit(0)

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            if hasattr(signal, 'SIGBREAK'):
                signal.signal(signal.SIGBREAK, signal_handler)
        except (OSError, ValueError):
            pass

    async def start(self) -> bool:
        """Start the serial reader subprocess"""
        if self._is_running:
            return True

        try:
            # Create communication queues
            self._command_queue = mp.Queue()
            self._status_queue = mp.Queue()

            # Start subprocess
            self._process = mp.Process(
                target=run_subprocess,
                args=(self._command_queue, self._status_queue, self.app_logs)
            )
            self._process.daemon = True
            self._process.start()

            # Start status monitoring thread
            self._status_thread = threading.Thread(target=self._status_monitor, daemon=True)
            self._status_thread.start()

            self._is_running = True
            return True

        except Exception as e:
            self._cleanup()
            raise RuntimeError(f"Failed to start serial reader: {e}")

    async def stop(self):
        """Stop the serial reader subprocess"""
        if not self._is_running:
            return

        try:
            # Send quit command
            if self._command_queue:
                self._command_queue.put(CommandMessage(Command.QUIT))

            # Stop status monitoring
            self._stop_event.set()

            # Wait for subprocess to finish
            if self._process and self._process.is_alive():
                await asyncio.get_event_loop().run_in_executor(
                    None, self._wait_for_process
                )

            # Wait for status thread
            if self._status_thread and self._status_thread.is_alive():
                await asyncio.get_event_loop().run_in_executor(
                    None, self._status_thread.join, 1.0
                )

        finally:
            self._cleanup()

    def _wait_for_process(self):
        """Helper to wait for subprocess termination"""
        if self._process and self._process.is_alive():
            self._process.join(timeout=2.0)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
                if self._process.is_alive():
                    self._process.kill()

    def open_port(self, port_name: str, baudrate: int = 115200) -> Tuple[bool, Optional[str]]:
        """
        Synchronously open a serial port. Blocks until completion.
        Returns (success, error_message)
        """
        if not self._is_running:
            return False, "Serial reader not started"

        request_id = str(uuid.uuid4())

        try:
            # Set up response waiting
            response_event = threading.Event()
            self._response_events[request_id] = response_event

            # Send command
            self._command_queue.put(CommandMessage(Command.OPEN_PORT, {
                'port_name': port_name,
                'baudrate': baudrate
            }, request_id))

            # Wait for response (blocking)
            if response_event.wait(timeout=5.0):  # 5 second timeout
                response = self._pending_responses.pop(request_id, None)
                if response and response.get('success'):
                    return True, None
                else:
                    return False, response.get('error', 'Unknown error')
            else:
                return False, "Operation timed out"

        except Exception as e:
            return False, str(e)
        finally:
            # Cleanup
            self._response_events.pop(request_id, None)
            self._pending_responses.pop(request_id, None)

    def close_port(self) -> Tuple[bool, Optional[str]]:
        """
        Synchronously close the serial port. Blocks until completion.
        Returns (success, error_message)
        """
        if not self._is_running:
            return True, None

        request_id = str(uuid.uuid4())

        try:
            # Set up response waiting
            response_event = threading.Event()
            self._response_events[request_id] = response_event

            # Send command
            self._command_queue.put(CommandMessage(Command.CLOSE_PORT, None, request_id))

            # Wait for response (blocking)
            if response_event.wait(timeout=5.0):
                response = self._pending_responses.pop(request_id, None)
                if response and response.get('success'):
                    return True, None
                else:
                    return False, response.get('error', 'Unknown error')
            else:
                return False, "Operation timed out"

        except Exception as e:
            return False, str(e)
        finally:
            # Cleanup
            self._response_events.pop(request_id, None)
            self._pending_responses.pop(request_id, None)

    async def read_data(self):
        """
        Async generator that yields a uniform, chronologically ordered list of frames.

        Args:
            None

        Yields:
            List[FrameData]: Ordered list of frames containing:
                - Valid frames: FrameData with frame_type="valid", data=LogEntry
                - Error frames: FrameData with frame_type="error", error_reason=error_msg
                - Dropped frames: FrameData with frame_type="dropped", error_reason="buffer_overflow"

        All frames are ordered by timestamp_us for proper chronological sequence.
        Use this in an async for loop to continuously read data.
        """
        while self._is_running:
            try:
                data = await self._data_queue.get()
                frames = data.get('frames', [])
                if frames:
                    yield frames
            except asyncio.CancelledError:
                break

    def is_running(self) -> bool:
        """Check if the serial reader is running"""
        return self._is_running and self._process and self._process.is_alive()

    def _status_monitor(self):
        """Monitor status messages from subprocess"""
        while not self._stop_event.is_set() and self._is_running:
            try:
                # Check subprocess health
                if self._process and not self._process.is_alive():
                    break

                # Check for status messages with timeout
                try:
                    status_msg = self._status_queue.get(timeout=0.1)
                except:
                    continue

                if isinstance(status_msg, StatusMessage):
                    self._handle_status_message(status_msg)

            except Exception:
                pass

    def _handle_status_message(self, msg: StatusMessage):
        """Handle status messages from subprocess"""
        if msg.status == Status.COMMAND_RESPONSE and msg.request_id:
            # Handle synchronous command response
            self._pending_responses[msg.request_id] = msg.data
            event = self._response_events.get(msg.request_id)
            if event:
                event.set()

        elif msg.status == Status.DATA_READY:
            # Handle async data
            try:
                # Put data into async queue (non-blocking)
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(
                    self._data_queue.put(msg.data), loop
                )
            except RuntimeError:
                # No event loop running, ignore
                pass

    def _cleanup(self):
        """Internal cleanup method"""
        self._is_running = False
        self._stop_event.set()

        # Clear pending responses
        for event in self._response_events.values():
            event.set()
        self._response_events.clear()
        self._pending_responses.clear()

        # Close queues
        if self._command_queue:
            try:
                self._command_queue.close()
            except:
                pass
        if self._status_queue:
            try:
                self._status_queue.close()
            except:
                pass

        self._command_queue = None
        self._status_queue = None
        self._process = None
        self._status_thread = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop()

    def __del__(self):
        """Destructor - ensures cleanup"""
        try:
            self._cleanup()
        except:
            pass

def create_async_serial_reader(app_logs) -> AsyncSerialReaderAPI:
    """Create a new AsyncSerialReaderAPI instance"""
    return AsyncSerialReaderAPI(app_logs)


"""
Example Usage:

# ASYNC API (Recommended for new code)
async def main():
    async with create_async_serial_reader(app_logs) as reader:
        # Synchronous port operations (blocking, returns error status)
        success, error = reader.open_port("COM3", 115200)
        if not success:
            print(f"Failed to open port: {error}")
            return

        # Async data reading with unified frame format
        async for frames in reader.read_data():
            # Process all frames in chronological order
            for frame in frames:
                timestamp_s = frame.timestamp_us / 1_000_000.0

                if frame.frame_type == "valid":
                    # Process valid log entry
                    process_log(frame.data, timestamp_s)
                elif frame.frame_type == "error":
                    # Handle error frame
                    print(f"Error at {timestamp_s:.6f}s: {frame.error_reason}")
                elif frame.frame_type == "dropped":
                    # Handle dropped frame
                    print(f"Dropped frame at {timestamp_s:.6f}s: {frame.error_reason}")

        # Synchronous close (blocking)
        success, error = reader.close_port()

# Or with manual management
async def manual_example():
    reader = create_async_serial_reader(app_logs)
    try:
        await reader.start()

        success, error = reader.open_port("COM3", 115200)

        if success:
            async for frames in reader.read_data():
                # Process all frames in unified, chronological order
                for frame in frames:
                    if frame.frame_type == "valid":
                        process_log(frame.data)
                    elif frame.frame_type in ["error", "dropped"]:
                        handle_error_frame(frame.timestamp_us, frame.error_reason)
    finally:
        await reader.stop()


# Legacy format example (for backward compatibility)
async def legacy_example():
    async with create_async_serial_reader(app_logs) as reader:
        success, error = reader.open_port("COM3", 115200)
        if success:
            # Use legacy method for old code compatibility
            async for logs, dropped_frames in reader.read_data_legacy():
                for log in logs:
                    process_log(log)
                for dropped in dropped_frames:
                    handle_dropped_frame(dropped.timestamp_us, dropped.reason)

"""


if __name__ == "__main__":
    from Logger import Logger
    log = Logger("serial_reader_test")

    async def main():
        async with create_async_serial_reader(log) as reader:
            # Synchronous port operations (blocking, returns error status)
            success, error = reader.open_port("COM3", 115200)

            if not success:
                print(f"Failed to open port: {error}")
                return

            # Async data reading with unified frame format
            async for frames in reader.read_data():
                # Process all frames in chronological order
                for frame in frames:
                    timestamp_s = frame.timestamp_us / 1_000_000.0

                    if frame.frame_type == "valid":
                        # Process valid log entry
                        print(frame.data, timestamp_s)
                    elif frame.frame_type == "error":
                        # Handle error frame
                        print(f"Error at {timestamp_s:.6f}s: {frame.error_reason}")
                    elif frame.frame_type == "dropped":
                        # Handle dropped frame
                        print(f"Dropped frame at {timestamp_s:.6f}s: {frame.error_reason}")

            # Synchronous close (blocking)
            success, error = reader.close_port()

    asyncio.run(main())
