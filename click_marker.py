"""
点击位置标记 - 在屏幕上闪一下红/绿点，标明点击坐标。
"""

import tkinter as tk


class ClickMarker:
    """浮动标记，显示点击落点（不用 Canvas，避免 macOS 上变灰块）。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._windows: list = []

    def close_all(self) -> None:
        """关闭所有未消失的标记窗口，避免回放时被挡住。"""
        for win in list(self._windows):
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._windows.clear()

    def flash(
        self,
        x: int,
        y: int,
        color: str = "#e53935",
        duration_ms: int = 900,
        label: str = "",
    ) -> None:
        """在 (x, y) 显示标记。"""
        x = int(round(x))
        y = int(round(y))

        size = 52
        half = size // 2

        win = tk.Toplevel(self.root)
        self._windows.append(win)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=color)
        win.geometry(f"{size}x{size}+{max(0, x - half)}+{max(0, y - half)}")

        text = label if label else "●"
        tk.Label(
            win,
            text=text,
            bg=color,
            fg="white",
            font=("Helvetica", 20, "bold"),
        ).pack(expand=True, fill=tk.BOTH)

        win.lift()
        win.after(duration_ms, lambda w=win: self._destroy_marker(w))

    def _destroy_marker(self, win: tk.Toplevel) -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass
        try:
            self._windows.remove(win)
        except ValueError:
            pass

    def flash_async(
        self,
        x: int,
        y: int,
        color: str = "#e53935",
        duration_ms: int = 900,
        label: str = "",
    ) -> None:
        """线程安全：切回主线程显示标记。"""
        self.root.after(0, lambda: self.flash(x, y, color, duration_ms, label))
