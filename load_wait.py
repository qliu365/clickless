"""
页面加载等待 — 截取屏幕区域，画面稳定后再继续下一步（适合 Safari / 网页）。
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

Region = Tuple[int, int, int, int]  # x, y, width, height

DEFAULT_TIMEOUT = 15.0
DEFAULT_STABLE_FOR = 0.45
DEFAULT_POLL = 0.12
DEFAULT_THRESHOLD = 0.018


def _screen_size() -> Tuple[int, int]:
    try:
        import pyautogui

        return int(pyautogui.size().width), int(pyautogui.size().height)
    except Exception:
        return 1440, 900


def _clamp_region(region: Region) -> Region:
    sw, sh = _screen_size()
    x, y, w, h = region
    w = max(80, min(int(w), sw))
    h = max(60, min(int(h), sh))
    x = max(0, min(int(x), sw - w))
    y = max(0, min(int(y), sh - h))
    return x, y, w, h


def region_around_point(x: int, y: int) -> Region:
    """
    根据点击位置选择监测区域。
    左侧边栏点击（如 Shopify Products）时监测右侧主内容区。
    """
    sw, sh = _screen_size()
    if x < 350:
        w = min(720, sw - 120)
        h = min(520, sh - 120)
        rx = min(max(280, x + 120), sw - w - 20)
        ry = max(60, min(y - h // 3, sh - h - 60))
    else:
        w = min(560, sw - 40)
        h = min(420, sh - 40)
        rx = max(20, min(x - w // 2, sw - w - 20))
        ry = max(40, min(y - h // 2, sh - h - 40))
    return _clamp_region((rx, ry, w, h))


def region_from_step(step: dict) -> Region:
    """从 wait_load 步骤或带坐标的步骤解析监测区域。"""
    if step.get("w") and step.get("h"):
        return _clamp_region(
            (
                int(step.get("x", 0)),
                int(step.get("y", 0)),
                int(step["w"]),
                int(step["h"]),
            )
        )
    if step.get("x") is not None and step.get("y") is not None:
        return region_around_point(int(step["x"]), int(step["y"]))
    sw, sh = _screen_size()
    return _clamp_region((sw // 8, sh // 8, sw * 3 // 4, sh * 3 // 4))


def _grab_region(region: Region):
    import pyautogui

    box = _clamp_region(region)
    return pyautogui.screenshot(region=box)


def _image_diff_ratio(a, b) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    a_gray = a.convert("L")
    b_gray = b.convert("L")
    diff = ImageChops.difference(a_gray, b_gray)
    stat = ImageStat.Stat(diff)
    return float(stat.mean[0]) / 255.0


def wait_for_screen_stable(
    region: Optional[Region] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    stable_for: float = DEFAULT_STABLE_FOR,
    poll: float = DEFAULT_POLL,
    threshold: float = DEFAULT_THRESHOLD,
    stop_event=None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    等待屏幕区域连续 stable_for 秒几乎不变（加载动画/转圈结束）。

    Returns:
        True 表示已稳定；False 表示超时或被 stop_event 中断。
    """
    if Image is None:
        return False

    box = _clamp_region(region) if region else region_from_step({})
    deadline = time.time() + max(0.5, float(timeout))
    stable_since: Optional[float] = None
    previous = None
    last_report = 0.0
    grab_failures = 0

    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False

        try:
            current = _grab_region(box)
            grab_failures = 0
        except Exception:
            grab_failures += 1
            if grab_failures >= 3:
                if on_progress:
                    on_progress("Screen capture unavailable — skipping load wait")
                return False
            time.sleep(poll)
            continue

        if previous is not None:
            diff = _image_diff_ratio(previous, current)
            if diff <= threshold:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= stable_for:
                    return True
            else:
                stable_since = None

        previous = current
        now = time.time()
        if on_progress and now - last_report >= 0.4:
            remaining = max(0.0, deadline - now)
            on_progress(f"Waiting for page load ({remaining:.0f}s left)…")
            last_report = now
        time.sleep(poll)

    return False
