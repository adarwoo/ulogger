# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=['ulogger.cli', 'ulogger.viewer_textual', 'ulogger.settings', 'ulogger.elf_reader', 'ulogger.serial_reader', 'ulogger.logs', 'ulogger.messages', 'ulogger.buffer', 'ulogger.models', 'psutil'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['kivy', 'kivymd', 'kivy_deps', 'pygame', 'pygame_sdl2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ulogger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ulogger.ico',
)
