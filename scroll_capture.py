"""
滚轮/触控板滚动监听 + macOS 鼠标补充监听。

macOS 上 pynput 用整型 delta，触控板经常是 0，导致录不到 scroll。
这里用 Quartz EventTap 读 PointDelta；鼠标点击作为 pynput 的补充（去重后合并）。
Windows 仍走 pynput。
"""

import sys
import threading
from typing import Callable, Optional

# EventTap 回调线程里访问 Quartz.CGEventGetLocation 会触发 pyobjc lazy-import KeyError。
# 启动时在主线程一次性绑定；_run 里再拷到闭包局部变量。
if sys.platform == "darwin":
    try:
        from ApplicationServices import (  # type: ignore
            CFMachPortCreateRunLoopSource as _CFMachPortCreateRunLoopSource,
            CGEventGetDoubleValueField as _CGEventGetDoubleValueField,
            CGEventGetIntegerValueField as _CGEventGetIntegerValueField,
            CGEventGetLocation as _CGEventGetLocation,
            CGEventMaskBit as _CGEventMaskBit,
            CGEventTapCreate as _CGEventTapCreate,
            CGEventTapEnable as _CGEventTapEnable,
            kCGEventLeftMouseDown as _kCGEventLeftMouseDown,
            kCGEventLeftMouseUp as _kCGEventLeftMouseUp,
            kCGEventOtherMouseDown as _kCGEventOtherMouseDown,
            kCGEventOtherMouseUp as _kCGEventOtherMouseUp,
            kCGEventRightMouseDown as _kCGEventRightMouseDown,
            kCGEventRightMouseUp as _kCGEventRightMouseUp,
            kCGEventScrollWheel as _kCGEventScrollWheel,
            kCGEventTapDisabledByTimeout as _kCGEventTapDisabledByTimeout,
            kCGEventTapDisabledByUserInput as _kCGEventTapDisabledByUserInput,
            kCGEventTapOptionListenOnly as _kCGEventTapOptionListenOnly,
            kCGHeadInsertEventTap as _kCGHeadInsertEventTap,
            kCGMouseEventButtonNumber as _kCGMouseEventButtonNumber,
            kCGScrollWheelEventDeltaAxis1 as _kCGScrollWheelEventDeltaAxis1,
            kCGScrollWheelEventDeltaAxis2 as _kCGScrollWheelEventDeltaAxis2,
            kCGScrollWheelEventPointDeltaAxis1 as _kCGScrollWheelEventPointDeltaAxis1,
            kCGScrollWheelEventPointDeltaAxis2 as _kCGScrollWheelEventPointDeltaAxis2,
            kCGSessionEventTap as _kCGSessionEventTap,
        )
    except ImportError:
        import Quartz as _Quartz

        _CGEventGetLocation = _Quartz.CGEventGetLocation
        _CGEventGetDoubleValueField = _Quartz.CGEventGetDoubleValueField
        _CGEventGetIntegerValueField = _Quartz.CGEventGetIntegerValueField
        _CGEventTapCreate = _Quartz.CGEventTapCreate
        _CGEventTapEnable = _Quartz.CGEventTapEnable
        _CGEventMaskBit = _Quartz.CGEventMaskBit
        _CFMachPortCreateRunLoopSource = _Quartz.CFMachPortCreateRunLoopSource
        _kCGEventScrollWheel = _Quartz.kCGEventScrollWheel
        _kCGEventLeftMouseDown = _Quartz.kCGEventLeftMouseDown
        _kCGEventLeftMouseUp = _Quartz.kCGEventLeftMouseUp
        _kCGEventRightMouseDown = _Quartz.kCGEventRightMouseDown
        _kCGEventRightMouseUp = _Quartz.kCGEventRightMouseUp
        _kCGEventOtherMouseDown = _Quartz.kCGEventOtherMouseDown
        _kCGEventOtherMouseUp = _Quartz.kCGEventOtherMouseUp
        _kCGEventTapDisabledByTimeout = _Quartz.kCGEventTapDisabledByTimeout
        _kCGEventTapDisabledByUserInput = _Quartz.kCGEventTapDisabledByUserInput
        _kCGMouseEventButtonNumber = _Quartz.kCGMouseEventButtonNumber
        _kCGScrollWheelEventPointDeltaAxis1 = _Quartz.kCGScrollWheelEventPointDeltaAxis1
        _kCGScrollWheelEventPointDeltaAxis2 = _Quartz.kCGScrollWheelEventPointDeltaAxis2
        _kCGScrollWheelEventDeltaAxis1 = _Quartz.kCGScrollWheelEventDeltaAxis1
        _kCGScrollWheelEventDeltaAxis2 = _Quartz.kCGScrollWheelEventDeltaAxis2
        _kCGSessionEventTap = _Quartz.kCGSessionEventTap
        _kCGHeadInsertEventTap = _Quartz.kCGHeadInsertEventTap
        _kCGEventTapOptionListenOnly = _Quartz.kCGEventTapOptionListenOnly


