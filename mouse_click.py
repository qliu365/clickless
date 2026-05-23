"""
鼠标点击 - macOS 上用 Quartz 发事件，浏览器里更可靠。
"""

import sys
import time


def perform_click(
    x: int,
    y: int,
    button: str = "left",
    *,
    settle: bool = False,
    retry: int = 1,
) -> None:
    """在屏幕坐标 (x, y) 执行鼠标点击。"""
    x = int(round(x))
    y = int(round(y))
    attempts = max(1, retry)

    for attempt in range(attempts):
        is_settle = settle or attempt == 0
        if sys.platform == "darwin":
            if not _perform_click_quartz(x, y, button, settle=is_settle):
                _perform_click_pynput(x, y, button, settle=is_settle)
        else:
            if is_settle:
                _warp_cursor(x, y)
            _perform_click_pynput(x, y, button, settle=is_settle)

        if attempt < attempts - 1:
            time.sleep(0.25)


def _warp_cursor(x: int, y: int) -> None:
    """先把鼠标移到目标位置（首次点击更稳）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.SetCursorPos(x, y)
            time.sleep(0.2)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            from Quartz import (
                CGAssociateMouseAndMouseCursorPosition,
                CGWarpMouseCursorPosition,
            )

            CGAssociateMouseAndMouseCursorPosition(True)
            CGWarpMouseCursorPosition((float(x), float(y)))
            time.sleep(0.2)
        except Exception:
            pass


def _perform_click_quartz(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    """通过 CGEvent 注入点击（macOS 浏览器识别率更高）。"""
    try:
        from Quartz import (
            CGEventCreateMouseEvent,
            CGEventPost,
            CGEventSetIntegerValueField,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGEventMouseMoved,
            kCGEventRightMouseDown,
            kCGEventRightMouseUp,
            kCGHIDEventTap,
            kCGMouseButtonLeft,
            kCGMouseButtonRight,
            kCGMouseEventClickState,
        )

        point = (float(x), float(y))
        if button == "right":
            down_type = kCGEventRightMouseDown
            up_type = kCGEventRightMouseUp
            btn = kCGMouseButtonRight
        else:
            down_type = kCGEventLeftMouseDown
            up_type = kCGEventLeftMouseUp
            btn = kCGMouseButtonLeft

        if settle:
            _warp_cursor(x, y)
            time.sleep(0.05)

        move = CGEventCreateMouseEvent(None, kCGEventMouseMoved, point, btn)
        CGEventPost(kCGHIDEventTap, move)
        time.sleep(0.2 if settle else 0.12)

        down = CGEventCreateMouseEvent(None, down_type, point, btn)
        CGEventSetIntegerValueField(down, kCGMouseEventClickState, 1)
        CGEventPost(kCGHIDEventTap, down)
        time.sleep(0.08 if settle else 0.05)

        up = CGEventCreateMouseEvent(None, up_type, point, btn)
        CGEventSetIntegerValueField(up, kCGMouseEventClickState, 1)
        CGEventPost(kCGHIDEventTap, up)
        time.sleep(0.15 if settle else 0.12)
        return True
    except Exception:
        return False


def _perform_click_pynput(
    x: int, y: int, button: str, *, settle: bool = False
) -> None:
    from pynput.mouse import Button, Controller

    btn_map = {
        "left": Button.left,
        "right": Button.right,
        "middle": Button.middle,
    }
    btn = btn_map.get(button, Button.left)
    mouse = Controller()
    mouse.position = (x, y)
    time.sleep(0.2 if settle else 0.12)
    mouse.press(btn)
    time.sleep(0.08 if settle else 0.06)
    mouse.release(btn)
    time.sleep(0.15 if settle else 0.1)
