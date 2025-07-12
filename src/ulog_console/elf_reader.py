import asyncio
import os

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

    async def run(self):
        while self.running:
            if not os.path.exists(self.elf_path):
                await self.queue.put(ControlMsg.WAIT_FOR_ELF)
                continue
            else:
                mtime = os.path.getmtime(self.elf_path)

                if self.last_mtime != mtime:
                    await self.load_elf()
                    self.last_mtime = mtime

            await asyncio.sleep(self.poll_interval)

    async def load_elf(self):
        try:
            if not os.path.isfile(self.elf_path):
                raise FileNotFoundError(f"ELF file not found: {self.elf_path}")

            try:
                elf = ELFFile(open(self.elf_path, 'rb'))
            except Exception as open_exc:
                raise Exception(f"Failed to open/read ELF file: {self.elf_path} ({open_exc})")

            section = elf.get_section_by_name('.logs')

            if not section:
                raise Exception(f"Invalid ELF file '{self.elf_path}': no .logs section found")

            # Reset the logs to check for the elf validity
            self.logs.reset(section)

            await self.queue.put(ControlMsg.ELF_OK)
        except FileNotFoundError as fnf_error:
            await self.queue.put(ControlMsg.WAIT_FOR_ELF)
        except Exception as e:
            await self.queue.put(
                ControlMsg.failed_to_read_elf(str(e))
            )
        else:
            if self.last_mtime is not None:
                await self.queue.put(ControlMsg.RELOADED_ELF)