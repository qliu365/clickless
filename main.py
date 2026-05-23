#!/usr/bin/env python3
"""
Clickless 自动化助手 - 主程序入口

录制一次、永久自动的桌面重复操作助手。
"""

import sys
from pathlib import Path


def _get_app_root() -> Path:
    """源码运行用项目目录；打包后用用户可写目录。"""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "Clickless"
        elif sys.platform == "win32":
            root = Path.home() / "AppData" / "Local" / "Clickless"
        else:
            root = Path.home() / ".clickless"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent


ROOT_DIR = _get_app_root()

# 源码模式下确保能导入本地模块
if not getattr(sys, "frozen", False) and str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 流程文件存放目录（运行时自动创建）
FLOWS_DIR = ROOT_DIR / "flows"


def ensure_flows_dir() -> None:
    """确保 flows 目录存在。"""
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """启动 Clickless 图形界面。"""
    ensure_flows_dir()

    from gui import ClicklessApp

    app = ClicklessApp(flows_dir=FLOWS_DIR)
    app.run()


if __name__ == "__main__":
    main()
