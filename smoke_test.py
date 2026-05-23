#!/usr/bin/env python3
"""Clickless 冒烟测试 — 本地或 CI 验证能否正常启动。"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


REQUIRED_ZIP_FILES = (
    "Clickless/Clickless.exe",
    "Clickless/_internal",
    "Clickless/START.bat",
    "Clickless/windows_launch.bat",
    "Clickless/README-Windows.txt",
)


def validate_zip(zip_path: Path) -> None:
    """检查 Windows 安装包结构。"""
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        internal = [n for n in names if n.startswith("Clickless/_internal/")]
        if not internal:
            raise RuntimeError("missing Clickless/_internal/ in zip")

        for item in REQUIRED_ZIP_FILES:
            if item.endswith("/") or item.endswith("\\"):
                continue
            if item not in names:
                raise RuntimeError(f"missing in zip: {item}")

        start_bat = zf.read("Clickless/START.bat").decode("utf-8", errors="replace")
        for needle in ("Clickless.exe", "_internal", "tasklist"):
            if needle not in start_bat:
                raise RuntimeError(f"START.bat missing marker: {needle}")

    print(f"[OK] zip structure: {zip_path}")


def validate_source() -> None:
    """检查 Python 源码能否导入并初始化核心模块。"""
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from main import FLOWS_DIR, _configure_windows, ensure_flows_dir

    _configure_windows()
    ensure_flows_dir()
    assert FLOWS_DIR.is_dir()

    import mouse_click  # noqa: F401
    import player  # noqa: F401
    import recorder  # noqa: F401
    import keyboard_shortcuts  # noqa: F401

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.title("Clickless smoke")
    root.update_idletasks()
    root.destroy()

    if sys.platform == "win32":
        import pyautogui

        pyautogui.position()

    print(f"[OK] source imports on {sys.platform}")


def main() -> None:
    root = Path(__file__).resolve().parent
    zip_path = root / "Clickless-win.zip"

    validate_source()
    if zip_path.exists():
        validate_zip(zip_path)
    else:
        print(f"[SKIP] no zip at {zip_path}")

    print("SMOKE OK")


if __name__ == "__main__":
    main()
