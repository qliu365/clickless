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
            "OfficeLego needs system permissions to record and simulate mouse/keyboard:\n\n"
            "1. System Settings → Privacy & Security → Accessibility\n"
            "   Enable Terminal (or Python / OfficeLego)\n\n"
            "2. System Settings → Privacy & Security → Input Monitoring\n"
            "   Enable Terminal / Python / OfficeLego as well\n\n"
            "Quit and reopen this app after enabling."
        )
    if sys.platform == "win32":
        return (
            "OfficeLego on Windows usually does not need separate permission prompts.\n\n"
            "If antivirus blocks the app, choose Allow.\n"
            "Before playback, switch to the target window.\n\n"
            "Note: Chinese text input may not record fully on Windows; "
            "use English/numbers or re-record on Windows."
        )
    return "Ensure this app can control the mouse and keyboard."
