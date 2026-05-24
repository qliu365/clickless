"""
回放模块 - 按顺序重放录制的鼠标/键盘操作。
"""

import sys
import threading
import time
from typing import Callable, List, Optional, Tuple

RunOnMain = Callable[[Callable[[], None]], None]

from pynput import mouse
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key

from mouse_click import perform_click as _perform_click
from mouse_click import perform_double_click as _perform_double_click
from mouse_click import perform_drag as _perform_drag
from mouse_click import perform_scroll as _perform_scroll
from mouse_click import perform_scroll_pan as _perform_scroll_pan
from keyboard_shortcuts import (
    clipboard_action_for_hotkey,
    perform_copy,
    perform_paste,
)
from window_bounds import (
    clear_playback_offset,
    expected_click_point,
    resolve_click_point,
    resolve_drag_points,
    resolve_scroll_point,
    set_playback_offset,
)

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
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
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
    if key_name == "return":
        key_name = "enter"
    if key_name == "escape":
        key_name = "esc"

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


def _merge_double_clicks(steps: List[dict]) -> List[dict]:
    """相邻同位置快速连点合并为双击（打开文档常见）。"""
    merged: List[dict] = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if (
            i + 1 < len(steps)
            and step.get("type") == "click"
            and steps[i + 1].get("type") == "click"
        ):
            nxt = steps[i + 1]
            dx = abs(step["x"] - nxt["x"])
            dy = abs(step["y"] - nxt["y"])
            gap = nxt.get("delay", 0)
            if dx <= 12 and dy <= 12 and gap <= 0.5:
                dc = {
                    "type": "double_click",
                    "x": int(round((step["x"] + nxt["x"]) / 2)),
                    "y": int(round((step["y"] + nxt["y"]) / 2)),
                    "button": step.get("button", "left"),
                    "delay": step.get("delay", 0),
                }
                if "ox" in step and "oy" in step:
                    dc["ox"] = int(round((step["ox"] + nxt["ox"]) / 2))
                    dc["oy"] = int(round((step["oy"] + nxt["oy"]) / 2))
                merged.append(dc)
                i += 2
                continue
        merged.append(step)
        i += 1
    return merged


def _prepare_steps_for_playback(steps: List[dict]) -> List[dict]:
    """回放前优化步骤：合并双击、缩短首步等待。"""
    if not steps:
        return steps

    prepared = _merge_double_clicks(steps)
    first = dict(prepared[0])
    # 录制时第一步 delay 是切窗口耗时，回放已有倒计时
    first["delay"] = min(float(first.get("delay", 0)), 2.0)
    prepared[0] = first
    return prepared


def _first_pointer_anchor(steps: List[dict]) -> Optional[Tuple[int, int]]:
    """流程里第一个需要屏幕坐标的步骤（用于运行前对齐）。"""
    for step in steps:
        step_type = step.get("type")
        if step_type in ("click", "double_click"):
            return expected_click_point(step)
        if step_type == "drag":
            return expected_click_point(step)
        if step_type == "scroll" and step.get("x") is not None:
            return expected_click_point(step)
    return None


