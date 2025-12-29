import os
import time
import hashlib

from elftools.elf.elffile import ELFFile, ELFError

from .messages import ControlMsg
from .logs import ApplicationLogs


class Reader:
    def __init__(self, args, queue):
        self.elf_path = args.elf
        self.poll_interval = 1.0  # seconds
        self.running = True
        self.queue = queue
        self.last_mtime = None
        self.logs = ApplicationLogs()

    def run(self):
        while self.running:
            if not os.path.exists(self.elf_path):
                self.queue.put(ControlMsg.WAIT_FOR_ELF)
                time.sleep(self.poll_interval)
            else:
                mtime = os.path.getmtime(self.elf_path)

                if self.last_mtime != mtime:
                    self.load_elf()
                    self.last_mtime = mtime

            time.sleep(self.poll_interval)

    def stop(self):
        self.running = False

    def load_elf(self):
        section = None
        digest = None

        if not os.path.isfile(self.elf_path):
            self.queue.put(ControlMsg.WAIT_FOR_ELF)
            return

        try:
            sha256 = hashlib.sha256()

            with open(self.elf_path, 'rb') as elf_file:

                for chunk in iter(lambda: elf_file.read(4096), b''):
                    sha256.update(chunk)

                elf_file.seek(0)
                elf = ELFFile(elf_file)
                section = elf.get_section_by_name('.logs')

                if not section:
                    self.queue.put(ControlMsg.failed_to_read_elf(f"No .logs section in ELF file '{self.elf_path}'"))
                    return

                # Read the section data (the elf file must still be opened)
                # Detect endianness from ELF header
                little_endian = elf.little_endian
                self.logs.reset(section, little_endian)

            digest = sha256.hexdigest()
        except (ELFError, OSError) as open_exc:
            self.queue.put(ControlMsg.failed_to_read_elf(f"Failed to open the ELF file '{self.elf_path}'"))
            return
        else:
            if self.last_mtime is not None:
                self.queue.put(ControlMsg.reload_elf(digest))
            else:
                self.queue.put(ControlMsg.elf_ok(digest))
