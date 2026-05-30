"""State and automation logic for the OfficeLego web UI."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from flow_correct import correct_steps
from flow_helpers import is_copy_step, is_paste_step, loop_body_after_mark
from flow_merge import merge_loop_marks
from module_storage import ModuleStorage
from permissions import (
    is_accessibility_granted,
    permission_hint,
    request_accessibility_prompt,
)
from player import Player, flow_has_pointer_steps
from recorder import Recorder
from screen_capture import CaptureSession, resolve_capture_path
from step_edit import (
    collect_steps_from_indices,
    describe_selection,
    fill_indices_range,
    gap_insert_labels,
)
from step_format import format_step
from storage import FlowStorage

if sys.platform == "darwin":
    from frontmost_app import is_wps_frontmost
    from range_pick import RangePickWatcher
else:
    RangePickWatcher = None  # type: ignore[misc, assignment]

    def is_wps_frontmost() -> bool:  # type: ignore[misc]
        return False


class OfficeLegoWebBackend:
    """Thread-safe bridge between Flask and desktop automation."""

    def __init__(
        self,
        flows_dir: Path,
        modules_dir: Path,
        captures_dir: Path,
    ) -> None:
        self.flow_storage = FlowStorage(flows_dir)
        self.module_storage = ModuleStorage(modules_dir)
        self.captures_dir = Path(captures_dir)
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.player = Player()
        self.recorder: Optional[Recorder] = None
        self._capture_session: Optional[CaptureSession] = None
        self._lock = threading.Lock()
        self._current_steps: List[dict] = []
        self._current_flow_name = ""
        self._recording = False
        self._loop_body_mode = False
        self._status = "Ready"
        self._playback_label = ""
        self._auto_correct = True
        self._playback_speed = 1.0
        self._wait_load = True
        self._countdown_remaining = 0
        self._playback_step = 0
        self._playback_total = 0
        self._fix_messages: List[str] = []
        self._range_pick_watcher: Optional[Any] = None
        self._range_pick_state = "idle"
        self._range_pick_message = ""
        self._range_pick_rows: Optional[int] = None
        self._range_pick_address = ""

    # --- permissions ---

    def permissions(self) -> Dict[str, Any]:
        return {
            "granted": is_accessibility_granted(),
            "hint": permission_hint(),
            "platform": sys.platform,
        }

    def prompt_permissions(self) -> Dict[str, Any]:
        request_accessibility_prompt()
        return self.permissions()

    # --- step summaries ---

    def _capture_urls(self, step: dict) -> Dict[str, Optional[str]]:
        if self._capture_session:
            return self._capture_session.capture_urls(step)
        before = step.get("capture_before")
        after = step.get("capture_after")
        return {
            "before": f"/api/captures/{before}" if before else None,
            "after": f"/api/captures/{after}" if after else None,
        }

    def _step_entry(self, index: int, step: dict) -> Dict[str, Any]:
        caps = self._capture_urls(step)
        return {
            "index": index,
            "type": step.get("type"),
            "label": format_step(index, step),
            "has_capture": bool(caps.get("before") or caps.get("after")),
            "capture_before_url": caps.get("before"),
            "capture_after_url": caps.get("after"),
        }

    def get_step_detail(self, index: int) -> Dict[str, Any]:
        with self._lock:
            if index < 0 or index >= len(self._current_steps):
                raise IndexError("Step index out of range")
            step = dict(self._current_steps[index])
        caps = self._capture_urls(step)
        body = None
        if step.get("type") == "loop":
            body = list(step.get("steps") or [])
        elif step.get("type") == "module":
            name = str(step.get("name", "")).strip()
            try:
                body = self.module_storage.load_steps(name) if name else []
            except (FileNotFoundError, OSError):
                body = []
        return {
            "index": index,
            "step": step,
            "capture_before_url": caps.get("before"),
            "capture_after_url": caps.get("after"),
            "loop_body": body,
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            steps = list(self._current_steps)
            return {
                "status": self._status,
                "recording": self._recording,
                "recording_paused": bool(
                    self.recorder and self.recorder.is_recording and self.recorder.is_paused
                ),
                "loop_body_mode": self._loop_body_mode,
                "playing": self.player.is_playing,
                "playback_label": self._playback_label,
                "countdown": self._countdown_remaining,
                "playback_step": self._playback_step,
                "playback_total": self._playback_total,
                "flow_name": self._current_flow_name,
                "step_count": len(steps),
                "steps": [self._step_entry(i, s) for i, s in enumerate(steps)],
                "auto_correct": self._auto_correct,
                "playback_speed": self._playback_speed,
                "wait_load": self._wait_load,
                "fix_messages": list(self._fix_messages),
                "range_pick": self.range_pick_status(),
                "is_wps": is_wps_frontmost() if sys.platform == "darwin" else False,
            }

    def _set_status(self, msg: str) -> None:
        with self._lock:
            self._status = msg

    def _sync_recorder_if_paused(self) -> None:
        if (
            self.recorder
            and self.recorder.is_recording
            and self.recorder.is_paused
        ):
            with self._lock:
                self.recorder.replace_steps(list(self._current_steps))

    # --- flows / modules ---

    def list_flows(self) -> List[Dict[str, Any]]:
        return self.flow_storage.list_flows()

    def list_modules(self) -> List[Dict[str, Any]]:
        return self.module_storage.list_modules()

    def load_flow(self, name: str) -> Dict[str, Any]:
        data = self.flow_storage.load(name)
        with self._lock:
            self._current_steps = list(data.get("steps", []))
            self._current_flow_name = data.get("name", name)
            self._fix_messages = []
        self._set_status(f"Loaded flow “{name}” ({len(self._current_steps)} steps)")
        return {"name": self._current_flow_name, "steps": self._current_steps}

    def save_flow(self, name: str) -> Dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Flow name cannot be empty")
        with self._lock:
            steps = list(self._current_steps)
        self.flow_storage.save(name, steps)
        with self._lock:
            self._current_flow_name = name
        self._set_status(f"Saved flow “{name}”")
        return {"name": name, "step_count": len(steps)}

    def delete_flow(self, name: str) -> bool:
        ok = self.flow_storage.delete(name)
        with self._lock:
            if ok and self._current_flow_name == name:
                self._current_flow_name = ""
        return ok

    def load_module_steps(self, name: str) -> List[dict]:
        return list(self.module_storage.load_steps(name))

    def save_module_file(self, name: str, steps: List[dict]) -> None:
        self.module_storage.save(name, steps)

    def get_gaps(self) -> Dict[str, Any]:
        with self._lock:
            labels, positions = gap_insert_labels(self._current_steps)
        return {"labels": labels, "positions": positions}

    def set_steps(self, steps: List[dict]) -> None:
        with self._lock:
            self._current_steps = list(steps)
        self._sync_recorder_if_paused()
        self._set_status(f"{len(steps)} steps")

    def insert_type_step(self, text: str, index: Optional[int] = None) -> None:
        step = {"type": "type", "text": text, "delay": 0.1}
        with self._lock:
            if index is None or index < 0 or index > len(self._current_steps):
                self._current_steps.append(step)
            else:
                self._current_steps.insert(index, step)
        self._sync_recorder_if_paused()
        self._set_status("Inserted text step")

    def insert_step_at(self, step: dict, at_index: int) -> None:
        with self._lock:
            at_index = max(0, min(at_index, len(self._current_steps)))
            self._current_steps.insert(at_index, step)
        self._sync_recorder_if_paused()

    def delete_steps(self, indices: List[int]) -> None:
        if not indices:
            return
        with self._lock:
            for i in sorted(set(indices), reverse=True):
                if 0 <= i < len(self._current_steps):
                    self._current_steps.pop(i)
        self._sync_recorder_if_paused()
        self._set_status(f"Deleted {len(indices)} step(s)")

    def move_step(self, from_index: int, to_index: int) -> None:
        with self._lock:
            n = len(self._current_steps)
            if not (0 <= from_index < n and 0 <= to_index < n):
                raise IndexError("Invalid step index")
            step = self._current_steps.pop(from_index)
            self._current_steps.insert(to_index, step)
        self._sync_recorder_if_paused()

    def update_step(self, index: int, patch: dict) -> None:
        with self._lock:
            if index < 0 or index >= len(self._current_steps):
                raise IndexError("Step index out of range")
            step = dict(self._current_steps[index])
            step_type = step.get("type")
            if step_type == "type" and "text" in patch:
                step["text"] = str(patch["text"])
            elif step_type == "loop" and "count" in patch:
                step["count"] = max(1, min(int(patch["count"]), 10000))
            elif step_type == "loop" and "steps" in patch:
                step["steps"] = list(patch["steps"])
            self._current_steps[index] = step
        self._sync_recorder_if_paused()

    def set_options(
        self,
        *,
        auto_correct: Optional[bool] = None,
        playback_speed: Optional[float] = None,
        wait_load: Optional[bool] = None,
    ) -> None:
        with self._lock:
            if auto_correct is not None:
                self._auto_correct = auto_correct
            if playback_speed is not None:
                self._playback_speed = max(0.1, float(playback_speed))
            if wait_load is not None:
                self._wait_load = wait_load

    # --- modules & loops (edit while not playing) ---

    def save_as_module(
        self,
        name: str,
        indices: List[int],
        *,
        expand_modules: bool = True,
    ) -> Dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Module name cannot be empty")
        if not indices:
            raise ValueError("Select at least one step")
        loader = self.module_storage.load_steps
        with self._lock:
            steps = collect_steps_from_indices(
                self._current_steps,
                indices,
                loader=loader,
                expand_modules=expand_modules,
            )
            if not steps:
                raise ValueError("No steps to save")
            filled = fill_indices_range(indices)
            insert_at = filled[0]
            removed = len(filled)
        if self.module_storage.exists(name):
            pass  # caller may confirm overwrite in UI
        self.module_storage.save(name, steps)
        with self._lock:
            for i in reversed(filled):
                del self._current_steps[i]
            self._current_steps.insert(
                insert_at, {"type": "module", "name": name, "delay": 0}
            )
        self._sync_recorder_if_paused()
        self._set_status(f'Saved module "{name}" — replaced {removed} steps')
        return {"name": name, "insert_at": insert_at, "removed": removed}

    def insert_module(self, module_name: str, at_index: int) -> None:
        module_name = module_name.strip()
        if not module_name:
            raise ValueError("Module name required")
        if not self.module_storage.exists(module_name):
            raise FileNotFoundError(f'Module "{module_name}" not found')
        self._pause_for_edit()
        self.insert_step_at(
            {"type": "module", "name": module_name, "delay": 0}, at_index
        )
        self._set_status(f'Inserted module "{module_name}" at step {at_index + 1}')

    def insert_loop(
        self,
        count: int,
        *,
        source: str,
        module_name: str = "",
        indices: Optional[List[int]] = None,
        remove_selected: bool = False,
    ) -> None:
        count = max(1, min(int(count), 10000))
        loader = self.module_storage.load_steps
        if source == "module":
            mod = module_name.strip()
            if not mod or not self.module_storage.exists(mod):
                raise FileNotFoundError(f'Module "{mod}" not found')
            self.insert_step_at(
                {"type": "loop", "count": count, "module": mod, "delay": 0},
                len(self._current_steps),
            )
        else:
            if not indices:
                raise ValueError("Select steps for the loop body")
            body = collect_steps_from_indices(
                self._current_steps,
                indices,
                loader=loader,
                expand_modules=True,
            )
            if not body:
                raise ValueError("Selected steps are empty")
            if remove_selected:
                filled = fill_indices_range(indices)
                with self._lock:
                    for i in reversed(filled):
                        del self._current_steps[i]
                    at = filled[0]
                self.insert_step_at(
                    {"type": "loop", "count": count, "steps": body, "delay": 0}, at
                )
            else:
                self.insert_step_at(
                    {"type": "loop", "count": count, "steps": body, "delay": 0},
                    len(self._current_steps),
                )
        self._sync_recorder_if_paused()
        self._set_status(f"Inserted loop ×{count}")

    def _pause_for_edit(self) -> None:
        if (
            self.recorder
            and self.recorder.is_recording
            and not self.recorder.is_paused
        ):
            self.recorder.pause()

    def pause_recording(self) -> None:
        if self.recorder and self.recorder.is_recording:
            self.recorder.pause()
            self._set_status("Recording paused — edit steps in the browser")

    def resume_recording(self) -> None:
        if self.recorder and self.recorder.is_recording:
            self.recorder.resume()
            self._set_status("Recording resumed")

    # --- recording ---

    def _on_click_press(self, x: int, y: int) -> Optional[str]:
        if self._capture_session:
            return self._capture_session.click_press(x, y)
        return None

    def _on_click_complete(
        self, capture_id: str, step: dict, x1: int, y1: int, x2: int, y2: int
    ) -> None:
        if not self._capture_session:
            return
        meta = self._capture_session.click_release(capture_id, x2, y2)
        self._capture_session.attach_to_step(step, meta)
        with self._lock:
            if self._current_steps and self._current_steps[-1].get("type") == "click":
                self._current_steps[-1] = dict(step)

    def start_recording(self, *, clear: bool = True) -> None:
        if self.player.is_playing:
            raise RuntimeError("Stop playback first.")
        if not is_accessibility_granted():
            raise PermissionError(permission_hint())
        with self._lock:
            if self._recording:
                raise RuntimeError("Already recording.")
            if clear:
                self._current_steps = []
            self._recording = True
            self._loop_body_mode = False
            self._fix_messages = []

        self._capture_session = CaptureSession(self.captures_dir)

        def on_step(step: dict) -> None:
            with self._lock:
                self._current_steps.append(dict(step))
                n = len(self._current_steps)
            self._set_status(f"Recording — {n} steps")

        def on_escape() -> None:
            self.stop_recording()

        self.recorder = Recorder(
            on_step=on_step,
            on_escape=on_escape,
            on_click_press=self._on_click_press,
            on_click_complete=self._on_click_complete,
        )
        try:
            self.recorder.start()
        except Exception as exc:
            with self._lock:
                self._recording = False
            self.recorder = None
            self._capture_session = None
            raise RuntimeError(
                "Could not start listeners. Grant Accessibility and Input Monitoring, "
                "then restart."
            ) from exc
        self._set_status("Recording — switch to the target app")

    def stop_recording(self) -> Dict[str, Any]:
        with self._lock:
            if not self._recording:
                return {"steps": list(self._current_steps), "fix_messages": []}
            self._recording = False
            self._loop_body_mode = False

        self._cancel_range_pick()

        if self.recorder and self.recorder.is_recording:
            with self._lock:
                self._current_steps = self.recorder.stop()
        elif self.recorder:
            self.recorder.stop()

        with self._lock:
            self._current_steps = merge_loop_marks(self._current_steps)
            fix_msgs: List[str] = []
            if self._auto_correct:
                fixed, fix_msgs = correct_steps(self._current_steps)
                if fix_msgs:
                    self._current_steps = fixed
            self._fix_messages = fix_msgs
            count = len(self._current_steps)

        self.recorder = None
        self._capture_session = None
        self._set_status(f"Recording finished — {count} steps")
        return {"steps": list(self._current_steps), "fix_messages": fix_msgs}

    # --- loop during recording ---

    def apply_loop_mark(self, rows: int, address: str) -> None:
        if not self.recorder or not self.recorder.is_recording:
            raise RuntimeError("Start recording first")
        rows = max(1, min(int(rows), 10000))
        address = str(address).strip() or f"{rows} rows"
        if self.recorder.is_paused:
            self.recorder.resume()
        self.recorder.insert_loop_mark(rows, address)
        with self._lock:
            self._loop_body_mode = True
        self._set_status(
            f"Loop ×{rows} — record once (copy → web → paste → sheet), then Loop done"
        )

    def loop_pick_wps(self, rows: int) -> None:
        self._pause_for_edit()
        self.apply_loop_mark(rows, f"WPS {rows} rows")

    def range_pick_status(self) -> Dict[str, Any]:
        return {
            "state": self._range_pick_state,
            "message": self._range_pick_message,
            "rows": self._range_pick_rows,
            "address": self._range_pick_address,
        }

    def _cancel_range_pick(self) -> None:
        if self._range_pick_watcher:
            self._range_pick_watcher.cancel()
            self._range_pick_watcher = None
        self._range_pick_state = "idle"
        self._range_pick_message = ""
        self._range_pick_rows = None
        self._range_pick_address = ""

    def start_range_pick(self) -> Dict[str, Any]:
        if not self.recorder or not self.recorder.is_recording:
            raise RuntimeError("Start recording first")
        if RangePickWatcher is None:
            raise RuntimeError("Drag-to-select loop is macOS only")
        if is_wps_frontmost():
            raise RuntimeError("WPS detected — use WPS row count instead")

        self._cancel_range_pick()
        self._pause_for_edit()
        self._range_pick_state = "waiting"
        self._range_pick_message = "Drag to select cells in Excel…"

        def on_complete(sel) -> None:
            rows = sel.rows
            address = sel.address
            if sel.source in ("unknown", "wps") or is_wps_frontmost():
                self._range_pick_state = "confirm"
                self._range_pick_rows = rows
                self._range_pick_address = address
                self._range_pick_message = (
                    f"Detected ~{rows} rows — confirm count in the browser"
                )
            else:
                self._range_pick_state = "done"
                self._range_pick_rows = rows
                self._range_pick_address = address
                self._range_pick_message = f"Selected {address}"
            self._range_pick_watcher = None

        def on_fail(msg: str) -> None:
            self._range_pick_state = "failed"
            self._range_pick_message = msg
            self._range_pick_watcher = None
            if self.recorder and self.recorder.is_recording and self.recorder.is_paused:
                self.recorder.resume()

        self._range_pick_watcher = RangePickWatcher(on_complete, on_fail)
        self._range_pick_watcher.start()
        return self.range_pick_status()

    def confirm_range_pick(self, rows: Optional[int] = None) -> Dict[str, Any]:
        if self._range_pick_state not in ("confirm", "done"):
            raise RuntimeError("No selection ready")
        if rows is None:
            rows = self._range_pick_rows or 10
        rows = max(1, min(int(rows), 10000))
        address = self._range_pick_address or f"{rows} rows"
        self.apply_loop_mark(rows, address)
        self._cancel_range_pick()
        return self.range_pick_status()

    def cancel_range_pick(self) -> Dict[str, Any]:
        self._cancel_range_pick()
        if self.recorder and self.recorder.is_recording and self.recorder.is_paused:
            self.recorder.resume()
        self._set_status("Selection cancelled")
        return self.range_pick_status()

    def loop_body_done(self) -> Dict[str, Any]:
        with self._lock:
            self._loop_body_mode = False
            steps = list(self._current_steps)
        body = loop_body_after_mark(steps)
        warnings = []
        if body and (not any(is_copy_step(s) for s in body) or not any(is_paste_step(s) for s in body)):
            warnings.append(
                "Loop body should include Copy and Paste (copy → web → paste → sheet)"
            )
        self._set_status("Loop body recorded — continue or stop recording")
        return {"warnings": warnings}

    def capture_file_path(self, rel: str) -> Optional[Path]:
        return resolve_capture_path(self.captures_dir, rel)

    # --- playback ---

    def _prepare_steps(self, steps: List[dict]) -> List[dict]:
        prepared = merge_loop_marks(list(steps))
        with self._lock:
            if self._auto_correct:
                prepared, _ = correct_steps(prepared)
        return prepared

    def _validate_steps(self, steps: List[dict], *, path_prefix: str = "") -> Optional[str]:
        for i, step in enumerate(steps):
            loc = f"{path_prefix}step {i + 1}"
            step_type = step.get("type")
            if step_type == "module":
                name = str(step.get("name", "")).strip()
                if not name:
                    return f"{loc}: module name is empty"
                if not self.module_storage.exists(name):
                    return f'{loc}: module "{name}" does not exist'
                if not self.module_storage.load_steps(name):
                    return f'{loc}: module "{name}" has no steps'
            elif step_type == "loop":
                inner = list(step.get("steps") or [])
                mod = str(step.get("module", "")).strip()
                if not inner and not mod:
                    return f"{loc}: loop body is empty"
                if mod:
                    if not self.module_storage.exists(mod):
                        return f'{loc}: loop references missing module "{mod}"'
                    if not self.module_storage.load_steps(mod):
                        return f'{loc}: module "{mod}" has no steps'
                if inner:
                    err = self._validate_steps(inner, path_prefix=f"{loc} (loop body)")
                    if err:
                        return err
                after = list(step.get("after") or [])
                if after:
                    err = self._validate_steps(
                        after, path_prefix=f"{loc} (after loop)"
                    )
                    if err:
                        return err
        return None

    def _countdown_seconds(self, steps: List[dict]) -> int:
        loader = self.module_storage.load_steps
        return 2 if flow_has_pointer_steps(steps, loader) else 0

    def start_playback(self, *, flow_name: Optional[str] = None) -> None:
        if self._recording:
            raise RuntimeError("Stop recording first.")
        if self.player.is_playing:
            raise RuntimeError("Playback already in progress.")
        if not is_accessibility_granted():
            raise PermissionError(permission_hint())

        if flow_name:
            data = self.flow_storage.load(flow_name)
            steps = list(data.get("steps", []))
            label = flow_name
        else:
            with self._lock:
                steps = list(self._current_steps)
                label = self._current_flow_name or "Current steps"

        if not steps:
            raise ValueError("No steps to run.")

        prepared = self._prepare_steps(steps)
        err = self._validate_steps(prepared)
        if err:
            raise ValueError(err)

        countdown = self._countdown_seconds(prepared)
        with self._lock:
            self._playback_label = label
            self._playback_total = len(prepared)
            self._playback_step = 0
            self._countdown_remaining = countdown
            speed = self._playback_speed
            wait_load = self._wait_load

        if countdown > 0:
            self._set_status(f"Starting in {countdown}s — switch to the target window")
        else:
            self._set_status(f"Running “{label}”…")

        def on_countdown(remaining: int) -> None:
            with self._lock:
                self._countdown_remaining = remaining
            self._set_status(f"{remaining}s — switch to the target window")

        def on_before_step(index: int, step: dict) -> None:
            with self._lock:
                self._playback_step = index + 1
                self._countdown_remaining = 0
            self._set_status(
                f"Step {index + 1}/{len(prepared)} — {step.get('type', '?')}"
            )

        def on_step(index: int, _step: dict) -> None:
            self._set_status(f"“{label}” — step {index + 1}/{len(prepared)}")

        def on_done(step_errors=None) -> None:
            errors = step_errors or []
            if errors:
                self._set_status(
                    f"Finished with {len(errors)} error(s) — {len(prepared)} steps"
                )
            else:
                self._set_status(f"Playback finished — {len(prepared)} steps")
            with self._lock:
                self._playback_label = ""
                self._playback_step = 0
                self._playback_total = 0

        def on_error(exc: Exception) -> None:
            self._set_status(f"Playback failed: {exc}")
            with self._lock:
                self._playback_label = ""

        def on_step_error(index: int, step: dict, exc: Exception) -> None:
            self._set_status(
                f"Step {index + 1} failed ({step.get('type')}): {exc} — continuing…"
            )

        self.player.play(
            prepared,
            countdown=countdown,
            on_countdown=on_countdown if countdown > 0 else None,
            on_before_step=on_before_step,
            on_step=on_step,
            on_done=on_done,
            on_error=on_error,
            on_step_error=on_step_error,
            run_on_main=_windows_run_on_main(),
            wait_load_after_click=wait_load,
            on_wait_load=self._set_status,
            playback_speed=speed,
            module_loader=self.module_storage.load_steps,
            use_alignment=False,
        )

    def stop_playback(self) -> None:
        self.player.stop()
        self._set_status("Playback stopped")


_win_tk_root = None


def _windows_run_on_main() -> Optional[Callable[[Callable[[], None]], None]]:
    if sys.platform != "win32":
        return None
    global _win_tk_root
    if _win_tk_root is None:
        import tkinter as tk

        _win_tk_root = tk.Tk()
        _win_tk_root.withdraw()

    root = _win_tk_root

    def run_on_main(fn: Callable[[], None]) -> None:
        root.after(0, fn)
        root.update()

    return run_on_main
