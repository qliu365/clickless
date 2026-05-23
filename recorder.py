"""
录制模块 - 监听鼠标点击和键盘输入，生成可回放的步骤列表。
"""

import sys
import threading
import time
from typing import Callable, List, Optional

from pynput import keyboard, mouse

from window_bounds import attach_drag_window_offset, attach_window_offset

from keyboard_shortcuts import clipboard_action_for_hotkey

if sys.platform == "darwin":
    from scroll_capture import MacScrollListener
    from text_capture import get_focused_text_value


def _patch_pynput_macos_keyboard() -> None:
    """macOS 15+ 上 pynput 键盘监听线程会触发 TSM 崩溃，跳过无用的 context 初始化。"""
    if sys.platform != "darwin":
        return

    from pynput._util.darwin import ListenerMixin
    from pynput.keyboard._darwin import Listener as DarwinKeyboardListener

    if getattr(DarwinKeyboardListener, "_clickless_patched", False):
        return

    def _run_without_keycode_context(self) -> None:
        ListenerMixin._run(self)

    DarwinKeyboardListener._run = _run_without_keycode_context
    DarwinKeyboardListener._clickless_patched = True


class Recorder:
    """录制鼠标/键盘操作，输出 JSON 兼容的步骤列表。"""

    def __init__(
        self,
        on_step: Optional[Callable[[dict], None]] = None,
        should_record_click: Optional[Callable[[int, int], bool]] = None,
    ) -> None:
        """
        Args:
            on_step: 每录到一步时的回调（可选，用于界面实时更新）
            should_record_click: 返回 False 则忽略该次点击（如点在 Clickless 窗口上）
        """
        self._steps: List[dict] = []
        self._on_step = on_step
        self._should_record_click = should_record_click
        self._recording = False
        self._last_event_time: Optional[float] = None
        self._text_buffer = ""
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._modifiers: set = set()
        # macOS 中文 IME：跟踪焦点输入框文本
        self._use_field_sync = sys.platform == "darwin"
        self._field_baseline: Optional[str] = None
        self._baseline_initialized = False
        self._had_keyboard_since_reset = False
        self._sync_timer: Optional[threading.Timer] = None
        self._sync_lock = threading.Lock()
        self._pending_press: Optional[object] = None  # (x,y,button) | "ignored"
        self._last_scroll_merge_time: float = 0.0
        self._mac_scroll_listener: Optional["MacScrollListener"] = None

    _DRAG_THRESHOLD = 8  # 移动超过此像素数视为拖拽

    _MODIFIER_NAMES = {
        "cmd",
        "cmd_l",
        "cmd_r",
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "alt",
        "alt_l",
        "alt_r",
        "alt_gr",
        "shift",
        "shift_l",
        "shift_r",
    }

    _SPECIAL_KEYS = frozenset(
        {
            "enter",
            "return",
            "tab",
            "esc",
            "escape",
            "up",
            "down",
            "left",
            "right",
            "home",
            "end",
            "page_up",
            "page_down",
            "delete",
            "insert",
            "f1",
            "f2",
            "f3",
            "f4",
            "f5",
            "f6",
            "f7",
            "f8",
            "f9",
            "f10",
            "f11",
            "f12",
        }
    )

    _KEY_ALIASES = {
        "return": "enter",
        "escape": "esc",
    }

    @property
    def steps(self) -> List[dict]:
        """返回已录制的步骤（副本）。"""
        return list(self._steps)

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        """开始录制。"""
        if self._recording:
            return

        self._steps.clear()
        self._text_buffer = ""
        self._modifiers.clear()
        self._field_baseline = None
        self._baseline_initialized = False
        self._had_keyboard_since_reset = False
        self._pending_press = None
        self._last_scroll_merge_time = 0.0
        self._last_event_time = time.time()
        self._recording = True

        _patch_pynput_macos_keyboard()

        if sys.platform == "darwin":
            self._mac_scroll_listener = MacScrollListener(self._on_scroll)
            self._mac_scroll_listener.start()
            self._mouse_listener = mouse.Listener(on_click=self._on_click)
        else:
            self._mac_scroll_listener = None
            self._mouse_listener = mouse.Listener(
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> List[dict]:
        """停止录制，刷新未提交的文本缓冲。"""
        if not self._recording:
            return self.steps

        self._cancel_field_sync_timer()
        self._flush_all_pending_text()

        self._recording = False

        if self._mac_scroll_listener:
            self._mac_scroll_listener.stop()
            self._mac_scroll_listener = None

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        return self.steps

    def clear(self) -> None:
        """清空已录制的步骤。"""
        self._steps.clear()
        self._text_buffer = ""
        self._field_baseline = None
        self._baseline_initialized = False
        self._had_keyboard_since_reset = False
        self._pending_press = None
        self._last_event_time = None

    def _calc_delay(self) -> float:
        """计算距上一步的时间间隔（秒）。"""
        now = time.time()
        if self._last_event_time is None:
            delay = 0.0
        else:
            delay = round(now - self._last_event_time, 3)
        self._last_event_time = now
        return delay

    def _append_step(self, step: dict) -> None:
        """追加一步并触发回调。"""
        self._steps.append(step)
        if self._on_step:
            self._on_step(step)

    def _append_type_text(self, text: str) -> None:
        """追加文字输入步骤（同一段连续输入合并为一步）。"""
        if not text:
            return
        if self._steps and self._steps[-1].get("type") == "type":
            self._steps[-1]["text"] += text
            return
        step = {
            "type": "type",
            "text": text,
            "delay": self._calc_delay(),
        }
        self._append_step(step)

    def _apply_field_diff(self, old_text: str, new_text: str) -> None:
        """根据输入框文本差异生成步骤，保持与操作顺序一致。"""
        if new_text == old_text:
            return

        if new_text.startswith(old_text):
            added = new_text[len(old_text) :]
            self._append_type_text(added)
            return

        if old_text.startswith(new_text):
            removed = len(old_text) - len(new_text)
            for _ in range(removed):
                step = {
                    "type": "key",
                    "key": "backspace",
                    "delay": self._calc_delay(),
                }
                self._append_step(step)
            return

        for _ in range(len(old_text)):
            step = {
                "type": "key",
                "key": "backspace",
                "delay": self._calc_delay(),
            }
            self._append_step(step)
        if new_text:
            self._append_type_text(new_text)

    def _flush_all_pending_text(self) -> None:
        """提交未保存的文字：优先读输入框（中文 IME），否则用按键缓冲。"""
        steps_before = len(self._steps)
        if self._use_field_sync:
            self._flush_pending_field_text()
        if len(self._steps) == steps_before:
            self._flush_text_buffer()
        else:
            self._text_buffer = ""

    def _flush_pending_field_text(self) -> None:
        """
        立刻把未写入步骤的输入提交（点击/功能键前调用）。
        确保「先输入再点击」的顺序不会被打乱。
        """
        if not self._use_field_sync:
            return

        new_text = get_focused_text_value()
        if new_text is None:
            return

        if not self._baseline_initialized:
            if not self._had_keyboard_since_reset:
                return
            old_text = ""
        else:
            old_text = self._field_baseline or ""

        if new_text != old_text:
            self._apply_field_diff(old_text, new_text)
            self._text_buffer = ""
        self._field_baseline = new_text
        self._baseline_initialized = True

    def _flush_text_buffer(self) -> None:
        """把缓冲中的文字写入一步（非 macOS 或 AX 不可用时的兜底）。"""
        if not self._text_buffer:
            return
        self._append_type_text(self._text_buffer)
        self._text_buffer = ""

    def _cancel_field_sync_timer(self) -> None:
        if self._sync_timer:
            self._sync_timer.cancel()
            self._sync_timer = None

    def _schedule_field_sync(self, delay: float = 0.15) -> None:
        """IME 上屏有延迟，防抖后再读输入框文本。"""
        if not self._use_field_sync or not self._recording:
            return

        def _run() -> None:
            with self._sync_lock:
                if self._recording:
                    self._sync_text_from_focused_field()

        self._cancel_field_sync_timer()
        self._sync_timer = threading.Timer(delay, _run)
        self._sync_timer.daemon = True
        self._sync_timer.start()

    def _sync_text_from_focused_field(self) -> None:
        """对比焦点输入框文本变化，记录新增/删除的文字。"""
        if not self._use_field_sync:
            return

        new_text = get_focused_text_value()
        if new_text is None:
            return

        if not self._baseline_initialized:
            self._field_baseline = new_text
            self._baseline_initialized = True
            return

        old_text = self._field_baseline or ""
        if new_text == old_text:
            return

        self._apply_field_diff(old_text, new_text)
        self._field_baseline = new_text
        # 输入框已读到文字，清掉按键缓冲避免重复
        self._text_buffer = ""

    def _reset_field_tracking(self) -> None:
        """点击后重置输入框跟踪，下一段输入重新建立基准。"""
        self._field_baseline = None
        self._baseline_initialized = False
        self._had_keyboard_since_reset = False

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        """鼠标按下/抬起：区分点击与拖拽。"""
        if not self._recording:
            return

        ix, iy = int(round(x)), int(round(y))

        if pressed:
            if self._should_record_click and not self._should_record_click(ix, iy):
                self._pending_press = "ignored"
            else:
                self._pending_press = (ix, iy, button.name)
            return

        if self._pending_press in (None, "ignored"):
            self._pending_press = None
            return

        x1, y1, btn = self._pending_press
        self._pending_press = None
        x2, y2 = ix, iy

        self._cancel_field_sync_timer()
        self._flush_all_pending_text()

        self._reset_field_tracking()

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx >= self._DRAG_THRESHOLD or dy >= self._DRAG_THRESHOLD:
            if btn == "middle":
                step = {
                    "type": "scroll_pan",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "delay": self._calc_delay(),
                }
            else:
                step = {
                    "type": "drag",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "button": btn,
                    "delay": self._calc_delay(),
                }
                role = self._drag_scroll_role(x1, y1, x2, y2)
                if role:
                    step["role"] = role
            attach_drag_window_offset(step, x1, y1, x2, y2)
            self._append_step(step)
        else:
            step = {
                "type": "click",
                "button": btn,
                "delay": self._calc_delay(),
            }
            attach_window_offset(step, x1, y1)
            self._append_step(step)

        if self._use_field_sync:
            self._schedule_field_sync(delay=0.2)

    @staticmethod
    def _drag_scroll_role(x1: int, y1: int, x2: int, y2: int) -> Optional[str]:
        """竖向/横向为主的拖拽，视为拖滚动条。"""
        h = abs(x2 - x1)
        v = abs(y2 - y1)
        if v >= 8 and v > h * 1.8:
            return "scrollbar_v"
        if h >= 8 and h > v * 1.8:
            return "scrollbar_h"
        return None

    def _on_scroll(self, x: int, y: int, dx: float, dy: float) -> None:
        """滚轮/触控板滚动。"""
        if not self._recording:
            return

        ix, iy = int(round(x)), int(round(y))
        dx_f, dy_f = float(dx), float(dy)
        if dx_f == 0 and dy_f == 0:
            return

        if self._should_record_click and not self._should_record_click(ix, iy):
            return

        self._cancel_field_sync_timer()
        self._flush_all_pending_text()

        now = time.time()
        if (
            self._steps
            and self._steps[-1].get("type") == "scroll"
            and abs(self._steps[-1].get("x", 0) - ix) < 80
            and abs(self._steps[-1].get("y", 0) - iy) < 80
            and now - self._last_scroll_merge_time < 0.4
        ):
            last = self._steps[-1]
            last["dx"] = last.get("dx", 0) + dx_f
            last["dy"] = last.get("dy", 0) + dy_f
            self._last_scroll_merge_time = now
            if self._on_step:
                self._on_step(last)
            return

        step = {
            "type": "scroll",
            "x": ix,
            "y": iy,
            "dx": dx_f,
            "dy": dy_f,
            "delay": self._calc_delay(),
        }
        self._last_scroll_merge_time = now
        self._append_step(step)

    def _on_key_press(self, key) -> None:
        """组合录制：文字进缓冲，Enter/方向键等功能键单独成步。"""
        if not self._recording:
            return

        key_name = self._normalize_key_name(key)
        if not key_name:
            return

        if key_name in self._MODIFIER_NAMES:
            self._modifiers.add(key_name)
            return

        if self._modifiers:
            self._cancel_field_sync_timer()
            self._flush_all_pending_text()
            keys = self._normalize_hotkey_keys(list(self._modifiers), key_name)
            action = clipboard_action_for_hotkey(keys)
            if action == "copy":
                self._append_step({"type": "copy", "delay": self._calc_delay()})
            elif action == "paste":
                self._append_step({"type": "paste", "delay": self._calc_delay()})
            else:
                self._append_step(
                    {"type": "hotkey", "keys": keys, "delay": self._calc_delay()}
                )
            return

        if key_name == "backspace":
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            else:
                self._cancel_field_sync_timer()
                self._flush_all_pending_text()
                self._append_step(
                    {"type": "key", "key": "backspace", "delay": self._calc_delay()}
                )
            self._had_keyboard_since_reset = True
            if self._use_field_sync:
                self._schedule_field_sync(delay=0.12)
            return

        if self._is_typeable_char(key, key_name):
            self._text_buffer += key_name
            self._had_keyboard_since_reset = True
            if self._use_field_sync:
                self._schedule_field_sync(delay=0.18)
            return

        if key_name == "space":
            self._text_buffer += " "
            self._had_keyboard_since_reset = True
            if self._use_field_sync:
                self._schedule_field_sync(delay=0.18)
            return

        # Enter / 方向键 / Tab 等功能键
        self._cancel_field_sync_timer()
        self._flush_all_pending_text()
        self._append_step(
            {"type": "key", "key": key_name, "delay": self._calc_delay()}
        )
        if self._use_field_sync:
            self._schedule_field_sync(delay=0.1)

    @staticmethod
    def _is_typeable_char(key, key_name: str) -> bool:
        """单个可打印字符（字母、数字、符号）。"""
        if len(key_name) == 1 and key_name.isprintable() and key_name != " ":
            return True
        return hasattr(key, "char") and key.char is not None and len(key.char) == 1

    @classmethod
    def _normalize_key_name(cls, key) -> Optional[str]:
        """统一按键名，便于录制与回放。"""
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
            name = key.name if hasattr(key, "name") else str(key)
            if not name:
                return None
            name = name.lower()
            return cls._KEY_ALIASES.get(name, name)
        except AttributeError:
            return None

    def _on_key_release(self, key) -> None:
        """修饰键释放时更新状态；macOS 上按键释放后同步输入框文本。"""
        key_name = self._normalize_key_name(key)
        if key_name in self._MODIFIER_NAMES:
            self._modifiers.discard(key_name)
            return

        if self._recording and self._use_field_sync and not self._modifiers:
            self._had_keyboard_since_reset = True
            self._schedule_field_sync()

    @staticmethod
    def _normalize_hotkey_keys(modifiers: List[str], main_key: str) -> List[str]:
        """整理组合键顺序，便于回放。"""
        order = [
            "ctrl",
            "ctrl_l",
            "ctrl_r",
            "alt",
            "alt_l",
            "alt_r",
            "shift",
            "shift_l",
            "shift_r",
            "cmd",
            "cmd_l",
            "cmd_r",
        ]
        mods = sorted(modifiers, key=lambda k: order.index(k) if k in order else 99)
        simplified = []
        seen = set()
        alias = {
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "cmd_l": "cmd",
            "cmd_r": "cmd",
            "alt_l": "alt",
            "alt_r": "alt",
            "shift_l": "shift",
            "shift_r": "shift",
        }
        for m in mods:
            s = alias.get(m, m)
            if s not in seen:
                seen.add(s)
                simplified.append(s)
        return simplified + [main_key]

