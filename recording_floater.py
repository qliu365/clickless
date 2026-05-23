"""
控制悬浮条 - 录制/回放时在屏幕角落显示，可随时停止。
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
        self._color = self.COLOR_RECORD

    def show(self, *, title: str, status: str = "", color: str = COLOR_RECORD) -> None:
        """显示悬浮条。"""
        self._color = color
        if self.win is None:
            self._create_window()

        assert self._title_label is not None
        assert self._status_label is not None
        self.win.configure(bg=self._color)
        for widget in self.win.winfo_children():
            widget.configure(bg=self._color)
            for child in widget.winfo_children():
                try:
                    child.configure(bg=self._color)
                except tk.TclError:
                    pass

        self._title_label.config(text=title, bg=self._color)
        self._status_label.config(text=status, bg=self._color)
        self.win.deiconify()
        self.win.lift()

    def set_status(self, text: str) -> None:
        """更新状态文字（可从回放线程调用）。"""
        if self._status_label is None:
            return
        self.root.after(0, lambda t=text: self._apply_status(t))

    def _apply_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.config(text=text)

    def hide(self) -> None:
        """隐藏悬浮条。"""
        if self.win is not None:
            self.win.destroy()
            self.win = None
            self._title_label = None
            self._status_label = None

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

    def _create_window(self) -> None:
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        frame = tk.Frame(self.win, bg=self._color, padx=10, pady=8)
        frame.pack()

        title_row = tk.Frame(frame, bg=self._color)
        title_row.pack(fill=tk.X)

        self._title_label = tk.Label(
            title_row,
            text="",
            fg="white",
            bg=self._color,
            font=("Helvetica", 12, "bold"),
        )
        self._title_label.pack(side=tk.LEFT, padx=(0, 10))

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
        stop.create_text(36, 14, text="停止", fill=self._color, font=("Helvetica", 11, "bold"))
        stop.bind("<Button-1>", lambda _e: self.on_stop())

        self._status_label = tk.Label(
            frame,
            text="",
            fg="white",
            bg=self._color,
            font=("Helvetica", 10),
            wraplength=180,
            justify=tk.LEFT,
        )
        self._status_label.pack(anchor=tk.W, pady=(6, 0))

        self.win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.win.geometry(f"+{sw - 220}+{sh - 100}")


# 兼容旧名称
RecordingFloater = ControlFloater
