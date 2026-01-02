"""Message for opening ELF files."""


class OpenElfFileMsg:
    """Message to request opening an ELF file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
