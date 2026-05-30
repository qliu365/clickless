"""
界面模块 - Tkinter 图形界面，串联录制、回放与流程管理。
"""

import sys
import threading
import time
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from click_marker import ClickMarker
from flow_correct import correct_steps, detect_batch_copy_paste
from keyboard_shortcuts import clipboard_action_for_hotkey
from permissions import (
    is_accessibility_granted,
    open_accessibility_settings,
    open_input_monitoring_settings,
    permission_hint,
    request_accessibility_prompt,
)
from player import (
    Player,
    flow_has_pointer_steps,
    iter_effective_steps,
    resolve_calibration_anchor,
)
from recorder import Recorder
from recording_floater import ControlFloater, RecordingFloater
from module_storage import ModuleStorage
from storage import FlowStorage
from window_bounds import expected_click_point

if sys.platform == "darwin":
    from frontmost_app import is_wps_frontmost
    from global_hotkey import MacFloaterHotkey
    from range_pick import RangePickWatcher
else:
    MacFloaterHotkey = None  # type: ignore[misc, assignment]
    RangePickWatcher = None  # type: ignore[misc, assignment]

    def is_wps_frontmost() -> bool:  # type: ignore[misc]
        return False

from esc_listener import EscKeyListener


def _is_copy_step(step: dict) -> bool:
    if step.get("type") == "copy":
        return True
    if step.get("type") == "hotkey":
        return clipboard_action_for_hotkey(step.get("keys") or []) == "copy"
    return False


def _is_paste_step(step: dict) -> bool:
    if step.get("type") == "paste":
        return True
    if step.get("type") == "hotkey":
        return clipboard_action_for_hotkey(step.get("keys") or []) == "paste"
    return False


def _loop_body_after_mark(steps: List[dict]) -> List[dict]:
    """loop_mark 之后到下一个 loop_mark 或结尾的步骤。"""
    body: List[dict] = []
    after_mark = False
    for step in steps:
        if step.get("type") == "loop_mark":
            after_mark = True
            body.clear()
            continue
        if after_mark:
            if step.get("type") == "loop_mark":
                break
            body.append(step)
    return body


EXCEL_WEB_LOOP_HINT = (
    "Record this sequence once (do not record \"next row\"):\n\n"
    "① Cmd+C to copy the current cell\n"
    "② Click the web input field\n"
    "③ Cmd+V to paste\n"
    "④ Press Enter (if you need to submit)\n"
    "⑤ Click back to the Excel / WPS sheet\n"
    "⑥ Click Done on the floater\n\n"
    "The app will press ↓ for the next row and repeat the sequence."
)


# 界面配色
COLOR_BG = "#f5f5f5"
COLOR_RED_IDLE = "#e53935"
COLOR_RED_ACTIVE = "#b71c1c"
COLOR_RED_RING = "#c62828"
COLOR_GREEN = "#43a047"
COLOR_GREEN_ACTIVE = "#2e7d32"
COLOR_GRAY = "#9e9e9e"
COLOR_GRAY_ACTIVE = "#757575"
COLOR_TEXT = "#333333"
COLOR_MUTED = "#666666"


class _RepeatWizardDialog(tk.Toplevel):
    """录完后设置重复：看清每一步，选起止步数和次数。"""

    def __init__(
        self,
        parent: tk.Tk,
        step_labels: List[str],
        *,
        default_from: int = 1,
        default_to: Optional[int] = None,
        default_count: int = 10,
    ) -> None:
        super().__init__(parent)
        self.title("Set Repeat")
        self.resizable(True, True)
        self.minsize(420, 360)
        self.result: Optional[tuple] = None
        self.transient(parent)
        self._labels = step_labels
        n = len(step_labels)
        default_to = default_to if default_to is not None else n

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="No need to plan while recording. After recording, choose which steps to repeat here.",
            wraplength=400,
        ).pack(anchor=tk.W)

        list_frame = ttk.LabelFrame(outer, text="Your recorded steps (reference)", padding=6)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 10))

        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox = tk.Listbox(
            list_frame,
            height=min(10, max(4, n)),
            yscrollcommand=scroll.set,
            font=("Helvetica", 11),
            selectmode=tk.SINGLE,
        )
        self._listbox.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self._listbox.yview)
        for label in step_labels:
            self._listbox.insert(tk.END, label)

        opts = ttk.Frame(outer)
        opts.pack(fill=tk.X)

        ttk.Label(opts, text="From step").grid(row=0, column=0, sticky=tk.W)
        self._from_var = tk.StringVar(value=str(default_from))
        self._from_combo = ttk.Combobox(
            opts,
            textvariable=self._from_var,
            values=[str(i) for i in range(1, n + 1)],
            width=4,
            state="readonly",
        )
        self._from_combo.grid(row=0, column=1, padx=(4, 0))
        self._from_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

        ttk.Label(opts, text=" to step").grid(row=0, column=2, padx=(8, 0))
        self._to_var = tk.StringVar(value=str(default_to))
        self._to_combo = ttk.Combobox(
            opts,
            textvariable=self._to_var,
            values=[str(i) for i in range(1, n + 1)],
            width=4,
            state="readonly",
        )
        self._to_combo.grid(row=0, column=3, padx=(4, 0))
        self._to_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())

        ttk.Label(opts, text=", repeat").grid(row=0, column=4, padx=(8, 0))
        self._count_var = tk.StringVar(value=str(default_count))
        ttk.Entry(opts, textvariable=self._count_var, width=6).grid(
            row=0, column=5, padx=(4, 0)
        )
        ttk.Label(opts, text="times").grid(row=0, column=6, padx=(4, 0))

        self._preview_var = tk.StringVar()
        ttk.Label(
            outer,
            textvariable=self._preview_var,
            wraplength=400,
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(8, 0))

        ttk.Label(
            outer,
            text="Tip: For Excel iteration, usually start repeating from step 2 (step 1 clicks the first cell). The last step should be ↓.",
            wraplength=400,
            font=("Helvetica", 9),
            foreground="#888888",
        ).pack(anchor=tk.W, pady=(6, 0))

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_row, text="OK", command=self._ok, width=10).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(btn_row, text="No Repeat", command=self.destroy, width=12).pack(
            side=tk.LEFT
        )

        self._update_preview()
        self._highlight_range(default_from - 1, default_to - 1)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _update_preview(self) -> None:
        try:
            start = int(self._from_var.get()) - 1
            end = int(self._to_var.get()) - 1
            count = int(self._count_var.get().strip())
        except ValueError:
            self._preview_var.set("")
            return
        if start < 0 or end >= len(self._labels) or start > end:
            self._preview_var.set("Check the step range")
            return
        body = self._labels[start : end + 1]
        preview = " → ".join(s.split(". ", 1)[-1] for s in body[:3])
        if len(body) > 3:
            preview += f" … and {len(body)} more steps"
        self._preview_var.set(f"Will repeat {count} times: {preview}")
        self._highlight_range(start, end)

    def _highlight_range(self, start: int, end: int) -> None:
        self._listbox.selection_clear(0, tk.END)
        for i in range(start, end + 1):
            self._listbox.selection_set(i)
        if 0 <= start < self._listbox.size():
            self._listbox.see(start)

    def _ok(self) -> None:
        try:
            start = int(self._from_var.get())
            end = int(self._to_var.get())
            count = int(self._count_var.get().strip())
        except ValueError:
            messagebox.showwarning("Notice", "Enter valid step numbers and repeat count.", parent=self)
            return
        if start < 1 or end > len(self._labels) or start > end:
            messagebox.showwarning("Notice", "Start step cannot be after end step.", parent=self)
            return
        if count < 1 or count > 10000:
            messagebox.showwarning("Notice", "Repeat count must be between 1 and 10000.", parent=self)
            return
        self.result = (start - 1, end - 1, count)
        self.destroy()


class _ModulePicker(tk.Toplevel):
    """从已保存模块中选一个。"""

    def __init__(self, parent: tk.Tk, modules: List[str], *, title: str = "Select Module") -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result: Optional[str] = None
        self.transient(parent)

        frame = ttk.Frame(self, padding=12)
        frame.pack()

        ttk.Label(frame, text="Module:").grid(row=0, column=0, sticky=tk.W)
        self._combo = ttk.Combobox(frame, values=modules, state="readonly", width=28)
        self._combo.grid(row=0, column=1, padx=(6, 0))
        if modules:
            self._combo.current(0)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_row, text="OK", command=self._ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=8).pack(side=tk.LEFT)

        self.bind("<Return>", lambda _e: self._ok())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _ok(self) -> None:
        value = self._combo.get().strip()
        if value:
            self.result = value
        self.destroy()


class _InsertModuleDialog(tk.Toplevel):
    """Pick a module and an insertion point between existing steps."""

    def __init__(
        self,
        parent: tk.Tk,
        modules: List[str],
        *,
        gap_labels: List[str],
        gap_positions: List[int],
        default_position: int = 0,
    ) -> None:
        super().__init__(parent)
        self.title("Insert Module")
        self.resizable(False, False)
        self.result: Optional[tuple] = None  # (module_name, at_index)
        self.transient(parent)
        self._gap_positions = gap_positions

        frame = ttk.Frame(self, padding=12)
        frame.pack()

        ttk.Label(frame, text="Module:").grid(row=0, column=0, sticky=tk.W)
        self._module_combo = ttk.Combobox(
            frame, values=modules, state="readonly", width=30
        )
        self._module_combo.grid(row=0, column=1, padx=(6, 0), sticky=tk.W)
        if modules:
            self._module_combo.current(0)

        ttk.Label(frame, text="Insert at:").grid(row=1, column=0, sticky=tk.NW, pady=(10, 0))
        self._pos_combo = ttk.Combobox(
            frame, values=gap_labels, state="readonly", width=36
        )
        self._pos_combo.grid(row=1, column=1, padx=(6, 0), pady=(10, 0), sticky=tk.W)
        if gap_labels:
            try:
                idx = gap_positions.index(default_position)
            except ValueError:
                idx = len(gap_labels) - 1
            self._pos_combo.current(idx)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_row, text="OK", command=self._ok, width=8).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=8).pack(
            side=tk.LEFT
        )

        self.bind("<Return>", lambda _e: self._ok())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _ok(self) -> None:
        module = self._module_combo.get().strip()
        if not module:
            return
        pos_label = self._pos_combo.get()
        idx = self._pos_combo.current()
        if idx < 0 or idx >= len(self._gap_positions):
            return
        self.result = (module, self._gap_positions[idx])
        self.destroy()


