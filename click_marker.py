"""
点击位置标记 - 在屏幕上闪一下红/绿点，标明点击坐标。
"""

import tkinter as tk
from typing import Optional


class ClickMarker:
    """浮动标记，显示点击落点（不用 Canvas，避免 macOS 上变灰块）。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._windows: list = []
        self._calibration_win: Optional[tk.Toplevel] = None
        # 独立 overlay 宿主：主窗口回放时会被移到屏幕外，子 Toplevel 坐标会偏。
        self._host = tk.Toplevel(root)
        self._host.overrideredirect(True)
        self._host.geometry("1x1+0+0")
        self._host.attributes("-topmost", False)
        try:
            self._host.attributes("-alpha", 0.01)
        except tk.TclError:
            pass
        self._host.lower()
        self._host.update_idletasks()

    def reanchor_host(self) -> None:
        """主窗口移出屏幕后，把 overlay 宿主钉回屏幕原点。"""
        self._host.geometry("1x1+0+0")
        self._host.update_idletasks()

    def _place_overlay(self, win: tk.Toplevel, x: int, y: int, size: int) -> None:
        """把 overlay 中心对准屏幕坐标 (x, y)。"""
        x = int(round(x))
        y = int(round(y))
        half = size // 2
        left = x - half
        top = y - half
        win.geometry(f"{size}x{size}+{left}+{top}")
        win.update_idletasks()

        # macOS 上 master 移出屏幕后 geometry 可能偏移，读回实际位置再校正。
        actual_x = win.winfo_rootx() + half
        actual_y = win.winfo_rooty() + half
        if abs(actual_x - x) > 2 or abs(actual_y - y) > 2:
            win.geometry(
                f"{size}x{size}+{left + (x - actual_x)}+{top + (y - actual_y)}"
            )
            win.update_idletasks()

    def close_flashes(self) -> None:
        """关闭短暂闪点，保留倒计时对齐锚点。"""
        for win in list(self._windows):
            try:
                win.destroy()
            except tk.TclError:
                pass
        self._windows.clear()

    def close_all(self) -> None:
        """关闭所有未消失的标记窗口，避免回放时被挡住。"""
        self.hide_calibration()
        self.close_flashes()

    def show_calibration(
        self,
        x: int,
        y: int,
        *,
        label: str = "align",
        color: str = "#fb8c00",
    ) -> None:
        """倒计时期间显示对齐锚点（橙色圆点，直到 hide_calibration）。"""
        self.hide_calibration()
        x = int(round(x))
        y = int(round(y))
        size = 56

        win = tk.Toplevel(self._host)
        self._calibration_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=color)
        self._place_overlay(win, x, y, size)

        tk.Label(
            win,
            text=label,
            bg=color,
            fg="white",
            font=("Helvetica", 11, "bold"),
        ).pack(expand=True, fill=tk.BOTH)
        win.lift()

    def hide_calibration(self) -> None:
        if self._calibration_win is None:
            return
        try:
            self._calibration_win.destroy()
        except tk.TclError:
            pass
        self._calibration_win = None

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

        win = tk.Toplevel(self._host)
        self._windows.append(win)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=color)
        self._place_overlay(win, x, y, size)

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
