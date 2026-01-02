"""
Launcher script for ulogger - works with PyInstaller.
This script uses absolute imports instead of relative imports.
Auto-launches in a terminal if double-clicked.
"""
import sys
import os
import subprocess
from pathlib import Path

def is_running_in_terminal():
    """Check if we're running in a real terminal."""
    # Check if stdout is a TTY (terminal)
    if not sys.stdout.isatty():
        return False

    # On Windows, check if parent process is explorer.exe (double-clicked)
    if sys.platform == 'win32':
        try:
            import psutil
            parent = psutil.Process(os.getpid()).parent()
            if parent and 'explorer.exe' in parent.name().lower():
                return False
        except (ImportError, Exception):
            # If psutil not available, fall back to TTY check
            pass

    return True

def relaunch_in_terminal():
    """Relaunch this script in a new terminal window."""
    exe_path = sys.executable
    args = sys.argv[1:]  # Get any command-line arguments

    if sys.platform == 'win32':
        # Try Windows Terminal first
        wt_cmd = ['wt', '-w', '0', 'nt', '--title', 'uLogger', exe_path] + args
        try:
            subprocess.run(['where', 'wt'], capture_output=True, check=True)
            subprocess.Popen(wt_cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Fallback to cmd
        cmd_args = ['cmd', '/k', exe_path] + args
        subprocess.Popen(cmd_args, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        # On Linux/Mac, try common terminal emulators
        terminals = [
            ['x-terminal-emulator', '-e'],
            ['gnome-terminal', '--'],
            ['konsole', '-e'],
            ['xterm', '-e'],
        ]

        for term_cmd in terminals:
            try:
                subprocess.Popen(term_cmd + [exe_path] + args)
                return
            except FileNotFoundError:
                continue

        # If no terminal found, print error
        print("Error: Could not find a terminal emulator. Please run from command line.")
        input("Press Enter to exit...")

if __name__ == '__main__':
    # Check if running in terminal
    if not is_running_in_terminal():
        relaunch_in_terminal()
        sys.exit(0)

    # Add src directory to path so we can import ulogger
    src_path = Path(__file__).parent / 'src'
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    # Import and run the main function
    from ulogger.__main__ import main
    main()
