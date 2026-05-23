#!/usr/bin/env python3
"""
Clickless 自动化助手 - 主程序入口

录制一次、永久自动的桌面重复操作助手。
"""

import sys
from pathlib import Path


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
    ensure_flows_dir()
    _migrate_legacy_flows(FLOWS_DIR)

    from gui import ClicklessApp

    app = ClicklessApp(flows_dir=FLOWS_DIR)
    app.run()


if __name__ == "__main__":
    main()