def _point_in_rects(x: int, y: int, rects: List[Tuple[int, int, int, int]]) -> bool:
    for x1, y1, x2, y2 in rects:
        if x1 <= x <= x2 and y1 <= y <= y2:
            return True
    return False


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
    POST_COUNTDOWN_DELAY = 1.5  # 倒计时结束后额外等待，让浏览器稳定获得焦点
    FIRST_CLICK_EXTRA_DELAY = 1.2  # 第一次点击前再等一会

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
        exclude_rects: Optional[Callable[[], List[Tuple[int, int, int, int]]]] = None,
        run_on_main: Optional[RunOnMain] = None,
    ) -> None:
        """在后台线程中回放步骤。"""
        if self.is_playing:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(
                steps,
                countdown,
                on_countdown,
                on_step,
                on_before_step,
                on_done,
                on_error,
                exclude_rects,
                run_on_main,
            ),
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
        exclude_rects: Optional[Callable[[], List[Tuple[int, int, int, int]]]],
        run_on_main: Optional[RunOnMain],
    ) -> None:
        listener: Optional[mouse.Listener] = None
        try:
            clear_playback_offset()
            steps = _prepare_steps_for_playback(steps)
            has_pointer_steps = _first_pointer_anchor(steps) is not None
            calibration: dict = {"x": None, "y": None}

            # Windows 上 pynput 监听会干扰后续鼠标注入，跳过运行前对齐监听
            use_calibration_listener = has_pointer_steps and sys.platform != "win32"

            if use_calibration_listener:

                def _on_calibration_click(x: float, y: float, button: mouse.Button, pressed: bool) -> None:
                    if not pressed or button != mouse.Button.left:
                        return
                    ix, iy = int(round(x)), int(round(y))
                    rects = exclude_rects() if exclude_rects else []
                    if _point_in_rects(ix, iy, rects):
                        return
                    calibration["x"] = ix
                    calibration["y"] = iy

                listener = mouse.Listener(on_click=_on_calibration_click)
                listener.start()

            for remaining in range(countdown, 0, -1):
                if self._stop_event.is_set():
                    return
                if on_countdown:
                    on_countdown(remaining)
                time.sleep(1)

            if listener is not None:
                listener.stop()
                listener = None

            anchor = _first_pointer_anchor(steps)
            if (
                anchor is not None
                and calibration["x"] is not None
                and calibration["y"] is not None
            ):
                expected_x, expected_y = anchor
                set_playback_offset(
                    calibration["x"] - expected_x,
                    calibration["y"] - expected_y,
                )

            time.sleep(self.POST_COUNTDOWN_DELAY)

            first_click_pending = any(
                step.get("type") in ("click", "double_click") for step in steps
            )

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

                self._execute_step(
                    step,
                    first_click_pending=first_click_pending,
                    run_on_main=run_on_main,
                )

                if step.get("type") in ("click", "double_click") and first_click_pending:
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
        finally:
            if listener is not None:
                listener.stop()
            clear_playback_offset()

    def _execute_step(
        self,
        step: dict,
        *,
        first_click_pending: bool = False,
        run_on_main: Optional[RunOnMain] = None,
    ) -> None:
        """执行单步操作。Windows 上鼠标/键盘必须在主线程注入。"""

        def run() -> None:
            self._execute_step_impl(step, first_click_pending=first_click_pending)

        if run_on_main and sys.platform == "win32":
            run_on_main(run)
        else:
            run()

    def _execute_step_impl(self, step: dict, *, first_click_pending: bool = False) -> None:
        """实际执行单步（应在 Windows 主线程调用）。"""
        step_type = step.get("type")

        if step_type == "click":
            if first_click_pending:
                time.sleep(self.FIRST_CLICK_EXTRA_DELAY)
            x, y = resolve_click_point(step)
            _perform_click(
                x,
                y,
                step.get("button", "left"),
                settle=first_click_pending,
                retry=3 if first_click_pending else 1,
            )
            time.sleep(0.15)

        elif step_type == "double_click":
            if first_click_pending:
                time.sleep(self.FIRST_CLICK_EXTRA_DELAY)
            x, y = resolve_click_point(step)
            _perform_double_click(
                x,
                y,
                step.get("button", "left"),
                settle=True,
            )
            time.sleep(0.2)

        elif step_type == "drag":
            x1, y1, x2, y2 = resolve_drag_points(step)
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            role = step.get("role")
            if role in ("scrollbar_v", "scrollbar_h"):
                duration = min(1.0, max(0.35, dist / 450))
            else:
                duration = min(0.8, max(0.25, dist / 600))
            _perform_drag(
                x1,
                y1,
                x2,
                y2,
                step.get("button", "left"),
                duration=duration,
            )
            time.sleep(0.15)

        elif step_type == "scroll_pan":
            x1, y1, x2, y2 = resolve_drag_points(step)
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            duration = min(0.6, max(0.2, dist / 700))
            _perform_scroll_pan(x1, y1, x2, y2, duration=duration)
            time.sleep(0.1)

        elif step_type == "scroll":
            scroll_at = resolve_scroll_point(step)
            scroll_x = scroll_at[0] if scroll_at else None
            scroll_y = scroll_at[1] if scroll_at else None
            _perform_scroll(
                step.get("dx", 0),
                step.get("dy", 0),
                scroll_x,
                scroll_y,
            )
            time.sleep(0.1)

        elif step_type == "type":
            _type_text(step.get("text", ""))

        elif step_type == "key":
            _perform_key(step.get("key", ""))

        elif step_type == "copy":
            perform_copy()

        elif step_type == "paste":
            perform_paste()

        elif step_type == "hotkey":
            keys = step.get("keys", [])
            action = clipboard_action_for_hotkey(keys)
            if action == "copy":
                perform_copy()
            elif action == "paste":
                perform_paste()
            else:
                _perform_hotkey(keys)

        else:
            raise ValueError(f"未知步骤类型: {step_type}")
