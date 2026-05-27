# Clickless

**Record once, replay forever.** Clickless is a desktop automation assistant for macOS and Windows. It records mouse clicks, keyboard input, scrolling, copy/paste, and shortcuts, then replays them on demand—useful for repetitive Excel/WPS → web → spreadsheet workflows and other UI tasks.

## Features

- **Record & playback** — Red button to start/stop recording; green **Run** to replay the current flow or a saved flow.
- **Floating control bar** — Pause, resume, stop, and loop helpers while recording.
- **Saved flows** — Name and save sequences as JSON; double-click a flow in the list to run it.
- **Modules** — Save selected steps as reusable blocks; **Insert module** to compose longer flows.
- **Loops** — Repeat a step range or a module N times; Excel row loops with drag-select or WPS row count.
- **Pick steps** — Non-contiguous selection (gaps are filled in order when building modules/loops).
- **Keyboard select** — Insert Shift+arrow steps for Excel/WPS without clicking cells.
- **Rename / update modules** — Manage module files on disk; references update in the current flow and saved flows.
- **Playback options** — Speed (0.5×–5×), optional page-load wait (Safari), calibration countdown before clicks.
- **English UI** — Main window and floater labels are in English.

## Requirements

- **Python 3.10+** (for running from source)
- Dependencies: see [`requirements.txt`](requirements.txt)

```bash
pip install -r requirements.txt
```

### macOS permissions

Recording and playback need **Accessibility** and often **Input Monitoring** for Terminal, Python, or the Clickless app:

**System Settings → Privacy & Security → Accessibility** (and **Input Monitoring**) → enable your launcher.

Restart the app after granting permissions. Run a quick check:

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

1. Click the **red** button and perform your actions in the target app.
2. Click **red** again to stop.
3. Enter a **Name** and click **Save**, or click **Run** to try without saving.
4. Use **Pick steps** / **Save module** / **Insert module** / **Loop** to structure longer automations.

## Where data is stored

| Platform | Location |
|----------|----------|
| macOS | `~/Library/Application Support/Clickless/` |
| Windows | `%LOCALAPPDATA%\Clickless\` |
| Linux | `~/.clickless/` |

Under that folder:

- `flows/` — saved automation flows (JSON)
- `modules/` — reusable step modules (JSON)
- `clickless-error.log` — crash log if startup fails
- `self-test.log` — output from `--self-test`

Legacy `flows/` next to the project directory are migrated into the app data folder on first run.

## Modules & loops (short guide)

| Action | What it does |
|--------|----------------|
| **Save module** | Writes selected steps to `modules/`; does not remove them from the current flow. |
| **Module + loop** | Saves a module and inserts a loop that references it; optionally removes the original steps. |
| **Insert module** | Adds one step that calls a saved module. |
| **Update module** | Overwrites an existing module with newly selected steps. |
| **Rename module** | Renames the module file and updates references in open and saved flows. |
| **Loop** | Repeats selected steps or a module; use **Remove original steps** to avoid running twice. |

**Excel → web row loop:** use the floater **loop** control, record copy → web paste → return to sheet once, then **Done**; the app advances with ↓ between iterations.

## Building installable apps

**macOS**

```bash
./build_mac.sh
# Output: dist/Clickless.app, dist/Clickless-mac.zip
```

**Windows**

```bash
build_win.bat
# Or: pyinstaller --noconfirm --clean clickless.spec
```

See [`README-Windows.txt`](README-Windows.txt) for end-user zip instructions (keep `Clickless.exe` and `_internal` together).

CI builds are available via GitHub Actions (`.github/workflows/build.yml`, manual **workflow_dispatch**).

## Project layout

| File | Role |
|------|------|
| `main.py` | Entry point |
| `gui.py` | Tkinter UI |
| `recorder.py` | Input capture |
| `player.py` | Playback engine |
| `module_storage.py` / `storage.py` | Modules and flows on disk |
| `recording_floater.py` | Recording/playback floater |
| `permissions.py` | macOS permission helpers |

## Troubleshooting

- **Nothing happens on run** — Check Accessibility; confirm the flow has steps and any referenced **modules** exist under `modules/`.
- **Wrong click position** — Use the orange calibration dot during the countdown; keep browser zoom at 100% and the same window layout as when recording.
- **Clipboard / paste issues** — Avoid multiple copies before multiple pastes in one loop; split into ordered modules instead.
- **Startup error** — See `clickless-error.log` in the app data folder.

## License

No license file is included yet. Use and distribute according to your team’s policy.

## Repository

https://github.com/qliu365/clickless
