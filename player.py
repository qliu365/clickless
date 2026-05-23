"""
回放模块 - 按顺序重放录制的鼠标/键盘操作。
"""

import sys
import threading
import time
from typing import Callable, List, Optional

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key

from mouse_click import perform_click as _perform_click

_keyboard_controller = KeyboardController()

# 录制时的按键名 -> pynput Key
_SPECIAL_KEYS = {
    "enter": Key.enter,
    "return": Key.enter,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "esc": Key.esc,
    "escape": Key.esc,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "shift": Key.shift,
    "shift_l": Key.shift,
    "shift_r": Key.shift,
    "ctrl": Key.ctrl,
    "ctrl_l": Key.ctrl,
    "ctrl_r": Key.ctrl,
    "alt": Key.alt,
    "alt_l": Key.alt,
    "alt_r": Key.alt,
    "alt_gr": Key.alt,
    "cmd": Key.cmd,
    "cmd_l": Key.cmd,
    "cmd_r": Key.cmd,
}


def _type_text(text: str) -> None:
    """
    输入文字。
    macOS / 中文等：剪贴板 + Command+V（浏览器里最稳，不依赖输入法状态）。
    纯英文：也可逐字输入。
    """
    if not text:
        return

    use_paste = any(ord(c) > 127 for c in text) or sys.platform in ("darwin", "win32")

    if use_paste:
        import pyperclip

        previous = None
        try:
            previous = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.12)
        paste_mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with _keyboard_controller.pressed(paste_mod):
            _keyboard_controller.press("v")
            _keyboard_controller.release("v")
        time.sleep(0.25)

        if previous is not None:
            try:
                pyperclip.copy(previous)
            except Exception:
                pass
        return

    for char in text:
        _keyboard_controller.press(char)
        _keyboard_controller.release(char)
        time.sleep(0.02)


def _perform_key(key_name: str) -> None:
    """按下并释放一个键（Enter、Backspace、方向键等）。"""
    key_name = key_name.lower()

    if key_name in _SPECIAL_KEYS:
        key = _SPECIAL_KEYS[key_name]
        _keyboard_controller.press(key)
        time.sleep(0.03)
        _keyboard_controller.release(key)
        time.sleep(0.05)
        return

    if len(key_name) == 1:
        _keyboard_controller.press(key_name)
        _keyboard_controller.release(key_name)
        time.sleep(0.05)
        return

    # 兜底：pyautogui
    import pyautogui

    pyautogui.press(key_name)


def _perform_hotkey(keys: List[str]) -> None:
    """组合键，如 Command+C / Command+V。"""
    mapped: List = []
    for name in keys:
        name = name.lower()
        if name in _SPECIAL_KEYS:
            mapped.append(_SPECIAL_KEYS[name])
        elif len(name) == 1:
            mapped.append(name)
        else:
            mapped.append(name)

    if not mapped:
        return

    # 修饰键先按下，再按主键
    modifiers = mapped[:-1]
    main = mapped[-1]

    for mod in modifiers:
        _keyboard_controller.press(mod)
    time.sleep(0.03)
    _keyboard_controller.press(main)
    _keyboard_controller.release(main)
    time.sleep(0.03)
    for mod in reversed(modifiers):
        _keyboard_controller.release(mod)
    time.sleep(0.05)


class Player:
    """回放步骤列表，支持倒计时与中途停止。"""

    DEFAULT_COUNTDOWN = 5  # 给用户时间切换到浏览器
    POST_COUNTDOWN_DELAY = 1.0  # 倒计时结束后额外等待，让浏览器稳定获得焦点
    FIRST_CLICK_EXTRA_DELAY = 0.8  # 第一次点击前再等一会

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_playing(self) -> bool:
        """是否正在回放。"""
        return self._thread is not None and self._thread.is_alive()

    def play(
        self,
        steps: List[dict],
        countdown: int = DEFAULT_COUNTDOWN,
        on_countdown: Optional[Callable[[int], None]] = None,
        on_step: Optional[Callable[[int, dict], None]] = None,
        on_before_step: Optional[Callable[[int, dict], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """在后台线程中回放步骤。"""
        if self.is_playing:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(steps, countdown, on_countdown, on_step, on_before_step, on_done, on_error),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """请求停止回放。"""
        self._stop_event.set()

    def _run(
        self,
        steps: List[dict],
        countdown: int,
        on_countdown: Optional[Callable[[int], None]],
        on_step: Optional[Callable[[int, dict], None]],
        on_before_step: Optional[Callable[[int, dict], None]],
        on_done: Optional[Callable[[], None]],
        on_error: Optional[Callable[[Exception], None]],
    ) -> None:
        try:
            for remaining in range(countdown, 0, -1):
                if self._stop_event.is_set():
                    return
                if on_countdown:
                    on_countdown(remaining)
                time.sleep(1)

            time.sleep(self.POST_COUNTDOWN_DELAY)

            first_click_pending = any(step.get("type") == "click" for step in steps)

            for index, step in enumerate(steps):
                if self._stop_event.is_set():
                    break

                delay = step.get("delay", 0)
                if delay > 0:
                    end = time.time() + delay
                    while time.time() < end:
                        if self._stop_event.is_set():
                            return
                        time.sleep(min(0.1, end - time.time()))

                if on_before_step:
                    on_before_step(index, step)

                self._execute_step(step, first_click_pending=first_click_pending)

                if step.get("type") == "click" and first_click_pending:
                    first_click_pending = False

                if on_step:
                    on_step(index, step)

            if on_done and not self._stop_event.is_set():
                on_done()
        except Exception as exc:
            if on_error:
                on_error(exc)
            else:
                raise

    def _execute_step(self, step: dict, *, first_click_pending: bool = False) -> None:
        """执行单步操作。"""
        step_type = step.get("type")

        if step_type == "click":
            if first_click_pending:
                time.sleep(self.FIRST_CLICK_EXTRA_DELAY)
            _perform_click(
                step["x"],
                step["y"],
                step.get("button", "left"),
                settle=first_click_pending,
                retry=2 if first_click_pending else 1,
            )
            time.sleep(0.15)

        elif step_type == "type":
            _type_text(step.get("text", ""))

        elif step_type == "key":
            _perform_key(step.get("key", ""))

        elif step_type == "hotkey":
            _perform_hotkey(step.get("keys", []))

        else:
            raise ValueError(f"未知步骤类型: {step_type}")
