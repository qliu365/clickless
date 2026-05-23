"""
滚轮/触控板滚动监听。

macOS 上 pynput 用整型 delta，触控板经常是 0，导致录不到 scroll。
这里用 Quartz 读 PointDelta，Windows 仍走 pynput。
"""

import sys
import threading
from typing import Callable, Optional


ScrollCallback = Callable[[int, int, float, float], None]


class MacScrollListener:
    """macOS 专用滚动监听（Quartz EventTap）。"""

    def __init__(self, callback: ScrollCallback) -> None:
        self._callback = callback
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

    def _run(self) -> None:
        import Quartz
        from CoreFoundation import (
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRunInMode,
            kCFRunLoopDefaultMode,
        )

        def handler(_proxy, event_type, event, _refcon):
            if self._stop.is_set():
                return event
            if event_type != Quartz.kCGEventScrollWheel:
                return event

            px, py = Quartz.CGEventGetLocation(event)
            dy = Quartz.CGEventGetDoubleValueField(
                event, Quartz.kCGScrollWheelEventPointDeltaAxis1
            )
            dx = Quartz.CGEventGetDoubleValueField(
                event, Quartz.kCGScrollWheelEventPointDeltaAxis2
            )
            if abs(dy) < 0.01:
                dy = float(
                    Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGScrollWheelEventDeltaAxis1
                    )
                )
            if abs(dx) < 0.01:
                dx = float(
                    Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGScrollWheelEventDeltaAxis2
                    )
                )

            if dx != 0 or dy != 0:
                self._callback(int(round(px)), int(round(py)), dx, dy)
            return event

        mask = Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            handler,
            None,
        )
        if not tap:
            return

        self._tap = tap
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(loop, source, kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)

        while not self._stop.is_set():
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.3, False)

        Quartz.CGEventTapEnable(tap, False)
