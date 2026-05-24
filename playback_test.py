"""Windows 回放线程测试 — 模拟后台线程经主线程注入鼠标。"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk


def _run_on_main(root: tk.Tk, q: queue.Queue, fn, timeout: float = 15.0) -> None:
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

    q.put(job)
    if not done.wait(timeout):
        raise TimeoutError("playback thread test timeout")
    if state["error"] is not None:
        raise state["error"]


def main() -> int:
    if sys.platform != "win32":
        print("[SKIP] playback thread test (Windows only)")
        return 0

    from player import Player
    from self_test import _get_cursor_pos, _get_screen_size

    root = tk.Tk()
    root.withdraw()
    q: queue.Queue = queue.Queue()

    def poll() -> None:
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                break
            job()
        root.after(20, poll)

    poll()

    sw, sh = _get_screen_size()
    start = _get_cursor_pos()
    # 目标点避开当前位置，避免光标已在中心时误判
    target_x = max(80, min(sw - 80, 200 if start[0] > sw // 2 else sw - 200))
    target_y = max(80, min(sh - 80, 200 if start[1] > sh // 2 else sh - 200))

    player = Player()
    steps = [{"type": "click", "x": target_x, "y": target_y, "button": "left", "delay": 0}]
    errors: list = []

    def on_error(exc: Exception) -> None:
        errors.append(exc)

    def run_playback() -> None:
        player._run(
            steps,
            0,
            None,
            None,
            None,
            None,
            on_error,
            None,
            lambda fn: _run_on_main(root, q, fn),
        )

    thread = threading.Thread(target=run_playback, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while thread.is_alive() and time.time() < deadline:
        root.update()
        time.sleep(0.01)

    if thread.is_alive():
        root.destroy()
        raise RuntimeError("playback thread did not finish")

    if errors:
        root.destroy()
        raise errors[0]

    after = _get_cursor_pos()
    root.destroy()

    moved = abs(after[0] - start[0]) + abs(after[1] - start[1]) >= 15
    if not moved:
        raise RuntimeError(
            f"playback thread mouse did not move: before={start} after={after} target=({target_x},{target_y})"
        )

    print(f"[OK] playback thread test: {start} -> {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
