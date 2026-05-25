"""
鼠标点击与滚动 - macOS 上用 Quartz，浏览器/Excel 里更可靠。
"""

import sys
import time
from typing import Optional

_pyautogui_ready = False


def _ensure_pyautogui():
    global _pyautogui_ready
    import pyautogui

    if not _pyautogui_ready:
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.03
        _pyautogui_ready = True
    return pyautogui


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
        elif sys.platform == "win32":
            if not _perform_click_windows(x, y, button, settle=is_settle):
                _perform_click_pynput(x, y, button, settle=is_settle)
        else:
            if is_settle:
                _warp_cursor(x, y)
            _perform_click_pynput(x, y, button, settle=is_settle)

        if attempt < attempts - 1:
            time.sleep(0.25)


def perform_double_click(
    x: int,
    y: int,
    button: str = "left",
    *,
    settle: bool = False,
) -> None:
    """双击（打开文档/文件夹等）。"""
    x = int(round(x))
    y = int(round(y))
    if settle:
        _warp_cursor(x, y)
        time.sleep(0.15)

    if sys.platform == "darwin" and _perform_double_click_quartz(x, y, button, settle=settle):
        return

    if sys.platform == "win32" and _perform_double_click_windows(x, y, button, settle=settle):
        return

    from pynput.mouse import Button, Controller

    btn_map = {
        "left": Button.left,
        "right": Button.right,
        "middle": Button.middle,
    }
    btn = btn_map.get(button, Button.left)
    mouse = Controller()
    mouse.position = (x, y)
    time.sleep(0.2)
    mouse.click(btn, 2)
    time.sleep(0.2)


def perform_drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    button: str = "left",
    *,
    duration: float = 0.35,
) -> None:
    """按住从 (x1,y1) 拖到 (x2,y2)，Excel 选区/拖文件等。"""
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    duration = max(0.2, duration)

    if sys.platform == "darwin" and _perform_drag_quartz(x1, y1, x2, y2, button, duration):
        return

    if sys.platform == "win32" and _perform_drag_windows(x1, y1, x2, y2, button, duration):
        return

    from pynput.mouse import Button, Controller

    btn_map = {
        "left": Button.left,
        "right": Button.right,
        "middle": Button.middle,
    }
    btn = btn_map.get(button, Button.left)
    mouse = Controller()
    mouse.position = (x1, y1)
    time.sleep(0.15)
    mouse.press(btn)
    time.sleep(0.08)

    steps = max(int(duration / 0.02), 8)
    for i in range(1, steps + 1):
        t = i / steps
        mouse.position = (
            int(x1 + (x2 - x1) * t),
            int(y1 + (y2 - y1) * t),
        )
        time.sleep(duration / steps)

    mouse.release(btn)
    time.sleep(0.1)


def _scroll_to_lines(delta: float) -> int:
    """把录制的 scroll 值换算成行数。"""
    value = float(delta)
    if abs(value) < 0.01:
        return 0
    # 触控板 point delta 通常 5~15 一行；鼠标滚轮整型 ~1 一行
    if abs(value) <= 3:
        lines = int(round(value))
    else:
        lines = int(round(value / 8))
    if lines == 0:
        lines = 1 if value > 0 else -1
    return lines


