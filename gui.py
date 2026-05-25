"""
界面模块 - Tkinter 图形界面，串联录制、回放与流程管理。
"""

import sys
import threading
import time
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from click_marker import ClickMarker
from permissions import (
    is_accessibility_granted,
    open_accessibility_settings,
    open_input_monitoring_settings,
    permission_hint,
    request_accessibility_prompt,
)
from player import Player, resolve_calibration_anchor
from recorder import Recorder
from recording_floater import ControlFloater, RecordingFloater
from storage import FlowStorage
from window_bounds import expected_click_point


# 界面配色
COLOR_BG = "#f5f5f5"
COLOR_RED_IDLE = "#e53935"
COLOR_RED_ACTIVE = "#b71c1c"
COLOR_RED_RING = "#c62828"
COLOR_GREEN = "#43a047"
COLOR_GREEN_ACTIVE = "#2e7d32"
COLOR_GRAY = "#9e9e9e"
COLOR_GRAY_ACTIVE = "#757575"
COLOR_TEXT = "#333333"
COLOR_MUTED = "#666666"


class ClicklessApp:
    """Clickless 主窗口。"""

    def __init__(self, flows_dir: Path) -> None:
        self.flows_dir = flows_dir
        self.storage = FlowStorage(flows_dir)
        self.player = Player()
        self.recorder: Optional[Recorder] = None
        self._recording = False
        self._controls_locked = False

        self.root = tk.Tk()
        self.root.title("Clickless Automation")
        self.root.geometry("680x620")
        self.root.minsize(560, 520)
        self.root.configure(bg=COLOR_BG)

        self._status_var = tk.StringVar(value="Ready — click the red button to start recording")
        self._flow_name_var = tk.StringVar()
        self._record_hint_var = tk.StringVar(value="Click to record")
        self._wait_load_var = tk.BooleanVar(value=False)
        self._playback_speed_var = tk.StringVar(value="1x")
        self._hide_mouse_var = tk.BooleanVar(value=False)
        self._current_steps: List[dict] = []

        self._click_marker = ClickMarker(self.root)
        self._control_floater = RecordingFloater(self.root, self._on_floater_stop)
        self._floater_mode: Optional[str] = None  # "record" | "play"
        self._main_thread_queue: queue.Queue = queue.Queue()
        self._poll_main_thread_queue()

        self._build_ui()
        self._refresh_flow_list()
        self.root.after(500, self._check_permissions_on_startup)

    def _check_permissions_on_startup(self) -> None:
        """启动时检查 macOS 权限。"""
        if sys.platform != "darwin":
            self._set_status("Ready — click the red button to start recording")
            return
        if is_accessibility_granted():
            self._set_status("Ready — click the red button to start recording")
            return
        self._set_status("Missing permissions — mouse/keyboard may not work")
        request_accessibility_prompt()
        messagebox.showwarning("Permissions Required", permission_hint())

    def _ensure_permissions(self) -> bool:
        """录制/回放前确认权限。"""
        if sys.platform != "darwin":
            return True
        if is_accessibility_granted():
            return True

        request_accessibility_prompt()
        if is_accessibility_granted():
            return True

        answer = messagebox.askyesnocancel(
            "Permissions Required",
            permission_hint() + "\n\nYes = Open Accessibility settings\nNo = Open Input Monitoring settings",
        )
        if answer is True:
            open_accessibility_settings()
        elif answer is False:
            open_input_monitoring_settings()
        return False

    def run(self) -> None:
        """启动主循环。"""
        self.root.mainloop()

    def _build_ui(self) -> None:
        """构建界面布局。"""
        # 顶部状态栏
        status_frame = tk.Frame(self.root, bg=COLOR_BG, padx=16, pady=12)
        status_frame.pack(fill=tk.X)
        tk.Label(
            status_frame,
            text="Clickless",
            font=("Helvetica", 18, "bold"),
            fg=COLOR_RED_IDLE,
            bg=COLOR_BG,
        ).pack(anchor=tk.W)
        tk.Label(
            status_frame,
            textvariable=self._status_var,
            font=("Helvetica", 12),
            fg=COLOR_TEXT,
            bg=COLOR_BG,
            wraplength=620,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        # 主控制区：红按钮 + 运行/停止
        hero_frame = tk.Frame(self.root, bg=COLOR_BG, padx=16, pady=8)
        hero_frame.pack(fill=tk.X)

        control_row = tk.Frame(hero_frame, bg=COLOR_BG)
        control_row.pack()

        # 红色圆形录制按钮
        record_wrap = tk.Frame(control_row, bg=COLOR_BG)
        record_wrap.pack(side=tk.LEFT, padx=(0, 28))

        self._record_canvas = tk.Canvas(
            record_wrap,
            width=96,
            height=96,
            highlightthickness=0,
            bg=COLOR_BG,
            cursor="hand2",
        )
        self._record_canvas.pack()
        self._record_outer = self._record_canvas.create_oval(
            8, 8, 88, 88, fill=COLOR_RED_IDLE, outline=COLOR_RED_RING, width=3
        )
        self._record_inner = self._record_canvas.create_oval(
            32, 32, 64, 64, fill="white", outline=""
        )
        self._record_canvas.bind("<Button-1>", lambda _e: self._on_red_button_click())
        self._record_canvas.bind("<Enter>", lambda _e: self._on_record_hover(True))
        self._record_canvas.bind("<Leave>", lambda _e: self._on_record_hover(False))

        tk.Label(
            record_wrap,
            textvariable=self._record_hint_var,
            font=("Helvetica", 11, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_BG,
        ).pack(pady=(6, 0))

        # 运行 / 停止回放（用 Canvas 绘制，避免 macOS 上 tk.Button 自定义颜色崩溃）
        action_col = tk.Frame(control_row, bg=COLOR_BG)
        action_col.pack(side=tk.LEFT, pady=12)

        self._btn_run = self._create_canvas_button(
            action_col,
            text="Run",
            fill=COLOR_GREEN,
            active_fill=COLOR_GREEN_ACTIVE,
            command=self._on_run_current,
            width=120,
            height=48,
        )
        self._btn_run.pack(pady=(0, 10))

        self._btn_stop_play = self._create_canvas_button(
            action_col,
            text="Stop",
            fill=COLOR_GRAY,
            active_fill=COLOR_GRAY_ACTIVE,
            command=self._on_stop_playback,
            width=120,
            height=36,
            disabled=True,
        )
        self._btn_stop_play.pack()

        ttk.Checkbutton(
            action_col,
            text="Wait for page load (Safari/web only)",
            variable=self._wait_load_var,
        ).pack(pady=(10, 0))

        speed_row = ttk.Frame(action_col)
        speed_row.pack(pady=(8, 0))
        ttk.Label(speed_row, text="Speed:").pack(side=tk.LEFT)
        self._speed_combo = ttk.Combobox(
            speed_row,
            textvariable=self._playback_speed_var,
            values=("0.5x", "1x", "2x", "3x", "5x"),
            width=5,
            state="readonly",
        )
        self._speed_combo.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Checkbutton(
            action_col,
            text="Hide mouse (Safari only — keep off for WPS/Excel)",
            variable=self._hide_mouse_var,
        ).pack(pady=(8, 0))

        tk.Label(
            hero_frame,
            text="Record: text, Enter, arrows, clicks, scroll, drag; Ctrl/Cmd+C/V = copy/paste.\n"
            "WPS/Excel: turn OFF hide mouse & page-load wait. Speed changes step wait times.",
            font=("Helvetica", 10),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
            wraplength=620,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(12, 0))

        # Current steps preview
        steps_frame = ttk.LabelFrame(self.root, text="Current Steps", padding=10)
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        steps_scroll = ttk.Scrollbar(steps_frame)
        steps_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._steps_list = tk.Listbox(
            steps_frame, height=6, yscrollcommand=steps_scroll.set
        )
        self._steps_list.pack(fill=tk.BOTH, expand=True)
        steps_scroll.config(command=self._steps_list.yview)
        self._steps_list.bind("<<ListboxSelect>>", self._on_step_list_select)

        # Save flow
        save_frame = ttk.LabelFrame(self.root, text="Save Flow", padding=10)
        save_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        save_row = ttk.Frame(save_frame)
        save_row.pack(fill=tk.X)
        ttk.Label(save_row, text="Name:").pack(side=tk.LEFT)
        ttk.Entry(save_row, textvariable=self._flow_name_var, width=30).pack(
            side=tk.LEFT, padx=(4, 8), fill=tk.X, expand=True
        )
        ttk.Button(save_row, text="Save", command=self._on_save).pack(side=tk.LEFT)

        # Saved flows
        flows_frame = ttk.LabelFrame(self.root, text="Saved Flows", padding=10)
        flows_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        flows_scroll = ttk.Scrollbar(flows_frame)
        flows_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._flows_list = tk.Listbox(
            flows_frame, height=5, yscrollcommand=flows_scroll.set
        )
        self._flows_list.pack(fill=tk.BOTH, expand=True)
        self._flows_list.bind("<<ListboxSelect>>", self._on_flow_select)
        self._flows_list.bind("<Double-Button-1>", lambda _e: self._on_run_selected())
        flows_scroll.config(command=self._flows_list.yview)

        flows_btn_row = ttk.Frame(flows_frame)
        flows_btn_row.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(flows_btn_row, text="Run Selected", command=self._on_run_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(flows_btn_row, text="Save & Run", command=self._on_save_and_run).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(flows_btn_row, text="Delete", command=self._on_delete_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(flows_btn_row, text="Refresh", command=self._refresh_flow_list).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    def _create_canvas_button(
        self,
        parent,
        text: str,
        fill: str,
        active_fill: str,
        command,
        width: int = 120,
        height: int = 40,
        disabled: bool = False,
    ) -> tk.Canvas:
        """创建 Canvas 圆角按钮，兼容 macOS Tk。"""
        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bg=COLOR_BG,
            cursor="arrow" if disabled else "hand2",
        )
        rect = canvas.create_rectangle(
            2, 2, width - 2, height - 2, fill=fill, outline="", width=0
        )
        label = canvas.create_text(
            width // 2,
            height // 2,
            text=text,
            fill="white",
            font=("Helvetica", 13, "bold"),
        )
        canvas._btn_state = {
            "disabled": disabled,
            "fill": fill,
            "active_fill": active_fill,
            "command": command,
            "rect": rect,
        }

        def _click(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                command()

        def _enter(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                canvas.itemconfig(rect, fill=active_fill)

        def _leave(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                canvas.itemconfig(rect, fill=fill)

        canvas.bind("<Button-1>", _click)
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        return canvas

    def _set_canvas_button_enabled(self, canvas: tk.Canvas, enabled: bool) -> None:
        """启用/禁用 Canvas 按钮。"""
        state = canvas._btn_state
        state["disabled"] = not enabled
        canvas.config(cursor="hand2" if enabled else "arrow")
        canvas.itemconfig(state["rect"], fill=state["fill"] if enabled else COLOR_GRAY)

    def _point_in_rect(self, x: int, y: int, rect) -> bool:
        """判断点是否在矩形区域内。"""
        if rect is None:
            return False
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _get_app_window_rect(self):
        """主窗口屏幕区域（含边框）。"""
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            return (x, y, x + w, y + h)
        except tk.TclError:
            return None

    def _should_record_click(self, x: int, y: int) -> bool:
        """忽略点在 Clickless 自身 UI 上的点击。"""
        for rect in (self._get_app_window_rect(), self._control_floater.bounds()):
            if self._point_in_rect(x, y, rect):
                return False
        return True

    def _hide_for_playback(self) -> None:
        """回放时隐藏 Clickless，避免窗口挡住目标应用点击。"""
        self._click_marker.close_flashes()
        try:
            self.root.update_idletasks()
            if sys.platform in ("win32", "darwin"):
                # withdraw 会导致后台/主线程鼠标注入失效（Windows + macOS WPS/Excel）
                self._saved_playback_geometry = self.root.geometry()
                self.root.geometry("1x1+-200+-200")
                self.root.lower()
            else:
                self._control_floater.hide()
                self.root.withdraw()
            self.root.update_idletasks()
            self._click_marker.reanchor_host()
        except tk.TclError:
            pass

    def _show_after_playback(self) -> None:
        """回放结束后恢复主窗口。"""
        try:
            if sys.platform in ("win32", "darwin") and getattr(
                self, "_saved_playback_geometry", None
            ):
                self.root.geometry(self._saved_playback_geometry)
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _poll_main_thread_queue(self) -> None:
        """主线程轮询：执行回放线程投递的鼠标/键盘操作。"""
        while True:
            try:
                job = self._main_thread_queue.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception:
                pass
        self.root.after(20, self._poll_main_thread_queue)

    def _run_on_main_thread(self, fn: Callable[[], None], *, timeout: float = 120.0) -> None:
        """回放线程把鼠标/键盘操作切回 Tk 主线程（Windows / macOS 桌面应用必须）。"""
        if threading.current_thread() is threading.main_thread():
            fn()
            return

        done = threading.Event()
        state = {"error": None}

        def job() -> None:
            try:
                fn()
            except Exception as exc:
                state["error"] = exc
            finally:
                done.set()

        self._main_thread_queue.put(job)
        if not done.wait(timeout):
            raise TimeoutError("Playback step timed out")
        if state["error"] is not None:
            raise state["error"]

    def _hide_main_for_recording(self) -> None:
        """录制时把主窗口移到屏幕外，不挡住网页。"""
        try:
            self.root.update_idletasks()
            self._saved_geometry = self.root.geometry()
            self.root.geometry("1x1+-200+-200")
            self.root.lower()
        except tk.TclError:
            pass

    def _restore_main_after_recording(self) -> None:
        """录制结束后恢复主窗口。"""
        try:
            if getattr(self, "_saved_geometry", None):
                self.root.geometry(self._saved_geometry)
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _park_main_window_for_capture(self) -> None:
        """兼容旧调用：录制时等同隐藏主窗口。"""
        self._hide_main_for_recording()

    def _restore_main_window(self) -> None:
        """兼容旧调用。"""
        self._restore_main_after_recording()

    def _show_click_marker_for_step(self, step: dict, color: str, label: str) -> None:
        """对点击步骤显示落点标记。"""
        if step.get("type") != "click":
            return
        self._click_marker.flash(
            step["x"],
            step["y"],
            color=color,
            label=label,
        )

    def _parse_playback_speed(self) -> float:
        """解析界面上的倍速，如 '2x' -> 2.0。"""
        raw = self._playback_speed_var.get().strip().lower().rstrip("x")
        try:
            return max(0.1, float(raw))
        except ValueError:
            return 1.0

    def _get_calibration_anchor_from_selection(
        self, steps: List[dict]
    ) -> Tuple[Optional[Tuple[int, int]], Optional[int]]:
        """若步骤列表选中了点击步骤，用它作为运行前对齐锚点。"""
        selection = self._steps_list.curselection()
        if not selection:
            return None, None
        index = selection[0]
        if index >= len(steps):
            return None, None
        step = steps[index]
        if step.get("type") not in ("click", "double_click"):
            return None, None
        return expected_click_point(step), index

    def _on_step_list_select(self, _event=None) -> None:
        """选中步骤时，在屏幕上预览点击落点。"""
        selection = self._steps_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._current_steps):
            return
        step = self._current_steps[index]
        if step.get("type") == "click":
            self._show_click_marker_for_step(step, COLOR_RED_IDLE, f"#{index + 1}")
            self._set_status(
                f"Step {index + 1} at ({step['x']}, {step['y']}) — "
                f"select this step before Run to align on that click"
            )

    def _on_floater_stop(self) -> None:
        """悬浮条停止按钮：录制或回放中途停止。"""
        if self._floater_mode == "record":
            self._on_stop_record()
        elif self._floater_mode == "play":
            self._on_stop_playback()

    def _show_record_floater(self) -> None:
        self._floater_mode = "record"
        self._control_floater.show(
            title="REC",
            status="0 steps",
            color=ControlFloater.COLOR_RECORD,
            compact=True,
        )

    def _show_play_floater(self, label: str) -> None:
        self._floater_mode = "play"
        self._control_floater.show(
            title="Running",
            status=f"'{label}' starting…",
            color=ControlFloater.COLOR_PLAY,
        )

    def _hide_control_floater(self) -> None:
        self._control_floater.hide()
        self._floater_mode = None

    def _offer_save_after_record(self) -> None:
        """录制中途停止后，提示保存以便下次直接运行。"""
        if not self._current_steps:
            return
        name = self._flow_name_var.get().strip()
        if name and self.storage.exists(name):
            if messagebox.askyesno(
                "Save Flow",
                f"Update '{name}' with the current {len(self._current_steps)} steps?\n\n"
                "You can run it from Saved Flows below.",
            ):
                try:
                    self.storage.save(name, self._current_steps)
                    self._refresh_flow_list()
                    self._set_status(f"Saved '{name}' — select it below and click Run Selected")
                except (ValueError, OSError) as exc:
                    messagebox.showerror("Save Failed", str(exc))
            return

        if messagebox.askyesno(
            "Save Flow",
            f"Recorded {len(self._current_steps)} steps.\n\n"
            "Save now? You can run it anytime from Saved Flows.",
        ):
            self._on_save()

    def _on_record_hover(self, entering: bool) -> None:
        """录制按钮悬停效果。"""
        if self._controls_locked or self._recording:
            return
        color = COLOR_RED_ACTIVE if entering else COLOR_RED_IDLE
        self._record_canvas.itemconfig(self._record_outer, fill=color)

    def _set_red_button_recording(self, recording: bool) -> None:
        """更新红色按钮外观。"""
        self._recording = recording
        if recording:
            self._record_canvas.itemconfig(self._record_outer, fill=COLOR_RED_ACTIVE)
            # 录制中显示白色方块（停止图标）
            self._record_canvas.coords(self._record_inner, 36, 36, 60, 60)
            self._record_canvas.itemconfig(self._record_inner, fill="white")
            self._record_hint_var.set("Recording…")
        else:
            self._record_canvas.itemconfig(self._record_outer, fill=COLOR_RED_IDLE)
            # idle: white dot
            self._record_canvas.coords(self._record_inner, 32, 32, 64, 64)
            self._record_canvas.itemconfig(self._record_inner, fill="white")
            self._record_hint_var.set("Click to record")

    def _set_controls_locked(self, locked: bool) -> None:
        """回放期间锁定录制/运行按钮。"""
        self._controls_locked = locked
        cursor = "arrow" if locked else "hand2"
        self._record_canvas.config(cursor=cursor)
        self._set_canvas_button_enabled(self._btn_run, not locked)

    def _on_red_button_click(self) -> None:
        """红按钮：切换录制开始/停止。"""
        if self._controls_locked:
            return
        if self._recording:
            self._on_stop_record()
        else:
            self._on_start_record()

    def _set_status(self, text: str) -> None:
        """更新状态文字（线程安全）。"""
        def apply() -> None:
            self._status_var.set(text)
            if self._floater_mode == "record":
                self._control_floater.set_status(text)

        self.root.after(0, apply)

    def _format_step(self, index: int, step: dict) -> str:
        """把步骤格式化为可读字符串。"""
        delay = step.get("delay", 0)
        step_type = step.get("type")

        if step_type == "wait_load":
            region = f"({step.get('x', '?')}, {step.get('y', '?')})"
            if step.get("w") and step.get("h"):
                region = f"{region} {step['w']}×{step['h']}"
            return f"{index + 1}. Wait for load {region} wait {delay}s"
        if step_type == "click":
            return (
                f"{index + 1}. Click ({step['x']}, {step['y']}) "
                f"[{step.get('button', 'left')}] wait {delay}s"
            )
        if step_type == "double_click":
            return (
                f"{index + 1}. Double-click ({step['x']}, {step['y']}) "
                f"[{step.get('button', 'left')}] wait {delay}s"
            )
        if step_type == "drag":
            role = step.get("role")
            if role == "scrollbar_v":
                label = "Drag vertical scrollbar"
            elif role == "scrollbar_h":
                label = "Drag horizontal scrollbar"
            else:
                label = "Drag"
            return (
                f"{index + 1}. {label} ({step['x1']},{step['y1']}) → "
                f"({step['x2']},{step['y2']}) wait {delay}s"
            )
        if step_type == "scroll_pan":
            return (
                f"{index + 1}. Middle-button pan ({step['x1']},{step['y1']}) → "
                f"({step['x2']},{step['y2']}) wait {delay}s"
            )
        if step_type == "scroll":
            parts = []
            dy = float(step.get("dy", 0))
            dx = float(step.get("dx", 0))
            if abs(dy) >= 0.01:
                lines = abs(int(round(dy / 8))) if abs(dy) > 3 else abs(int(round(dy)))
                lines = max(1, lines)
                parts.append(f"{'up' if dy > 0 else 'down'} {lines}")
            if abs(dx) >= 0.01:
                lines = abs(int(round(dx / 8))) if abs(dx) > 3 else abs(int(round(dx)))
                lines = max(1, lines)
                parts.append(f"{'right' if dx > 0 else 'left'} {lines}")
            label = " ".join(parts) if parts else ""
            if label:
                return f"{index + 1}. Scroll {label} wait {delay}s"
            return f"{index + 1}. Scroll wait {delay}s"
        if step_type == "type":
            text = step.get("text", "")
            display = text if len(text) <= 20 else text[:20] + "..."
            return f'{index + 1}. Type "{display}" wait {delay}s'
        if step_type == "key":
            return f"{index + 1}. Key [{step.get('key', '')}] wait {delay}s"
        if step_type == "copy":
            return f"{index + 1}. Copy (Ctrl/Cmd+C) wait {delay}s"
        if step_type == "paste":
            return f"{index + 1}. Paste (Ctrl/Cmd+V) wait {delay}s"
        if step_type == "hotkey":
            keys = step.get("keys", [])
            action_label = {
                "copy": "Copy (Ctrl/Cmd+C)",
                "paste": "Paste (Ctrl/Cmd+V)",
            }.get(clipboard_action_for_hotkey(keys) or "")
            if action_label:
                return f"{index + 1}. {action_label} wait {delay}s"
            keys_str = "+".join(keys)
            return f"{index + 1}. Hotkey [{keys_str}] wait {delay}s"
        return f"{index + 1}. Unknown step {step}"

    def _refresh_steps_list(self) -> None:
        """刷新当前步骤列表显示。"""
        self._steps_list.delete(0, tk.END)
        for i, step in enumerate(self._current_steps):
            self._steps_list.insert(tk.END, self._format_step(i, step))

    def _refresh_flow_list(self) -> None:
        """刷新已保存流程列表。"""
        self._flows_list.delete(0, tk.END)
        for flow in self.storage.list_flows():
            line = f"{flow['name']} ({flow['step_count']} steps)"
            self._flows_list.insert(tk.END, line)

    def _get_selected_flow_name(self) -> Optional[str]:
        """获取列表中选中的流程名称。"""
        selection = self._flows_list.curselection()
        if not selection:
            return None
        flows = self.storage.list_flows()
        index = selection[0]
        if index >= len(flows):
            return None
        return flows[index]["name"]

    def _on_flow_select(self, _event=None) -> None:
        """选中流程时加载步骤预览。"""
        name = self._get_selected_flow_name()
        if not name:
            return
        try:
            data = self.storage.load(name)
            self._current_steps = data.get("steps", [])
            self._flow_name_var.set(name)
            self._refresh_steps_list()
        except (FileNotFoundError, OSError):
            pass

    def _on_start_record(self) -> None:
        """开始录制。"""
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Stop playback first.")
            return
        if not self._ensure_permissions():
            return

        self._current_steps = []
        self._refresh_steps_list()

        def on_step(step: dict) -> None:
            def update() -> None:
                self._current_steps.append(step)
                self._steps_list.insert(
                    tk.END, self._format_step(len(self._current_steps) - 1, step)
                )
                n = len(self._current_steps)
                self._control_floater.set_status(f"{n} step{'s' if n != 1 else ''}")

            self.root.after(0, update)

        self.recorder = Recorder(
            on_step=on_step,
            should_record_click=self._should_record_click,
        )
        self.recorder.start()

        self._set_red_button_recording(True)
        self._set_canvas_button_enabled(self._btn_run, False)
        self._floater_mode = "record"
        self._hide_main_for_recording()
        self._show_record_floater()

    def _on_stop_record(self) -> None:
        """停止录制。"""
        if not self.recorder or not self.recorder.is_recording:
            return

        self._current_steps = self.recorder.stop()
        self._refresh_steps_list()

        self._hide_control_floater()
        self._restore_main_after_recording()
        self._set_red_button_recording(False)
        self._set_canvas_button_enabled(self._btn_run, True)
        self._set_status(
            f"Recording stopped — {len(self._current_steps)} steps. Save or run now."
        )
        self._offer_save_after_record()

    def _on_save(self) -> None:
        """保存当前步骤为流程文件。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter a flow name.")
            return
        if not self._current_steps:
            messagebox.showwarning("Notice", "No steps to save. Record a flow first.")
            return

        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._set_status(f"Saved flow: {name}")
            messagebox.showinfo("Success", f"Flow '{name}' saved.")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save Failed", str(exc))

    def _on_save_and_run(self) -> None:
        """保存当前步骤后立即运行。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter a flow name.")
            return
        if not self._current_steps:
            messagebox.showwarning("Notice", "No steps to save. Record a flow first.")
            return
        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._start_playback(self._current_steps, name)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save Failed", str(exc))

    def _on_delete_selected(self) -> None:
        """删除选中的流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("Notice", "Select a saved flow first.")
            return

        if not messagebox.askyesno("Confirm Delete", f"Delete flow '{name}'?"):
            return

        if self.storage.delete(name):
            self._refresh_flow_list()
            self._set_status(f"Deleted flow: {name}")
        else:
            messagebox.showerror("Delete Failed", f"Flow not found: {name}")

    def _set_playback_ui(self, playing: bool) -> None:
        """切换回放期间的按钮状态。"""
        self._set_controls_locked(playing)
        self._set_canvas_button_enabled(self._btn_stop_play, playing)

    def _start_playback(self, steps: List[dict], label: str) -> None:
        """开始回放指定步骤。"""
        if not steps:
            messagebox.showwarning("Notice", "No steps to run.")
            return
        if self.recorder and self.recorder.is_recording:
            messagebox.showwarning("Notice", "Stop recording first.")
            return
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Playback already in progress.")
            return
        if not self._ensure_permissions():
            return

        has_click = any(
            step.get("type") in ("click", "double_click", "drag") for step in steps
        )
        has_type = any(step.get("type") == "type" for step in steps)

        self._hide_for_playback()
        self._set_playback_ui(True)
        self._show_play_floater(label)

        if has_type and not has_click:
            self._set_status(
                "No click steps — click the input field now, then playback continues in 5s"
            )

        selected_anchor, anchor_step_index = self._get_calibration_anchor_from_selection(
            steps
        )
        first_click_index = next(
            (
                i
                for i, s in enumerate(steps)
                if s.get("type") in ("click", "double_click")
            ),
            None,
        )
        display_anchor = selected_anchor or resolve_calibration_anchor(steps, None)
        anchor_step_num = (
            anchor_step_index + 1
            if anchor_step_index is not None
            else ((first_click_index + 1) if first_click_index is not None else 1)
        )
        if selected_anchor is not None:
            align_hint = (
                f"Selected step {anchor_step_num} is the align target — "
                f"click that same spot (orange dot) during countdown."
            )
        else:
            align_hint = (
                "Tip: select the Products (or target) click step in the list before Run, "
                "then click the orange dot during countdown."
            )
        if sys.platform == "darwin":
            align_hint += (
                " Safari: scroll page to the same position as when recorded "
                "(toolbar hide/show shifts clicks)."
            )

        self._set_status(
            f"Starting '{label}' in 5s — switch to target app. {align_hint}"
        )
        self.root.update_idletasks()
        play_exclude_rects: List[Tuple[int, int, int, int]] = []
        floater_rect = self._control_floater.bounds()
        if floater_rect:
            play_exclude_rects.append(floater_rect)

        if display_anchor is not None:
            ax, ay = display_anchor
            self._click_marker.reanchor_host()
            self._click_marker.show_calibration(
                ax,
                ay,
                label=str(anchor_step_num),
            )

        def on_countdown(remaining: int) -> None:
            if display_anchor is not None:
                msg = (
                    f"{remaining}s — click the ORANGE dot (step {anchor_step_num}) "
                    f"to align, or wait if unchanged"
                )
            else:
                msg = (
                    f"{remaining}s — click a page element to align, "
                    f"or wait if unchanged"
                )
            self._set_status(f"{msg} (Stop at bottom-right)")
            self._control_floater.set_status(msg)

        def exclude_rects() -> List[Tuple[int, int, int, int]]:
            return play_exclude_rects

        playback_speed = self._parse_playback_speed()
        speed_label = (
            f"{playback_speed:g}x"
            if playback_speed != int(playback_speed)
            else f"{int(playback_speed)}x"
        )

        def on_before_step(index: int, step: dict) -> None:
            if index == 0:
                self.root.after(0, self._click_marker.hide_calibration)

            def highlight_step() -> None:
                self._steps_list.selection_clear(0, tk.END)
                self._steps_list.selection_set(index)
                self._steps_list.see(index)

            self.root.after(0, highlight_step)

            delay = float(step.get("delay", 0))
            eff_delay = delay / playback_speed if playback_speed else delay
            msg = f"[{speed_label}] Step {index + 1}/{len(steps)}"
            if delay > 0:
                msg += f" — wait {eff_delay:.2f}s (recorded {delay:.2f}s)"
            else:
                msg += f" — {step.get('type', '?')}"
            self._set_status(msg)
            self._control_floater.set_status(msg)

            if step.get("type") in ("click", "double_click"):
                hint = (
                    " — keep browser in front"
                    if index == first_click_index
                    else ""
                )
                click_msg = (
                    f"[{speed_label}] Click ({int(step['x'])}, {int(step['y'])}) "
                    f"— step {index + 1}/{len(steps)}{hint}"
                )
                self._set_status(click_msg)
                self._control_floater.set_status(click_msg)

        def on_step(index: int, step: dict) -> None:
            if step.get("type") == "click":
                self._set_status(
                    f"Clicked ({int(step['x'])}, {int(step['y'])}) "
                    f"— step {index + 1}/{len(steps)}"
                )
            else:
                self._set_status(f"'{label}' step {index + 1}/{len(steps)}")
            self._control_floater.set_status(f"Step {index + 1}/{len(steps)}")

        def on_done(step_errors=None) -> None:
            errors = step_errors or []

            def finish() -> None:
                self._click_marker.hide_calibration()
                self._set_playback_ui(False)
                self._hide_control_floater()
                self._show_after_playback()
                if errors:
                    lines = "\n".join(
                        f"Step {idx + 1}: {exc}" for idx, exc in errors[:5]
                    )
                    extra = f"\n…and {len(errors) - 5} more" if len(errors) > 5 else ""
                    self._set_status(
                        f"'{label}' finished with {len(errors)} step error(s)"
                    )
                    messagebox.showwarning(
                        "Playback Completed with Errors",
                        f"Ran all {len(steps)} steps; {len(errors)} step(s) failed:\n\n"
                        f"{lines}{extra}",
                    )
                else:
                    self._set_status(
                        f"'{label}' playback finished — all {len(steps)} steps done"
                    )

            self.root.after(0, finish)

        def on_step_error(index: int, step: dict, exc: Exception) -> None:
            self._set_status(
                f"Step {index + 1}/{len(steps)} failed ({step.get('type')}): {exc} — continuing…"
            )

        def on_error(exc: Exception) -> None:
            def show_error() -> None:
                self._click_marker.hide_calibration()
                self._set_playback_ui(False)
                self._hide_control_floater()
                self._show_after_playback()
                self._set_status("Playback error")
                messagebox.showerror("Playback Failed", str(exc))

            self.root.after(0, show_error)

        def on_wait_load(msg: str) -> None:
            self._set_status(msg)
            self._control_floater.set_status(msg)

        self.player.play(
            steps,
            countdown=5,
            on_countdown=on_countdown,
            on_before_step=on_before_step,
            on_step=on_step,
            on_done=on_done,
            on_error=on_error,
            on_step_error=on_step_error,
            exclude_rects=exclude_rects,
            run_on_main=self._run_on_main_thread
            if sys.platform in ("win32", "darwin")
            else None,
            calibration_anchor=selected_anchor,
            wait_load_after_click=self._wait_load_var.get(),
            on_wait_load=on_wait_load,
            playback_speed=playback_speed,
            hide_cursor=self._hide_mouse_var.get(),
        )

    def _on_run_current(self) -> None:
        """运行当前步骤（未保存也可运行）。"""
        self._start_playback(self._current_steps, "Current Steps")

    def _on_run_selected(self) -> None:
        """运行选中的已保存流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("Notice", "Select a saved flow first.")
            return

        try:
            data = self.storage.load(name)
            steps = data.get("steps", [])
            self._current_steps = steps
            self._refresh_steps_list()
            self._start_playback(steps, name)
        except (FileNotFoundError, OSError) as exc:
            messagebox.showerror("Load Failed", str(exc))

    def _on_stop_playback(self) -> None:
        """停止回放。"""
        self.player.stop()
        self._set_playback_ui(False)
        self._hide_control_floater()
        self._show_after_playback()
        self._set_status("Playback stopped — select a saved flow below to continue")
