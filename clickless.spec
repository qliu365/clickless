# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置 — Windows / Mac 通用。"""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

extra_datas = []
extra_binaries = []
extra_hidden = []

for pkg in ("pynput", "pyautogui", "pyperclip"):
    try:
        datas, binaries, hidden = collect_all(pkg)
        extra_datas += datas
        extra_binaries += binaries
        extra_hidden += hidden
    except Exception:
        pass

hiddenimports = [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
    "keyboard_shortcuts",
    "scroll_capture",
    "window_bounds",
    "gui",
    "recorder",
    "player",
    "storage",
    "mouse_click",
    "click_marker",
    "recording_floater",
    "permissions",
    "text_capture",
    "PIL._tkinter_finder",
] + extra_hidden

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=extra_binaries,
    datas=extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["keyboard"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Clickless",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Clickless",
)
