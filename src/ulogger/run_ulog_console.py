# Necessary evil to allow pyinstaller to find the main module

from ulog_console.__main__ import main

if __name__ == "__main__":
    main()