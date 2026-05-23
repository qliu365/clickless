"""
点击坐标 — 使用录制时的屏幕绝对坐标；运行前对齐偏移由 playback offset 处理。
"""

from typing import Optional, Tuple

_playback_offset: Tuple[int, int] = (0, 0)


def set_playback_offset(dx: int, dy: int) -> None:
    """回放前对齐：本次回放给所有坐标加上偏移。"""
    global _playback_offset
    _playback_offset = (int(dx), int(dy))


def clear_playback_offset() -> None:
    set_playback_offset(0, 0)


def _apply_playback_offset(x: int, y: int) -> Tuple[int, int]:
    ox, oy = _playback_offset
    return int(x + ox), int(y + oy)


def resolve_click_point(step: dict) -> Tuple[int, int]:
    """把步骤里的点击坐标解析为屏幕绝对坐标。"""
    return _apply_playback_offset(int(step["x"]), int(step["y"]))


def expected_click_point(step: dict) -> Tuple[int, int]:
    """解析坐标，但不加运行前对齐偏移。"""
    if "x1" in step and "y1" in step:
        return int(step["x1"]), int(step["y1"])
    return int(step["x"]), int(step["y"])


def resolve_drag_points(step: dict) -> Tuple[int, int, int, int]:
    x1, y1 = _apply_playback_offset(int(step["x1"]), int(step["y1"]))
    x2, y2 = _apply_playback_offset(int(step["x2"]), int(step["y2"]))
    return x1, y1, x2, y2


def resolve_scroll_point(step: dict) -> Optional[Tuple[int, int]]:
    if step.get("x") is None or step.get("y") is None:
        return None
    return resolve_click_point(step)


def attach_window_offset(step: dict, x: int, y: int) -> None:
    """录制点击时保存屏幕坐标。"""
    step["x"] = x
    step["y"] = y


def attach_drag_window_offset(step: dict, x1: int, y1: int, x2: int, y2: int) -> None:
    step["x1"], step["y1"], step["x2"], step["y2"] = x1, y1, x2, y2
