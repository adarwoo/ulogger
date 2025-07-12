#!/usr/bin/env python3
import os
import struct

class ElfNotReady(Exception):
    pass

class TypeNone:
    length = 0
    @classmethod
    def from_bytes(cls, data):
        return None

class TypeU8:
    length = 1
    @classmethod
    def from_bytes(cls, data):
        return int(data[0])

class TypeS8:
    length = 1
    @classmethod
    def from_bytes(cls, data):
        val = int(data[0])
        return val if val < 0x80 else val - 0x100

class TypeB8:
    length = 1
    @classmethod
    def from_bytes(cls, data):
        return bool(data[0])

class TypeU16:
    length = 2
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:2], 'little')

class TypeS16:
    length = 2
    @classmethod
    def from_bytes(cls, data):
        val = int.from_bytes(data[:2], 'little')
        return val if val < 0x8000 else val - 0x10000

class TypePtr16:
    length = 2
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:2], 'little')

class TypeU32:
    length = 4
    @classmethod
    def from_bytes(cls, data):
        return int.from_bytes(data[:4], 'little')

class TypeS32:
    length = 4
    @classmethod
    def from_bytes(cls, data):
        val = int.from_bytes(data[:4], 'little')
        return val if val < 0x80000000 else val - 0x100000000

class TypeFloat32:
    length = 4
    @classmethod
    def from_bytes(cls, data):
        return struct.unpack('<f', data[:4])[0]

class TypeStr4:
    length = 4
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
        code = (typecode >> (i * 8)) & 0xFF

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
    __slots__ = ('level', 'line', 'filename', 'fmt', 'payload_length', 'types', 'data')

    def __init__(self, level, line, filename, fmt, payload_length, types):
        self.level = level
        self.line = line
        self.filename = filename
        self.fmt = fmt
        self.payload_length = payload_length
        self.types = types
        # Store the Python typed data for displaying
        self.data = None

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
        """ Decode a serial data frame into a log entry. """

        if not self.elf_ready:
            raise ElfNotReady("ELF file not ready")

        # The first byte is the log ID, the second byte is the payload length
        log_id = data[0]

        # Check if the log ID is valid
        if log_id >= len(self.entries):
            raise ValueError(f"Invalid log ID: {log_id}")

        entry = self.entries[log_id]

        offset = 1 # Use offset to avoid createing a new slice
        values = []

        # For each of the types, read the payload
        for value_type in entry.types:
            if len(data) < offset + value_type.length:
                raise ValueError(f"Invalid payload length for log ID {log_id}: "
                                 f"expected {value_type.length}, got {len(data) - offset}")
            # Read the value from the data
            value = value_type.from_bytes(data[offset:offset + value_type.length])
            offset += value_type.length

            values.append(value)

        # If the payload length is not equal to the expected length, raise an error
        if offset != len(data):
            raise ValueError(f"Invalid payload length for log ID {log_id}: "
                             f"expected {entry.payload_length}, got {offset}")

        # Store the values in the entry
        entry.data = values

        return entry

