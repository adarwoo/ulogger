#!/usr/bin/env python3
import os
import struct
import logging

# Configure debug logging to file
logging.basicConfig(filename='ulogger_debug.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class ElfNotReady(Exception):
    pass

class TypeNone:
    length = 0
    unpack_format = ''
    @classmethod
    def from_bytes(cls, data):
        return None

class TypeU8:
    length = 1
    unpack_format = 'B'
    @classmethod
    def from_bytes(cls, data):
        return int(data[0])

class TypeS8:
    length = 1
    unpack_format = 'b'
    @classmethod
    def from_bytes(cls, data):
        val = int(data[0])
        return val if val < 0x80 else val - 0x100

class TypeB8:
    length = 1
    unpack_format = '?'
    @classmethod
    def from_bytes(cls, data):
        return bool(data[0])

class TypeU16:
    length = 2
    unpack_format = 'H'
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:2], 'big')

class TypeS16:
    length = 2
    unpack_format = 'h'
    @classmethod
    def from_bytes(cls, data):
        val = int.from_bytes(data[:2], 'big')
        return val if val < 0x8000 else val - 0x10000

class TypePtr16:
    length = 2
    unpack_format = 'H'
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:2], 'big')

class TypeU32:
    length = 4
    unpack_format = 'I'
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:4], 'big')

class TypeS32:
    length = 4
    unpack_format = 'i'
    @classmethod
    def from_bytes(cls, data):
        val = int.from_bytes(data[:4], 'big')
        return val if val < 0x80000000 else val - 0x100000000

class TypeFloat32:
    length = 4
    unpack_format = 'f'
    @classmethod
    def from_bytes(cls, data):
        return struct.unpack('<f', data[:4])[0]

class TypeStr:
    length = 0  # Variable length - look for ending null byte
    unpack_format = 's'  # Will be handled specially
    @classmethod
    def from_bytes(cls, data):
        # Find null terminator, if present
        null_idx = data.find(b'\x00')
        if null_idx != -1:
            return data[:null_idx].decode(errors='replace')
        return data.decode(errors='replace')


def decode_typecode(typecode):
    """
    Decodes a 32-bit typecode into a tuple of argument types.
    Each byte in typecode represents an argument type.
    """
    TYPE_MAP = {
        0x00: TypeNone,
        0x01: TypeU8,
        0x02: TypeS8,
        0x03: TypeB8,
        0x04: TypeU16,
        0x05: TypeS16,
        0x06: TypePtr16,
        0x07: TypeU32,
        0x08: TypeS32,
        0x09: TypeFloat32,
        0x0A: TypeStr
    }

    types = []
    length = 0

    for i in range(8):
        code = (typecode >> ((i) * 4)) & 0x0F

        if code == 0x00:
            break

        value_type = TYPE_MAP.get(code, None)

        if value_type is None:
            raise ValueError(f"Unknown type code: {code:02x}")

        length += value_type.length
        types.append(value_type)

    return (length, tuple(types))

class Log:
    """
    Represents a single static log entry in the .logs segment with its metadata.

    Returns:
        _type_: _description_
    """
    __slots__ = ('level', 'line', 'filename', 'fmt', 'payload_length', 'types', 'decode_string')

    def __init__(self, level, line, filename, fmt, payload_length, types):
        self.level = level
        self.line = line
        self.filename = filename
        self.fmt = fmt
        self.payload_length = payload_length
        self.types = types
        self.decode_string = ''.join(t.unpack_format for t in types)

    @classmethod
    def from_elf_data(cls, data, endianness='little'):
        level = int.from_bytes(data[0:4], endianness)
        line = int.from_bytes(data[4:8], endianness)
        typecode_raw = int.from_bytes(data[8:12], endianness)
        payload_length, types = decode_typecode(typecode_raw)

        logging.debug(f"ELF Log Entry: level={level}, line={line}, typecode=0x{typecode_raw:08x}, types={[t.__name__ for t in types]}")

        def read_cstr(offset=12, is_filename=True):
            start = offset
            while offset < len(data) and data[offset] != 0:
                offset += 1
            s = data[start:offset].decode(errors='replace')
            offset += 1

            if is_filename:
                return os.path.basename(s), offset

            return s, offset

        filename, offset = read_cstr()
        fmt, _ = read_cstr(offset, False)
        return cls(level, line, filename, fmt, payload_length, types)


