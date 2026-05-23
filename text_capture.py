"""
macOS 输入框文本读取 - 用于中文输入法（IME）录制。

pynput 只能录到拼音按键，无法录到 IME 上屏后的汉字；
通过辅助功能 API 读取当前焦点输入框的文本变化来补全。
"""

import sys
from typing import Optional

# 常见可编辑控件角色（浏览器 input/textarea 通常也能读到 AXValue）
_TEXT_ROLES = frozenset(
    {
        "AXTextField",
        "AXTextArea",
        "AXComboBox",
        "AXSearchField",
        "AXStaticText",  # 部分网页控件
    }
)


def get_focused_text_value() -> Optional[str]:
    """
    读取当前焦点控件的文本内容。
    需要「辅助功能」权限；读不到时返回 None。
    """
    if sys.platform != "darwin":
        return None

    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
            kAXFocusedUIElementAttribute,
            kAXRoleAttribute,
            kAXValueAttribute,
        )

        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, kAXFocusedUIElementAttribute, None
        )
        if err != 0 or focused is None:
            return None

        err, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        if err == 0 and role is not None and role not in _TEXT_ROLES:
            # 网页里焦点有时落在 AXGroup 等容器上，仍尝试读 value
            pass

        err, value = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if err != 0 or value is None:
            return None

        return str(value)
    except Exception:
        return None
