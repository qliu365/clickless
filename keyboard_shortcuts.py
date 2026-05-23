"""
复制/粘贴快捷键 — 录制识别 Ctrl/Cmd+C/V，回放时按当前系统发送。
"""

import sys
import time
from typing import List, Optional

from pynput.keyboard import Controller, Key

_controller = Controller()


def is_copy_keys(keys: List[str]) -> bool:
    normalized = [k.lower() for k in keys]
    if not normalized or normalized[-1] != "c":
        return False
    mods = set(normalized[:-1])
    return bool(mods & {"ctrl", "cmd"})


def is_paste_keys(keys: List[str]) -> bool:
    normalized = [k.lower() for k in keys]
    if not normalized or normalized[-1] != "v":
        return False
    mods = set(normalized[:-1])
    return bool(mods & {"ctrl", "cmd"})


def clipboard_action_for_hotkey(keys: List[str]) -> Optional[str]:
    """把组合键解析为 copy / paste，无法识别则返回 None。"""
    if is_copy_keys(keys):
        return "copy"
    if is_paste_keys(keys):
        return "paste"
    return None


def perform_copy() -> None:
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with _controller.pressed(mod):
        _controller.press("c")
        _controller.release("c")
    time.sleep(0.08)


def perform_paste() -> None:
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with _controller.pressed(mod):
        _controller.press("v")
        _controller.release("v")
    time.sleep(0.12)
