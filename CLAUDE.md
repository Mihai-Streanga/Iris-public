# Iris — instructions for Claude Code

Local voice dictation for Windows: you speak, and the text is typed into the text box that has
the cursor. Whisper runs on the machine (`large-v3-turbo`); nothing leaves the computer.
Code comments, docstrings and the interface are in Romanian; keep new ones in Romanian.

## Map

| file | what it holds |
|---|---|
| `iris.py` | the window, the state machine, routing between engines, text cleanup (`curata()`) |
| `ferestre.py` | the Windows side, `ctypes` only: typing into the active window, the global hotkey |
| `pulsar.py` | the pulsar that shows the state, rendered with NumPy |
| `fereastra_libera.py` | the frameless window with per-pixel alpha |
| `iris.json` | all settings, read once at startup |
| `fa-sunete.py`, `fa-pictograma.py` | regenerate `sunete/*.wav` and `iris.ico`; their output is committed |

## Commands

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe iris.py
```

Tests use no microphone, window or network. The 2 tests in `test_model.py` load the real model
and are **skipped with their reason** when it is not in the Hugging Face cache; keep it that way
for any new test that needs the model.

## Invariants

None of these is broken without a measurement that justifies it.

- **Never send `Enter`, never type `\n`.** In a chat box a line break sends half a sentence.
  `curata()` collapses all whitespace.
- **Nothing on disk** except the window position. Audio lives in memory and is gone with the
  transcription.
- **`SetProcessDpiAwareness` and the `AppUserModelID` are set before any window exists**:
  Windows reads them once.
- **The scale comes from Tk** (`winfo_fpixels("1i")`), not from `GetDpiForWindow`.
- **Nothing moves the window behind Tk's back.** What `ShowWindow` moves, Tk cannot restore.
  The frame is removed through Windows styles; restoring is left to Tk.
- **The window is touched only from `_pompa`**, on Tk's thread. Other threads talk to it through
  `self.mesaje`.
- **No `except: pass` on a path nobody checks.** Where an exception really has to be swallowed,
  it is remembered and shown in the window.
- **Accuracy beats speed.** A setting that loses a word is rejected, however much faster it is.
  The iGPU route for short dictations (`granita_igpu` in `iris.json`) is the one written
  exception; it is a decision, not a regression to fix.
- **Colour says the state**, and all text follows it. Hierarchy comes from size and weight, not
  colour.
- **No network layer**: no HTTP client, no socket, no open port. The model is loaded with
  `local_files_only=True`.

The corpus that measures accuracy is the author's recorded voice and stays private, so a change
to the engine settings cannot be validated from this repository; say so instead of claiming it.
