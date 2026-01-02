# Screenshot Guide for µLogger

This guide will help you capture professional screenshots for the README.

## Recommended Screenshots

### 1. Main View (main_view.png)
- **What to show:** Main log viewer with live logs
- **Setup:**
  - Run ulogger with an active ELF file and COM port
  - Let some logs accumulate (various levels)
  - Show colorful log output with different levels
- **Hotkey:** Use Windows Snipping Tool (Win+Shift+S) or your preferred tool
- **Size:** Full terminal window

### 2. File Filter Dialog (file_filter.png)
- **What to show:** File filter modal with color-coded counts
- **Setup:**
  - Press `f` to open file filter
  - Shows files with checkmarks and level counts in colors
  - Capture with several files listed
- **Tip:** Make sure window is wide enough to show full filenames

### 3. Level Filter Dialog (level_filter.png)
- **What to show:** Level filter selection
- **Setup:**
  - Press `l` to open level filter
  - Shows all log levels with colors
  - Some checked, some unchecked

### 4. Log Entries Viewer (log_entries.png)
- **What to show:** ELF metadata viewer
- **Setup:**
  - Press `e` to open log entries viewer
  - Shows file:line, format strings, and variable types
  - Demonstrates the "S" sort feature if possible

### 5. COM Port Selection (com_port_selection.png)
- **What to show:** COM port selection dialog
- **Setup:**
  - Press `p` to open COM port selector
  - Shows available ports with current one highlighted

### 6. Search Feature (search_feature.png)
- **What to show:** Search in log entries viewer
- **Setup:**
  - In log entries viewer, press `Ctrl+F`
  - Type a search term
  - Shows matching results highlighted

## Taking Screenshots on Windows

### Method 1: Windows Snipping Tool (Recommended)
1. Press `Win + Shift + S`
2. Select the area
3. Screenshot copied to clipboard
4. Open Paint/Paint3D and paste
5. Save as PNG in `screenshots/` folder

### Method 2: Terminal Built-in Screenshot
1. Right-click terminal title bar
2. Select "Screenshot" (if available in Windows Terminal)

### Method 3: ShareX (Advanced)
1. Download ShareX (free)
2. Configure region capture
3. Automatically saves to folder

## Naming Convention

Use these exact names for consistency:
- `main_view.png` - Main logging interface
- `file_filter.png` - File filter dialog
- `level_filter.png` - Level filter dialog
- `log_entries.png` - Log entries viewer
- `com_port_selection.png` - COM port dialog
- `search_feature.png` - Search functionality
- `status_bar.png` - Status bar closeup (optional)

## Size Guidelines

- **Preferred width:** 1200-1600 pixels
- **Preferred height:** 800-1000 pixels
- **Format:** PNG (for quality and transparency)
- **Compression:** Optimize with tools like TinyPNG if needed

## Tips for Great Screenshots

✅ **Use a nice color scheme** - Default Windows Terminal themes work well
✅ **Show real data** - Use actual ELF files and logs, not placeholder text
✅ **Zoom appropriately** - Terminal font should be readable but not too large
✅ **Clean background** - Dark or light theme that looks professional
✅ **Show functionality** - Each screenshot should demonstrate a feature
✅ **Consistent sizing** - Keep all screenshots roughly the same dimensions

## After Capturing

Once you have the screenshots:

1. Save them in the `screenshots/` folder
2. Optimize file sizes (keep under 500KB each if possible)
3. Update README.md with the screenshot links:

```markdown
## Screenshots

### Main Interface
![Main View](screenshots/main_view.png)

### File Filter
![File Filter](screenshots/file_filter.png)

### Level Filter
![Level Filter](screenshots/level_filter.png)

### Log Entries Viewer
![Log Entries](screenshots/log_entries.png)

### COM Port Selection
![COM Port](screenshots/com_port_selection.png)
```

## Testing the README

After adding screenshots, view README.md on GitHub to ensure:
- Images load correctly
- Sizing is appropriate
- Layout looks good on both desktop and mobile
- Images enhance understanding of the features

---

**Note:** Screenshots should be taken with ulogger running normally (not in debug mode) to show the actual user experience.
