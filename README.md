# Clickless

**Record once, replay forever — built from LEGO-style blocks.**

Clickless is a desktop automation assistant for macOS and Windows. You record small pieces of work once, save them as **reusable modules** (building blocks), then **snap blocks together** into full **flows**. Loops repeat a block many times (e.g. every Excel row). Same idea as LEGO: a few bricks, many assemblies.

Great for repetitive Excel/WPS → web → spreadsheet work and any click-and-type routine.

## LEGO-style building blocks

Think of automation in three layers:

```
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │   Module    │     │   Module    │     │   Module    │  ← bricks (saved once)
  │  "Copy cell"│     │ "Paste web" │     │ "Back Excel"│
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                    ┌─────────────────┐
                    │      Flow       │  ← full model (your job)
                    │  open → loop ×N │
                    └─────────────────┘
```

| Layer | What it is | On disk |
|-------|------------|---------|
| **Step** | One click, key, copy, paste, etc. | Inside a recording |
| **Module** | A named bundle of steps — one brick | `modules/*.json` |
| **Loop** | “Run this brick (or these steps) N times” | Inside a flow |
| **Flow** | The full script you run end-to-end | `flows/*.json` |

**Typical workflow**

1. **Record** a small chunk (e.g. copy cell → click browser → paste).
2. **Pause** → select those steps → **Save module** (creates a brick; your flow stays unchanged).
3. Keep recording, or **Insert module** to drop in bricks you already have.
4. **Module + loop** — save a brick and add “repeat × 10” in one step.
5. **Save** the whole assembly as a **flow** and **Run** anytime.

Bricks stay in a shared library (`modules/`). Update or **Rename module** once; flows that reference it can be updated automatically. **Pick steps** lets you choose non-contiguous steps; middle steps are still included in order when you build a brick or loop.

## Features

- **LEGO modules** — Save, insert, update, rename reusable blocks; compose long jobs from short recordings.
- **Loops** — Repeat a module or step range N times; Excel drag-select or WPS row count for row-by-row jobs.
- **Record & playback** — Red button to record; green **Run** for trial or saved flows.
- **Floating control bar** — Pause, resume, stop, loop-once recording helpers.
- **Saved flows** — Name and save full assemblies; double-click to run.
- **Pick steps** — Checkbox + keyboard selection for building bricks from scattered steps.
- **Keyboard select** — Shift+arrow steps for Excel/WPS without clicking cells.
- **Playback options** — Speed (0.5×–5×), optional page-load wait (Safari), click calibration countdown.
- **English UI** — Main window and floater in English.

## Module actions (cheat sheet)

| Button | LEGO analogy | Effect |
|--------|----------------|--------|
| **Save module** | Mold a new brick | Writes `modules/`; does **not** remove steps from the current flow. |
| **Insert module** | Snap a brick in | One step that runs a saved module. |
| **Module + loop** | Brick + “× N” | Saves module and inserts loop; optionally removes original steps. |
| **Update module** | Reshape a brick | Overwrites module file with newly selected steps. |
| **Rename module** | Relabel a brick | Renames file; updates references in current + saved flows. |
| **Loop** | Repeat a section | Inline steps or a module, N times. |

**Excel → web rows:** record one row’s brick once (copy → web → paste → back), use floater **loop** + **Done**; Clickless presses ↓ between iterations.

## Requirements

- **Python 3.10+** (for running from source)
- Dependencies: [`requirements.txt`](requirements.txt)

```bash
pip install -r requirements.txt
```

### macOS permissions

Recording and playback need **Accessibility** and often **Input Monitoring** for Terminal, Python, or Clickless:

**System Settings → Privacy & Security → Accessibility** (and **Input Monitoring**) → enable your launcher.

Restart after granting. Quick check:

```bash
python main.py --self-test
```

## Quick start (from source)

```bash
git clone https://github.com/qliu365/clickless.git
cd clickless
pip install -r requirements.txt
python main.py
```

1. **Record** a short sequence → **Save module** (first brick).
2. Record more, or **Insert module** to add bricks.
3. **Save** the full **flow** → **Run** or double-click the flow in the list.

## Where data is stored

| Platform | Location |
|----------|----------|
| macOS | `~/Library/Application Support/Clickless/` |
| Windows | `%LOCALAPPDATA%\Clickless\` |
| Linux | `~/.clickless/` |

- `modules/` — your brick library  
- `flows/` — full assemblies  
- `clickless-error.log` — startup errors  
- `self-test.log` — `--self-test` output  

Legacy `flows/` beside the project folder migrate into the app data folder on first run.

## Building installable apps

**macOS:** `./build_mac.sh` → `dist/Clickless.app`, `dist/Clickless-mac.zip`  

**Windows:** `build_win.bat` or `pyinstaller --noconfirm --clean clickless.spec`  

See [`README-Windows.txt`](README-Windows.txt) for zip install notes (keep `Clickless.exe` and `_internal` together).

CI: `.github/workflows/build.yml` (manual **workflow_dispatch**).

## Project layout

| File | Role |
|------|------|
| `main.py` | Entry point |
| `gui.py` | Tkinter UI |
| `recorder.py` | Input capture |
| `player.py` | Playback (expands modules & loops) |
| `module_storage.py` | Brick library on disk |
| `storage.py` | Saved flows |
| `recording_floater.py` | Recording/playback floater |

## Troubleshooting

- **Nothing on run** — Accessibility on? Do all **modules** in the flow still exist under `modules/`?
- **Wrong clicks** — Calibrate with the orange dot; same zoom/layout as when you recorded the brick.
- **Paste wrong / only last cell** — Don’t stack many copies then many pastes in one loop; use separate bricks in order: copy → paste → next row.
- **Startup error** — `clickless-error.log` in the app data folder.

## License

No license file yet. Use per your team’s policy.

## Repository

https://github.com/qliu365/clickless
