"""
macOS 权限检测 - 录制/回放需要「辅助功能」权限。
"""

import subprocess
import sys


def is_accessibility_granted() -> bool:
    """检查当前进程是否已获得辅助功能权限。"""
    if sys.platform != "darwin":
        return True

    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def request_accessibility_prompt() -> bool:
    """弹出系统对话框，请求辅助功能权限。"""
    if sys.platform != "darwin":
        return True

    if is_accessibility_granted():
        return True

    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        options = {kAXTrustedCheckOptionPrompt: True}
        return bool(AXIsProcessTrustedWithOptions(options))
    except Exception:
        return False


def open_accessibility_settings() -> None:
    """打开系统「辅助功能」设置页。"""
    if sys.platform != "darwin":
        return
    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility",
        ],
        check=False,
    )


def open_input_monitoring_settings() -> None:
    """打开「输入监控」设置页（键盘监听可能需要）。"""
    if sys.platform != "darwin":
        return
    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ListenEvent",
        ],
        check=False,
    )


def permission_hint() -> str:
    if sys.platform == "darwin":
        return (
            "Clickless 需要系统权限才能录制和模拟鼠标/键盘：\n\n"
            "1. 系统设置 → 隐私与安全性 → 辅助功能\n"
            "   勾选 Terminal（或 Python / Clickless）\n\n"
            "2. 系统设置 → 隐私与安全性 → 输入监控\n"
            "   同样勾选 Terminal / Python / Clickless\n\n"
            "勾选后请完全退出并重新打开本程序。"
        )
    if sys.platform == "win32":
        return (
            "Windows 版 Clickless 一般不需要像 macOS 那样单独授权。\n\n"
            "若杀毒软件弹出拦截，请选择「允许」。\n"
            "运行回放前请切换到浏览器，并手动点一下网页空白处。\n\n"
            "中文输入：Windows 上录制中文可能不完整，"
            "可先在 Mac 上录好流程 JSON 发给同事，或在 Windows 上录英文/数字步骤。"
        )
    return "请确保本程序有权限控制鼠标和键盘。"
