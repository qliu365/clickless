"""
录制模块 - 监听鼠标点击和键盘输入，生成可回放的步骤列表。
"""

import sys
import threading
import time
from typing import Callable, List, Optional

from pynput import keyboard, mouse

if sys.platform == "darwin":
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

    _SPECIAL_KEYS = {
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
        self._last_event_time = time.time()
        self._recording = True

        _patch_pynput_macos_keyboard()

        self._mouse_listener = mouse.Listener(on_click=self._on_click)
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
        if self._use_field_sync:
            self._flush_pending_field_text()
        else:
            self._flush_text_buffer()

        self._recording = False

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

    def _reset_field_tracking(self) -> None:
        """点击后重置输入框跟踪，下一段输入重新建立基准。"""
        self._field_baseline = None
        self._baseline_initialized = False
        self._had_keyboard_since_reset = False

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        """鼠标点击：只记录按下瞬间。"""
        if not self._recording or not pressed:
            return

        if self._should_record_click and not self._should_record_click(x, y):
            return

        self._cancel_field_sync_timer()
        if self._use_field_sync:
            self._flush_pending_field_text()
        else:
            self._flush_text_buffer()

        self._reset_field_tracking()

        step = {
            "type": "click",
            "x": int(round(x)),
            "y": int(round(y)),
            "button": button.name,  # left / right / middle
            "delay": self._calc_delay(),
        }
        self._append_step(step)

        if self._use_field_sync:
            # 点击后焦点切换，稍后再抓取输入框基准文本
            self._schedule_field_sync(delay=0.2)

    def _on_key_press(self, key) -> None:
        """键盘按下：普通字符进缓冲，功能键/组合键单独成步。"""
        if not self._recording:
            return

        key_name = self._key_to_name(key)

        # 修饰键：记录按下状态
        if key_name in self._MODIFIER_NAMES:
            self._modifiers.add(key_name)
            return

        # 组合键（Command+C / Ctrl+V 等）
        if self._modifiers:
            self._cancel_field_sync_timer()
            if self._use_field_sync:
                self._flush_pending_field_text()
            else:
                self._flush_text_buffer()
            keys = self._normalize_hotkey_keys(list(self._modifiers), key_name)
            step = {
                "type": "hotkey",
                "keys": keys,
                "delay": self._calc_delay(),
            }
            self._append_step(step)
            return

        if self._use_field_sync:
            # 功能键：先同步 IME 未上屏文字，再记录按键
            if key_name in self._SPECIAL_KEYS:
                self._cancel_field_sync_timer()
                self._flush_pending_field_text()
                step = {
                    "type": "key",
                    "key": key_name,
                    "delay": self._calc_delay(),
                }
                self._append_step(step)
                self._schedule_field_sync(delay=0.1)
            elif key_name == "space":
                # 空格常用来选 IME 候选，不在按下时记为 space 键
                pass
            elif key_name == "backspace":
                # 删除由输入框 diff 在 release 后捕获
                pass
            else:
                # 拼音字母等：等 IME 上屏后再读输入框
                pass
            return

        # --- 非 macOS：按键级录制 ---
        if key_name == "backspace":
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            else:
                self._flush_text_buffer()
                step = {"type": "key", "key": "backspace", "delay": self._calc_delay()}
                self._append_step(step)
            return

        if hasattr(key, "char") and key.char is not None:
            self._text_buffer += key.char
            return

        if key_name is None:
            return

        self._flush_text_buffer()
        step = {
            "type": "key",
            "key": key_name,
            "delay": self._calc_delay(),
        }
        self._append_step(step)

    def _on_key_release(self, key) -> None:
        """修饰键释放时更新状态；macOS 上按键释放后同步输入框文本。"""
        key_name = self._key_to_name(key)
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

    @staticmethod
    def _key_to_name(key) -> Optional[str]:
        """把 pynput 按键转为字符串，便于 JSON 存储。"""
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
            return key.name if hasattr(key, "name") else str(key)
        except AttributeError:
            return None