ScrollCallback = Callable[[int, int, float, float], None]
ClickCallback = Callable[[int, int, str, bool], None]
TapFailedCallback = Callable[[], None]


class MacInputListener:
    """macOS 专用 scroll + 鼠标点击补充监听（Quartz EventTap）。"""

    def __init__(
        self,
        on_scroll: Optional[ScrollCallback] = None,
        on_click: Optional[ClickCallback] = None,
        on_tap_failed: Optional[TapFailedCallback] = None,
    ) -> None:
        self._on_scroll = on_scroll
        self._on_click = on_click
        self._on_tap_failed = on_tap_failed
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._tap = None

    def start(self) -> bool:
        if sys.platform != "darwin":
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _click_button_name(event_type, event) -> str:
        if event_type in (
            _kCGEventLeftMouseDown,
            _kCGEventLeftMouseUp,
        ):
            return "left"
        if event_type in (
            _kCGEventRightMouseDown,
            _kCGEventRightMouseUp,
        ):
            return "right"
        btn = _CGEventGetIntegerValueField(event, _kCGMouseEventButtonNumber)
        if btn == 2:
            return "middle"
        return "left"

    @staticmethod
    def _is_mouse_pressed(event_type) -> bool:
        return event_type in (
            _kCGEventLeftMouseDown,
            _kCGEventRightMouseDown,
            _kCGEventOtherMouseDown,
        )

    def _run(self) -> None:
        from CoreFoundation import (
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRunInMode,
            kCFRunLoopDefaultMode,
        )

        # 在监听线程里再绑定一次，避免 EventTap 回调里触发 pyobjc lazy import。
        get_location = _CGEventGetLocation
        get_double = _CGEventGetDoubleValueField
        get_integer = _CGEventGetIntegerValueField
        tap_create = _CGEventTapCreate
        tap_enable = _CGEventTapEnable
        mask_bit = _CGEventMaskBit
        port_source = _CFMachPortCreateRunLoopSource

        mouse_types = (
            _kCGEventLeftMouseDown,
            _kCGEventLeftMouseUp,
            _kCGEventRightMouseDown,
            _kCGEventRightMouseUp,
            _kCGEventOtherMouseDown,
            _kCGEventOtherMouseUp,
        )

        def _event_location(event) -> tuple[int, int]:
            try:
                px, py = get_location(event)
                return int(round(px)), int(round(py))
            except Exception:
                try:
                    from pynput.mouse import Controller

                    pos = Controller().position
                    return int(round(pos[0])), int(round(pos[1]))
                except Exception:
                    return 0, 0

        def handler(_proxy, event_type, event, _refcon):
            if self._stop.is_set():
                return event

            if event_type in (
                _kCGEventTapDisabledByTimeout,
                _kCGEventTapDisabledByUserInput,
            ):
                if self._tap:
                    tap_enable(self._tap, True)
                return event

            ix, iy = _event_location(event)

            if event_type == _kCGEventScrollWheel:
                if self._on_scroll:
                    dy = get_double(event, _kCGScrollWheelEventPointDeltaAxis1)
                    dx = get_double(event, _kCGScrollWheelEventPointDeltaAxis2)
                    if abs(dy) < 0.01:
                        dy = float(
                            get_integer(event, _kCGScrollWheelEventDeltaAxis1)
                        )
                    if abs(dx) < 0.01:
                        dx = float(
                            get_integer(event, _kCGScrollWheelEventDeltaAxis2)
                        )
                    if dx != 0 or dy != 0:
                        self._on_scroll(ix, iy, dx, dy)
                return event

            if event_type in mouse_types and self._on_click:
                btn = self._click_button_name(event_type, event)
                pressed = self._is_mouse_pressed(event_type)
                self._on_click(ix, iy, btn, pressed)
            return event

        mask = mask_bit(_kCGEventScrollWheel)
        for event_type in mouse_types:
            mask |= mask_bit(event_type)

        tap = tap_create(
            _kCGSessionEventTap,
            _kCGHeadInsertEventTap,
            _kCGEventTapOptionListenOnly,
            mask,
            handler,
            None,
        )
        if not tap:
            if self._on_tap_failed:
                self._on_tap_failed()
            return

        self._tap = tap
        source = port_source(None, tap, 0)
        loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(loop, source, kCFRunLoopDefaultMode)
        tap_enable(tap, True)

        while not self._stop.is_set():
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.3, False)

        tap_enable(tap, False)
        self._tap = None


class MacScrollListener(MacInputListener):
    """兼容旧接口：仅滚动回调。"""

    def __init__(self, callback: ScrollCallback) -> None:
        super().__init__(on_scroll=callback)
