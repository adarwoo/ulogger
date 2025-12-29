#!/usr/bin/env python3
import os
import struct

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
    length = None  # Variable length
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
        payload_length, types = decode_typecode(int.from_bytes(data[8:12], endianness))

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
        self.endianness = 'little'  # Default to little-endian
        # Packet reassembly state
        self._pending_log_id = None
        self._pending_args = []
        self._pending_string_chunks = []  # For accumulating string data across packets
        self._incomplete_log_queue = []  # Queue for incomplete log errors

    def reset(self, section, little_endian=True):
        """Process a new .logs section.

        Args:
            section: The .logs section from the ELF file
            little_endian: Boolean indicating if the ELF is little-endian (default: True)
        """
        self.entries = [] # Reset the entries
        offset = 0
        data = section.data()

        while offset < len(data):
            # Create a slice of .data_alignment bytes
            if offset + section.data_alignment > len(data):
                self.entries = [] # 1 bad = all bad
                raise ValueError("Not enough data for a complete log entry")

            data_slice = data[offset:offset + section.data_alignment]
            entry = Log.from_elf_data(data_slice)
            self.entries.append(entry)
            offset += section.data_alignment

        self.elf_ready = True

    def decode_packet(self, data):
        """
        Decode a single packet (one argument). Each log entry may span multiple packets.
        Args:
            data (bytes): The raw packet data [log_id][arg_data]
        Returns:
            Tuple of (Log, values) if log entry is complete, None if more packets needed
        """
        # First, check if there's a queued incomplete log to return
        if self._incomplete_log_queue:
            return self._incomplete_log_queue.pop(0)

        if not self.elf_ready:
            raise ElfNotReady("ELF file not ready")

        if len(data) < 1:
            return None

        log_id = data[0]
        arg_data = data[1:] if len(data) > 1 else b''

        # Handle special log IDs
        if log_id == 255:  # Overflow
            entry = Log(0, 0, "OVERRUN", "< ------------------ {} Logs lost ------------------ >", 1, [TypeU8])
            count = struct.unpack('B', arg_data[:1])[0] if len(arg_data) >= 1 else 0
            return (entry, (count,))
        elif log_id == 254:  # Start
            entry = Log(0, 0, "START", "#" * 79, 0, [])
            return (entry, ())
        elif log_id >= len(self.entries):
            raise ValueError(f"Invalid log ID: {log_id}")

        entry = self.entries[log_id]

        # Check if this is a new log or continuation
        if self._pending_log_id is not None and self._pending_log_id != log_id:
            # New log ID before previous log completed - data loss!
            # Queue an error entry for the incomplete log
            prev_entry = self.entries[self._pending_log_id]
            incomplete_entry = Log(0, 0, "INCOMPLETE",
                                  f"Log ID {self._pending_log_id} ({prev_entry.filename}:{prev_entry.line}): expected {len(prev_entry.types)} args, got {len(self._pending_args)}",
                                  0, [])
            self._incomplete_log_queue.append((incomplete_entry, tuple(self._pending_args)))

            # Reset state for new log and continue processing current packet
            self._pending_log_id = log_id
            self._pending_args = []
            self._pending_string_chunks = []

        elif self._pending_log_id != log_id:
            # Starting a new log entry
            self._pending_log_id = log_id
            self._pending_args = []
            self._pending_string_chunks = []

        # Determine expected argument type
        arg_idx = len(self._pending_args)
        if arg_idx >= len(entry.types):
            # All arguments received - reset and return
            result = (entry, tuple(self._pending_args))
            self._pending_log_id = None
            self._pending_args = []
            self._pending_string_chunks = []
            return result

        arg_type = entry.types[arg_idx]

        # Handle string type (variable length, multi-packet)
        if arg_type == TypeStr:
            # Check if this packet contains null terminator
            if b'\x00' in arg_data:
                # String complete
                self._pending_string_chunks.append(arg_data)
                full_string_data = b''.join(self._pending_string_chunks)
                string_value = TypeStr.from_bytes(full_string_data)
                self._pending_args.append(string_value)
                self._pending_string_chunks = []
            else:
                # More string data coming
                self._pending_string_chunks.append(arg_data)
                return None  # Need more packets
        else:
            # Fixed-size argument - decode directly
            endian_prefix = '<' if self.endianness == 'little' else '>'
            fmt = endian_prefix + arg_type.unpack_format
            value = struct.unpack(fmt, arg_data[:arg_type.length])[0]
            self._pending_args.append(value)

        # Check if all arguments received
        if len(self._pending_args) == len(entry.types):
            result = (entry, tuple(self._pending_args))
            self._pending_log_id = None
            self._pending_args = []
            self._pending_string_chunks = []
            return result

        # More arguments expected
        return None

    def decode_frame(self, data):
        """
        Legacy method for backward compatibility.
        Now delegates to decode_packet().
        """
        return self.decode_packet(data)
