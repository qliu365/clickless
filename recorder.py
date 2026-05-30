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
from text_sanitize import sanitize_typed_text

if sys.platform == "darwin":
    from frontmost_app import is_browser_like_frontmost, is_office_like_frontmost
    from mouse_poll import MacMousePoller
    from scroll_capture import MacInputListener
    from text_capture import get_focused_text_value
else:

    def is_office_like_frontmost() -> bool:  # type: ignore[misc]
        return False

    def is_browser_like_frontmost() -> bool:  # type: ignore[misc]
        return False


def _input_context_tag() -> Optional[str]:
    if is_office_like_frontmost():
        return "office"
    if is_browser_like_frontmost():
        return "browser"
    return None


def _tag_input_context(step: dict) -> dict:
    ctx = _input_context_tag()
    if ctx:
        step["ctx"] = ctx
    return step


def _patch_pynput_macos_keyboard() -> None:
    """macOS 15+ 上 pynput 键盘监听线程会触发 TSM 崩溃，跳过无用的 context 初始化。"""
    if sys.platform != "darwin":
        return

    from pynput._util.darwin import ListenerMixin
    from pynput.keyboard._darwin import Listener as DarwinKeyboardListener

    if getattr(DarwinKeyboardListener, "_officelego_patched", False):
        return

    def _run_without_keycode_context(self) -> None:
        ListenerMixin._run(self)

    DarwinKeyboardListener._run = _run_without_keycode_context
    DarwinKeyboardListener._officelego_patched = True


