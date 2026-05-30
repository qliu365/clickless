#!/usr/bin/env python3
"""
OfficeLego 自动化助手 - 主程序入口

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


def _legacy_app_roots() -> list[Path]:
    """旧版数据目录（升级时迁移到 OfficeLego）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return [base / "Clickless", base / "OfficeLEGO"]
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
        return [base / "Clickless", base / "OfficeLEGO"]
    return [Path.home() / ".clickless", Path.home() / ".officelego"]


def _migrate_legacy_app_data(root: Path) -> None:
    """首次使用 OfficeLego 时，从 Clickless 目录复制 flows/modules/captures。"""
    if any((root / name).exists() for name in ("flows", "modules", "captures")):
        return
    for legacy in _legacy_app_roots():
        if not legacy.is_dir() or legacy.resolve() == root.resolve():
            continue
        import shutil

        root.mkdir(parents=True, exist_ok=True)
        for name in ("flows", "modules", "captures"):
            src = legacy / name
            if src.is_dir():
                shutil.copytree(src, root / name, dirs_exist_ok=True)
        return


def _get_app_root() -> Path:
    """用户数据目录：源码和打包版共用，避免流程文件分散。"""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "OfficeLego"
    elif sys.platform == "win32":
        root = Path.home() / "AppData" / "Local" / "OfficeLego"
    else:
        root = Path.home() / ".officelego"
    root.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_app_data(root)
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
MODULES_DIR = ROOT_DIR / "modules"


def ensure_flows_dir() -> None:
    """确保 flows 目录存在。"""
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    MODULES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """启动 OfficeLego 图形界面。"""
    if "--self-test" in sys.argv:
        from self_test import run_self_test

        raise SystemExit(run_self_test())

    if "--web" in sys.argv:
        _configure_windows()
        ensure_flows_dir()
        _migrate_legacy_flows(FLOWS_DIR)
        from web_app import run_web_app

        from web_config import load_web_settings

        argv = sys.argv[1:]
        port = None
        host = None
        token = None
        public = "--public" in argv
        if "--port" in argv:
            i = argv.index("--port")
            if i + 1 < len(argv):
                port = int(argv[i + 1])
        if "--host" in argv:
            i = argv.index("--host")
            if i + 1 < len(argv):
                host = argv[i + 1]
        if "--token" in argv:
            i = argv.index("--token")
            if i + 1 < len(argv):
                token = argv[i + 1]
        open_browser = "--no-browser" not in argv
        use_waitress = "--waitress" in argv
        settings = load_web_settings(
            host=host,
            port=port,
            auth_token=token,
            public_mode=public,
        )
        run_web_app(
            FLOWS_DIR,
            MODULES_DIR,
            settings=settings,
            open_browser=open_browser,
            use_waitress=use_waitress,
        )
        return

    try:
        _configure_windows()
        ensure_flows_dir()
        _migrate_legacy_flows(FLOWS_DIR)

        from gui import OfficeLegoApp

        app = OfficeLegoApp(flows_dir=FLOWS_DIR, modules_dir=MODULES_DIR)
        app.run()
    except Exception:
        import traceback

        log_dir = _get_app_root()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "officelego-error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")

        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "OfficeLego failed to start",
                f"An error occurred. Send this file to support:\n\n{log_path}",
            )
            root.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
