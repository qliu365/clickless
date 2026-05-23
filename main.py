#!/usr/bin/env python3
"""
Clickless 自动化助手 - 主程序入口

录制一次、永久自动的桌面重复操作助手。
"""

import sys
from pathlib import Path


def _configure_windows() -> None:
    """Windows：DPI 感知 + pyautogui，避免鼠标坐标/点击失效。"""
    if sys.platform != "win32":
        return

    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.03
    except Exception:
        pass


def _get_app_root() -> Path:
    """用户数据目录：源码和打包版共用，避免流程文件分散。"""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Clickless"
    elif sys.platform == "win32":
        root = Path.home() / "AppData" / "Local" / "Clickless"
    else:
        root = Path.home() / ".clickless"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _migrate_legacy_flows(flows_dir: Path) -> None:
    """把旧版项目目录 flows/ 里的流程迁移到统一位置。"""
    if getattr(sys, "frozen", False):
        legacy = Path(sys.executable).resolve().parent / "flows"
    else:
        legacy = Path(__file__).resolve().parent / "flows"

    if not legacy.is_dir() or legacy.resolve() == flows_dir.resolve():
        return

    flows_dir.mkdir(parents=True, exist_ok=True)
    for path in legacy.glob("*.json"):
        target = flows_dir / path.name
        if not target.exists():
            target.write_bytes(path.read_bytes())


ROOT_DIR = _get_app_root()

# 源码模式下确保能导入本地模块
if not getattr(sys, "frozen", False):
    code_dir = Path(__file__).resolve().parent
    if str(code_dir) not in sys.path:
        sys.path.insert(0, str(code_dir))

# 流程文件存放目录（运行时自动创建）
FLOWS_DIR = ROOT_DIR / "flows"


def ensure_flows_dir() -> None:
    """确保 flows 目录存在。"""
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """启动 Clickless 图形界面。"""
    try:
        _configure_windows()
        ensure_flows_dir()
        _migrate_legacy_flows(FLOWS_DIR)

        from gui import ClicklessApp

        app = ClicklessApp(flows_dir=FLOWS_DIR)
        app.run()
    except Exception:
        import traceback

        log_dir = _get_app_root()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "clickless-error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")

        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Clickless 启动失败",
                f"程序出错，请把下面文件发给技术支持：\n\n{log_path}",
            )
            root.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
