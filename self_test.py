"""
Windows / macOS 自检 — 验证鼠标能否移动和点击。
用法: Clickless.exe --self-test
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple


def _get_cursor_pos() -> Tuple[int, int]:
    if sys.platform == "win32":
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            raise OSError("GetCursorPos failed")
        return int(pt.x), int(pt.y)

    from pynput.mouse import Controller

    pos = Controller().position
    return int(pos[0]), int(pos[1])


def _get_screen_size() -> Tuple[int, int]:
    if sys.platform == "win32":
        import ctypes

        return (
            int(ctypes.windll.user32.GetSystemMetrics(0)),
            int(ctypes.windll.user32.GetSystemMetrics(1)),
        )

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return int(w), int(h)


def run_self_test() -> int:
    """运行自检并弹窗显示结果。返回 0=成功，1=失败。"""
    from main import FLOWS_DIR, _configure_windows, ensure_flows_dir

    _configure_windows()
    ensure_flows_dir()

    lines: List[str] = []
    ok = True

    def record(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        if not passed:
            ok = False
        mark = "OK" if passed else "FAIL"
        text = f"[{mark}] {label}"
        if detail:
            text += f" — {detail}"
        lines.append(text)
        print(text)

    try:
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            record("exe directory", exe_dir.is_dir(), str(exe_dir))
            record("_internal folder", (exe_dir / "_internal").is_dir(), str(exe_dir / "_internal"))
        record("flows directory", FLOWS_DIR.is_dir(), str(FLOWS_DIR))

        sw, sh = _get_screen_size()
        record("screen size", sw > 0 and sh > 0, f"{sw}x{sh}")

        start_x, start_y = _get_cursor_pos()
        record("read cursor", True, f"({start_x}, {start_y})")

        target_x = max(50, min(sw - 50, sw // 2))
        target_y = max(50, min(sh - 50, sh // 2))

        from mouse_click import perform_click

        print(f"Moving mouse to ({target_x}, {target_y}) in 2 seconds...")
        time.sleep(2)
        perform_click(target_x, target_y, settle=True)

        time.sleep(0.3)
        after_x, after_y = _get_cursor_pos()
        moved = abs(after_x - start_x) + abs(after_y - start_y) >= 20
        near_target = abs(after_x - target_x) <= 25 and abs(after_y - target_y) <= 25
        record(
            "mouse move",
            moved or near_target,
            f"before=({start_x},{start_y}) after=({after_x},{after_y}) target=({target_x},{target_y})",
        )
    except Exception as exc:
        ok = False
        record("self-test", False, str(exc))
        import traceback

        lines.append("")
        lines.append(traceback.format_exc())

    report = "\n".join(lines)
    log_path = Path.home()
    if sys.platform == "win32":
        log_path = log_path / "AppData" / "Local" / "Clickless"
    elif sys.platform == "darwin":
        log_path = log_path / "Library" / "Application Support" / "Clickless"
    else:
        log_path = log_path / ".clickless"
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "self-test.log"
    log_file.write_text(report + "\n", encoding="utf-8")

    title = "Clickless self-test passed" if ok else "Clickless self-test failed"
    body = report + f"\n\nLog saved to:\n{log_file}"
    if not ok and sys.platform == "win32":
        body += (
            "\n\nIf the mouse did not move:\n"
            "1. Run TEST.bat as administrator\n"
            "2. Allow Clickless in antivirus\n"
            "3. Send self-test.log to support"
        )

    ci_mode = os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CLICKLESS_CI") == "1"
    if ci_mode:
        print(body)
    else:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            if ok:
                messagebox.showinfo(title, body)
            else:
                messagebox.showerror(title, body)
            root.destroy()
        except Exception:
            print(body)

    return 0 if ok else 1
