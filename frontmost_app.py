"""
当前前台应用检测 — WPS/Office 下需关闭 AX 文本同步，避免菜单栏闪烁。
"""

import sys
from typing import Optional

_OFFICE_KEYWORDS = (
    "wps",
    "wpsoffice",
    "kingsoft",
    "moffice",
    "word",
    "excel",
    "powerpoint",
    "presentation",
    "演示",
    "表格",
    "文字",
    "office",
    "microsoft",
    "金山",
)

# 常见 WPS macOS bundle 片段
_OFFICE_BUNDLE_KEYWORDS = (
    "kingsoft",
    "wpsoffice",
    "moffice",
    "microsoft.word",
    "microsoft.excel",
    "microsoft.powerpoint",
)

_BROWSER_KEYWORDS = (
    "safari",
    "google chrome",
    "chrome",
    "firefox",
    "arc",
    "microsoft edge",
    "edge",
    "brave",
    "opera",
    "chromium",
    "vivaldi",
)

_BROWSER_BUNDLE_KEYWORDS = (
    "com.apple.safari",
    "com.google.chrome",
    "org.mozilla.firefox",
    "company.thebrowser.browser",
    "com.microsoft.edgemac",
    "com.brave.browser",
    "com.operasoftware.opera",
    "org.chromium.chromium",
)


def _quartz_frontmost_owner() -> Optional[str]:
    """任意线程可用：读当前最前窗口所属应用名。"""
    if sys.platform != "darwin":
        return None
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        if not windows:
            return None
        # layer 0 且面积最大的通常是用户正在操作的主窗口
        candidates = []
        for win in windows:
            layer = win.get("kCGWindowLayer", 999)
            if layer != 0:
                continue
            owner = win.get("kCGWindowOwnerName") or ""
            bounds = win.get("kCGWindowBounds") or {}
            area = float(bounds.get("Width", 0)) * float(bounds.get("Height", 0))
            if owner and area > 4000:
                candidates.append((area, str(owner)))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]
    except Exception:
        return None


def get_frontmost_bundle_id() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        return str(app.bundleIdentifier() or "")
    except Exception:
        return None


def get_frontmost_app_name() -> Optional[str]:
    if sys.platform != "darwin":
        return None
    quartz_name = _quartz_frontmost_owner()
    if quartz_name:
        return quartz_name
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        return str(app.localizedName() or "")
    except Exception:
        return None


def is_office_like_frontmost() -> bool:
    """WPS / Microsoft Office 等桌面文档应用。"""
    name = (get_frontmost_app_name() or "").lower()
    bundle = (get_frontmost_bundle_id() or "").lower()
    haystack = f"{name} {bundle}"
    if any(k in haystack for k in _OFFICE_KEYWORDS):
        return True
    if any(k in bundle for k in _OFFICE_BUNDLE_KEYWORDS):
        return True
    return False


def is_browser_like_frontmost() -> bool:
    """Safari / Chrome 等浏览器 — AX 读输入框常返回片段，应只用按键缓冲录制。"""
    if sys.platform != "darwin":
        return False
    name = (get_frontmost_app_name() or "").lower()
    bundle = (get_frontmost_bundle_id() or "").lower()
    haystack = f"{name} {bundle}"
    if any(k in haystack for k in _BROWSER_KEYWORDS):
        return True
    if any(k in bundle for k in _BROWSER_BUNDLE_KEYWORDS):
        return True
    return False
