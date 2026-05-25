"""
macOS 鼠标 HID 轮询 — 补录 WPS 等不向系统上报点击的应用。
"""

import sys
import threading
import time
from typing import Callable, Optional

ClickCallback = Callable[[int, int, str, bool], None]


class MacMousePoller:
    INTERVAL = 0.012

    def __init__(self, on_click: ClickCallback) -> None:
        self._on_click = on_click
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._left_down = False
        self._right_down = False

    def start(self) -> bool:
        if sys.platform != "darwin":
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._left_down = False
        self._right_down = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _read() -> tuple[int, int, bool, bool]:
        import Quartz
        from pynput.mouse import Controller

        pos = Controller().position
        x, y = int(round(pos[0])), int(round(pos[1]))
        left = bool(
            Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateHIDSystemState,
                Quartz.kCGMouseButtonLeft,
            )
        )
        right = bool(
            Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateHIDSystemState,
                Quartz.kCGMouseButtonRight,
            )
        )
        return x, y, left, right

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                x, y, left, right = self._read()
            except Exception:
                time.sleep(self.INTERVAL)
                continue
            if left != self._left_down:
                self._left_down = left
                self._on_click(x, y, "left", left)
            if right != self._right_down:
                self._right_down = right
                self._on_click(x, y, "right", right)
            time.sleep(self.INTERVAL)
