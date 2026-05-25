"""
控制悬浮条 - 录制/回放时显示小浮窗，可拖动，随时停止。
"""

import tkinter as tk
from typing import Callable, Optional, Tuple


class ControlFloater:
    """录制或回放期间置顶小窗口。"""

    COLOR_RECORD = "#b71c1c"
    COLOR_PLAY = "#2e7d32"

    def __init__(self, root: tk.Tk, on_stop: Callable[[], None]) -> None:
        self.root = root
        self.on_stop = on_stop
        self.win: Optional[tk.Toplevel] = None
        self._title_label: Optional[tk.Label] = None
        self._status_label: Optional[tk.Label] = None
        self._step_label: Optional[tk.Label] = None
        self._color = self.COLOR_RECORD
        self._compact = False
        self._drag_x = 0
        self._drag_y = 0

    def show(
        self,
        *,
        title: str,
        status: str = "",
        color: str = COLOR_RECORD,
        compact: bool = False,
    ) -> None:
        """显示悬浮条。compact=True 时为录屏风格小 tab。"""
        self._color = color
        self._compact = compact
        if self.win is None:
            if compact:
                self._create_compact_window()
            else:
                self._create_window()
        else:
            self._apply_color()

        assert self._title_label is not None
        if self._compact:
            if self._step_label is not None:
                self._step_label.config(text=status, bg=self._color)
        elif self._status_label is not None:
            self._status_label.config(text=status, bg=self._color)

        self._title_label.config(text=title, bg=self._color)
        self.win.deiconify()
        self.win.lift()

    def set_status(self, text: str) -> None:
        """更新状态文字（可从回放线程调用）。"""
        if self._status_label is None and self._step_label is None:
            return
        self.root.after(0, lambda t=text: self._apply_status(t))

    def _apply_status(self, text: str) -> None:
        if self._compact and self._step_label is not None:
            self._step_label.config(text=text)
        elif self._status_label is not None:
            self._status_label.config(text=text)

    def hide(self) -> None:
        """隐藏悬浮条。"""
        if self.win is not None:
            self.win.destroy()
            self.win = None
            self._title_label = None
            self._status_label = None
            self._step_label = None

    def bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """返回 (x1, y1, x2, y2) 屏幕坐标，用于过滤误录。"""
        if self.win is None:
            return None
        try:
            x = self.win.winfo_rootx()
            y = self.win.winfo_rooty()
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            return (x, y, x + w, y + h)
        except tk.TclError:
            return None

    def _apply_color(self) -> None:
        if self.win is None:
            return
        self.win.configure(bg=self._color)
        for widget in self.win.winfo_children():
            try:
                widget.configure(bg=self._color)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                try:
                    child.configure(bg=self._color)
                except tk.TclError:
                    pass

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._on_drag, add="+")

    def _start_drag(self, event: tk.Event) -> None:
        if self.win is None:
            return
        self._drag_x = event.x_root - self.win.winfo_x()
        self._drag_y = event.y_root - self.win.winfo_y()

    def _on_drag(self, event: tk.Event) -> None:
        if self.win is None:
            return
        x = max(0, event.x_root - self._drag_x)
        y = max(0, event.y_root - self._drag_y)
        self.win.geometry(f"+{x}+{y}")

    def _create_compact_window(self) -> None:
        """录屏风格小 tab：可拖动，红点 + 步数 + 停止。"""
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        bar = tk.Frame(self.win, bg=self._color, padx=8, pady=6)
        bar.pack()
        self._bind_drag(bar)

        dot = tk.Canvas(
            bar,
            width=10,
            height=10,
            highlightthickness=0,
            bg=self._color,
            cursor="fleur",
        )
        dot.pack(side=tk.LEFT, padx=(0, 6))
        dot.create_oval(1, 1, 9, 9, fill="#ff5252", outline="")
        self._bind_drag(dot)

        self._title_label = tk.Label(
            bar,
            text="REC",
            fg="white",
            bg=self._color,
            font=("Helvetica", 11, "bold"),
            cursor="fleur",
        )
        self._title_label.pack(side=tk.LEFT)
        self._bind_drag(self._title_label)

        self._step_label = tk.Label(
            bar,
            text="0 steps",
            fg="#ffcdd2",
            bg=self._color,
            font=("Helvetica", 10),
            cursor="fleur",
        )
        self._step_label.pack(side=tk.LEFT, padx=(8, 10))
        self._bind_drag(self._step_label)

        stop = tk.Canvas(
            bar,
            width=22,
            height=22,
            highlightthickness=0,
            bg=self._color,
            cursor="hand2",
        )
        stop.pack(side=tk.LEFT)
        stop.create_rectangle(4, 4, 18, 18, fill="white", outline="")
        stop.bind("<Button-1>", lambda _e: self.on_stop())

        self._status_label = None

        self.win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        self.win.geometry(f"+{sw - 160}+24")

    def _create_window(self) -> None:
        """回放用稍大的悬浮条（含详细状态）。"""
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        frame = tk.Frame(self.win, bg=self._color, padx=10, pady=8)
        frame.pack()
        self._bind_drag(frame)

        title_row = tk.Frame(frame, bg=self._color)
        title_row.pack(fill=tk.X)
        self._bind_drag(title_row)

        self._title_label = tk.Label(
            title_row,
            text="",
            fg="white",
            bg=self._color,
            font=("Helvetica", 12, "bold"),
            cursor="fleur",
        )
        self._title_label.pack(side=tk.LEFT, padx=(0, 10))
        self._bind_drag(self._title_label)

        stop = tk.Canvas(
            title_row,
            width=72,
            height=28,
            highlightthickness=0,
            bg=self._color,
            cursor="hand2",
        )
        stop.pack(side=tk.LEFT)
        stop.create_rectangle(2, 2, 70, 26, fill="white", outline="")
        stop.create_text(36, 14, text="Stop", fill=self._color, font=("Helvetica", 11, "bold"))
        stop.bind("<Button-1>", lambda _e: self.on_stop())

        self._status_label = tk.Label(
            frame,
            text="",
            fg="white",
            bg=self._color,
            font=("Helvetica", 10),
            wraplength=280,
            justify=tk.LEFT,
        )
        self._status_label.pack(anchor=tk.W, pady=(6, 0))

        self._step_label = None

        self.win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.win.geometry(f"+{sw - 220}+{sh - 100}")


# 兼容旧名称
RecordingFloater = ControlFloater
