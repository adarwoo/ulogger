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

class TypeStr4:
    length = 4
    unpack_format = '4s'
    @classmethod
    def from_bytes(cls, data):
        return data[:4].decode(errors='replace')


def decode_typecode(typecode):
    """
    Decodes a 32-bit typecode into a tuple of argument types.
    Each byte in typecode represents an argument type.
    """
    TYPE_MAP = {
        0x00: TypeNone,
        0x10: TypeU8,
        0x11: TypeS8,
        0x12: TypeB8,
        0x20: TypeU16,
        0x21: TypeS16,
        0x22: TypePtr16,
        0x40: TypeU32,
        0x41: TypeS32,
        0x42: TypeFloat32,
        0x43: TypeStr4
    }

    types = []
    length = 0

    for i in range(4):
        code = (typecode >> ((i) * 8)) & 0xFF

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
    def from_elf_data(cls, data):
        level = data[0]
        line = int.from_bytes(data[1:5], 'little')
        payload_length, types = decode_typecode(int.from_bytes(data[5:9], 'little'))

        def read_cstr(offset=9, is_filename=True):
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

    def reset(self, section):
        """Process a new .logs section."""
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

    def decode_frame(self, data):
        """
        Decode a serial data frame into a log entry.
        Args:
            data (bytes): The raw data frame received from the serial port.
        Returns:
            A tuple of (Log, list of values) where:
            - Log is the static log entry metadata.
            - list of values is the decoded payload values.
        """

        if not self.elf_ready:
            raise ElfNotReady("ELF file not ready")

        # The first byte is the log ID, the second byte is the payload length
        log_id = data[0]

        # ID = 255 -> Overflow!
        if log_id == 255:
            entry =  Log(0, 0, "OVERRUN", "< ------------------ {} Logs lost ------------------ >", 1, [TypeU8])
        elif log_id == 254:
            entry =  Log(0, 0, "START", "#" * 79, 0, [])
        # Check if the log ID is valid
        elif log_id >= len(self.entries):
            raise ValueError(f"Invalid log ID: {log_id}")
        else:
            entry = self.entries[log_id]

        # Decode each value in the payload using the decode_string and unpack
        values = struct.unpack("<" + entry.decode_string, data[1:])

        return entry, values
