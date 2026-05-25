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
from mouse_click import set_hide_cursor
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
from load_wait import region_from_step, wait_for_screen_stable
from text_sanitize import looks_like_url, sanitize_typed_text

if sys.platform == "darwin":
    from frontmost_app import is_office_like_frontmost
else:

    def is_office_like_frontmost() -> bool:  # type: ignore[misc]
        return False

_keyboard_controller = KeyboardController()

# macOS 虚拟键码 — Excel/WPS 里 pynput 方向键常无效，用 Quartz 注入。
_MAC_KEY_CODES = {
    "enter": 36,
    "return": 36,
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "delete": 117,
    "esc": 53,
    "escape": 53,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "home": 115,
    "end": 119,
    "page_up": 116,
    "page_down": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

if sys.platform == "darwin":
    try:
        from ApplicationServices import (  # type: ignore
            CGEventCreateKeyboardEvent as _CGEventCreateKeyboardEvent,
            CGEventKeyboardSetUnicodeString as _CGEventKeyboardSetUnicodeString,
            CGEventPost as _CGEventPost,
            kCGHIDEventTap as _kCGHIDEventTap,
        )
    except ImportError:
        from Quartz import (  # type: ignore
            CGEventCreateKeyboardEvent as _CGEventCreateKeyboardEvent,
            CGEventKeyboardSetUnicodeString as _CGEventKeyboardSetUnicodeString,
            CGEventPost as _CGEventPost,
            kCGHIDEventTap as _kCGHIDEventTap,
        )

_NAV_KEYS = frozenset({"up", "down", "left", "right", "home", "end", "page_up", "page_down"})

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


def _select_all_field() -> None:
    """浏览器输入框先全选，避免和原有文字拼在一起。"""
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with _keyboard_controller.pressed(mod):
        _keyboard_controller.press("a")
        _keyboard_controller.release("a")
    time.sleep(0.08)


def _perform_key_quartz(key_name: str) -> bool:
    """macOS：Quartz 注入方向键等功能键（Excel/WPS 比 pynput 可靠）。"""
    if sys.platform != "darwin":
        return False
    code = _MAC_KEY_CODES.get(key_name)
    if code is None:
        return False
    try:
        pause = 0.07 if key_name in _NAV_KEYS else 0.05
        down = _CGEventCreateKeyboardEvent(None, code, True)
        _CGEventPost(_kCGHIDEventTap, down)
        time.sleep(pause)
        up = _CGEventCreateKeyboardEvent(None, code, False)
        _CGEventPost(_kCGHIDEventTap, up)
        time.sleep(0.06 if key_name in _NAV_KEYS else 0.04)
        return True
    except Exception:
        return False


def _type_char_quartz(char: str) -> bool:
    """macOS：Unicode 字符注入（Safari / Shopify 比 pynput 可靠）。"""
    if sys.platform != "darwin" or not char:
        return False
    try:
        down = _CGEventCreateKeyboardEvent(None, 0, True)
        _CGEventKeyboardSetUnicodeString(down, len(char), char)
        _CGEventPost(_kCGHIDEventTap, down)
        up = _CGEventCreateKeyboardEvent(None, 0, False)
        _CGEventKeyboardSetUnicodeString(up, len(char), char)
        _CGEventPost(_kCGHIDEventTap, up)
        return True
    except Exception:
        return False


def _type_chars(text: str, *, delay: float = 0.04) -> None:
    """逐字输入（网址、Shopify 搜索框等）。"""
    time.sleep(0.1)
    for char in text:
        if char == " ":
            if not _perform_key_quartz("space"):
                _keyboard_controller.press(Key.space)
                _keyboard_controller.release(Key.space)
        elif sys.platform == "darwin" and _type_char_quartz(char):
            pass
        else:
            _keyboard_controller.press(char)
            _keyboard_controller.release(char)
        time.sleep(delay)


def _paste_text(text: str, *, select_all: bool) -> None:
    """剪贴板粘贴（中文等）；可选先全选。"""
    import pyperclip

    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:
        pass

    time.sleep(0.1)
    if select_all and sys.platform in ("darwin", "win32"):
        _select_all_field()

    pyperclip.copy(text)
    time.sleep(0.06)
    perform_paste()
    time.sleep(0.1)

    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass


def _type_text(text: str) -> None:
    """
    输入文字。
    Safari / Shopify：网址和英文逐字输入（Quartz）。
    中文：剪贴板粘贴。
    Excel/WPS：禁止 Cmd+A 全选整表。
    """
    if not text:
        return

    text = sanitize_typed_text(text)
    if not text:
        return

    if is_office_like_frontmost():
        if all(ord(c) < 128 for c in text):
            _type_chars(text, delay=0.03)
        else:
            _paste_text(text, select_all=False)
        return

    if looks_like_url(text) or all(ord(c) < 128 for c in text):
        delay = 0.05 if looks_like_url(text) else 0.035
        _type_chars(text, delay=delay)
        return

    _paste_text(text, select_all=True)


def _perform_key(key_name: str) -> None:
    """按下并释放一个键（Enter、Backspace、方向键等）。"""
    key_name = key_name.lower()
    if key_name == "return":
        key_name = "enter"
    if key_name == "escape":
        key_name = "esc"

    if key_name in _SPECIAL_KEYS:
        if _perform_key_quartz(key_name):
            return
        key = _SPECIAL_KEYS[key_name]
        _keyboard_controller.press(key)
        pause = 0.06 if key_name == "backspace" else 0.04
        time.sleep(pause)
        _keyboard_controller.release(key)
        time.sleep(0.06 if key_name in ("backspace", "enter") else 0.03)
        return

    if len(key_name) == 1:
        _keyboard_controller.press(key_name)
        _keyboard_controller.release(key_name)
        time.sleep(0.01)
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


def _merge_type_steps(steps: List[dict]) -> List[dict]:
    """合并相邻 type 步（Safari AX 误录的碎片）。"""
    merged: List[dict] = []
    for step in steps:
        if (
            merged
            and step.get("type") == "type"
            and merged[-1].get("type") == "type"
        ):
            prev = dict(merged[-1])
            prev["text"] = prev.get("text", "") + step.get("text", "")
            merged[-1] = prev
        else:
            merged.append(dict(step))
    for step in merged:
        if step.get("type") == "type" and step.get("text"):
            step["text"] = sanitize_typed_text(str(step["text"]))
    return merged


def _prepare_steps_for_playback(steps: List[dict]) -> List[dict]:
    """回放前优化步骤：合并双击、合并文字碎片、缩短首步等待。"""
    if not steps:
        return steps

    prepared = _merge_type_steps(_merge_double_clicks(steps))
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


def resolve_calibration_anchor(
    steps: List[dict],
    anchor_override: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    """运行前对齐锚点；可指定为某次点击的坐标（如侧边栏 Products）。"""
    if anchor_override is not None:
        return anchor_override
    return _first_pointer_anchor(steps)


def _point_in_rects(x: int, y: int, rects: List[Tuple[int, int, int, int]]) -> bool:
    for x1, y1, x2, y2 in rects:
        if x1 <= x <= x2 and y1 <= y <= y2:
            return True
    return False


def _win_poll_calibration_click(
    calibration: dict,
    exclude_rects: Optional[Callable[[], List[Tuple[int, int, int, int]]]],
) -> None:
    """Windows：轮询左键按下位置做运行前对齐（不用 pynput 监听）。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if user32.GetAsyncKeyState(0x01) & 0x8000:
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            pt = POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                ix, iy = int(pt.x), int(pt.y)
                rects = exclude_rects() if exclude_rects else []
                if not _point_in_rects(ix, iy, rects):
                    calibration["x"] = ix
                    calibration["y"] = iy
    except Exception:
        pass


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
    time.sleep(0.01)
    _keyboard_controller.press(main)
    _keyboard_controller.release(main)
    time.sleep(0.01)
    for mod in reversed(modifiers):
        _keyboard_controller.release(mod)
    time.sleep(0.01)


class Player:
    """回放步骤列表，支持倒计时与中途停止。"""

    DEFAULT_COUNTDOWN = 5  # 给用户时间切换到浏览器
    POST_COUNTDOWN_DELAY = 1.0  # 倒计时结束后等目标应用获得焦点
    FIRST_CLICK_EXTRA_DELAY = 1.0  # 首次点击前多等一会（WPS/Safari）
    LOAD_WAIT_TIMEOUT = 8.0
    LOAD_WAIT_STABLE = 0.45
    LOAD_WAIT_MIN_NEXT_DELAY = 0.8  # 下一步等待超过此值才在点击后检测加载

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wait_load_after_click = True
        self._on_wait_load: Optional[Callable[[str], None]] = None
        self._on_step_error: Optional[Callable[[int, dict, Exception], None]] = None
        self._playback_speed = 1.0

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
        calibration_anchor: Optional[Tuple[int, int]] = None,
        wait_load_after_click: bool = True,
        on_wait_load: Optional[Callable[[str], None]] = None,
        playback_speed: float = 1.0,
        on_step_error: Optional[Callable[[int, dict, Exception], None]] = None,
        hide_cursor: bool = True,
    ) -> None:
        """在后台线程中回放步骤。"""
        if self.is_playing:
            return

        self._wait_load_after_click = wait_load_after_click
        self._on_wait_load = on_wait_load
        self._playback_speed = max(0.1, float(playback_speed))
        self._on_step_error = on_step_error
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
                calibration_anchor,
                wait_load_after_click,
                on_wait_load,
                self._playback_speed,
                on_step_error,
                hide_cursor,
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
        calibration_anchor: Optional[Tuple[int, int]],
        wait_load_after_click: bool,
        on_wait_load: Optional[Callable[[str], None]],
        playback_speed: float,
        on_step_error: Optional[Callable[[int, dict, Exception], None]],
        hide_cursor: bool,
    ) -> None:
        listener: Optional[mouse.Listener] = None
        step_errors: List[Tuple[int, Exception]] = []
        set_hide_cursor(hide_cursor)
        try:
            self._wait_load_after_click = wait_load_after_click
            self._on_wait_load = on_wait_load
            self._on_step_error = on_step_error
            self._playback_speed = max(0.1, float(playback_speed))
            clear_playback_offset()
            steps = _prepare_steps_for_playback(steps)
            anchor = resolve_calibration_anchor(steps, calibration_anchor)
            has_pointer_steps = anchor is not None
            calibration: dict = {"x": None, "y": None}

            # Windows 用轮询对齐；macOS 用 pynput 监听
            use_calibration_listener = has_pointer_steps and sys.platform != "win32"
            use_calibration_poll = has_pointer_steps and sys.platform == "win32"

            if use_calibration_listener:

                def _on_calibration_click(x, y, button, pressed, injected=False) -> None:
                    if injected or not pressed or button != mouse.Button.left:
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
                if use_calibration_poll:
                    for _ in range(10):
                        if self._stop_event.is_set():
                            return
                        _win_poll_calibration_click(calibration, exclude_rects)
                        time.sleep(0.02)
                else:
                    time.sleep(1)

            if listener is not None:
                listener.stop()
                listener = None

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

                delay = float(step.get("delay", 0)) / self._playback_speed
                if delay > 0:
                    end = time.time() + delay
                    while time.time() < end:
                        if self._stop_event.is_set():
                            break
                        time.sleep(min(0.05, end - time.time()))
                    if self._stop_event.is_set():
                        break

                if on_before_step:
                    try:
                        on_before_step(index, step)
                    except Exception:
                        pass

                next_step = steps[index + 1] if index + 1 < len(steps) else None
                try:
                    self._execute_step(
                        step,
                        next_step=next_step,
                        first_click_pending=first_click_pending,
                        run_on_main=run_on_main,
                    )
                except Exception as exc:
                    step_errors.append((index, exc))
                    if on_step_error:
                        on_step_error(index, step, exc)
                    elif on_error:
                        on_error(exc)
                        return
                    continue

                if step.get("type") in ("click", "double_click") and first_click_pending:
                    first_click_pending = False

                if on_step:
                    try:
                        on_step(index, step)
                    except Exception:
                        pass

            if on_done and not self._stop_event.is_set():
                on_done(step_errors)
        except Exception as exc:
            if on_error:
                on_error(exc)
            else:
                raise
        finally:
            if listener is not None:
                listener.stop()
            clear_playback_offset()
            set_hide_cursor(False)

    def _should_wait_for_load(self, step: dict, next_step: Optional[dict]) -> bool:
        """仅在可能触发页面跳转的步骤后等待加载完成。"""
        if not self._wait_load_after_click:
            return False
        step_type = step.get("type")
        if step_type == "wait_load":
            return True
        if step_type == "key" and str(step.get("key", "")).lower() in ("enter", "return"):
            return True
        if step_type in ("click", "double_click"):
            if next_step is None:
                return True
            return float(next_step.get("delay", 0)) >= self.LOAD_WAIT_MIN_NEXT_DELAY
        return False

    def _execute_step(
        self,
        step: dict,
        *,
        next_step: Optional[dict] = None,
        first_click_pending: bool = False,
        run_on_main: Optional[RunOnMain] = None,
    ) -> None:
        """执行单步操作。Windows 上鼠标/键盘必须在主线程注入。"""

        def run() -> None:
            self._execute_step_impl(
                step,
                next_step=next_step,
                first_click_pending=first_click_pending,
            )

        if run_on_main and sys.platform in ("win32", "darwin"):
            run_on_main(run)
        else:
            run()

    def _wait_for_page_load(self, step: dict) -> None:
        """检测屏幕区域稳定后再继续（网页/Safari 加载完成）。"""
        region = region_from_step(step)
        timeout = float(step.get("timeout", self.LOAD_WAIT_TIMEOUT))

        def report(msg: str) -> None:
            if self._on_wait_load:
                self._on_wait_load(msg)

        report("Waiting for page to finish loading…")
        wait_for_screen_stable(
            region,
            timeout=timeout,
            stable_for=self.LOAD_WAIT_STABLE,
            stop_event=self._stop_event,
            on_progress=report,
        )

    def _execute_step_impl(
        self,
        step: dict,
        *,
        next_step: Optional[dict] = None,
        first_click_pending: bool = False,
    ) -> None:
        """实际执行单步（应在 Windows 主线程调用）。"""
        step_type = step.get("type")

        if step_type == "click":
            if first_click_pending:
                time.sleep(self.FIRST_CLICK_EXTRA_DELAY)
            x, y = resolve_click_point(step)
            mac_desktop = sys.platform == "darwin"
            _perform_click(
                x,
                y,
                step.get("button", "left"),
                settle=first_click_pending or mac_desktop,
                retry=3 if first_click_pending else (2 if mac_desktop else 1),
            )
            time.sleep(0.02)
            if self._should_wait_for_load(step, next_step):
                self._wait_for_page_load(step)

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
            time.sleep(0.02)
            if self._should_wait_for_load(step, next_step):
                self._wait_for_page_load(step)

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
            time.sleep(0.02)

        elif step_type == "scroll_pan":
            x1, y1, x2, y2 = resolve_drag_points(step)
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            duration = min(0.6, max(0.2, dist / 700))
            _perform_scroll_pan(x1, y1, x2, y2, duration=duration)
            time.sleep(0.02)

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
            time.sleep(0.02)

        elif step_type == "type":
            _type_text(step.get("text", ""))

        elif step_type == "key":
            _perform_key(step.get("key", ""))
            if self._should_wait_for_load(step, next_step):
                self._wait_for_page_load(step)

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

        elif step_type == "wait_load":
            self._wait_for_page_load(step)

        else:
            raise ValueError(f"Unknown step type: {step_type}")