class _TextStepDialog(tk.Toplevel):
    """Enter or edit text for a Type playback step."""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        initial: str = "",
        title: str = "Insert Text",
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(True, True)
        self.minsize(360, 240)
        self.result: Optional[str] = None
        self.transient(parent)

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text=(
                "This text is typed during playback. "
                "Record a click on the target field first, then insert this step after it."
            ),
            wraplength=380,
        ).pack(anchor=tk.W)

        text_frame = ttk.Frame(outer)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 10))
        scroll = ttk.Scrollbar(text_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text = tk.Text(
            text_frame,
            height=8,
            width=44,
            wrap=tk.WORD,
            font=("Helvetica", 11),
            yscrollcommand=scroll.set,
        )
        self._text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self._text.yview)
        if initial:
            self._text.insert("1.0", initial)
        self._text.focus_set()

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="OK", command=self._ok, width=10).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=10).pack(
            side=tk.LEFT
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        self.result = self._text.get("1.0", "end-1c")
        self.destroy()


class _LoopDialog(tk.Toplevel):
    """配置循环：次数 + 模块或选中步骤。"""

    def __init__(
        self,
        parent: tk.Tk,
        *,
        modules: List[str],
        has_selection: bool,
        selection_label: str = "",
    ) -> None:
        super().__init__(parent)
        self.title("Loop")
        self.resizable(False, False)
        self.result: Optional[tuple] = None
        self.transient(parent)

        frame = ttk.Frame(self, padding=12)
        frame.pack()

        ttk.Label(frame, text="Repeat count:").grid(row=0, column=0, sticky=tk.W)
        self._count_var = tk.StringVar(value="10")
        ttk.Entry(frame, textvariable=self._count_var, width=10).grid(
            row=0, column=1, sticky=tk.W, padx=(6, 0)
        )

        self._source_var = tk.StringVar(
            value="module" if modules else ("selection" if has_selection else "module")
        )

        row = 1
        if modules:
            ttk.Radiobutton(
                frame, text="Use saved module", variable=self._source_var, value="module"
            ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
            row += 1
            ttk.Label(frame, text="Module:").grid(row=row, column=0, sticky=tk.W)
            self._module_combo = ttk.Combobox(
                frame, values=modules, state="readonly", width=26
            )
            self._module_combo.grid(row=row, column=1, sticky=tk.W, padx=(6, 0))
            self._module_combo.current(0)
            row += 1
        else:
            self._module_combo = None

        if has_selection:
            ttk.Radiobutton(
                frame, text="Use currently selected steps", variable=self._source_var, value="selection"
            ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
            row += 1
            if selection_label:
                ttk.Label(
                    frame,
                    text=selection_label,
                    wraplength=300,
                    foreground="#555555",
                ).grid(row=row, column=0, columnspan=2, sticky=tk.W)
                row += 1
            self._remove_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                frame,
                text="Remove these steps from the flow (avoid running twice)",
                variable=self._remove_var,
            ).grid(row=row, column=0, columnspan=2, sticky=tk.W)
            row += 1
        else:
            self._remove_var = tk.BooleanVar(value=False)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_row, text="OK", command=self._ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=8).pack(side=tk.LEFT)

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _ok(self) -> None:
        try:
            count = int(self._count_var.get().strip())
        except ValueError:
            messagebox.showwarning("Notice", "Enter a valid repeat count.", parent=self)
            return
        if count < 1 or count > 10000:
            messagebox.showwarning("Notice", "Count must be between 1 and 10000.", parent=self)
            return

        source = self._source_var.get()
        if source == "module":
            if self._module_combo is None:
                messagebox.showwarning("Notice", "Save a module first, or select steps as the loop body.", parent=self)
                return
            module_name = self._module_combo.get().strip()
            if not module_name:
                messagebox.showwarning("Notice", "Select a module.", parent=self)
                return
            self.result = (count, "module", module_name, False)
        else:
            self.result = (count, "selection", "", self._remove_var.get())
        self.destroy()


class _LoopEditorDialog(tk.Toplevel):
    """查看/编辑循环步骤：次数、循环体、after 步骤。"""

    def __init__(
        self,
        parent: tk.Tk,
        step: dict,
        *,
        format_step_label: Callable[[int, dict], str],
        module_loader: Optional[Callable[[str], List[dict]]] = None,
    ) -> None:
        super().__init__(parent)
        self.title("Edit Loop")
        self.resizable(True, True)
        self.minsize(420, 360)
        self.result: Optional[dict] = None
        self.transient(parent)
        self._format_step_label = format_step_label
        self._module_loader = module_loader
        self._working = dict(step)
        self._module_name = str(step.get("module", "")).strip()
        self._inline_mode = not bool(self._module_name)
        self._body_steps = self._load_body_steps(step)
        self._after_steps = [dict(s) for s in (step.get("after") or [])]

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        head = ttk.Frame(outer)
        head.pack(fill=tk.X)
        ttk.Label(head, text="Repeat count:").pack(side=tk.LEFT)
        self._count_var = tk.StringVar(value=str(step.get("count", 1)))
        ttk.Entry(head, textvariable=self._count_var, width=8).pack(side=tk.LEFT, padx=(6, 0))

        self._source_var = tk.StringVar()
        self._source_label = ttk.Label(head, textvariable=self._source_var, foreground="#555555")
        self._source_label.pack(side=tk.LEFT, padx=(12, 0))
        self._refresh_source_label()

        ttk.Label(
            outer,
            text="Steps inside loop (run each iteration):",
        ).pack(anchor=tk.W, pady=(10, 4))

        body_frame = ttk.Frame(outer)
        body_frame.pack(fill=tk.BOTH, expand=True)
        body_scroll = ttk.Scrollbar(body_frame)
        body_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._body_list = tk.Listbox(
            body_frame,
            height=8,
            yscrollcommand=body_scroll.set,
            font=("Helvetica", 11),
            exportselection=False,
        )
        self._body_list.pack(fill=tk.BOTH, expand=True)
        body_scroll.config(command=self._body_list.yview)
        self._refresh_body_list()

        if self._after_steps:
            ttk.Label(
                outer,
                text="Steps after each iteration (skipped on last round):",
            ).pack(anchor=tk.W, pady=(8, 4))
            after_frame = ttk.Frame(outer)
            after_frame.pack(fill=tk.BOTH, expand=True)
            after_scroll = ttk.Scrollbar(after_frame)
            after_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self._after_list = tk.Listbox(
                after_frame,
                height=4,
                yscrollcommand=after_scroll.set,
                font=("Helvetica", 11),
                exportselection=False,
            )
            self._after_list.pack(fill=tk.BOTH, expand=True)
            after_scroll.config(command=self._after_list.yview)
            self._refresh_after_list()
        else:
            self._after_list = None

        tool_row = ttk.Frame(outer)
        tool_row.pack(fill=tk.X, pady=(8, 0))
        if self._module_name:
            ttk.Button(
                tool_row, text="Convert to Inline", command=self._convert_to_inline, width=12
            ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tool_row, text="Delete Selected", command=self._delete_selected, width=8).pack(
            side=tk.LEFT, padx=(0, 4)
        )

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="Save", command=self._ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=8).pack(side=tk.LEFT)

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _load_body_steps(self, step: dict) -> List[dict]:
        if self._module_name and self._module_loader:
            try:
                return [dict(s) for s in self._module_loader(self._module_name)]
            except (FileNotFoundError, OSError):
                return []
        return [dict(s) for s in (step.get("steps") or [])]

    def _refresh_source_label(self) -> None:
        if self._module_name and not self._inline_mode:
            self._source_var.set(f'Uses module "{self._module_name}" (click Convert to Inline to edit steps)')
        else:
            self._source_var.set(f"Inline: {len(self._body_steps)} steps")

    def _refresh_body_list(self) -> None:
        self._body_list.delete(0, tk.END)
        for i, s in enumerate(self._body_steps):
            self._body_list.insert(tk.END, self._format_step_label(i, s))

    def _refresh_after_list(self) -> None:
        if self._after_list is None:
            return
        self._after_list.delete(0, tk.END)
        for i, s in enumerate(self._after_steps):
            self._after_list.insert(tk.END, self._format_step_label(i, s))

    def _convert_to_inline(self) -> None:
        if not self._module_name:
            return
        if not self._body_steps:
            messagebox.showwarning("Notice", "Module has no steps.", parent=self)
            return
        if not messagebox.askyesno(
            "Convert to Inline",
            f'Copy steps from module "{self._module_name}" into this loop?\n'
            "You can edit them here; the module file will no longer be referenced.",
            parent=self,
        ):
            return
        self._inline_mode = True
        self._module_name = ""
        self._refresh_source_label()

    def _delete_selected(self) -> None:
        if not self._inline_mode:
            messagebox.showinfo(
                "Notice",
                "This loop references a module; you cannot delete steps directly.\nClick Convert to Inline first.",
                parent=self,
            )
            return
        body_sel = list(self._body_list.curselection())
        after_sel = list(self._after_list.curselection()) if self._after_list else []
        if not body_sel and not after_sel:
            messagebox.showwarning("Notice", "Select steps to delete in the list first.", parent=self)
            return
        if body_sel:
            if len(body_sel) >= len(self._body_steps):
                messagebox.showwarning("Notice", "Loop body must keep at least one step.", parent=self)
                return
            for i in reversed(body_sel):
                del self._body_steps[i]
            self._refresh_body_list()
        if after_sel and self._after_list is not None:
            for i in reversed(after_sel):
                del self._after_steps[i]
            self._refresh_after_list()
        self._refresh_source_label()

    def _ok(self) -> None:
        try:
            count = int(self._count_var.get().strip())
        except ValueError:
            messagebox.showwarning("Notice", "Enter a valid repeat count.", parent=self)
            return
        if count < 1 or count > 10000:
            messagebox.showwarning("Notice", "Count must be between 1 and 10000.", parent=self)
            return
        if not self._body_steps:
            messagebox.showwarning("Notice", "Loop body cannot be empty.", parent=self)
            return

        updated = dict(self._working)
        updated["type"] = "loop"
        updated["count"] = count
        updated["delay"] = updated.get("delay", 0)
        if self._inline_mode or not self._module_name:
            updated["steps"] = [dict(s) for s in self._body_steps]
            updated.pop("module", None)
        else:
            updated["module"] = self._module_name
            updated.pop("steps", None)
        if self._after_steps:
            updated["after"] = [dict(s) for s in self._after_steps]
        else:
            updated.pop("after", None)
        self.result = updated
        self.destroy()


class _ModuleEditorDialog(tk.Toplevel):
    """查看/编辑流程中的「模块」步骤。"""

    def __init__(
        self,
        parent: tk.Tk,
        module_name: str,
        steps: List[dict],
        *,
        format_step_label: Callable[[int, dict], str],
    ) -> None:
        super().__init__(parent)
        self.title(f"Module: {module_name}")
        self.resizable(True, True)
        self.minsize(400, 320)
        self.result: Optional[tuple] = None  # (module_name, steps) if saved
        self.transient(parent)
        self._module_name = module_name
        self._steps = [dict(s) for s in steps]
        self._format_step_label = format_step_label

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text=f'Steps in module "{module_name}":').pack(anchor=tk.W)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox = tk.Listbox(
            list_frame,
            height=10,
            yscrollcommand=scroll.set,
            font=("Helvetica", 11),
            exportselection=False,
        )
        self._listbox.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self._listbox.yview)
        for i, s in enumerate(self._steps):
            self._listbox.insert(tk.END, format_step_label(i, s))

        tool_row = ttk.Frame(outer)
        tool_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(tool_row, text="Delete Selected", command=self._delete_selected, width=8).pack(
            side=tk.LEFT
        )

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="Save to Module", command=self._ok, width=10).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Cancel", command=self.destroy, width=8).pack(side=tk.LEFT)

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_window()

    def _delete_selected(self) -> None:
        sel = list(self._listbox.curselection())
        if not sel:
            messagebox.showwarning("Notice", "Select steps to delete first.", parent=self)
            return
        if len(sel) >= len(self._steps):
            messagebox.showwarning("Notice", "Module must keep at least one step.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            f'Delete {len(sel)} step(s) from module "{self._module_name}"?',
            parent=self,
        ):
            return
        for i in reversed(sel):
            del self._steps[i]
        self._listbox.delete(0, tk.END)
        for i, s in enumerate(self._steps):
            self._listbox.insert(tk.END, self._format_step_label(i, s))

    def _ok(self) -> None:
        if not self._steps:
            messagebox.showwarning("Notice", "Module cannot be empty.", parent=self)
            return
        if not messagebox.askyesno(
            "Save Module",
            f'Overwrite module "{self._module_name}" with the current {len(self._steps)} steps?',
            parent=self,
        ):
            return
        self.result = (self._module_name, [dict(s) for s in self._steps])
        self.destroy()