class LogEntry:
    """
    Represents a log entry with its metadata and payloads.
    This is used to store the logs in the circular buffer.
    """
    def __init__(self, static_log, timestamp, data):
        self.logmeta = static_log
        self.timestamp = timestamp
        self.data = data

    @property
    def level(self):
        return self.logmeta.level

    @property
    def line(self):
        return self.logmeta.line

    @property
    def filename(self):
        return self.logmeta.filename

    @property
    def fmt(self):
        return self.logmeta.fmt

    def __repr__(self):
        return f"LogEntry(logmeta={self.logmeta}, timestamp={self.timestamp}, data={self.data})"


class ApplicationLogs:
    """Represents the application logs with their metadata and payloads."""
    def __init__(self):
        self.entries = []
        self.elf_ready = False
        self.endianness = 'little'  # Native endianness (default to little-endian)
        # Packet reassembly state
        self._pending_log_id = None
        self._pending_args = []
        self._pending_string_chunks = []  # For accumulating string data across packets
        self._incomplete_log_queue = []  # Queue for incomplete log errors
        self._is_first_packet = True  # Track if expecting first packet (bit 15 = 0)

    def reset(self, section, little_endian=False):
        """Process a new .logs section.

        Args:
            section: The .logs section from the ELF file
            little_endian: Boolean indicating if the ELF is little-endian (default: False, uses big-endian)
        """
        self.entries = [] # Reset the entries
        # Set endianness based on ELF file (for both metadata and transmitted data)
        self.endianness = 'little' if little_endian else 'big'
        logging.debug(f"Loading ELF with endianness: {self.endianness}")
        offset = 0
        data = section.data()

        while offset < len(data):
            # Create a slice of .data_alignment bytes
            if offset + section.data_alignment > len(data):
                self.entries = [] # 1 bad = all bad
                raise ValueError("Not enough data for a complete log entry")

            data_slice = data[offset:offset + section.data_alignment]
            entry = Log.from_elf_data(data_slice, self.endianness)
            self.entries.append(entry)
            offset += section.data_alignment

        self.elf_ready = True

    def decode_packet(self, data):
        """
        Decode a single packet (one argument/variable). Each variable is sent in a distinct packet.

        Protocol:
        - Packet header (log ID) is 16-bits in target CPU's native endianness (from ELF)
        - Bit 15 (MSB) indicates packet type: 0 = first packet, 1 = continuation packet
        - Data payload also uses target CPU's native endianness
        - Strings can be sent segmented; last packet contains zero to indicate end

        Args:
            data (bytes): The raw packet data [log_id_low][log_id_high][arg_data] (little-endian for AVR)
        Returns:
            Tuple of (Log, values) if log entry is complete, None if more packets needed
        """
        # First, check if there's a queued incomplete log to return
        if self._incomplete_log_queue:
            return self._incomplete_log_queue.pop(0)

        if not self.elf_ready:
            raise ElfNotReady("ELF file not ready")

        if len(data) < 2:
            return None

        # Parse 16-bit log ID using target CPU's native endianness (from ELF)
        # logging.debug(f"Raw packet bytes: {data[:4].hex()}")
        log_id_raw = int.from_bytes(data[0:2], self.endianness)

        # Extract bit 15 (MSB) to determine if first or continuation packet
        is_first_packet = (log_id_raw & 0x8000) == 0

        # Mask out bit 15 to get actual log ID
        log_id = log_id_raw & 0x7FFF

        arg_data = data[2:] if len(data) > 2 else b''

        # logging.debug(f"Received packet - raw_id=0x{log_id_raw:04x}, log_id={log_id}, is_first={is_first_packet}, data_len={len(arg_data)}")
        # Handle special log IDs (using 16-bit values now)
        if log_id == 0x7FFF:  # Overrun
            entry = Log(0, 0, "OVERRUN", "< ------------------ {} Logs lost ------------------ >", 1, [TypeU8])
            count = struct.unpack('B', arg_data[:1])[0] if len(arg_data) >= 1 else 0
            return (entry, (count,))
        elif log_id == 0x7FFE:  # Start
            entry = Log(0, 0, "START", "#" * 79, 0, [])
            return (entry, ())
        elif log_id >= len(self.entries):
            raise ValueError(f"Invalid log ID: {log_id}")

        entry = self.entries[log_id]

        # Check if this is a new log entry (first packet with bit 15 = 0)
        if is_first_packet:
            # logging.debug(f"First packet for log_id={log_id}, entry types={[t.__name__ for t in entry.types]}, fmt={entry.fmt}")
            # If we were assembling a previous log, it's incomplete
            if self._pending_log_id is not None:
                # logging.debug(f"Incomplete previous log {self._pending_log_id} with {len(self._pending_args)} args")
                prev_entry = self.entries[self._pending_log_id]
                incomplete_entry = Log(0, 0, "INCOMPLETE",
                                      f"Log ID {self._pending_log_id} ({prev_entry.filename}:{prev_entry.line}): expected {len(prev_entry.types)} args, got {len(self._pending_args)}",
                                      0, [])
                self._incomplete_log_queue.append((incomplete_entry, tuple(self._pending_args)))

            # Start new log entry
            self._pending_log_id = log_id
            self._pending_args = []
            self._pending_string_chunks = []
            self._is_first_packet = True
            # logging.debug(f"Started new log entry, expects {len(entry.types)} args")
        else:
            # Continuation packet (bit 15 = 1) - should be for the current pending log
            # logging.debug(f"Continuation packet - log_id={log_id}, log_id_raw=0x{log_id_raw:04x}, is_first={is_first_packet}")
            # logging.debug(f"State - pending_log_id={self._pending_log_id}, pending_args={len(self._pending_args)}, pending_string_chunks={len(self._pending_string_chunks)}")
            if self._pending_log_id is None:
                # Continuation packet without a first packet - error
                logging.error(f"ERROR - No log in progress!")
                raise ValueError(f"Unexpected continuation packet for log ID {log_id} - no log in progress")
            if self._pending_log_id != log_id:
                # Continuation packet for different log ID - error
                logging.error(f"ERROR - Wrong log ID! Expected {self._pending_log_id}, got {log_id}")
                raise ValueError(f"Unexpected continuation packet: expected log ID {self._pending_log_id}, got {log_id}")

        # Determine expected argument type based on how many args we've already collected
        arg_idx = len(self._pending_args)

        # If we're processing a continuation for a string that's not yet complete,
        # the arg_idx should still point to the current string argument
        if self._pending_string_chunks:
            # We're in the middle of a multi-packet string - don't increment arg_idx
            arg_idx = len(self._pending_args)

        if arg_idx >= len(entry.types):
            # All arguments received - this shouldn't happen
            # Reset and return the complete log
            result = (entry, tuple(self._pending_args))
            self._pending_log_id = None
            self._pending_args = []
            self._pending_string_chunks = []
            self._is_first_packet = True
            return result

        arg_type = entry.types[arg_idx]

        # Handle string type (variable length, can be multi-packet/segmented)
        if arg_type == TypeStr:
            # Accumulate all string data from this packet (no length checking for strings)
            self._pending_string_chunks.append(arg_data)

            # Check if this packet contains null terminator (end of string)
            if b'\x00' in arg_data:
                # String complete
                full_string_data = b''.join(self._pending_string_chunks)
                string_value = TypeStr.from_bytes(full_string_data)
                self._pending_args.append(string_value)
                self._pending_string_chunks = []
            else:
                # More string data coming in next packet
                return None  # Need more packets
        else:
            # Fixed-size argument - decode directly using native endianness from ELF
            # For fixed-size types, we know the exact length and use all arg_data
            endian_prefix = '<' if self.endianness == 'little' else '>'
            fmt = endian_prefix + arg_type.unpack_format
            if len(arg_data) >= arg_type.length:
                value = struct.unpack(fmt, arg_data[:arg_type.length])[0]
                # logging.debug(f"Decoded {arg_type.__name__}: fmt={fmt}, data={arg_data[:arg_type.length].hex()}, value={value}")
                self._pending_args.append(value)
            else:
                raise ValueError(f"Insufficient data for {arg_type.__name__}: expected {arg_type.length} bytes, got {len(arg_data)}")

        # Check if all arguments received
        if len(self._pending_args) == len(entry.types):
            result = (entry, tuple(self._pending_args))
            self._pending_log_id = None
            self._pending_args = []
            self._pending_string_chunks = []
            self._is_first_packet = True
            return result

        # More arguments expected
        return None

    def decode_frame(self, data):
        """
        Legacy method for backward compatibility.
        Now delegates to decode_packet().
        """
        return self.decode_packet(data)