def perform_scroll(
    dx: float,
    dy: float,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> None:
    """滚轮/触控板滚动。"""
    if abs(float(dx)) < 0.01 and abs(float(dy)) < 0.01:
        return

    if x is not None and y is not None:
        _warp_cursor(int(x), int(y))
        time.sleep(0.12)

    if sys.platform == "darwin":
        _perform_scroll_quartz(dx, dy)
    elif sys.platform == "win32":
        _perform_scroll_windows(dx, dy)
    else:
        _perform_scroll_pynput(dx, dy)


def perform_scroll_pan(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    duration: float = 0.25,
) -> None:
    """中键按住拖动平移。"""
    perform_drag(x1, y1, x2, y2, button="middle", duration=duration)


def _perform_scroll_quartz(dx: float, dy: float) -> None:
    """macOS Quartz 行级滚动，Excel/浏览器识别率高。"""
    try:
        import Quartz

        line_y = _scroll_to_lines(dy)
        line_x = _scroll_to_lines(dx)
        if line_x == 0 and line_y == 0:
            return

        remaining_y, remaining_x = line_y, line_x
        while remaining_y != 0 or remaining_x != 0:
            chunk_y = 0
            chunk_x = 0
            if remaining_y:
                step = max(-3, min(3, remaining_y))
                chunk_y = step
                remaining_y -= step
            if remaining_x:
                step = max(-3, min(3, remaining_x))
                chunk_x = step
                remaining_x -= step

            Quartz.CGEventPost(
                Quartz.kCGHIDEventTap,
                Quartz.CGEventCreateScrollWheelEvent(
                    None,
                    Quartz.kCGScrollEventUnitLine,
                    2,
                    chunk_y,
                    chunk_x,
                ),
            )
            time.sleep(0.05)
        time.sleep(0.06)
    except Exception:
        _perform_scroll_pynput(dx, dy)


def _perform_scroll_windows(dx: float, dy: float) -> None:
    """Windows pyautogui 滚轮。"""
    try:
        pyautogui = _ensure_pyautogui()

        clicks_y = int(round(float(dy)))
        clicks_x = int(round(float(dx)))
        if clicks_y:
            pyautogui.scroll(clicks_y)
        if clicks_x:
            pyautogui.hscroll(clicks_x)
        time.sleep(0.06)
    except Exception:
        _perform_scroll_pynput(dx, dy)


def _perform_click_windows(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    """Windows 点击：SendInput（浏览器能收到 mousemove），再 fallback。"""
    if _perform_click_sendinput(x, y, button, settle=settle):
        return True
    if _perform_click_win32(x, y, button, settle=settle):
        return True
    try:
        pyautogui = _ensure_pyautogui()
        btn_map = {"left": "left", "right": "right", "middle": "middle"}
        btn = btn_map.get(button, "left")
        pyautogui.moveTo(x, y, duration=0.15 if settle else 0.08)
        time.sleep(0.2 if settle else 0.1)
        pyautogui.click(x, y, button=btn)
        time.sleep(0.12 if settle else 0.08)
        return True
    except Exception:
        return False


def _perform_click_sendinput(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    """
    Windows SendInput — 发送 mousemove + click。
    浏览器/网页需要 mousemove 才能正确识别悬停和点击（SetCursorPos 不够）。
    """
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        user32 = ctypes.windll.user32
        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]

            _anonymous_ = ("u",)
            _fields_ = [
                ("type", wintypes.DWORD),
                ("u", _INPUT_UNION),
            ]

        INPUT_MOUSE = 0
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040
        MOUSEEVENTF_ABSOLUTE = 0x8000
        MOUSEEVENTF_VIRTUALDESK = 0x4000
        MOVE_ABS = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = max(user32.GetSystemMetrics(78), 1)
        vh = max(user32.GetSystemMetrics(79), 1)
        ax = int((int(x) - vx) * 65535 / max(vw - 1, 1))
        ay = int((int(y) - vy) * 65535 / max(vh - 1, 1))

        if button == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif button == "middle":
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        else:
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

        def send_mouse(flags: int) -> None:
            inp = INPUT(type=INPUT_MOUSE)
            inp.mi = MOUSEINPUT(ax, ay, 0, flags, 0, ULONG_PTR(0))
            if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
                raise OSError("SendInput failed")

        send_mouse(MOVE_ABS)
        time.sleep(0.35 if settle else 0.18)
        send_mouse(MOVE_ABS | down_flag)
        time.sleep(0.06 if settle else 0.04)
        send_mouse(MOVE_ABS | up_flag)
        time.sleep(0.12)
        return True
    except Exception:
        return False


def _perform_click_win32(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    """Windows API SetCursorPos + mouse_event。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if settle:
            time.sleep(0.05)
        if not user32.SetCursorPos(int(x), int(y)):
            return False
        time.sleep(0.15 if settle else 0.08)

        if button == "right":
            down, up = 0x0008, 0x0010
        elif button == "middle":
            down, up = 0x0020, 0x0040
        else:
            down, up = 0x0002, 0x0004

        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.1)
        return True
    except Exception:
        return False


def _perform_double_click_windows(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    if button == "left" and _perform_double_click_sendinput(x, y, settle=settle):
        return True
    try:
        pyautogui = _ensure_pyautogui()
        btn_map = {"left": "left", "right": "right", "middle": "middle"}
        btn = btn_map.get(button, "left")
        pyautogui.moveTo(x, y, duration=0.15 if settle else 0.08)
        time.sleep(0.2 if settle else 0.1)
        if btn == "left":
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.click(x, y, button=btn, clicks=2, interval=0.08)
        time.sleep(0.15)
        return True
    except Exception:
        return False


def _perform_double_click_sendinput(x: int, y: int, *, settle: bool = False) -> bool:
    try:
        if not _perform_click_sendinput(x, y, "left", settle=settle):
            return False
        time.sleep(0.08)
        return _perform_click_sendinput(x, y, "left", settle=False)
    except Exception:
        return False


def _perform_drag_windows(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    button: str,
    duration: float,
) -> bool:
    try:
        pyautogui = _ensure_pyautogui()
        btn_map = {"left": "left", "right": "right", "middle": "middle"}
        btn = btn_map.get(button, "left")
        pyautogui.moveTo(x1, y1, duration=0.08)
        time.sleep(0.1)
        pyautogui.drag(x2 - x1, y2 - y1, duration=duration, button=btn)
        time.sleep(0.1)
        return True
    except Exception:
        return False


def _perform_scroll_pynput(dx: float, dy: float) -> None:
    from pynput.mouse import Controller

    mouse = Controller()
    mouse.scroll(int(round(dx)), int(round(dy)))
    time.sleep(0.08)


def _warp_cursor(x: int, y: int) -> None:
    """先把鼠标移到目标位置（首次点击更稳）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.user32.SetCursorPos(int(x), int(y)):
                time.sleep(0.15)
                return
        except Exception:
            pass
        try:
            pyautogui = _ensure_pyautogui()
            pyautogui.moveTo(x, y, duration=0.05)
            time.sleep(0.15)
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
        time.sleep(0.28 if settle else 0.15)

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


def _perform_double_click_quartz(
    x: int, y: int, button: str, *, settle: bool = False
) -> bool:
    """Quartz 双击，浏览器/桌面打开文件更可靠。"""
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
            time.sleep(0.1)

        move = CGEventCreateMouseEvent(None, kCGEventMouseMoved, point, btn)
        CGEventPost(kCGHIDEventTap, move)
        time.sleep(0.15)

        for click_state in (1, 2):
            down = CGEventCreateMouseEvent(None, down_type, point, btn)
            CGEventSetIntegerValueField(down, kCGMouseEventClickState, click_state)
            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.05)
            up = CGEventCreateMouseEvent(None, up_type, point, btn)
            CGEventSetIntegerValueField(up, kCGMouseEventClickState, click_state)
            CGEventPost(kCGHIDEventTap, up)
            time.sleep(0.08 if click_state == 1 else 0.15)
        return True
    except Exception:
        return False


def _perform_drag_quartz(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    button: str,
    duration: float,
) -> bool:
    """Quartz 拖拽事件。"""
    try:
        from Quartz import (
            CGEventCreateMouseEvent,
            CGEventPost,
            kCGEventLeftMouseDragged,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGEventRightMouseDragged,
            kCGEventRightMouseDown,
            kCGEventRightMouseUp,
            kCGHIDEventTap,
            kCGMouseButtonLeft,
            kCGMouseButtonRight,
        )

        start = (float(x1), float(y1))
        end = (float(x2), float(y2))
        if button == "right":
            down_type = kCGEventRightMouseDown
            drag_type = kCGEventRightMouseDragged
            up_type = kCGEventRightMouseUp
            btn = kCGMouseButtonRight
        else:
            down_type = kCGEventLeftMouseDown
            drag_type = kCGEventLeftMouseDragged
            up_type = kCGEventLeftMouseUp
            btn = kCGMouseButtonLeft

        _warp_cursor(x1, y1)
        time.sleep(0.1)

        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, down_type, start, btn))
        time.sleep(0.08)

        steps = max(int(duration / 0.02), 8)
        for i in range(1, steps + 1):
            t = i / steps
            point = (
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
            )
            CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, drag_type, point, btn))
            time.sleep(duration / steps)

        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, up_type, end, btn))
        time.sleep(0.1)
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