class OfficeLegoApp:
    """OfficeLego 主窗口。"""

    def __init__(self, flows_dir: Path, modules_dir: Optional[Path] = None) -> None:
        self.flows_dir = flows_dir
        self._app_root = flows_dir.parent
        self.storage = FlowStorage(flows_dir)
        self.module_storage = ModuleStorage(
            modules_dir if modules_dir is not None else flows_dir.parent / "modules"
        )
        self.player = Player()
        self.recorder: Optional[Recorder] = None
        self._recording = False
        self._controls_locked = False

        self.root = tk.Tk()
        self.root.title("OfficeLego")
        self.root.geometry("460x520")
        self.root.minsize(420, 460)
        self.root.configure(bg=COLOR_BG)

        self._status_var = tk.StringVar(value="Ready — click the red button to start recording")
        self._flow_name_var = tk.StringVar()
        self._record_hint_var = tk.StringVar(value="Start Recording")
        self._wait_load_var = tk.BooleanVar(value=False)
        self._playback_speed_var = tk.StringVar(value="1x")
        self._hide_mouse_var = tk.BooleanVar(value=False)
        self._auto_correct_var = tk.BooleanVar(value=True)
        self._current_steps: List[dict] = []

        self._click_marker = ClickMarker(self.root)
        self._control_floater = RecordingFloater(
            self.root,
            self._on_floater_stop,
            on_pause_toggle=self._toggle_record_pause,
        )
        self._floater_mode: Optional[str] = None  # "record" | "play"
        self._floater_hotkey: Optional["MacFloaterHotkey"] = None
        self._esc_listener = EscKeyListener(on_escape=lambda: self.root.after(0, self._on_escape_key))
        self._range_pick_watcher: Optional["RangePickWatcher"] = None
        self._loop_body_mode = False
        self._rerecord_insert_at: Optional[int] = None
        self._rerecord_new_count = 0
        self._rerecord_backup: Optional[List[dict]] = None
        self._steps_edited_while_paused = False
        self._playback_during_pause_record = False
        self._accessibility_granted: Optional[bool] = None
        self._recording_exclude_rects: List[Tuple[int, int, int, int]] = []
        self._exclude_rect_refresh_job: Optional[str] = None
        self._record_boot_job: Optional[str] = None
        self._step_drag_anchor: Optional[int] = None
        self._step_click_time: float = 0.0
        self._step_click_index: Optional[int] = None
        self._step_click_count: int = 0
        self._main_thread_queue: queue.Queue = queue.Queue()
        self._poll_main_thread_queue()

        self._build_ui()
        self._refresh_flow_list()
        self.root.bind("<Escape>", lambda _e: self._on_escape_key())
        self.root.after(0, self._warm_recording_stack)
        self.root.after(500, self._check_permissions_on_startup)

    def _warm_recording_stack(self) -> None:
        """提前加载 macOS 监听依赖，避免点录制时长时间卡住。"""
        try:
            from recorder import _patch_pynput_macos_keyboard

            _patch_pynput_macos_keyboard()
            if sys.platform == "darwin":
                import scroll_capture  # noqa: F401
                import mouse_poll  # noqa: F401
        except Exception:
            pass

    def _check_permissions_on_startup(self) -> None:
        """启动时检查 macOS 权限。"""
        if sys.platform != "darwin":
            self._accessibility_granted = True
            self._set_status("Ready — click the red button to start recording")
            return
        self._accessibility_granted = is_accessibility_granted()
        if self._accessibility_granted:
            self._set_status("Ready — click the red button to start recording")
            return
        self._set_status("Missing permissions — mouse/keyboard may not work")
        request_accessibility_prompt()
        self._accessibility_granted = is_accessibility_granted()
        messagebox.showwarning("Permissions Required", permission_hint())

    def _ensure_permissions(self) -> bool:
        """录制/回放前确认权限。"""
        if sys.platform != "darwin":
            return True
        self._accessibility_granted = is_accessibility_granted()
        if self._accessibility_granted:
            return True

        request_accessibility_prompt()
        self._accessibility_granted = is_accessibility_granted()
        if self._accessibility_granted:
            return True

        answer = messagebox.askyesnocancel(
            "Permissions Required",
            permission_hint() + "\n\nYes = Open Accessibility settings\nNo = Open Input Monitoring settings",
        )
        if answer is True:
            open_accessibility_settings()
        elif answer is False:
            open_input_monitoring_settings()
        return False

    def run(self) -> None:
        """启动主循环。"""
        self.root.mainloop()

    def _build_ui(self) -> None:
        """构建界面布局。"""
        status_frame = tk.Frame(self.root, bg=COLOR_BG, padx=16, pady=10)
        status_frame.pack(fill=tk.X)
        tk.Label(
            status_frame,
            text="OfficeLego",
            font=("Helvetica", 20, "bold"),
            fg=COLOR_RED_IDLE,
            bg=COLOR_BG,
        ).pack(anchor=tk.W)
        tk.Label(
            status_frame,
            textvariable=self._status_var,
            font=("Helvetica", 11),
            fg=COLOR_TEXT,
            bg=COLOR_BG,
            wraplength=400,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 0))

        hero_frame = tk.Frame(self.root, bg=COLOR_BG, padx=16, pady=10)
        hero_frame.pack(fill=tk.X)

        control_row = tk.Frame(hero_frame, bg=COLOR_BG)
        control_row.pack()

        record_wrap = tk.Frame(control_row, bg=COLOR_BG)
        record_wrap.pack(side=tk.LEFT, padx=(0, 24))

        self._record_canvas = tk.Canvas(
            record_wrap,
            width=80,
            height=80,
            highlightthickness=0,
            bg=COLOR_BG,
            cursor="hand2",
        )
        self._record_canvas.pack()
        self._record_outer = self._record_canvas.create_oval(
            6, 6, 74, 74, fill=COLOR_RED_IDLE, outline=COLOR_RED_RING, width=3
        )
        self._record_inner = self._record_canvas.create_oval(
            28, 28, 52, 52, fill="white", outline=""
        )
        self._record_canvas.bind("<Button-1>", lambda _e: self._on_red_button_click())
        self._record_canvas.bind("<Enter>", lambda _e: self._on_record_hover(True))
        self._record_canvas.bind("<Leave>", lambda _e: self._on_record_hover(False))

        tk.Label(
            record_wrap,
            textvariable=self._record_hint_var,
            font=("Helvetica", 11, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_BG,
        ).pack(pady=(4, 0))

        action_col = tk.Frame(control_row, bg=COLOR_BG)
        action_col.pack(side=tk.LEFT, pady=4)

        self._btn_run = self._create_canvas_button(
            action_col,
            text="Run",
            fill=COLOR_GREEN,
            active_fill=COLOR_GREEN_ACTIVE,
            command=self._on_run_current,
            width=100,
            height=44,
        )
        self._btn_run.pack(pady=(0, 8))

        self._btn_stop_play = self._create_canvas_button(
            action_col,
            text="Stop",
            fill=COLOR_GRAY,
            active_fill=COLOR_GRAY_ACTIVE,
            command=self._on_stop_playback,
            width=100,
            height=32,
            disabled=True,
        )
        self._btn_stop_play.pack()

        tk.Label(
            hero_frame,
            text=(
                "Modular workflow: Save as Module → Insert Module into any gap (select a step to default the gap after it)"
            ),
            font=("Helvetica", 10),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
            wraplength=400,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 0))

        steps_frame = ttk.LabelFrame(self.root, text="Recorded Steps (multi-select)", padding=8)
        steps_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 4))

        mod_row = ttk.Frame(steps_frame)
        mod_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(mod_row, text="Save as Module", command=self._on_save_module).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(mod_row, text="Insert Module", command=self._on_insert_module).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(mod_row, text="Loop", command=self._on_insert_loop).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(mod_row, text="Re-record Selected", command=self._on_rerecord_selected).pack(
            side=tk.LEFT
        )

        mod_row2 = ttk.Frame(steps_frame)
        mod_row2.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(mod_row2, text="Insert Text", command=self._on_insert_text).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(mod_row2, text="Delete Selected", command=self._on_delete_selected_steps).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(mod_row2, text="Edit Step", command=self._on_edit_container_step).pack(
            side=tk.LEFT
        )
        tk.Label(
            mod_row2,
            text="Cmd+click to multi-select; Space to toggle; Shift for range",
            font=("Helvetica", 9),
            fg=COLOR_MUTED,
        ).pack(side=tk.LEFT, padx=(8, 0))

        steps_scroll = ttk.Scrollbar(steps_frame)
        steps_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._steps_list = tk.Listbox(
            steps_frame,
            height=5,
            yscrollcommand=steps_scroll.set,
            font=("Helvetica", 11),
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        self._steps_list.pack(fill=tk.BOTH, expand=True)
        steps_scroll.config(command=self._steps_list.yview)
        self._steps_list.bind("<<ListboxSelect>>", self._on_step_list_select)
        self._steps_list.bind("<space>", self._on_steps_list_space)
        self._steps_list.bind(
            "<Command-Button-1>", self._on_steps_list_toggle_click, add="+"
        )
        self._steps_list.bind(
            "<Control-Button-1>", self._on_steps_list_toggle_click, add="+"
        )
        self._steps_list.bind("<ButtonPress-1>", self._on_steps_drag_press)
        self._steps_list.bind("<ButtonRelease-1>", self._on_steps_drag_release)

        save_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        save_frame.pack(fill=tk.X)

        save_row = ttk.Frame(save_frame)
        save_row.pack(fill=tk.X)
        ttk.Label(save_row, text="Name").pack(side=tk.LEFT)
        ttk.Entry(save_row, textvariable=self._flow_name_var, width=18).pack(
            side=tk.LEFT, padx=(6, 8), fill=tk.X, expand=True
        )
        ttk.Button(save_row, text="Save", command=self._on_save, width=6).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(save_row, text="Run", command=self._on_run_selected, width=6).pack(
            side=tk.LEFT
        )

        flows_frame = ttk.LabelFrame(self.root, text="Saved Flows", padding=8)
        flows_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        flows_scroll = ttk.Scrollbar(flows_frame)
        flows_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._flows_list = tk.Listbox(
            flows_frame,
            height=4,
            yscrollcommand=flows_scroll.set,
            font=("Helvetica", 11),
            exportselection=False,
        )
        self._flows_list.pack(fill=tk.BOTH, expand=True)
        self._flows_list.bind("<<ListboxSelect>>", self._on_flow_select)
        self._flows_list.bind("<Double-Button-1>", self._on_flows_double_click)
        flows_scroll.config(command=self._flows_list.yview)

        flows_btn_row = ttk.Frame(flows_frame)
        flows_btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(flows_btn_row, text="Delete", command=self._on_delete_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(
            flows_btn_row, text="More Options ▼", command=self._toggle_advanced
        ).pack(side=tk.RIGHT)

        self._advanced_frame = ttk.LabelFrame(self.root, text="More Options", padding=8)
        self._build_advanced_options(self._advanced_frame)

    def _build_advanced_options(self, parent: ttk.LabelFrame) -> None:
        """高级选项：默认隐藏，网页/Safari 才需要。"""
        ttk.Checkbutton(
            parent,
            text="Wait for page load (Safari/browser only)",
            variable=self._wait_load_var,
        ).pack(anchor=tk.W)

        speed_row = ttk.Frame(parent)
        speed_row.pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(speed_row, text="Playback speed").pack(side=tk.LEFT)
        self._speed_combo = ttk.Combobox(
            speed_row,
            textvariable=self._playback_speed_var,
            values=("0.5x", "1x", "2x", "3x", "5x"),
            width=5,
            state="readonly",
        )
        self._speed_combo.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Checkbutton(
            parent,
            text="Hide cursor (Safari only; turn off for WPS/Excel)",
            variable=self._hide_mouse_var,
        ).pack(anchor=tk.W, pady=(6, 0))

        ttk.Checkbutton(
            parent,
            text="Auto-correct flow (merge text, remove duplicate clicks, fix loops)",
            variable=self._auto_correct_var,
        ).pack(anchor=tk.W, pady=(6, 0))

        tk.Label(
            parent,
            text="Recording note: press F8 or Cmd+Shift+B (on Mac, F2 may be brightness)",
            font=("Helvetica", 9),
            fg=COLOR_MUTED,
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 0))

    def _toggle_advanced(self) -> None:
        """展开/收起高级选项。"""
        if self._advanced_frame.winfo_ismapped():
            self._advanced_frame.pack_forget()
        else:
            self._advanced_frame.pack(fill=tk.X, padx=12, pady=(0, 10))

    def _create_canvas_button(
        self,
        parent,
        text: str,
        fill: str,
        active_fill: str,
        command,
        width: int = 120,
        height: int = 40,
        disabled: bool = False,
    ) -> tk.Canvas:
        """创建 Canvas 圆角按钮，兼容 macOS Tk。"""
        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bg=COLOR_BG,
            cursor="arrow" if disabled else "hand2",
        )
        rect = canvas.create_rectangle(
            2, 2, width - 2, height - 2, fill=fill, outline="", width=0
        )
        label = canvas.create_text(
            width // 2,
            height // 2,
            text=text,
            fill="white",
            font=("Helvetica", 13, "bold"),
        )
        canvas._btn_state = {
            "disabled": disabled,
            "fill": fill,
            "active_fill": active_fill,
            "command": command,
            "rect": rect,
        }

        def _click(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                command()

        def _enter(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                canvas.itemconfig(rect, fill=active_fill)

        def _leave(_event=None) -> None:
            if not canvas._btn_state["disabled"]:
                canvas.itemconfig(rect, fill=fill)

        canvas.bind("<Button-1>", _click)
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        return canvas

    def _set_canvas_button_enabled(self, canvas: tk.Canvas, enabled: bool) -> None:
        """启用/禁用 Canvas 按钮。"""
        state = canvas._btn_state
        state["disabled"] = not enabled
        canvas.config(cursor="hand2" if enabled else "arrow")
        canvas.itemconfig(state["rect"], fill=state["fill"] if enabled else COLOR_GRAY)

    def _point_in_rect(self, x: int, y: int, rect) -> bool:
        """判断点是否在矩形区域内。"""
        if rect is None:
            return False
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _get_app_window_rect(self):
        """主窗口屏幕区域（含边框）。"""
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            return (x, y, x + w, y + h)
        except tk.TclError:
            return None

    def _refresh_recording_exclude_rects(self) -> None:
        """主线程更新：录制时只忽略悬浮条区域（不可在监听线程里调 Tk）。"""
        rects: List[Tuple[int, int, int, int]] = []
        floater = self._control_floater.bounds()
        if floater:
            rects.append(floater)
        if self.recorder and self.recorder.is_recording and self.recorder.is_paused:
            main = self._get_app_window_rect()
            if main:
                rects.append(main)
        self._recording_exclude_rects = rects

    def _schedule_recording_exclude_refresh(self) -> None:
        if not self._recording:
            return
        self._refresh_recording_exclude_rects()
        self._exclude_rect_refresh_job = self.root.after(
            400, self._schedule_recording_exclude_refresh
        )

    def _stop_recording_exclude_refresh(self) -> None:
        if self._exclude_rect_refresh_job is not None:
            try:
                self.root.after_cancel(self._exclude_rect_refresh_job)
            except tk.TclError:
                pass
            self._exclude_rect_refresh_job = None
        self._recording_exclude_rects = []

    def _should_record_click(self, x: int, y: int) -> bool:
        """忽略点在 OfficeLego UI 上的点击。"""
        if self._recording_exclude_rects:
            for rect in self._recording_exclude_rects:
                if self._point_in_rect(x, y, rect):
                    return False
            return True
        for rect in (self._control_floater.bounds(),):
            if self._point_in_rect(x, y, rect):
                return False
        return True

    def _hide_for_playback(self) -> None:
        """回放时隐藏 OfficeLego，避免窗口挡住目标应用点击。"""
        self._click_marker.close_flashes()
        try:
            self.root.update_idletasks()
            if sys.platform in ("win32", "darwin"):
                # withdraw 会导致后台/主线程鼠标注入失效（Windows + macOS WPS/Excel）
                self._saved_playback_geometry = self.root.geometry()
                self.root.geometry("1x1+-200+-200")
                self.root.lower()
            else:
                self._control_floater.hide()
                self.root.withdraw()
            self.root.update_idletasks()
            self._click_marker.reanchor_host()
        except tk.TclError:
            pass

    def _show_after_playback(self) -> None:
        """回放结束后恢复主窗口。"""
        try:
            if sys.platform in ("win32", "darwin") and getattr(
                self, "_saved_playback_geometry", None
            ):
                self.root.geometry(self._saved_playback_geometry)
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _drain_main_thread_queue(self) -> None:
        while True:
            try:
                job = self._main_thread_queue.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception:
                pass

    def _poll_main_thread_queue(self) -> None:
        """主线程轮询：执行回放线程投递的鼠标/键盘操作（仅 Windows）。"""
        self._drain_main_thread_queue()
        self.root.after(20, self._poll_main_thread_queue)

    def _run_on_main_thread(self, fn: Callable[[], None], *, timeout: float = 60.0) -> None:
        """回放线程把鼠标/键盘操作切回 Tk 主线程（Windows 必须）。"""
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

        self._main_thread_queue.put(job)
        try:
            self.root.after(0, self._drain_main_thread_queue)
        except tk.TclError:
            pass
        if not done.wait(timeout):
            raise TimeoutError(
                "Playback step timed out — the UI thread may be blocked. "
                "Close any open dialogs and try again."
            )
        if state["error"] is not None:
            raise state["error"]

    def _hide_main_for_recording(self) -> None:
        """录制时把主窗口移到屏幕外，不挡住网页。"""
        try:
            self.root.update_idletasks()
            self._saved_geometry = self.root.geometry()
            self.root.geometry("1x1+-200+-200")
            self.root.lower()
        except tk.TclError:
            pass

    def _restore_main_after_recording(self) -> None:
        """录制结束后恢复主窗口。"""
        try:
            if getattr(self, "_saved_geometry", None):
                self.root.geometry(self._saved_geometry)
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _park_main_window_for_capture(self) -> None:
        """兼容旧调用：录制时等同隐藏主窗口。"""
        self._hide_main_for_recording()

    def _restore_main_window(self) -> None:
        """兼容旧调用。"""
        self._restore_main_after_recording()

    def _show_click_marker_for_step(self, step: dict, color: str, label: str) -> None:
        """对点击步骤显示落点标记。"""
        if step.get("type") != "click":
            return
        self._click_marker.flash(
            step["x"],
            step["y"],
            color=color,
            label=label,
        )

    def _parse_playback_speed(self) -> float:
        """解析界面上的倍速，如 '2x' -> 2.0。"""
        raw = self._playback_speed_var.get().strip().lower().rstrip("x")
        try:
            return max(0.1, float(raw))
        except ValueError:
            return 1.0

    def _get_calibration_anchor_from_selection(
        self, steps: List[dict]
    ) -> Tuple[Optional[Tuple[int, int]], Optional[int]]:
        """若步骤列表选中了点击步骤，用它作为运行前对齐锚点。"""
        selection = self._steps_list.curselection()
        if not selection:
            return None, None
        index = selection[0]
        if index >= len(steps):
            return None, None
        step = steps[index]
        if step.get("type") not in ("click", "double_click"):
            return None, None
        return expected_click_point(step), index

    def _on_step_list_select(self, _event=None) -> None:
        """选中步骤时，在屏幕上预览点击落点。"""
        selection = self._steps_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self._current_steps):
            return
        step = self._current_steps[index]
        if step.get("type") == "click":
            self._show_click_marker_for_step(step, COLOR_RED_IDLE, f"#{index + 1}")
            self._set_status(
                f"Step {index + 1} at ({step['x']}, {step['y']}) — "
                f"select this step before Run to align on that click"
            )
        elif step.get("type") == "loop":
            count = step.get("count", 1)
            inner = len(step.get("steps") or [])
            mod = step.get("module", "")
            hint = f'module "{mod}"' if mod else f"{inner} steps"
            self._set_status(f"Step {index + 1}: repeat {count} times ({hint}) — double-click to view/edit")
        elif step.get("type") == "module":
            self._set_status(
                f'Step {index + 1}: module "{step.get("name", "")}" — double-click to view/edit'
            )

    def _on_steps_list_toggle_click(self, event) -> str:
        """Cmd/Ctrl+点击：在列表里直接多选（不必打开单独对话框）。"""
        if not self._steps_list_editable():
            return "break"
        idx = self._steps_list.nearest(event.y)
        if idx < 0 or idx >= len(self._current_steps):
            return "break"
        self._step_drag_anchor = None
        if self._steps_list.selection_includes(idx):
            self._steps_list.selection_clear(idx)
        else:
            self._steps_list.selection_set(idx)
        self._steps_list.activate(idx)
        self._update_steps_selection_status()
        return "break"

    def _update_steps_selection_status(self) -> None:
        indices = self._get_selected_step_indices()
        if not indices:
            return
        self._set_status(self._describe_selection(indices))

    def _on_steps_list_space(self, _event=None) -> str:
        """空格切换步骤勾选。"""
        if not self._steps_list_editable():
            return "break"
        try:
            idx = int(self._steps_list.index(tk.ACTIVE))
        except tk.TclError:
            return "break"
        if idx < 0 or idx >= len(self._current_steps):
            return "break"
        if self._steps_list.selection_includes(idx):
            self._steps_list.selection_clear(idx)
        else:
            self._steps_list.selection_set(idx)
        self._update_steps_selection_status()
        return "break"

    def _on_escape_key(self) -> None:
        """Esc：停止录制、停止运行或取消拖选。"""
        if self._range_pick_watcher:
            self._cancel_loop_pick()
            return
        if self._floater_mode == "play":
            self._on_stop_playback()
        elif self._floater_mode == "record":
            self._on_stop_record()

    def _start_floater_hotkeys(self, *, recording: bool) -> None:
        """悬浮条显示时：Esc 退出（macOS 用 EventTap，避免与录制用 pynput 冲突）。"""
        trigger = lambda: self.root.after(0, self._on_escape_key)
        if sys.platform == "darwin" and MacFloaterHotkey is not None:
            if self._floater_hotkey is not None:
                self._floater_hotkey.stop()
            self._floater_hotkey = MacFloaterHotkey(
                on_escape=trigger,
                on_insert_block=(
                    (lambda: self.root.after(0, self._on_f2_insert_block))
                    if recording
                    else None
                ),
            )
            self._floater_hotkey.start()
        else:
            self._esc_listener.start()

    def _stop_floater_hotkeys(self) -> None:
        self._esc_listener.stop()
        if self._floater_hotkey is not None:
            self._floater_hotkey.stop()
            self._floater_hotkey = None

    def _on_floater_stop(self) -> None:
        """悬浮条停止按钮：录制或回放中途停止。"""
        if self._floater_mode == "record":
            self._on_stop_record()
        elif self._floater_mode == "play":
            self._on_stop_playback()

    def _toggle_record_pause(self) -> None:
        """录制悬浮条：暂停 / 继续。"""
        if not self.recorder or not self.recorder.is_recording:
            return
        if self.recorder.is_paused:
            self.recorder.resume()
            self._control_floater.set_paused(False)
            self._leave_pause_edit_mode()
        else:
            self.recorder.pause()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()

    def _enter_pause_edit_mode(self) -> None:
        """暂停后显示主窗口，便于选中步骤、存模块、设循环。"""
        self._restore_main_after_recording()
        self._refresh_recording_exclude_rects()
        self._set_canvas_button_enabled(self._btn_run, True)
        self._set_status(
            "Paused — select steps, Save as Module, Insert Module, or Run to test; click ▶ to resume"
        )

    def _leave_pause_edit_mode(self) -> None:
        if self.recorder and self.recorder.is_recording and not self.recorder.is_paused:
            self._hide_main_for_recording()
            self._refresh_recording_exclude_rects()
            self._set_canvas_button_enabled(self._btn_run, False)
            self._set_status("Resuming recording…")

    def _can_edit_steps_ui(self) -> bool:
        """录制中须先暂停才能编辑步骤 / 模块 / 循环。"""
        if self.recorder and self.recorder.is_recording and not self.recorder.is_paused:
            messagebox.showinfo(
                "Pause First",
                "While recording, click ▶ on the floater to pause,\n"
                "then select steps, save as module, or insert module.",
            )
            return False
        return True

    def _sync_recorder_steps_if_paused(self) -> None:
        if (
            self.recorder
            and self.recorder.is_recording
            and self.recorder.is_paused
        ):
            self.recorder.replace_steps(self._current_steps)
            self._steps_edited_while_paused = True

    def _on_f2_insert_block(self) -> None:
        """F8/Cmd+Shift+B/F2：暂停 → 输入积木名 → 插入 → 继续录制。"""
        if not self.recorder or not self.recorder.is_recording:
            return
        if not self.recorder.is_paused:
            self.recorder.pause()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()
        self._prompt_block_name()

    def _prompt_block_name(self) -> None:
        """弹出文本框插入积木步骤。"""
        if not self.recorder or not self.recorder.is_recording:
            return
        name = simpledialog.askstring(
            "Insert Note",
            "Enter a short note (optional; not executed during playback):",
            parent=self.root,
        )
        if name and name.strip():
            self.recorder.insert_block(name.strip())
        if self.recorder.is_recording and self.recorder.is_paused:
            self.recorder.resume()
            self._control_floater.set_paused(False)

    def _show_record_floater(self) -> None:
        self._floater_mode = "record"
        self._control_floater.show(
            title="REC",
            status="0 steps",
            color=ControlFloater.COLOR_RECORD,
            compact=True,
        )

    def _show_play_floater(self, label: str, *, initial_status: str = "Starting soon") -> None:
        self._floater_mode = "play"
        self._control_floater.show(
            title="Run",
            status=initial_status,
            color=ControlFloater.COLOR_PLAY,
            compact=True,
            playback=True,
        )
        self._start_floater_hotkeys(recording=False)

    def _hide_control_floater(self) -> None:
        self._control_floater.hide()
        self._floater_mode = None
        self._stop_floater_hotkeys()

    def _offer_save_after_record(self) -> None:
        """录制中途停止后，提示保存以便下次直接运行。"""
        if not self._current_steps:
            return
        name = self._flow_name_var.get().strip()
        if name and self.storage.exists(name):
            if messagebox.askyesno(
                "Save Flow",
                f"Update '{name}' with the current {len(self._current_steps)} steps?\n\n"
                "You can run it from Saved Flows below.",
            ):
                try:
                    self.storage.save(name, self._current_steps)
                    self._refresh_flow_list()
                    self._set_status(f"Saved '{name}' — select it below and click Run Selected")
                except (ValueError, OSError) as exc:
                    messagebox.showerror("Save Failed", str(exc))
            return

        if messagebox.askyesno(
            "Save Flow",
            f"Recorded {len(self._current_steps)} steps.\n\n"
            "Save now? You can run it anytime from Saved Flows.",
        ):
            self._on_save()

    def _on_record_hover(self, entering: bool) -> None:
        """录制按钮悬停效果。"""
        if self._controls_locked or self._recording:
            return
        color = COLOR_RED_ACTIVE if entering else COLOR_RED_IDLE
        self._record_canvas.itemconfig(self._record_outer, fill=color)

    def _set_red_button_recording(self, recording: bool) -> None:
        """更新红色按钮外观。"""
        self._recording = recording
        if recording:
            self._record_canvas.itemconfig(self._record_outer, fill=COLOR_RED_ACTIVE)
            # 录制中显示白色方块（停止图标）
            self._record_canvas.coords(self._record_inner, 30, 30, 50, 50)
            self._record_canvas.itemconfig(self._record_inner, fill="white")
            self._record_hint_var.set("Recording…")
        else:
            self._record_canvas.itemconfig(self._record_outer, fill=COLOR_RED_IDLE)
            self._record_canvas.coords(self._record_inner, 28, 28, 52, 52)
            self._record_canvas.itemconfig(self._record_inner, fill="white")
            self._record_hint_var.set("Start Recording")

    def _set_controls_locked(self, locked: bool) -> None:
        """回放期间锁定录制/运行按钮。"""
        self._controls_locked = locked
        cursor = "arrow" if locked else "hand2"
        self._record_canvas.config(cursor=cursor)
        self._set_canvas_button_enabled(self._btn_run, not locked)

    def _on_red_button_click(self) -> None:
        """红按钮：切换录制开始/停止。"""
        if self._controls_locked:
            return
        if self._recording:
            self._on_stop_record()
        else:
            self._on_start_record()

    def _set_status(self, text: str) -> None:
        """更新状态文字（线程安全；不覆盖录制悬浮条上的步数）。"""
        def apply() -> None:
            self._status_var.set(text)

        self.root.after(0, apply)

    def _format_step(self, index: int, step: dict) -> str:
        """Format a step as a short English label."""
        n = index + 1
        step_type = step.get("type")

        if step_type == "click":
            return f"{n}. Click ({step['x']}, {step['y']})"
        if step_type == "double_click":
            return f"{n}. Double-click ({step['x']}, {step['y']})"
        if step_type == "type":
            text = step.get("text", "")
            display = text if len(text) <= 16 else text[:16] + "…"
            return f'{n}. Type "{display}"'
        if step_type == "key":
            return f"{n}. Key {step.get('key', '')}"
        if step_type == "select":
            direction = str(step.get("direction", "down")).lower()
            count = step.get("count", 1)
            names = {"down": "↓", "up": "↑", "left": "←", "right": "→"}
            arrow = names.get(direction, direction)
            return f"{n}. Select {arrow} ×{count}"
        if step_type == "copy":
            return f"{n}. Copy"
        if step_type == "paste":
            return f"{n}. Paste"
        if step_type == "loop_mark":
            return f'{n}. 🔁 Loop {step.get("range", "")} ({step.get("count", "?")} rows)'
        if step_type == "block":
            return f'{n}. Note: {step.get("name", "")}'
        if step_type == "module":
            return f'{n}. Module: {step.get("name", "")}'
        if step_type == "loop":
            count = step.get("count", 1)
            inner = list(step.get("steps") or [])
            range_label = step.get("range")
            prefix = f"🔁 {range_label} ×{count}" if range_label else f"🔁 Repeat {count} times"
            if step.get("module"):
                return f"{n}. {prefix} → {step['module']}"
            if inner:
                parts = [self._step_short_label(s) for s in inner[:3]]
                preview = " → ".join(parts)
                if len(inner) > 3:
                    preview += f" …{len(inner)} steps total"
                return f"{n}. {prefix}: {preview}"
            return f"{n}. {prefix}"
        if step_type == "scroll":
            dy = float(step.get("dy", 0))
            if abs(dy) >= 0.01:
                return f"{n}. Scroll {'up' if dy > 0 else 'down'}"
            return f"{n}. Scroll"
        if step_type == "drag":
            return f"{n}. Drag"
        if step_type == "scroll_pan":
            return f"{n}. Middle-button drag"
        if step_type == "wait_load":
            return f"{n}. Wait for load"
        if step_type == "hotkey":
            keys = step.get("keys", [])
            action = clipboard_action_for_hotkey(keys)
            if action == "copy":
                return f"{n}. Copy"
            if action == "paste":
                return f"{n}. Paste"
            return f"{n}. Hotkey {'+'.join(keys)}"
        return f"{n}. {step_type or 'unknown'}"

    def _step_short_label(self, step: dict) -> str:
        """单步简短描述（用于循环预览）。"""
        step_type = step.get("type")
        if step_type == "click":
            return "Click"
        if step_type == "double_click":
            return "Double-click"
        if step_type == "type":
            text = step.get("text", "")
            return f'Type "{text[:8]}"' if text else "Type"
        if step_type == "key":
            key = step.get("key", "")
            names = {"down": "↓", "up": "↑", "left": "←", "right": "→", "enter": "Enter"}
            return names.get(str(key).lower(), str(key))
        if step_type == "select":
            direction = str(step.get("direction", "down")).lower()
            count = step.get("count", 1)
            names = {"down": "↓", "up": "↑", "left": "←", "right": "→"}
            return f"Select {names.get(direction, direction)}×{count}"
        if step_type == "copy":
            return "Copy"
        if step_type == "paste":
            return "Paste"
        if step_type == "hotkey":
            action = clipboard_action_for_hotkey(step.get("keys", []))
            if action == "copy":
                return "Copy"
            if action == "paste":
                return "Paste"
        return step_type or "?"

    def _guess_repeat_defaults(self) -> tuple[int, int, int]:
        """猜一个常见的重复范围：跳过第一步，重复到最后。"""
        n = len(self._current_steps)
        if n < 2:
            return 1, n, 10
        start = 2
        if self._current_steps[0].get("type") not in ("click", "double_click"):
            start = 1
        return start, n, 10

    def _open_repeat_wizard(self) -> None:
        """打开「设置重复」向导。"""
        if len(self._current_steps) < 2:
            messagebox.showinfo("Notice", "Record at least 2 steps to set repeat.")
            return
        labels = [self._format_step(i, s) for i, s in enumerate(self._current_steps)]
        start, end, count = self._guess_repeat_defaults()
        dialog = _RepeatWizardDialog(
            self.root,
            labels,
            default_from=start,
            default_to=end,
            default_count=count,
        )
        if dialog.result:
            s, e, c = dialog.result
            self._apply_repeat_range(s, e, c)

    def _apply_repeat_range(self, start: int, end: int, count: int) -> None:
        """把 [start, end] 步合并为一步循环。"""
        if start > end or start < 0 or end >= len(self._current_steps):
            return
        body = [dict(self._current_steps[i]) for i in range(start, end + 1)]
        before = self._current_steps[:start]
        after = self._current_steps[end + 1 :]
        loop_step = {"type": "loop", "count": count, "steps": body, "delay": 0}
        self._current_steps = before + [loop_step] + after
        self._refresh_steps_list()
        self._steps_list.selection_clear(0, tk.END)
        self._steps_list.selection_set(len(before))
        self._steps_list.see(len(before))
        self._set_status(f"Set steps {start + 1}–{end + 1} to repeat {count} times")

    def _on_set_repeat(self) -> None:
        self._open_repeat_wizard()

    def _apply_loop_mark(self, rows: int, address: str) -> None:
        """插入循环标记并进入「录一遍」模式。"""
        if not self.recorder or not self.recorder.is_recording:
            return
        self.recorder.insert_loop_mark(rows, address)
        self._loop_body_mode = True
        self._control_floater.set_loop_body_mode(True)
        self.recorder.resume()
        self._control_floater.set_paused(False)
        self._control_floater.set_status(f"Loop ×{rows} — record once (no ↓ needed)")
        self._set_status(
            f"Looping {rows} rows. Record once: copy → web → paste → back to sheet, then click Done."
        )
        messagebox.showinfo("Excel → Web Loop", EXCEL_WEB_LOOP_HINT, parent=self.root)

    def _on_loop_pick_wps_rows(self) -> None:
        """WPS：无拖选蓝框，直接输入行数。"""
        if not self.recorder.is_paused:
            self.recorder.pause()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()
        self._control_floater.set_status("WPS: enter row count…")

        rows = simpledialog.askinteger(
            "WPS Loop Row Count",
            "WPS drag-select has no highlight box — enter the row count.\n\n"
            "Make sure you clicked the first cell, then enter how many rows to loop:",
            initialvalue=10,
            minvalue=1,
            maxvalue=10000,
            parent=self.root,
        )
        if rows is None:
            self._cancel_loop_pick()
            return
        self._apply_loop_mark(rows, f"WPS {rows} rows")

    def _on_loop_pick_cells(self) -> None:
        """悬浮条 🔁：Excel 拖选 / WPS 输入行数。"""
        if not self.recorder or not self.recorder.is_recording:
            return

        if is_wps_frontmost():
            self._on_loop_pick_wps_rows()
            return

        if RangePickWatcher is None:
            messagebox.showinfo("Notice", "Drag-to-select loop is macOS only.")
            return
        if self._range_pick_watcher:
            self._range_pick_watcher.cancel()
        if not self.recorder.is_paused:
            self.recorder.pause()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()

        self._control_floater.set_status("Excel: drag to select cells to loop…")

        def on_complete(sel) -> None:
            def apply() -> None:
                if not self.recorder or not self.recorder.is_recording:
                    return
                rows = sel.rows
                if sel.source in ("unknown", "wps") or is_wps_frontmost():
                    adjusted = simpledialog.askinteger(
                        "Confirm Row Count",
                        f"Detected about {rows} rows.\nHow many rows should the loop run?",
                        initialvalue=rows,
                        minvalue=1,
                        maxvalue=10000,
                        parent=self.root,
                    )
                    if adjusted is None:
                        self._cancel_loop_pick()
                        return
                    rows = adjusted

                self._apply_loop_mark(rows, sel.address)
                self._range_pick_watcher = None

            self.root.after(0, apply)

        def on_fail(msg: str) -> None:
            def apply() -> None:
                self._cancel_loop_pick()
                messagebox.showwarning("Selection Cancelled", msg)
            self.root.after(0, apply)

        self._range_pick_watcher = RangePickWatcher(on_complete, on_fail)
        self._range_pick_watcher.start()

    def _cancel_loop_pick(self) -> None:
        if self._range_pick_watcher:
            self._range_pick_watcher.cancel()
            self._range_pick_watcher = None
        if self.recorder and self.recorder.is_recording and self.recorder.is_paused:
            self.recorder.resume()
            self._control_floater.set_paused(False)
        self._control_floater.set_status("Waiting…")

    def _on_loop_body_done(self) -> None:
        """循环体录完。"""
        if not self._loop_body_mode:
            return
        self._loop_body_mode = False
        self._control_floater.set_loop_body_mode(False)
        body = _loop_body_after_mark(self._current_steps)
        has_copy = any(_is_copy_step(s) for s in body)
        has_paste = any(_is_paste_step(s) for s in body)
        if body and (not has_copy or not has_paste):
            messagebox.showwarning(
                "Incomplete Loop Body",
                "The loop should include one Copy and one Paste.\n\n"
                "Pause and delete wrong steps, or stop and re-record.\n"
                "Correct order: copy → click web → paste → back to sheet → Done",
                parent=self.root,
            )
        self._set_status("Loop body recorded. Continue recording or stop to save.")
        self._control_floater.set_status("Loop ready")

    def _merge_loop_marks(self, steps: List[dict]) -> List[dict]:
        """把 loop_mark + 后续步骤合并为 loop 步骤。"""
        if not any(s.get("type") == "loop_mark" for s in steps):
            return list(steps)
        merged: List[dict] = []
        i = 0
        while i < len(steps):
            step = steps[i]
            if step.get("type") != "loop_mark":
                merged.append(step)
                i += 1
                continue
            count = int(step.get("count", 1))
            range_label = step.get("range", "")
            body: List[dict] = []
            i += 1
            while i < len(steps):
                nxt = steps[i]
                if nxt.get("type") == "loop_mark":
                    break
                body.append(nxt)
                i += 1
            while (
                body
                and body[-1].get("type") == "key"
                and str(body[-1].get("key", "")).lower() == "down"
            ):
                body.pop()
            merged.append(
                {
                    "type": "loop",
                    "count": count,
                    "steps": body,
                    "range": range_label,
                    "after": [{"type": "key", "key": "down", "delay": 0.15}],
                    "delay": step.get("delay", 0),
                }
            )
        return merged

    def _finalize_loop_marks(self) -> None:
        """把 loop_mark + 后续步骤合并为 loop 步骤。"""
        self._current_steps = self._merge_loop_marks(self._current_steps)

    def _has_loop_from_cells(self) -> bool:
        return any(
            s.get("type") in ("loop_mark", "loop") and s.get("range")
            for s in self._current_steps
        )

    def _offer_repeat_after_record(self) -> None:
        """录完后询问是否设置重复。"""
        if self._has_loop_from_cells():
            return
        if len(self._current_steps) < 2:
            return
        if messagebox.askyesno(
            "Set Repeat?",
            f"Recorded {len(self._current_steps)} steps.\n\n"
            "Repeat some of them?\n"
            "(The next screen lists each step to choose from.)",
        ):
            self._open_repeat_wizard()

    def _gap_insert_labels(self) -> tuple[List[str], List[int]]:
        """Labels for every gap: before step 1, between steps, after last."""
        n = len(self._current_steps)
        if n == 0:
            return ["Start of flow"], [0]
        labels = ["Before step 1"]
        positions = [0]
        for i in range(n - 1):
            preview = self._step_short_label(self._current_steps[i])
            labels.append(f"After step {i + 1} ({preview})")
            positions.append(i + 1)
        labels.append(f"After step {n} (end)")
        positions.append(n)
        return labels, positions

    def _default_gap_insert_index(self) -> int:
        indices = self._get_selected_step_indices()
        if indices:
            return indices[-1] + 1
        return len(self._current_steps)

    def _insert_step_at(self, step: dict, at_index: int) -> None:
        """Insert a step at a specific index (0 = before first step)."""
        at_index = max(0, min(at_index, len(self._current_steps)))
        self._current_steps.insert(at_index, step)
        self._refresh_steps_list()
        self._steps_list.selection_clear(0, tk.END)
        self._steps_list.selection_set(at_index)
        self._steps_list.see(at_index)
        self._sync_recorder_steps_if_paused()

    def _insert_step(self, step: dict, *, after_selection: bool = True) -> None:
        """插入一步；若列表有选中项，插在选中区之后。"""
        if after_selection:
            indices = self._get_selected_step_indices()
            if indices:
                self._insert_step_at(step, indices[-1] + 1)
                return
        self._insert_step_at(step, len(self._current_steps))

    def _append_step(self, step: dict) -> None:
        """向当前流程追加一步并刷新列表。"""
        self._current_steps.append(step)
        self._steps_list.insert(
            tk.END, self._format_step(len(self._current_steps) - 1, step)
        )

    def _get_selected_step_indices(self) -> List[int]:
        return sorted(int(i) for i in self._steps_list.curselection())

    def _apply_step_selection(self, indices: List[int]) -> None:
        self._steps_list.selection_clear(0, tk.END)
        for i in indices:
            if 0 <= i < len(self._current_steps):
                self._steps_list.selection_set(i)
        if indices:
            self._steps_list.see(indices[0])

    def _click_has_selection_modifier(self, event) -> bool:
        """Shift/Ctrl/Cmd 点击时只做多选，不触发拖拽。"""
        return bool(event.state & 0x000D)  # Shift | Control | Mod1(Command)

    def _fill_indices_range(self, indices: List[int]) -> List[int]:
        """从最小到最大选中步，中间步骤也一并包含。"""
        if not indices:
            return []
        indices = sorted(set(indices))
        if len(indices) == 1:
            return indices
        return list(range(indices[0], indices[-1] + 1))

    def _describe_selection(self, indices: List[int]) -> str:
        """选中步骤的中文说明（不相邻选中时中间步骤也会包含）。"""
        if not indices:
            return ""
        indices = sorted(set(indices))
        if len(indices) == 1:
            return f"Selected step {indices[0] + 1}"
        filled = self._fill_indices_range(indices)
        if len(filled) == len(indices):
            return f"Selected steps {indices[0] + 1}–{indices[-1] + 1} ({len(indices)} steps)"
        picked = ", ".join(str(i + 1) for i in indices)
        return (
            f"Checked steps {picked} → includes steps {filled[0] + 1}–{filled[-1] + 1}"
            f" ({len(filled)} steps total; steps in between run in order)"
        )

    def _expand_step_for_module(self, step: dict) -> List[dict]:
        """模块调用展开为具体步骤；普通步骤原样保留。"""
        if step.get("type") != "module":
            return [dict(step)]
        name = str(step.get("name", "")).strip()
        if not name:
            return [dict(step)]
        try:
            return [dict(s) for s in self.module_storage.load_steps(name)]
        except (FileNotFoundError, OSError):
            return [dict(step)]

    def _collect_steps_from_indices(
        self,
        indices: List[int],
        *,
        expand_modules: bool = True,
        fill_range: bool = True,
    ) -> List[dict]:
        """收集步骤；从最小到最大步号之间全部包含（含中间未勾选项）。"""
        sorted_idx = sorted(set(indices))
        if fill_range and len(sorted_idx) > 1:
            sorted_idx = self._fill_indices_range(sorted_idx)
        out: List[dict] = []
        for i in sorted_idx:
            if i < 0 or i >= len(self._current_steps):
                continue
            step = dict(self._current_steps[i])
            if expand_modules and step.get("type") == "module":
                out.extend(self._expand_step_for_module(step))
            else:
                out.append(step)
        return out

    def _inner_step_label(self, index: int, step: dict) -> str:
        line = self._format_step(index, step)
        if ". " in line:
            return line.split(". ", 1)[-1]
        return line

    def _is_container_step(self, step: dict) -> bool:
        return step.get("type") in ("loop", "module")

    def _on_insert_text(self) -> None:
        """Insert a Type step with user-written text."""
        if not self._can_edit_steps_ui():
            return
        dialog = _TextStepDialog(self.root, title="Insert Text")
        if dialog.result is None:
            return
        text = dialog.result
        if not text.strip():
            messagebox.showwarning(
                "Notice", "Text cannot be empty.", parent=self.root
            )
            return
        self._insert_step({"type": "type", "text": text, "delay": 0.15})
        self._set_status("Inserted text step")

    def _on_edit_container_step(self) -> None:
        """Edit selected loop, module, or type step."""
        if not self._can_edit_steps_ui():
            return
        indices = self._get_selected_step_indices()
        if len(indices) != 1:
            messagebox.showwarning(
                "Notice",
                "Select one Loop, Module, or Type step to edit.",
                parent=self.root,
            )
            return
        self._open_container_editor(indices[0])

    def _open_container_editor(self, index: int) -> None:
        if index < 0 or index >= len(self._current_steps):
            return
        if not self._can_edit_steps_ui():
            return
        step = self._current_steps[index]
        step_type = step.get("type")

        if step_type == "loop":
            dialog = _LoopEditorDialog(
                self.root,
                step,
                format_step_label=self._inner_step_label,
                module_loader=self.module_storage.load_steps,
            )
            if not dialog.result:
                return
            self._current_steps[index] = dialog.result
        elif step_type == "module":
            name = str(step.get("name", "")).strip()
            if not name:
                messagebox.showwarning("Notice", "Module name is empty.", parent=self.root)
                return
            try:
                body = self.module_storage.load_steps(name)
            except (FileNotFoundError, OSError) as exc:
                messagebox.showerror("Load Failed", str(exc), parent=self.root)
                return
            dialog = _ModuleEditorDialog(
                self.root,
                name,
                body,
                format_step_label=self._inner_step_label,
            )
            if not dialog.result:
                return
            mod_name, mod_steps = dialog.result
            try:
                self.module_storage.save(mod_name, mod_steps)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Save Failed", str(exc), parent=self.root)
                return
            messagebox.showinfo("Success", f'Module "{mod_name}" updated.', parent=self.root)
        elif step_type == "type":
            dialog = _TextStepDialog(
                self.root,
                initial=str(step.get("text", "")),
                title="Edit Text",
            )
            if dialog.result is None:
                return
            if not dialog.result.strip():
                messagebox.showwarning(
                    "Notice", "Text cannot be empty.", parent=self.root
                )
                return
            updated = dict(step)
            updated["text"] = dialog.result
            self._current_steps[index] = updated
        else:
            messagebox.showwarning(
                "Notice",
                "Select a Loop, Module, or Type step.",
                parent=self.root,
            )
            return

        self._refresh_steps_list()
        self._steps_list.selection_clear(0, tk.END)
        self._steps_list.selection_set(index)
        self._steps_list.see(index)
        self._sync_recorder_steps_if_paused()
        self._set_status(f"Updated step {index + 1}")

    def _on_save_module(self) -> None:
        """把选中的步骤（含模块调用、可不相邻）存为可复用模块。"""
        if not self._can_edit_steps_ui():
            return
        indices = self._get_selected_step_indices()
        if not indices:
            messagebox.showwarning(
                "Notice",
                "Select steps in the list with Cmd+click or Space.",
                parent=self.root,
            )
            return
        self._save_module_from_indices(indices)

    def _save_module_from_indices(self, indices: List[int]) -> None:
        sel_desc = self._describe_selection(indices)
        has_module_ref = any(
            self._current_steps[i].get("type") == "module" for i in indices
        )
        expand = True
        if has_module_ref:
            expand = messagebox.askyesno(
                "Expand Modules?",
                f"{sel_desc}\n\n"
                "Selection includes Module steps.\n"
                "Expand them into concrete actions before saving?\n\n"
                "Yes = expand then save (recommended)\n"
                "No = keep as module references",
                parent=self.root,
            )
        name = simpledialog.askstring(
            "Save as Module",
            f"{sel_desc}\n\nModule name (e.g. Copy to web):",
            parent=self.root,
        )
        if not name or not name.strip():
            return
        mod_name = name.strip()
        steps = self._collect_steps_from_indices(indices, expand_modules=expand)
        if not steps:
            messagebox.showwarning("Notice", "No steps to save.", parent=self.root)
            return
        filled = self._fill_indices_range(indices)
        try:
            if self.module_storage.exists(mod_name):
                if not messagebox.askyesno(
                    "Overwrite Module",
                    f'Module "{mod_name}" already exists. Overwrite with the selected {len(steps)} steps?',
                    parent=self.root,
                ):
                    return
            self.module_storage.save(mod_name, steps)
            insert_at = filled[0]
            removed = len(filled)
            for i in reversed(filled):
                del self._current_steps[i]
            self._current_steps.insert(
                insert_at,
                {"type": "module", "name": mod_name, "delay": 0},
            )
            self._refresh_steps_list()
            self._steps_list.selection_clear(0, tk.END)
            self._steps_list.selection_set(insert_at)
            self._steps_list.see(insert_at)
            self._sync_recorder_steps_if_paused()
            messagebox.showinfo(
                "Success",
                f'Module "{mod_name}" saved ({len(steps)} steps).\n'
                f"Steps {insert_at + 1}–{insert_at + removed} were removed and replaced with a Module step.",
                parent=self.root,
            )
            self._set_status(
                f'Saved module "{mod_name}" — replaced {removed} steps'
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save Failed", str(exc), parent=self.root)

    def _on_delete_selected_steps(self) -> None:
        """删除步骤列表中选中的步骤。"""
        if not self._can_edit_steps_ui():
            return
        indices = self._get_selected_step_indices()
        if not indices:
            messagebox.showwarning("Notice", "Select steps to delete first.")
            return
        if not messagebox.askyesno(
            "Delete Steps",
            f"Delete steps {indices[0] + 1}–{indices[-1] + 1} ({len(indices)} steps)?",
        ):
            return
        for i in reversed(indices):
            del self._current_steps[i]
        self._refresh_steps_list()
        self._sync_recorder_steps_if_paused()
        self._set_status(f"Deleted {len(indices)} steps")

    def _on_rerecord_selected(self) -> None:
        """删除选中步骤并重新录制替换。"""
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Stop playback first.")
            return
        if self.recorder and self.recorder.is_recording:
            messagebox.showwarning("Notice", "Already recording.")
            return
        indices = self._get_selected_step_indices()
        if not indices:
            messagebox.showwarning(
                "Notice",
                "Select steps to re-record (Shift/Cmd for multi-select).",
            )
            return
        if not messagebox.askyesno(
            "Re-record Selected",
            f"Delete steps {indices[0] + 1}–{indices[-1] + 1} and re-record.\n"
            "New steps will be inserted at the same position when you stop recording.",
        ):
            return
        if not self._ensure_permissions():
            return

        self._rerecord_backup = [dict(self._current_steps[i]) for i in indices]
        insert_at = indices[0]
        for i in reversed(indices):
            del self._current_steps[i]
        self._refresh_steps_list()
        self._start_record_session(splice_at=insert_at)

    def _pause_recording_for_step_edit(self) -> None:
        """Auto-pause so modules can be inserted between steps while recording."""
        if (
            self.recorder
            and self.recorder.is_recording
            and not self.recorder.is_paused
        ):
            self.recorder.pause()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()

    def _on_insert_module(self) -> None:
        """Insert a module step at a chosen gap between existing steps."""
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Stop playback first.", parent=self.root)
            return
        self._pause_recording_for_step_edit()
        if not self._can_edit_steps_ui():
            return
        modules = [m["name"] for m in self.module_storage.list_modules()]
        if not modules:
            messagebox.showwarning(
                "Notice",
                "No modules yet. Select steps and click Save as Module.",
                parent=self.root,
            )
            return
        gap_labels, gap_positions = self._gap_insert_labels()
        default_at = self._default_gap_insert_index()
        if not self._current_steps:
            picker = _ModulePicker(self.root, modules, title="Insert Module")
            if not picker.result:
                return
            mod_name = picker.result
            at_index = 0
        else:
            dialog = _InsertModuleDialog(
                self.root,
                modules,
                gap_labels=gap_labels,
                gap_positions=gap_positions,
                default_position=default_at,
            )
            if not dialog.result:
                return
            mod_name, at_index = dialog.result
        self._insert_step_at(
            {"type": "module", "name": mod_name, "delay": 0},
            at_index,
        )
        self._set_status(f'Inserted module "{mod_name}" at step {at_index + 1}')

    def _on_insert_loop(self) -> None:
        """插入循环步骤。"""
        if not self._can_edit_steps_ui():
            return
        modules = [m["name"] for m in self.module_storage.list_modules()]
        indices = self._get_selected_step_indices()
        if not modules and not indices:
            messagebox.showwarning(
                "Notice",
                "Save as Module first, or select steps to repeat in the list.",
                parent=self.root,
            )
            return

        dialog = _LoopDialog(
            self.root,
            modules=modules,
            has_selection=bool(indices),
            selection_label=self._describe_selection(indices) if indices else "",
        )
        if not dialog.result:
            return

        count, source, module_name, remove_selected = dialog.result
        if source == "module":
            self._insert_step(
                {
                    "type": "loop",
                    "count": count,
                    "module": module_name,
                    "delay": 0,
                }
            )
            self._sync_recorder_steps_if_paused()
            return

        self._insert_loop_from_indices(indices, count=count, remove_selected=remove_selected)

    def _insert_loop_from_indices(
        self,
        indices: List[int],
        *,
        count: Optional[int] = None,
        remove_selected: Optional[bool] = None,
    ) -> None:
        """把选中的步骤（可不相邻）设为循环体。"""
        if not indices:
            messagebox.showwarning("Notice", "No steps selected.", parent=self.root)
            return
        sel_desc = self._describe_selection(indices)
        if count is None:
            count = simpledialog.askinteger(
                "Repeat Count",
                f"{sel_desc}\n\nHow many times should these steps repeat?",
                initialvalue=10,
                minvalue=1,
                maxvalue=10000,
                parent=self.root,
            )
            if count is None:
                return
        if remove_selected is None:
            remove_selected = messagebox.askyesno(
                "Remove Original Steps?",
                f"{sel_desc}\n\n"
                "Remove the original steps from the flow and keep only the loop?\n\n"
                "Choose Yes to avoid running the same steps twice.",
                parent=self.root,
            )

        body = self._collect_steps_from_indices(indices, expand_modules=True)
        if not body:
            messagebox.showwarning("Notice", "Selected steps are empty.", parent=self.root)
            return
        if remove_selected:
            remove_indices = self._fill_indices_range(indices)
            for i in reversed(remove_indices):
                del self._current_steps[i]
            self._refresh_steps_list()
        self._insert_step(
            {"type": "loop", "count": count, "steps": body, "delay": 0},
            after_selection=False,
        )
        self._sync_recorder_steps_if_paused()

    def _steps_list_editable(self) -> bool:
        """是否允许拖拽/删除等编辑步骤列表。"""
        if self._controls_locked:
            return False
        if self.recorder and self.recorder.is_recording and not self.recorder.is_paused:
            return False
        return True

    def _on_flows_double_click(self, event) -> None:
        """双击流程：按点击位置选中并运行（macOS 上 curselection 可能尚未更新）。"""
        idx = self._flows_list.nearest(event.y)
        flows = self.storage.list_flows()
        if idx < 0 or idx >= len(flows):
            return
        self._flows_list.selection_clear(0, tk.END)
        self._flows_list.selection_set(idx)
        self._flows_list.activate(idx)
        name = flows[idx]["name"]
        try:
            data = self.storage.load(name)
            steps = data.get("steps", [])
            self._current_steps = steps
            self._flow_name_var.set(name)
            self._refresh_steps_list()
            self._start_playback(steps, name)
        except (FileNotFoundError, OSError) as exc:
            messagebox.showerror("Load Failed", str(exc))

    def _on_steps_drag_press(self, event) -> None:
        if not self._steps_list_editable():
            self._step_drag_anchor = None
            return
        if self._click_has_selection_modifier(event):
            self._step_drag_anchor = None
            return
        self._step_drag_anchor = self._steps_list.nearest(event.y)

    def _on_steps_drag_release(self, event) -> None:
        anchor = self._step_drag_anchor
        self._step_drag_anchor = None
        if anchor is None or not self._steps_list_editable():
            return
        if self._click_has_selection_modifier(event):
            return
        # 快速连点（双击）时不触发拖拽
        now = time.time()
        target = self._steps_list.nearest(event.y)
        if (
            self._step_click_index == target
            and now - self._step_click_time < 0.45
        ):
            self._step_click_count += 1
        else:
            self._step_click_count = 1
        self._step_click_time = now
        self._step_click_index = target

        if self._step_click_count >= 2:
            self._step_click_count = 0
            if (
                self._can_edit_steps_ui()
                and 0 <= target < len(self._current_steps)
            ):
                self._apply_step_selection([target])
                step = self._current_steps[target]
                if self._is_container_step(step):
                    self._open_container_editor(target)
                    return
                self._save_module_from_indices([target])
            return
        if anchor >= len(self._current_steps):
            return

        target = self._steps_list.nearest(event.y)
        target = max(0, min(target, len(self._current_steps) - 1))

        indices = self._get_selected_step_indices()
        if not indices or anchor not in indices:
            indices = [anchor]

        if len(indices) == 1 and indices[0] == target:
            return
        if len(indices) > 1 and min(indices) <= target <= max(indices):
            return

        self._move_step_block(indices, target)

    def _move_step_block(self, from_indices: List[int], to_index: int) -> None:
        """把选中的一段步骤拖到 to_index 位置。"""
        from_indices = sorted(set(from_indices))
        if not from_indices or not self._current_steps:
            return

        block = [dict(self._current_steps[i]) for i in from_indices]
        for i in reversed(from_indices):
            del self._current_steps[i]

        removed_before = sum(1 for i in from_indices if i < to_index)
        insert_at = max(0, min(len(self._current_steps), to_index - removed_before))

        for offset, step in enumerate(block):
            self._current_steps.insert(insert_at + offset, step)

        self._refresh_steps_list()
        self._steps_list.selection_clear(0, tk.END)
        for i in range(insert_at, insert_at + len(block)):
            self._steps_list.selection_set(i)
        self._steps_list.see(insert_at)
        self._sync_recorder_steps_if_paused()
        self._set_status(f"Moved {len(block)} steps to position {insert_at + 1}")

    def _refresh_steps_list(self) -> None:
        """刷新当前步骤列表显示。"""
        self._steps_list.delete(0, tk.END)
        for i, step in enumerate(self._current_steps):
            self._steps_list.insert(tk.END, self._format_step(i, step))

    def _refresh_flow_list(self) -> None:
        """刷新已保存流程列表。"""
        self._flows_list.delete(0, tk.END)
        for flow in self.storage.list_flows():
            self._flows_list.insert(tk.END, f"{flow['name']} ({flow['step_count']} steps)")

    def _get_selected_flow_name(self) -> Optional[str]:
        """获取列表中选中的流程名称。"""
        selection = self._flows_list.curselection()
        if not selection:
            return None
        flows = self.storage.list_flows()
        index = selection[0]
        if index >= len(flows):
            return None
        return flows[index]["name"]

    def _on_flow_select(self, _event=None) -> None:
        """选中流程时加载步骤预览。"""
        name = self._get_selected_flow_name()
        if not name:
            return
        try:
            data = self.storage.load(name)
            self._current_steps = data.get("steps", [])
            self._flow_name_var.set(name)
            self._refresh_steps_list()
        except (FileNotFoundError, OSError):
            pass

    def _start_record_session(self, *, splice_at: Optional[int] = None) -> None:
        """开始录制；splice_at 不为 None 时为「重录选中」模式。"""
        self._rerecord_insert_at = splice_at
        self._rerecord_new_count = 0
        self._loop_body_mode = False

        if splice_at is None:
            self._current_steps = []
            self._rerecord_backup = None
            self._refresh_steps_list()

        def on_step(step: dict) -> None:
            def update() -> None:
                if self._rerecord_insert_at is not None:
                    idx = self._rerecord_insert_at + self._rerecord_new_count
                    self._current_steps.insert(idx, step)
                    self._rerecord_new_count += 1
                    self._refresh_steps_list()
                    n = self._rerecord_new_count
                else:
                    self._current_steps.append(step)
                    self._steps_list.insert(
                        tk.END,
                        self._format_step(len(self._current_steps) - 1, step),
                    )
                    n = len(self._current_steps)
                self._control_floater.set_status(f"{n} steps")

            self.root.after(0, update)

        def on_f2() -> None:
            self.root.after(0, self._on_f2_insert_block)

        def on_escape() -> None:
            self.root.after(0, self._on_escape_key)

        self.recorder = Recorder(
            on_step=on_step,
            should_record_click=self._should_record_click,
            on_f2=on_f2,
            on_escape=on_escape,
        )

        self._set_red_button_recording(True)
        self._set_canvas_button_enabled(self._btn_run, False)
        self._floater_mode = "record"
        self._hide_main_for_recording()
        self._show_record_floater()
        self._control_floater.set_status("0 steps")
        self.root.update_idletasks()
        if self._record_boot_job is not None:
            try:
                self.root.after_cancel(self._record_boot_job)
            except tk.TclError:
                pass
        self._record_boot_job = self.root.after(
            1, lambda: self._boot_recording_listeners(splice_at=splice_at)
        )

    def _boot_recording_listeners(self, *, splice_at: Optional[int]) -> None:
        """界面已显示后再启动监听（主线程，避免一点录制就卡住）。"""
        self._record_boot_job = None
        if not self._recording or self.recorder is None:
            return
        try:
            self.recorder.start()
        except Exception:
            messagebox.showerror(
                "Recording Failed",
                "Could not start mouse/keyboard listeners.\n\n"
                "In System Settings → Privacy & Security → Accessibility / Input Monitoring, "
                "allow Terminal or Python, then restart the app.",
            )
            self._on_stop_record()
            return
        self._refresh_recording_exclude_rects()
        self._schedule_recording_exclude_refresh()
        self._start_floater_hotkeys(recording=True)
        if splice_at is not None:
            self._set_status(f"Re-recording: new steps will insert at step {splice_at + 1}")
        else:
            self._set_status("Recording — use the target app")

    def _on_start_record(self) -> None:
        """开始录制（全新流程）。"""
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Stop playback first.")
            return
        if not self._ensure_permissions():
            return
        self._start_record_session(splice_at=None)

    def _on_stop_record(self) -> None:
        """停止录制。"""
        if not self._recording:
            return

        if self._record_boot_job is not None:
            try:
                self.root.after_cancel(self._record_boot_job)
            except tk.TclError:
                pass
            self._record_boot_job = None

        if self._range_pick_watcher:
            self._range_pick_watcher.cancel()
            self._range_pick_watcher = None

        was_rerecord = self._rerecord_insert_at is not None
        insert_at = self._rerecord_insert_at
        backup = self._rerecord_backup
        new_count = self._rerecord_new_count

        if self.recorder and self.recorder.is_recording:
            if was_rerecord:
                self.recorder.stop()
                if new_count == 0 and backup and insert_at is not None:
                    for i, step in enumerate(backup):
                        self._current_steps.insert(insert_at + i, step)
            else:
                if self._steps_edited_while_paused:
                    self.recorder.replace_steps(self._current_steps)
                self._current_steps = self.recorder.stop()
        elif self.recorder:
            self.recorder.stop()

        self._rerecord_insert_at = None
        self._rerecord_new_count = 0
        self._rerecord_backup = None
        self._steps_edited_while_paused = False
        self._stop_recording_exclude_refresh()
        self._stop_floater_hotkeys()
        self._finalize_loop_marks()
        fix_msgs: List[str] = []
        if self._auto_correct_var.get():
            fixed, fix_msgs = correct_steps(self._current_steps)
            if fix_msgs:
                self._current_steps = fixed
        self._loop_body_mode = False
        self._steps_edited_while_paused = False
        self._refresh_steps_list()

        self._hide_control_floater()
        self._restore_main_after_recording()
        self._set_red_button_recording(False)
        self._set_canvas_button_enabled(self._btn_run, True)
        if was_rerecord:
            self._set_status(
                f"Re-record done: replaced {new_count} steps. {len(self._current_steps)} steps total."
            )
        else:
            self._set_status(f"Recording finished: {len(self._current_steps)} steps. Save or run.")
            if self._auto_correct_var.get() and fix_msgs:
                messagebox.showinfo(
                    "Auto-corrected",
                    "Fixed issues in your flow:\n\n"
                    + "\n".join(f"• {m}" for m in fix_msgs),
                    parent=self.root,
                )
            if detect_batch_copy_paste(self._current_steps):
                messagebox.showwarning(
                    "Wrong Step Order",
                    "Detected: multiple copies in a row, then multiple pastes.\n\n"
                    "The clipboard is overwritten; only the last cell is pasted.\n\n"
                    "Split into modules and insert in order:\n"
                    "Excel copy → paste to web → back to sheet → next cell…",
                    parent=self.root,
                )
        self._offer_save_after_record()

    def _on_save(self) -> None:
        """保存当前步骤为流程文件。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter a flow name.")
            return
        if not self._current_steps:
            messagebox.showwarning("Notice", "No steps yet. Record first.")
            return

        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._set_status(f"Saved: {name}")
            messagebox.showinfo("Success", f'Flow "{name}" saved.')
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save Failed", str(exc))

    def _on_save_and_run(self) -> None:
        """保存当前步骤后立即运行。"""
        name = self._flow_name_var.get().strip()
        if not name:
            messagebox.showwarning("Notice", "Enter a flow name.")
            return
        if not self._current_steps:
            messagebox.showwarning("Notice", "No steps to save. Record a flow first.")
            return
        try:
            self.storage.save(name, self._current_steps)
            self._refresh_flow_list()
            self._start_playback(self._current_steps, name)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save Failed", str(exc))

    def _on_delete_selected(self) -> None:
        """删除选中的流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("Notice", "Select a saved flow first.")
            return

        if not messagebox.askyesno("Confirm Delete", f"Delete flow '{name}'?"):
            return

        if self.storage.delete(name):
            self._refresh_flow_list()
            self._set_status(f"Deleted flow: {name}")
        else:
            messagebox.showerror("Delete Failed", f"Flow not found: {name}")

    def _set_playback_ui(self, playing: bool) -> None:
        """切换回放期间的按钮状态。"""
        self._set_controls_locked(playing)
        self._set_canvas_button_enabled(self._btn_stop_play, playing)

    def _playback_countdown_seconds(self, steps: List[dict]) -> int:
        """运行前倒计时：给用户时间切换到目标应用。"""
        loader = self.module_storage.load_steps
        has_pointer = flow_has_pointer_steps(steps, loader)
        if self._playback_during_pause_record:
            return 1 if has_pointer else 0
        if has_pointer:
            return 2
        return 0

    def _validate_playback_steps(
        self, steps: List[dict], *, path_prefix: str = ""
    ) -> Optional[str]:
        """运行前检查模块/循环是否可加载；返回错误说明，None 表示通过。"""
        for i, step in enumerate(steps):
            loc = f"{path_prefix}step {i + 1}"
            step_type = step.get("type")
            if step_type == "module":
                name = str(step.get("name", "")).strip()
                if not name:
                    return f"{loc}: module name is empty"
                if not self.module_storage.exists(name):
                    return (
                        f'{loc}: module "{name}" does not exist.\n'
                        "Save again with Save as Module, or check the name."
                    )
                try:
                    if not self.module_storage.load_steps(name):
                        return f'{loc}: module "{name}" has no steps'
                except OSError as exc:
                    return f'{loc}: cannot read module "{name}": {exc}'
            elif step_type == "loop":
                inner = list(step.get("steps") or [])
                mod = str(step.get("module", "")).strip()
                if not inner and not mod:
                    return f"{loc}: loop body is empty (no inline steps or module)"
                if mod:
                    if not self.module_storage.exists(mod):
                        return (
                            f'{loc}: loop references missing module "{mod}".\n'
                            "Save as Module first, then reference it via Insert Module or Loop."
                        )
                    try:
                        if not self.module_storage.load_steps(mod):
                            return f'{loc}: module "{mod}" has no steps'
                    except OSError as exc:
                        return f'{loc}: cannot read module "{mod}": {exc}'
                if inner:
                    err = self._validate_playback_steps(
                        inner, path_prefix=f"{loc} (loop body)"
                    )
                    if err:
                        return err
                after = list(step.get("after") or [])
                if after:
                    err = self._validate_playback_steps(
                        after, path_prefix=f"{loc} (after loop)"
                    )
                    if err:
                        return err
        return None

    def _prepare_steps_for_playback(self, steps: List[dict]) -> List[dict]:
        prepared = self._merge_loop_marks(list(steps))
        if self._auto_correct_var.get():
            prepared, _msgs = correct_steps(prepared)
        return prepared

    def _start_playback(self, steps: List[dict], label: str) -> None:
        """开始回放指定步骤。"""
        if not steps:
            messagebox.showwarning("Notice", "No steps to run.")
            return
        steps = self._prepare_steps_for_playback(steps)
        preflight = self._validate_playback_steps(steps)
        if preflight:
            messagebox.showerror("Cannot Run", preflight, parent=self.root)
            return
        if self.recorder and self.recorder.is_recording:
            if not self.recorder.is_paused:
                messagebox.showwarning("Notice", "Pause recording first, or stop before running.")
                return
            self._playback_during_pause_record = True
        else:
            self._playback_during_pause_record = False
        if self.player.is_playing:
            messagebox.showwarning("Notice", "Playback is already in progress.")
            return
        if not self._ensure_permissions():
            return

        loader = self.module_storage.load_steps
        has_click = flow_has_pointer_steps(steps, loader)
        has_type = any(
            s.get("type") == "type" for s in iter_effective_steps(steps, loader)
        )

        self._hide_for_playback()
        self._set_playback_ui(True)
        countdown_secs = self._playback_countdown_seconds(steps)
        play_status = (
            f"{countdown_secs}s — switch to the target window"
            if countdown_secs > 0
            else "Starting soon"
        )
        self._show_play_floater(label, initial_status=play_status)

        if has_type and not has_click:
            self._set_status("No click steps — click the input field now; playback will start immediately")

        safari_hint = ""
        if sys.platform == "darwin" and has_click:
            safari_hint = " — keep Safari scroll position as when recorded"

        if countdown_secs > 0:
            self._set_status(
                f"Starting '{label}' in {countdown_secs} seconds"
                f" — switch to the target window{safari_hint}"
            )
        else:
            self._set_status(f"Running '{label}'…")
        self.root.update_idletasks()
        play_exclude_rects: List[Tuple[int, int, int, int]] = []
        floater_rect = self._control_floater.bounds()
        if floater_rect:
            play_exclude_rects.append(floater_rect)

        def on_countdown(remaining: int) -> None:
            msg = f"{remaining}s — switch to the target window"
            self._set_status(f"{msg} — Esc or Exit to cancel")
            self._control_floater.set_status(msg)

        def exclude_rects() -> List[Tuple[int, int, int, int]]:
            return play_exclude_rects

        playback_speed = self._parse_playback_speed()
        speed_label = (
            f"{playback_speed:g}x"
            if playback_speed != int(playback_speed)
            else f"{int(playback_speed)}x"
        )

        def on_before_step(index: int, step: dict) -> None:
            def highlight_step() -> None:
                self._steps_list.selection_clear(0, tk.END)
                self._steps_list.selection_set(index)
                self._steps_list.see(index)

            self.root.after(0, highlight_step)

            delay = float(step.get("delay", 0))
            eff_delay = delay / playback_speed if playback_speed else delay
            msg = f"[{speed_label}] Step {index + 1}/{len(steps)}"
            if delay > 0:
                msg += f" — wait {eff_delay:.2f}s (recorded {delay:.2f}s)"
            else:
                msg += f" — {step.get('type', '?')}"
            self._set_status(msg)
            self._control_floater.set_status(msg)

            if step.get("type") in ("click", "double_click"):
                hint = (
                    " — keep browser in front"
                    if index == first_click_index
                    else ""
                )
                click_msg = (
                    f"[{speed_label}] Click ({int(step['x'])}, {int(step['y'])}) "
                    f"— step {index + 1}/{len(steps)}{hint}"
                )
                self._set_status(click_msg)
                self._control_floater.set_status(click_msg)

        def on_step(index: int, step: dict) -> None:
            if step.get("type") == "click":
                self._set_status(
                    f"Clicked ({int(step['x'])}, {int(step['y'])}) "
                    f"— step {index + 1}/{len(steps)}"
                )
            else:
                self._set_status(f"'{label}' step {index + 1}/{len(steps)}")
            self._control_floater.set_status(f"Step {index + 1}/{len(steps)}")

        def on_done(step_errors=None) -> None:
            errors = step_errors or []

            def finish() -> None:
                self._set_playback_ui(False)
                if self._playback_during_pause_record:
                    self._playback_during_pause_record = False
                    self._show_record_floater()
                    self._control_floater.set_paused(True)
                    self._enter_pause_edit_mode()
                else:
                    self._hide_control_floater()
                    self._show_after_playback()
                if errors:
                    lines = "\n".join(
                        f"Step {idx + 1}: {exc}" for idx, exc in errors[:5]
                    )
                    extra = f"\n…and {len(errors) - 5} more" if len(errors) > 5 else ""
                    self._set_status(
                        f"'{label}' finished with {len(errors)} step error(s)"
                    )
                    messagebox.showwarning(
                        "Playback Completed with Errors",
                        f"Ran all {len(steps)} steps; {len(errors)} step(s) failed:\n\n"
                        f"{lines}{extra}",
                    )
                else:
                    self._set_status(
                        f"'{label}' playback finished — all {len(steps)} steps done"
                    )

            self.root.after(0, finish)

        def on_step_error(index: int, step: dict, exc: Exception) -> None:
            self._set_status(
                f"Step {index + 1}/{len(steps)} failed ({step.get('type')}): {exc} — continuing…"
            )

        def on_error(exc: Exception) -> None:
            def show_error() -> None:
                self._set_playback_ui(False)
                if self._playback_during_pause_record:
                    self._playback_during_pause_record = False
                    self._show_record_floater()
                    self._control_floater.set_paused(True)
                    self._enter_pause_edit_mode()
                else:
                    self._hide_control_floater()
                    self._show_after_playback()
                self._set_status("Playback error")
                messagebox.showerror("Playback Failed", str(exc))

            self.root.after(0, show_error)

        def on_wait_load(msg: str) -> None:
            self._set_status(msg)
            self._control_floater.set_status(msg)

        self.player.play(
            steps,
            countdown=countdown_secs,
            on_countdown=on_countdown if countdown_secs > 0 else None,
            on_before_step=on_before_step,
            on_step=on_step,
            on_done=on_done,
            on_error=on_error,
            on_step_error=on_step_error,
            exclude_rects=exclude_rects,
            run_on_main=self._run_on_main_thread
            if sys.platform == "win32"
            else None,
            calibration_anchor=None,
            wait_load_after_click=self._wait_load_var.get(),
            on_wait_load=on_wait_load,
            playback_speed=playback_speed,
            hide_cursor=self._hide_mouse_var.get(),
            module_loader=self.module_storage.load_steps,
            on_loop_progress=lambda cur, total, label: self._set_status(
                f"Loop {cur}/{total}: {label}"
            ),
            use_alignment=False,
        )

    def _on_run_current(self) -> None:
        """运行当前步骤（未保存也可运行）。"""
        if self.recorder and self.recorder.is_recording and not self.recorder.is_paused:
            messagebox.showwarning("Notice", "While recording, pause with ▶ on the floater before a test run.")
            return
        if self.recorder and self.recorder.is_recording and self.recorder.is_paused:
            self._sync_recorder_steps_if_paused()
        steps = self._prepare_steps_for_playback(self._current_steps)
        label = (
            "Test Run"
            if self.recorder and self.recorder.is_recording and self.recorder.is_paused
            else "Current Steps"
        )
        self._start_playback(steps, label)

    def _on_run_selected(self) -> None:
        """运行选中的已保存流程。"""
        name = self._get_selected_flow_name()
        if not name:
            messagebox.showwarning("Notice", "Select a saved flow below first.")
            return

        try:
            data = self.storage.load(name)
            steps = data.get("steps", [])
            self._current_steps = steps
            self._refresh_steps_list()
            self._start_playback(steps, name)
        except (FileNotFoundError, OSError) as exc:
            messagebox.showerror("Load Failed", str(exc))

    def _on_stop_playback(self) -> None:
        """停止回放。"""
        self.player.stop()
        self._click_marker.hide_calibration()
        self._click_marker.close_flashes()
        self._set_playback_ui(False)
        if self._playback_during_pause_record:
            self._playback_during_pause_record = False
            self._show_record_floater()
            self._control_floater.set_paused(True)
            self._enter_pause_edit_mode()
        else:
            self._hide_control_floater()
            self._show_after_playback()
        self._set_status("Stopped")
