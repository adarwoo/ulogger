#!/usr/bin/env python3
from elftools.elf.elffile import ELFFile
import struct

elf_path = r'E:\gax\dev\cnc_solution\modbus_relay\Release\modbus_relay.elf'

with open(elf_path, 'rb') as f:
    elf = ELFFile(f)
    section = elf.get_section_by_name('.logs')

    print(f"Section: {section.name}")
    print(f"Size: {section.data_size} bytes")
    print(f"Alignment: {section.data_alignment}")
    print(f"Endianness: {'little' if elf.little_endian else 'big'}")
    print(f"Total entries: {section.data_size // section.data_alignment}")
    print()

    # Parse the entries
    data = section.data()
    endianness = 'little' if elf.little_endian else 'big'
    entry_size = section.data_alignment

    # Find entry 62
    print(f"Looking for entry 62 (offset {62 * entry_size}):")
    if 62 * entry_size + entry_size <= len(data):
        offset = 62 * entry_size
        entry_data = data[offset:offset + entry_size]

        level = int.from_bytes(entry_data[0:4], endianness)
        line = int.from_bytes(entry_data[4:8], endianness)
        typecode = int.from_bytes(entry_data[8:12], endianness)

        print(f"  Entry 62:")
        print(f"    Level: {level}")
        print(f"    Line: {line}")
        print(f"    Typecode: 0x{typecode:08x}")
        print(f"    Raw bytes (first 32): {entry_data[:32].hex()}")

        # Try to extract strings
        str_start = 12
        null_pos = entry_data.find(b'\x00', str_start)
        if null_pos != -1:
            filename = entry_data[str_start:null_pos].decode(errors='replace')
            print(f"    Filename: {filename}")

            str_start = null_pos + 1
            null_pos = entry_data.find(b'\x00', str_start)
            if null_pos != -1:
                fmt = entry_data[str_start:null_pos].decode(errors='replace')
                print(f"    Format: {fmt}")
    else:
        print("  Entry 62 not found!")

    print()
    print("First 5 entries:")
    for i in range(min(5, section.data_size // entry_size)):
        offset = i * entry_size
        entry_data = data[offset:offset + entry_size]

        level = int.from_bytes(entry_data[0:4], endianness)
        line = int.from_bytes(entry_data[4:8], endianness)
        typecode = int.from_bytes(entry_data[8:12], endianness)

        print(f"  Entry {i}: level={level}, line={line}, typecode=0x{typecode:08x}")
