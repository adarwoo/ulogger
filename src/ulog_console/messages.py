from enum import Enum, auto


class ControlMsg(Enum):
    QUIT = auto()
    PAUSE = auto()
    RESET = auto()
    WAIT_FOR_ELF = auto()
    FAILED_TO_READ_ELF = auto()
    RELOADED_ELF = auto()
    BAD_DATA = auto()
    ELF_OK = auto()

    def __init__(self, *_):
        self.message = None

    @staticmethod
    def quit():
        return ControlMsg.QUIT

    @staticmethod
    def wait_for_elf():
        return ControlMsg.WAIT_FOR_ELF

    @staticmethod
    def failed_to_read_elf(reason=None):
        msg = ControlMsg.FAILED_TO_READ_ELF
        msg.message = reason
        return msg
