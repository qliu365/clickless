"""
macOS 输入框文本读取 - 用于中文输入法（IME）录制。

pynput 只能录到拼音按键，无法录到 IME 上屏后的汉字；
通过辅助功能 API 读取当前焦点输入框的文本变化来补全。
读不到时由 recorder 回退到按键缓冲。
"""

import sys
from typing import Any, Optional

# 常见可编辑控件角色
_TEXT_ROLES = frozenset(
    {
        "AXTextField",
        "AXTextArea",
        "AXComboBox",
        "AXSearchField",
        "AXStaticText",
        "AXWebArea",
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

        value = _read_element_text(focused)
        if value is not None:
            return value

        err, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        if err == 0 and role is not None and role in _TEXT_ROLES:
            return _deep_find_text(focused, depth=5)

        return _deep_find_text(focused, depth=5)
    except Exception:
        return None


def _read_element_text(element: Any) -> Optional[str]:
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            kAXSelectedTextAttribute,
            kAXValueAttribute,
        )

        err, selected = AXUIElementCopyAttributeValue(
            element, kAXSelectedTextAttribute, None
        )
        if err == 0 and selected is not None and str(selected):
            return str(selected)

        err, value = AXUIElementCopyAttributeValue(element, kAXValueAttribute, None)
        if err == 0 and value is not None:
            text = str(value)
            return text if text else None
    except Exception:
        pass
    return None


def _deep_find_text(element: Any, depth: int) -> Optional[str]:
    if depth <= 0:
        return None

    text = _read_element_text(element)
    if text is not None:
        return text

    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            kAXChildrenAttribute,
        )

        err, children = AXUIElementCopyAttributeValue(
            element, kAXChildrenAttribute, None
        )
        if err != 0 or not children:
            return None

        for child in children:
            found = _deep_find_text(child, depth - 1)
            if found is not None:
                return found
    except Exception:
        pass
    return None
