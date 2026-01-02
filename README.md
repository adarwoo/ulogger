# µLogger

> **Modern terminal-based viewer for ULog embedded traces**

µLogger is a powerful TUI (Text User Interface) application for viewing real-time logs from embedded systems using the ULog API. It combines a serial console with intelligent log parsing and filtering capabilities.

[![Release](https://img.shields.io/github/v/release/adarwoo/ulogger)](https://github.com/adarwoo/ulogger/releases)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

## ✨ Features

- 🖥️ **Modern Textual TUI** - Beautiful terminal interface with rich formatting
- 📦 **Standalone Executable** - No Python installation required (Windows)
- 🎨 **Color-Coded Logs** - Different colors for each log level
- 🔍 **Advanced Filtering** - Filter by file, log level, or search text
- 💾 **Persistent Settings** - Remembers recent files and COM ports
- 🔌 **Hot-Swap COM Ports** - Change serial ports without restarting
- 📊 **Real-Time Statistics** - Live log counts and buffer status
- 🔎 **Log Viewer** - Browse all log definitions from ELF file

## 🚀 Quick Start

### Download Standalone Executable (Windows)

1. Download `ulogger.exe` from [latest release](https://github.com/adarwoo/ulogger/releases/latest)
2. Double-click to run (auto-opens in terminal) or run from command line
3. Select your ELF file and COM port from the dialogs

### Install with pip

```bash
pip install ulogger
```

### Run from source

```bash
git clone https://github.com/adarwoo/ulogger.git
cd ulogger
poetry install
poetry run python -m ulogger
```

## 📖 Usage

```bash
ulogger [elf_file] [-C COM_PORT] [-l LEVEL] [-b BUFFER_DEPTH]
```

**Example:**
```bash
ulogger firmware.elf -C COM4
```

**First time usage:** Simply run `ulogger` and use the interactive dialogs to select your ELF file and COM port.

## 📸 Screenshots

### Main Interface
*Real-time log viewing with color-coded levels and filtering*

![Main View](screenshots/logs%20view.svg)

### File Filter
*Filter logs by source file with per-level counts*

![File Filter](screenshots/file%20filter%20view.svg)

### Level Filter
*Select which log levels to display*

![Level Filter](screenshots/level%20filter%20view.svg)

### Log Entries Viewer
*Browse all log definitions from the ELF file with sort and search*

![Log Entries](screenshots/all%20logs%20view.svg)

### File Selection
*Select ELF file from recent files or browse*

![ELF File Selection](screenshots/elf%20file%20selection%20view.svg)

### COM Port Selection
*Choose serial port for live logging*

![Port Selection](screenshots/port%20selection%20view.svg)

> 💡 **Note:** Screenshots captured using Textual's built-in SVG export feature for crisp, scalable images.

## Usage

You install the viewer using pip install or build a windows executable with pyinstaller.

```
usage: ulog_console.exe [-h] [-l LEVEL] [-x] [-C COMM] [-b BUFFER_DEPTH] elf

ulog trace viewer (ncurses + live UART)

positional arguments:
  elf                   Path to ELF file with .logs section

options:
  -h, --help            show this help message and exit
  -l, --level LEVEL     Display log level threshold (0–8)
  -x, --clear           Clear screen on ELF reload
  -C, --comm COMM       UART serial port (e.g. /dev/ttyUSB0 or COM4)
  -b, --buffer-depth BUFFER_DEPTH
                        Internal buffer depth (e.g. 100k, 2M). Default: 100000
```

## ⌨️ Keyboard Controls

| Key | Action |
|:---:|--------|
| `z` | Freeze/Unfreeze display (buffer keeps filling) |
| `c` | Clear all logs |
| `l` | Open level filter dialog |
| `+`/`-` | Expand/Contract level filter |
| `f` | Open file filter dialog |
| `p` | Select COM port |
| `r` | Reset all filters |
| `e` | View all log entry definitions from ELF |
| `v` | View all log lines in modal |
| `q` | Quit application |
| `↑`/`↓` | Scroll up/down |
| `PgUp`/`PgDn` | Page up/down |
| `Home`/`End` | Jump to top/bottom |

### In File/Level Filter Dialogs:
- Click on items to toggle selection
- Press `0-8` on a file to view logs at that level
- Press `Enter` on a file to view all its logs
- `Esc` or `q` to close dialog

### In Log Entries Viewer:
- `s` - Cycle sort mode (none → level → file)
- `Ctrl+F` - Toggle search
- `Esc` - Close search or exit viewer

## 📋 Command-Line Options

```
usage: ulogger [-h] [-l LEVEL] [-x] [-C COMM] [-b BUFFER_DEPTH] [elf]

positional arguments:
  elf                   Path to ELF file with .logs section (optional)

options:
  -h, --help            Show help message
  -l, --level LEVEL     Display log level threshold (0-8, default: 8)
  -x, --clear           Clear screen on ELF reload
  -C, --comm COMM       UART serial port (e.g. /dev/ttyUSB0 or COM4)
  -b, --buffer-depth BUFFER_DEPTH
                        Internal buffer depth (e.g. 100k, 2M, default: 100000)
```

## 🎯 Log Levels

| Level | Name | Color | Use Case |
|:-----:|------|-------|----------|
| 0 | ERROR | Red | Critical errors |
| 1 | WARN | Yellow | Warnings |
| 2 | MILE | Bright Yellow | Milestones |
| 3 | INFO | Green | General info |
| 4 | TRACE | Blue | Trace execution |
| 5 | DEBUG0 | White | Debug info |
| 6 | DEBUG1 | Gray | Detailed debug |
| 7 | DEBUG2 | Dim | Very detailed |
| 8 | DEBUG3 | Dim | Maximum detail |

## 🏗️ Building from Source

### Requirements
- Python 3.9+
- Poetry (package manager)

### Development Setup

```bash
# Clone repository
git clone https://github.com/adarwoo/ulogger.git
cd ulogger

# Install dependencies
poetry install

# Run in development
poetry run python -m ulogger

# Run tests (if available)
poetry run pytest
```

### Building Standalone Executable

```bash
# Install build dependencies
poetry add --group dev pyinstaller

# Generate icon (optional)
python create_icon.py

# Build executable
poetry run pyinstaller ulogger.spec

# Output: dist/ulogger.exe
```

The executable includes:
- ✅ All Python dependencies bundled
- ✅ Auto-terminal launch when double-clicked
- ✅ Custom icon
- ✅ No installation required
- ✅ ~8.5MB single file

## 🔧 Technical Details

### ULog Library Performance

On AVR microcontrollers, ULog provides exceptional performance:

| Metric | Value | Description |
|--------|-------|-------------|
| Library Size | **< 300 bytes** | Includes UART handling and double buffer |
| Throughput | **> 3000 msg/s** | At 115200 baud |
| Flash per Log | **8 bytes** | Zero RAM overhead |
| RAM Usage | **30-100 bytes** | Configurable buffer size |
| CPU Cycles/Trace | **214** (11µs) | Single trace, no arguments |
| CPU Load @ 300 msg/s | **< 1%** | Includes ULog and UART |
| IDLE Latency | **< 23µs** | Additional reactor handler latency |

### How It Works

ULog uses a clever approach different from other logging libraries:

1. **Zero-Cost Metadata** - All trace information (file, line, format, types) stored in ELF `.logs` section (unmapped, uses no flash)
2. **Minimal Runtime** - Only trace ID and raw data sent over UART
3. **COBS Framing** - Efficient binary framing (2 extra bytes per message)
4. **Double Buffering** - One buffer for logging, one for UART transmission
5. **Reactor-Safe** - Second buffer fills only when system is idle

### Benefits

✅ **No preprocessing required** - Unlike Trice, no JSON extraction needed
✅ **Tiny footprint** - 100 debug statements cost < 1KB flash
✅ **No code intrusion** - Linker script patch optional
✅ **Smart filtering** - Viewer knows all possible traces upfront
✅ **Type-safe** - Variable types extracted from ELF, no format strings needed

## 📦 Dependencies

### Runtime
- `textual >= 0.96.1` - Modern TUI framework
- `pyserial >= 3.5` - Serial port communication
- `platformdirs >= 4.0.0` - Cross-platform settings storage
- `pyelftools >= 0.31` - ELF file parsing
- `sqlalchemy >= 2.0.0` - Database models

### Development
- `poetry` - Dependency management
- `pyinstaller >= 6.16.0` - Executable building (optional)

## 🤝 Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🔗 Related Projects

- [ULog AVR Library](https://github.com/adarwoo/asx) - The embedded logging library
- [Textual](https://github.com/Textualize/textual) - Modern TUI framework

## 💬 Support

- 🐛 [Report Issues](https://github.com/adarwoo/ulogger/issues)
- 📖 [Documentation](https://github.com/adarwoo/ulogger/wiki)
- 💡 [Feature Requests](https://github.com/adarwoo/ulogger/issues/new)

---

Made with ❤️ for embedded developers

