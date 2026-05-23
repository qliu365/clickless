"""
录制悬浮条 - 录制时显示在屏幕角落，用于停止录制。
"""

import tkinter as tk
from typing import Callable, Optional, Tuple


class RecordingFloater:
    """录制期间置顶小窗口，避免主窗口挡住目标应用。"""

    COLOR = "#b71c1c"

    def __init__(self, root: tk.Tk, on_stop: Callable[[], None]) -> None:
        self.root = root
        self.on_stop = on_stop
        self.win: Optional[tk.Toplevel] = None
        self._stop_btn: Optional[tk.Canvas] = None

    def show(self) -> None:
        """显示悬浮停止条。"""
        if self.win is not None:
            return

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        frame = tk.Frame(self.win, bg=self.COLOR, padx=10, pady=8)
        frame.pack()

        tk.Label(
            frame,
            text="录制中",
            fg="white",
            bg=self.COLOR,
            font=("Helvetica", 12, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 10))

        stop = tk.Canvas(
            frame,
            width=72,
            height=28,
            highlightthickness=0,
            bg=self.COLOR,
            cursor="hand2",
        )
        stop.pack(side=tk.LEFT)
        rect = stop.create_rectangle(2, 2, 70, 26, fill="white", outline="")
        stop.create_text(36, 14, text="停止", fill=self.COLOR, font=("Helvetica", 11, "bold"))
        stop.bind("<Button-1>", lambda _e: self.on_stop())
        self._stop_btn = stop

        self.win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 放右下角，尽量不挡网页
        self.win.geometry(f"+{sw - 200}+{sh - 80}")

    def hide(self) -> None:
        """隐藏悬浮条。"""
        if self.win is not None:
            self.win.destroy()
            self.win = None
            self._stop_btn = None

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
