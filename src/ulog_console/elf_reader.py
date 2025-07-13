import os
import time
from elftools.elf.elffile import ELFFile

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
        try:
            if not os.path.isfile(self.elf_path):
                raise FileNotFoundError(f"ELF file not found: {self.elf_path}")

            try:
                f = open(self.elf_path, 'rb')
                elf = ELFFile(f)
            except Exception as open_exc:
                raise Exception(f"Failed to open/read ELF file: {self.elf_path} ({open_exc})")
            else:
                section = elf.get_section_by_name('.logs')

                if not section:
                    raise Exception(f"Invalid ELF file '{self.elf_path}': no .logs section found")

                self.logs.reset(section)
                self.queue.put(ControlMsg.ELF_OK)
            finally:
                f.close()
        except FileNotFoundError:
            self.queue.put(ControlMsg.WAIT_FOR_ELF)
        except Exception as e:
            self.queue.put(ControlMsg.failed_to_read_elf(str(e)))
        else:
            if self.last_mtime is not None:
                self.queue.put(ControlMsg.RELOADED_ELF)