class Recorder:
    """录制鼠标/键盘操作，输出 JSON 兼容的步骤列表。"""

    def __init__(
        self,
        on_step: Optional[Callable[[dict], None]] = None,
        should_record_click: Optional[Callable[[int, int], bool]] = None,
        on_f2: Optional[Callable[[], None]] = None,
        on_escape: Optional[Callable[[], None]] = None,
        on_click_press: Optional[Callable[[int, int], Optional[str]]] = None,
        on_click_complete: Optional[
            Callable[[str, dict, int, int, int, int], None]
        ] = None,
    ) -> None:
        """
        Args:
            on_step: 每录到一步时的回调（可选，用于界面实时更新）
            should_record_click: 返回 False 则忽略该次点击（如点在 OfficeLego 窗口上）
            on_f2: 按下 F2 时回调（插入积木，不录该键）
            on_escape: 按下 Esc 时回调（停止录制，不录该键）
            on_click_press: 鼠标按下时（返回 capture_id 供 on_click_complete 使用）
            on_click_complete: 点击步骤写入后 (capture_id, step, x1, y1, x2, y2)
        """
        self._steps: List[dict] = []
        self._on_step = on_step
        self._should_record_click = should_record_click
        self._on_f2 = on_f2
        self._on_escape = on_escape
        self._on_click_press = on_click_press
        self._on_click_complete = on_click_complete
        self._pending_capture_id: Optional[str] = None
        self._recording = False
        self._paused = False
        self._paused_at: Optional[float] = None
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
        self._pending_capture_id = None
        self._press_lock = threading.Lock()
        self._last_pynput_edge: Optional[tuple] = None
        self._last_scroll_merge_time: float = 0.0
        self._mac_input_listener: Optional["MacInputListener"] = None
        self._mac_mouse_poller: Optional["MacMousePoller"] = None

    _DRAG_THRESHOLD = 8
    _CLICK_MAX_NUDGE = 28
    _PYNPUT_EDGE_SEC = 0.12

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

    @property
    def is_paused(self) -> bool:
        return self._paused

    def replace_steps(self, steps: List[dict]) -> None:
        """暂停编辑步骤列表时，同步回录制器。"""
        if not self._recording:
            return
        self._steps = [dict(s) for s in steps]

    def _capturing(self) -> bool:
        """正在录制且未暂停时才写入步骤。"""
        return self._recording and not self._paused

    def pause(self) -> None:
        """暂停录制：不记录鼠标/键盘，暂停时长不计入下一步 delay。"""
        if not self._recording or self._paused:
            return
        self._cancel_field_sync_timer()
        self._flush_all_pending_text()
        self._pending_press = None
        self._paused = True
        self._paused_at = time.time()

    def resume(self) -> None:
        """继续录制：下一步 delay 从恢复时刻重新计算。"""
        if not self._recording or not self._paused:
            return
        self._paused = False
        self._paused_at = None
        self._last_event_time = time.time()

    def insert_block(self, name: str) -> None:
        """插入积木步骤 {"type": "block", "name": ...}。"""
        if not self._recording:
            return
        name = name.strip()
        if not name:
            return
        self._cancel_field_sync_timer()
        self._flush_all_pending_text()
        delay = self._delay_for_manual_step()
        step = {"type": "block", "name": name, "delay": delay}
        self._last_event_time = time.time()
        self._append_step(step)

    def insert_loop_mark(self, count: int, address: str) -> None:
        """插入循环区域标记（拖选 Excel 格子后）。"""
        if not self._recording:
            return
        count = max(1, min(int(count), 10000))
        address = address.strip()
        if not address:
            return
        self._cancel_field_sync_timer()
        self._flush_all_pending_text()
        delay = self._delay_for_manual_step()
        step = {
            "type": "loop_mark",
            "count": count,
            "range": address,
            "delay": delay,
        }
        self._last_event_time = time.time()
        self._append_step(step)

    def _append_or_extend_select(self, direction: str) -> None:
        """Shift+方向键扩展选区，合并同方向连续按键。"""
        if (
            self._steps
            and self._steps[-1].get("type") == "select"
            and self._steps[-1].get("direction") == direction
        ):
            last = dict(self._steps[-1])
            last["count"] = int(last.get("count", 1)) + 1
            self._steps[-1] = last
            if self._on_step:
                self._on_step(last)
            return
        self._append_step(
            _tag_input_context(
                {
                    "type": "select",
                    "direction": direction,
                    "count": 1,
                    "delay": self._calc_delay(),
                }
            )
        )

    def _delay_for_manual_step(self) -> float:
        """手动插入步骤的 delay（暂停期间不计入等待时间）。"""
        if self._last_event_time is None:
            return 0.0
        end = self._paused_at if self._paused and self._paused_at else time.time()
        return round(max(0.0, end - self._last_event_time), 3)

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
        self._last_pynput_edge = None
        self._last_scroll_merge_time = 0.0
        self._last_event_time = time.time()
        self._paused = False
        self._paused_at = None
        self._recording = True

        _patch_pynput_macos_keyboard()

        if sys.platform == "darwin":
            self._mac_input_listener = MacInputListener(on_scroll=self._on_scroll)
            self._mac_input_listener.start()
            self._mac_mouse_poller = MacMousePoller(self._on_polled_click)
            self._mac_mouse_poller.start()
            self._mouse_listener = mouse.Listener(on_click=self._on_pynput_click)
        else:
            self._mac_input_listener = None
            self._mac_mouse_poller = None
            self._mouse_listener = mouse.Listener(
                on_click=self._on_pynput_click,
                on_scroll=self._on_scroll,
            )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        if self._mouse_listener:
            self._mouse_listener.start()
        self._keyboard_listener.start()

    def _stop_listeners(self) -> None:
        if self._mac_mouse_poller:
            self._mac_mouse_poller.stop()
            self._mac_mouse_poller = None

        if self._mac_input_listener:
            self._mac_input_listener.stop()
            self._mac_input_listener = None

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None
        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

    def _on_polled_click(
        self, x: int, y: int, button_name: str, pressed: bool
    ) -> None:
        btn = {
            "left": mouse.Button.left,
            "right": mouse.Button.right,
            "middle": mouse.Button.middle,
        }.get(button_name, mouse.Button.left)
        self._on_handle_mouse_click(x, y, btn, pressed, from_poll=True)

    def _on_pynput_click(
        self, x, y, button, pressed, injected=False
    ) -> None:
        """pynput 要求回调恰好 5 个参数 (x, y, button, pressed, injected)。"""
        if injected:
            return
        # WPS/Excel 等 Office 应用：pynput 常产生幽灵事件，与 HID 轮询冲突，只信轮询。
        if sys.platform == "darwin" and is_office_like_frontmost():
            return
        self._on_handle_mouse_click(x, y, button, pressed, from_poll=False)

    def _mark_pynput_edge(self, x: int, y: int, pressed: bool) -> None:
        self._last_pynput_edge = (time.time(), x, y, pressed)

    def _polled_edge_redundant(self, x: int, y: int, pressed: bool) -> bool:
        # Office 前台只走 HID 轮询，不做 pynput 去重。
        if sys.platform == "darwin" and is_office_like_frontmost():
            return False
        last = self._last_pynput_edge
        if not last:
            return False
        t, lx, ly, lp = last
        return (
            lp == pressed
            and abs(x - lx) <= 4
            and abs(y - ly) <= 4
            and (time.time() - t) < self._PYNPUT_EDGE_SEC
        )

    def stop(self) -> List[dict]:
        """停止录制，刷新未提交的文本缓冲。"""
        if not self._recording:
            return self.steps

        self._cancel_field_sync_timer()
        self._flush_all_pending_text()

        self._recording = False
        self._paused = False
        self._paused_at = None

        self._stop_listeners()

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

    def _field_sync_active(self) -> bool:
        """文档/浏览器里不做 AX 读焦点；浏览器/Safari 片段误读，只用按键缓冲。"""
        if not self._use_field_sync:
            return False
        if sys.platform == "darwin" and is_office_like_frontmost():
            return False
        if sys.platform == "darwin" and is_browser_like_frontmost():
            return False
        return True

    def _flush_before_pointer_step(self) -> None:
        """点击/拖拽前：WPS 只刷按键缓冲，浏览器才走 AX 文本同步。"""
        if self._field_sync_active() and (
            self._text_buffer or self._had_keyboard_since_reset
        ):
            self._flush_all_pending_text()
        else:
            self._flush_text_buffer()

    def _record_click_step(self, x: int, y: int, btn: str) -> None:
        step = {
            "type": "click",
            "button": btn,
            "delay": self._calc_delay(),
        }
        attach_window_offset(step, x, y)
        self._append_step(step)

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

    _JUNK_TYPED_TEXT = frozenset(
        {
            "skip to content",
            "skip to main content",
        }
    )

    def _append_type_text(self, text: str) -> None:
        """追加文字输入步骤（同一段连续输入合并为一步）。"""
        if not text:
            return
        text = sanitize_typed_text(text)
        if not text:
            return
        if text.strip().lower() in self._JUNK_TYPED_TEXT:
            return
        low = text.strip().lower()
        if "do you want to save" in low or "save the changes" in low:
            return
        # Safari 自动完成后缀残留的单字符，不是用户输入
        if len(text) == 1 and not self._text_buffer:
            return
        if self._steps and self._steps[-1].get("type") == "type":
            self._steps[-1]["text"] += text
            return
        step = _tag_input_context(
            {
                "type": "type",
                "text": text,
                "delay": self._calc_delay(),
            }
        )
        self._append_step(step)

    def _is_spurious_ax_text(self, text: str) -> bool:
        """辅助功能误读（WPS 页码 0、Safari 片段等），不是用户按键输入。"""
        if not text or self._text_buffer:
            return False
        # 单个数字：多为 WPS/Office 界面 AX 读到的页码，不是用户打的
        if len(text) == 1 and text.isdigit():
            return True
        return False

    def _apply_field_diff(self, old_text: str, new_text: str) -> None:
        """根据输入框文本差异生成步骤，保持与操作顺序一致。"""
        if new_text == old_text:
            return

        if new_text.startswith(old_text):
            added = new_text[len(old_text) :]
            if self._is_spurious_ax_text(added):
                return
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
            if self._is_spurious_ax_text(new_text):
                return
            self._append_type_text(new_text)

    def _trust_field_read(self, new_text: Optional[str]) -> bool:
        """
        Safari 地址栏等纯英文场景：辅助功能常只读到片段（如 ypy），
        此时应信任按键缓冲（shopyfy）而不是 AX 文本。
        """
        if new_text is None:
            return False
        if not self._text_buffer:
            return True
        if not all(ord(c) < 128 for c in self._text_buffer):
            return True
        cleaned = sanitize_typed_text(new_text)
        if not cleaned:
            return False
        if all(ord(c) < 128 for c in cleaned):
            return len(cleaned) >= len(self._text_buffer)
        return True

    def _flush_all_pending_text(self) -> None:
        """提交未保存的文字：优先读输入框（中文 IME），否则用按键缓冲。"""
        steps_before = len(self._steps)
        if self._field_sync_active():
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
        if not self._field_sync_active():
            return

        new_text = get_focused_text_value()
        if new_text is None:
            return

        new_text = sanitize_typed_text(new_text)
        if not self._trust_field_read(new_text):
            return

        if self._field_baseline is not None:
            self._field_baseline = sanitize_typed_text(self._field_baseline)

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
        if not self._field_sync_active() or not self._capturing():
            return

        def _run() -> None:
            with self._sync_lock:
                if self._capturing():
                    self._sync_text_from_focused_field()

        self._cancel_field_sync_timer()
        self._sync_timer = threading.Timer(delay, _run)
        self._sync_timer.daemon = True
        self._sync_timer.start()

    def _sync_text_from_focused_field(self) -> None:
        """对比焦点输入框文本变化，记录新增/删除的文字。"""
        if not self._field_sync_active():
            return

        new_text = get_focused_text_value()
        if new_text is None:
            return

        new_text = sanitize_typed_text(new_text)
        if not self._trust_field_read(new_text):
            return

        if self._field_baseline is not None:
            self._field_baseline = sanitize_typed_text(self._field_baseline)

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

    def _on_handle_mouse_click(
        self,
        x: int,
        y: int,
        button: mouse.Button,
        pressed: bool,
        *,
        from_poll: bool,
    ) -> None:
        """鼠标按下/抬起：区分点击与拖拽。"""
        if not self._capturing():
            return

        ix, iy = int(round(x)), int(round(y))
        if from_poll:
            if self._polled_edge_redundant(ix, iy, pressed):
                return
        else:
            self._mark_pynput_edge(ix, iy, pressed)

        if pressed:
            ignored = (
                self._should_record_click is not None
                and not self._should_record_click(ix, iy)
            )
            capture_id = None
            if not ignored and self._on_click_press:
                try:
                    capture_id = self._on_click_press(ix, iy)
                except Exception:
                    capture_id = None
            with self._press_lock:
                self._pending_press = "ignored" if ignored else (ix, iy, button.name)
                self._pending_capture_id = capture_id
            return

        ignored = False
        orphaned_release = False
        with self._press_lock:
            if self._pending_press in (None, "ignored"):
                ignored = self._pending_press == "ignored"
                orphaned_release = self._pending_press is None
                self._pending_press = None
            else:
                x1, y1, btn = self._pending_press
                self._pending_press = None

        if ignored:
            self._pending_capture_id = None
            return
        if orphaned_release:
            self._pending_capture_id = None
            return

        x2, y2 = ix, iy

        self._cancel_field_sync_timer()
        self._flush_before_pointer_step()

        self._reset_field_tracking()

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        dist = (dx * dx + dy * dy) ** 0.5
        if dist >= self._DRAG_THRESHOLD:
            if btn != "middle" and dist <= self._CLICK_MAX_NUDGE:
                self._record_click_step(x1, y1, btn)
            elif btn == "middle":
                step = {
                    "type": "scroll_pan",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "delay": self._calc_delay(),
                }
                attach_drag_window_offset(step, x1, y1, x2, y2)
                self._append_step(step)
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
            self._record_click_step(x1, y1, btn)
            capture_id = self._pending_capture_id
            self._pending_capture_id = None
            if (
                capture_id
                and self._on_click_complete
                and self._steps
                and self._steps[-1].get("type") == "click"
            ):
                try:
                    self._on_click_complete(
                        capture_id, self._steps[-1], x1, y1, x2, y2
                    )
                except Exception:
                    pass

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
        if not self._capturing():
            return

        ix, iy = int(round(x)), int(round(y))
        dx_f, dy_f = float(dx), float(dy)
        if dx_f == 0 and dy_f == 0:
            return

        if self._should_record_click and not self._should_record_click(ix, iy):
            return

        self._cancel_field_sync_timer()
        self._flush_before_pointer_step()

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

        if key_name == "f2" and self._on_f2:
            self._on_f2()
            return

        if key_name in ("esc", "escape") and self._on_escape:
            self._on_escape()
            return

        if not self._capturing():
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
                self._append_step(
                    _tag_input_context(
                        {"type": "copy", "delay": self._calc_delay()}
                    )
                )
            elif action == "paste":
                self._append_step(
                    _tag_input_context(
                        {"type": "paste", "delay": self._calc_delay()}
                    )
                )
            elif (
                set(keys) == {"shift", key_name}
                and key_name in ("up", "down", "left", "right")
            ):
                self._append_or_extend_select(key_name)
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
            if self._field_sync_active():
                self._schedule_field_sync(delay=0.12)
            return

        if self._is_typeable_char(key, key_name):
            self._text_buffer += key_name
            self._had_keyboard_since_reset = True
            if self._field_sync_active():
                self._schedule_field_sync(delay=0.18)
            return

        if key_name == "space":
            self._text_buffer += " "
            self._had_keyboard_since_reset = True
            if self._field_sync_active():
                self._schedule_field_sync(delay=0.18)
            return

        # Enter / 方向键 / Tab 等功能键
        self._cancel_field_sync_timer()
        self._flush_all_pending_text()
        self._append_step(
            _tag_input_context(
                {"type": "key", "key": key_name, "delay": self._calc_delay()}
            )
        )
        if self._field_sync_active():
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

        if self._capturing() and self._field_sync_active() and not self._modifiers:
            if self._had_keyboard_since_reset or self._text_buffer:
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

