"""
界面模块 - Tkinter 图形界面，串联录制、回放与流程管理。
"""

import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import List, Optional, Tuple

from click_marker import ClickMarker
from permissions import (
    is_accessibility_granted,
    open_accessibility_settings,
    open_input_monitoring_settings,
    permission_hint,
    request_accessibility_prompt,
)
from player import Player
from recorder import Recorder
from recording_floater import ControlFloater, RecordingFloater
from storage import FlowStorage
from keyboard_shortcuts import clipboard_action_for_hotkey


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
        self.root.title("Clickless 自动化助手")
        self.root.geometry("680x620")
        self.root.minsize(560, 520)
        self.root.configure(bg=COLOR_BG)

        self._status_var = tk.StringVar(value="就绪 — 点击红色按钮开始录制")
        self._flow_name_var = tk.StringVar()
        self._record_hint_var = tk.StringVar(value="点击录制")
        self._current_steps: List[dict] = []

        self._click_marker = ClickMarker(self.root)
        self._control_floater = RecordingFloater(self.root, self._on_floater_stop)
        self._floater_mode: Optional[str] = None  # "record" | "play"

        self._build_ui()
        self._refresh_flow_list()
        self.root.after(500, self._check_permissions_on_startup)

    def _check_permissions_on_startup(self) -> None:
        """启动时检查 macOS 权限。"""
        if is_accessibility_granted():
            self._set_status("就绪 — 点击红色按钮开始录制")
            return
        self._set_status("缺少系统权限，鼠标/键盘将无法工作")
        request_accessibility_prompt()
        messagebox.showwarning("需要权限", permission_hint())

    def _ensure_permissions(self) -> bool:
        """录制/回放前确认权限。"""
        if is_accessibility_granted():
            return True

        request_accessibility_prompt()
        if is_accessibility_granted():
            return True

        answer = messagebox.askyesnocancel(
            "需要权限",
            permission_hint() + "\n\n是 = 打开辅助功能设置\n否 = 打开输入监控设置",
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
            text="运行",
            fill=COLOR_GREEN,
            active_fill=COLOR_GREEN_ACTIVE,
            command=self._on_run_current,
            width=120,
            height=48,
        )
        self._btn_run.pack(pady=(0, 10))

        self._btn_stop_play = self._create_canvas_button(
            action_col,
            text="停止回放",
            fill=COLOR_GRAY,
            active_fill=COLOR_GRAY_ACTIVE,
            command=self._on_stop_playback,
            width=120,
            height=36,
            disabled=True,
        )
        self._btn_stop_play.pack()

        tk.Label(
            hero_frame,
            text="录制：文字+Enter/方向键+点击+滚轮+拖拽；Ctrl/Cmd+C/V 自动识别为复制/粘贴。",
            font=("Helvetica", 10),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
            wraplength=620,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(12, 0))

        # 当前步骤预览
        steps_frame = ttk.LabelFrame(self.root, text="当前步骤", padding=10)
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        steps_scroll = ttk.Scrollbar(steps_frame)
        steps_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._steps_list = tk.Listbox(
            steps_frame, height=6, yscrollcommand=steps_scroll.set
        )
        self._steps_list.pack(fill=tk.BOTH, expand=True)
        steps_scroll.config(command=self._steps_list.yview)
        self._steps_list.bind("<<ListboxSelect>>", self._on_step_list_select)

        # 保存流程
        save_frame = ttk.LabelFrame(self.root, text="保存流程", padding=10)
        save_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        save_row = ttk.Frame(save_frame)
        save_row.pack(fill=tk.X)
        ttk.Label(save_row, text="名称：").pack(side=tk.LEFT)
        ttk.Entry(save_row, textvariable=self._flow_name_var, width=30).pack(
            side=tk.LEFT, padx=(4, 8), fill=tk.X, expand=True
        )
        ttk.Button(save_row, text="保存", command=self._on_save).pack(side=tk.LEFT)

        # 已保存流程
        flows_frame = ttk.LabelFrame(self.root, text="已保存流程", padding=10)
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

        ttk.Button(flows_btn_row, text="运行选中", command=self._on_run_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(flows_btn_row, text="保存并运行", command=self._on_save_and_run).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(flows_btn_row, text="删除", command=self._on_delete_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(flows_btn_row, text="刷新", command=self._refresh_flow_list).pack(
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
        """回放时完全隐藏 Clickless，避免窗口挡住网页点击。"""
        self._control_floater.hide()
        self._click_marker.close_all()
        try:
            self.root.withdraw()
            self.root.update_idletasks()
        except tk.TclError:
            pass

    def _show_after_playback(self) -> None:
        """回放结束后恢复主窗口。"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

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
                f"步骤 {index + 1} 落点：({step['x']}, {step['y']}) — 请看屏幕红圈"
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
            title="录制中",
            status="点停止结束录制",
            color=ControlFloater.COLOR_RECORD,
        )

    def _show_play_floater(self, label: str) -> None:
        self._floater_mode = "play"
        self._control_floater.show(
            title="运行中",
            status=f"「{label}」准备执行…",
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
                "保存流程",
                f"是否把当前 {len(self._current_steps)} 步更新到「{name}」？\n\n"
                "保存后可在下方「已保存流程」里直接运行。",
            ):
                try:
                    self.storage.save(name, self._current_steps)
                    self._refresh_flow_list()
                    self._set_status(f"已保存「{name}」— 可在下方选中后点「运行选中」")
                except (ValueError, OSError) as exc:
                    messagebox.showerror("保存失败", str(exc))
            return

        if messagebox.askyesno(
            "保存流程",
            f"已录制 {len(self._current_steps)} 步。\n\n"
            "是否现在保存？保存后可在「已保存流程」里随时运行。",
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
            self._record_hint_var.set("右下角点停止")
        else:
            self._record_canvas.itemconfig(self._record_outer, fill=COLOR_RED_IDLE)
            # idle 显示白色圆点
            self._record_canvas.coords(self._record_inner, 32, 32, 64, 64)
            self._record_canvas.itemconfig(self._record_inner, fill="white")
            self._record_hint_var.set("点击录制")

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
        self.root.after(0, lambda: self._status_var.set(text))

    def _format_step(self, index: int, step: dict) -> str:
        """把步骤格式化为可读字符串。"""
        delay = step.get("delay", 0)
        step_type = step.get("type")

        if step_type == "click":
            return (
                f"{index + 1}. 点击 ({step['x']}, {step['y']}) "
                f"[{step.get('button', 'left')}] 等待 {delay}s"
            )
        if step_type == "double_click":
            return (
                f"{index + 1}. 双击 ({step['x']}, {step['y']}) "
                f"[{step.get('button', 'left')}] 等待 {delay}s"
            )
        if step_type == "drag":
            role = step.get("role")
            if role == "scrollbar_v":
                label = "拖竖滚动条"
            elif role == "scrollbar_h":
                label = "拖横滚动条"
            else:
                label = "拖拽"
            return (
                f"{index + 1}. {label} ({step['x1']},{step['y1']}) → "
                f"({step['x2']},{step['y2']}) 等待 {delay}s"
            )
        if step_type == "scroll_pan":
            return (
                f"{index + 1}. 中键平移 ({step['x1']},{step['y1']}) → "
                f"({step['x2']},{step['y2']}) 等待 {delay}s"
            )
        if step_type == "scroll":
            parts = []
            dy = float(step.get("dy", 0))
            dx = float(step.get("dx", 0))
            if abs(dy) >= 0.01:
                lines = abs(int(round(dy / 8))) if abs(dy) > 3 else abs(int(round(dy)))
                lines = max(1, lines)
                parts.append(f"{'上' if dy > 0 else '下'}{lines}")
            if abs(dx) >= 0.01:
                lines = abs(int(round(dx / 8))) if abs(dx) > 3 else abs(int(round(dx)))
                lines = max(1, lines)
                parts.append(f"{'右' if dx > 0 else '左'}{lines}")
            label = "滚轮 " + " ".join(parts) if parts else "滚轮"
            return f"{index + 1}. {label} 等待 {delay}s"
        if step_type == "key" and step.get("key", "") in (
            "page_up",
            "page_down",
            "home",
            "end",
            "up",
            "down",
            "left",
            "right",
        ):
            return f"{index + 1}. 键盘滚动 [{step.get('key', '')}] 等待 {delay}s"
        if step_type == "type":
            text = step.get("text", "")
            display = text if len(text) <= 20 else text[:20] + "..."
            return f'{index + 1}. 输入 "{display}" 等待 {delay}s'
        if step_type == "key":
            return f"{index + 1}. 按键 [{step.get('key', '')}] 等待 {delay}s"
        if step_type == "copy":
            return f"{index + 1}. 复制 (Ctrl/Cmd+C) 等待 {delay}s"
        if step_type == "paste":
            return f"{index + 1}. 粘贴 (Ctrl/Cmd+V) 等待 {delay}s"
        if step_type == "hotkey":
            keys = step.get("keys", [])
            action_label = {
                "copy": "复制 (Ctrl/Cmd+C)",
                "paste": "粘贴 (Ctrl/Cmd+V)",
            }.get(clipboard_action_for_hotkey(keys) or "")
            if action_label:
                return f"{index + 1}. {action_label} 等待 {delay}s"
            keys_str = "+".join(keys)
            return f"{index + 1}. 组合键 [{keys_str}] 等待 {delay}s"
        return f"{index + 1}. 未知步骤 {step}"

    def _refresh_steps_list(self) -> None:
        """刷新当前步骤列表显示。"""
        self._steps_list.delete(0, tk.END)
        for i, step in enumerate(self._current_steps):
            self._steps_list.insert(tk.END, self._format_step(i, step))

    def _refresh_flow_list(self) -> None:
        """刷新已保存流程列表。"""
        self._flows_list.delete(0, tk.END)
        for flow in self.storage.list_flows():
            line = f"{flow['name']}（{flow['step_count']} 步）"
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
            messagebox.showwarning("提示", "请先停止回放。")
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
                # 录制时不弹标记（会挡在网页/input 上，导致点不进去）
                if step.get("type") == "click":
                    self._set_status(
                        f"已记录点击 ({int(step['x'])}, {int(step['y'])}) "
                        f"— 共 {len(self._current_steps)} 步"
                    )
                elif step.get("type") == "type":
                    preview = step.get("text", "")[:12]
                    self._set_status(
                        f'已记录输入 "{preview}" — 共 {len(self._current_steps)} 步'
                    )
                elif step.get("type") == "drag":
                    self._set_status(
                        f"已记录拖拽 ({step['x1']},{step['y1']})→"
                        f"({step['x2']},{step['y2']}) — 共 {len(self._current_steps)} 步"
                    )
                elif step.get("type") == "scroll":
                    dy, dx = step.get("dy", 0), step.get("dx", 0)
                    self._set_status(
                        f"已记录滚轮 dx={dx} dy={dy} — 共 {len(self._current_steps)} 步"
                    )
                elif step.get("type") == "scroll_pan":
                    self._set_status(
                        f"已记录中键平移 ({step['x1']},{step['y1']})→"
                        f"({step['x2']},{step['y2']}) — 共 {len(self._current_steps)} 步"
                    )
                else:
                    self._set_status(f"正在录制… 已记录 {len(self._current_steps)} 步")

            self.root.after(0, update)

        self.recorder = Recorder(
            on_step=on_step,
            should_record_click=self._should_record_click,
        )
        self.recorder.start()

        self._set_red_button_recording(True)
        self._set_canvas_button_enabled(self._btn_run, False)
        self._hide_main_for_recording()
        self.root.after(600, self._show_record_floater)
        self._set_status("正在录制 — 请切换到浏览器操作（右下角可停止）")

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
            f"录制已停止，共 {len(self._current_steps)} 步 — 可保存或直接运行"
        )
        self._offer_save_after_record()

    def _on_save(self) -> None:
        """保存当前步骤为流程文件。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入流程名称。")
            return
        if not self._current_steps:
            messagebox.showwarning("提示", "没有可保存的步骤，请先录制。")
            return

        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._set_status(f"已保存流程：{name}")
            messagebox.showinfo("成功", f"流程「{name}」已保存。")
        except (ValueError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc))

    def _on_save_and_run(self) -> None:
        """保存当前步骤后立即运行。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入流程名称。")
            return
        if not self._current_steps:
            messagebox.showwarning("提示", "没有可保存的步骤，请先录制。")
            return
        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._start_playback(self._current_steps, name)
        except (ValueError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc))

    def _on_delete_selected(self) -> None:
        """删除选中的流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("提示", "请先选择一个流程。")
            return

        if not messagebox.askyesno("确认删除", f"确定删除流程「{name}」吗？"):
            return

        if self.storage.delete(name):
            self._refresh_flow_list()
            self._set_status(f"已删除流程：{name}")
        else:
            messagebox.showerror("删除失败", f"找不到流程：{name}")

    def _set_playback_ui(self, playing: bool) -> None:
        """切换回放期间的按钮状态。"""
        self._set_controls_locked(playing)
        self._set_canvas_button_enabled(self._btn_stop_play, playing)

    def _start_playback(self, steps: List[dict], label: str) -> None:
        """开始回放指定步骤。"""
        if not steps:
            messagebox.showwarning("提示", "没有可运行的步骤。")
            return
        if self.recorder and self.recorder.is_recording:
            messagebox.showwarning("提示", "请先停止录制。")
            return
        if self.player.is_playing:
            messagebox.showwarning("提示", "已有回放正在进行。")
            return
        if not self._ensure_permissions():
            return

        has_click = any(step.get("type") == "click" for step in steps)
        has_type = any(step.get("type") == "type" for step in steps)
        if has_type and not has_click:
            messagebox.showwarning(
                "提示",
                "当前流程里没有「点击」步骤。\n\n"
                "运行前请手动点一下网页里的输入框，否则文字可能粘贴到错误位置。",
            )

        self._hide_for_playback()
        self._set_playback_ui(True)
        self._show_play_floater(label)
        self._set_status(
            f"5 秒后开始运行「{label}」— 切到 Excel；"
            f"若位置变了，请点第一个应对准的位置；没变则等待即可"
        )
        self.root.update_idletasks()

        def on_countdown(remaining: int) -> None:
            msg = (
                f"{remaining} 秒 — 位置变了就点应对准处；"
                f"没变则不用点"
            )
            self._set_status(f"{msg}（右下角可停止）")
            self._control_floater.set_status(msg)

        def exclude_rects() -> List[Tuple[int, int, int, int]]:
            rects: List[Tuple[int, int, int, int]] = []
            floater = self._control_floater.bounds()
            if floater:
                rects.append(floater)
            return rects

        first_click_index = next(
            (i for i, s in enumerate(steps) if s.get("type") == "click"),
            None,
        )

        def on_before_step(index: int, step: dict) -> None:
            if step.get("type") == "click":
                hint = (
                    " — 首次点击会稍等，请保持浏览器在最前面"
                    if index == first_click_index
                    else ""
                )
                self._set_status(
                    f"正在点击 ({int(step['x'])}, {int(step['y'])}) "
                    f"— 步骤 {index + 1}/{len(steps)}{hint}"
                )
                self._control_floater.set_status(
                    f"步骤 {index + 1}/{len(steps)} 点击中"
                )

        def on_step(index: int, step: dict) -> None:
            if step.get("type") == "click":
                self._set_status(
                    f"已点击 ({int(step['x'])}, {int(step['y'])}) "
                    f"— 步骤 {index + 1}/{len(steps)}"
                )
            else:
                self._set_status(f"「{label}」执行第 {index + 1}/{len(steps)} 步")
            self._control_floater.set_status(f"步骤 {index + 1}/{len(steps)}")

        def on_done() -> None:
            def finish() -> None:
                self._set_playback_ui(False)
                self._hide_control_floater()
                self._show_after_playback()
                self._set_status(f"「{label}」回放完成")

            self.root.after(0, finish)

        def on_error(exc: Exception) -> None:
            def show_error() -> None:
                self._set_playback_ui(False)
                self._hide_control_floater()
                self._show_after_playback()
                self._set_status("回放出错")
                messagebox.showerror("回放失败", str(exc))

            self.root.after(0, show_error)

        self.player.play(
            steps,
            countdown=5,
            on_countdown=on_countdown,
            on_before_step=on_before_step,
            on_step=on_step,
            on_done=on_done,
            on_error=on_error,
            exclude_rects=exclude_rects,
        )

    def _on_run_current(self) -> None:
        """运行当前步骤（未保存也可运行）。"""
        self._start_playback(self._current_steps, "当前步骤")

    def _on_run_selected(self) -> None:
        """运行选中的已保存流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("提示", "请先选择一个流程。")
            return

        try:
            data = self.storage.load(name)
            steps = data.get("steps", [])
            self._current_steps = steps
            self._refresh_steps_list()
            self._start_playback(steps, name)
        except (FileNotFoundError, OSError) as exc:
            messagebox.showerror("加载失败", str(exc))

    def _on_stop_playback(self) -> None:
        """停止回放。"""
        self.player.stop()
        self._set_playback_ui(False)
        self._hide_control_floater()
        self._show_after_playback()
        self._set_status("回放已停止 — 可在下方选择已保存流程继续运行")
