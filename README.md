# FileFlow 🧹 - safe, previewable file organizer

FileFlow scans a messy folder (thousands of files is fine), finds duplicates, and proposes a clean folder
structure. **It never moves, renames or deletes anything until you review a Preview Plan and confirm.**
Everything it does is journaled in SQLite so it can be undone.

## Safety model

| Rule | How it is enforced |
|---|---|
| Nothing changes without confirmation | Planning/scan/duplicate code is read-only; only `core/operations.py` touches files, and the UI asks before calling it. |
| Never overwrite | An existing destination makes the operation *skip*; plan building also picks `name (1).ext` for clashes. |
| Never silently delete | "Cleanup" and duplicate removal move files into `_FileFlow_Quarantine/<timestamp>/` inside the scanned folder. Empty folders are the only thing removed (`rmdir`, which refuses non-empty folders) and are re-created by Undo. You empty the quarantine yourself. |
| Full rollback | Each operation is written to the journal *before* it runs. Undo restores files in reverse order, never clobbers a file that now sits at the original path, and removes folders FileFlow created if they are empty. |
| Projects are left alone | Folders containing `.git`, `package.json`, `pyproject.toml`, `*.sln`, `Makefile`, ... are never reorganized. Hidden files, symlinks and `desktop.ini`/`Thumbs.db` are ignored by the planner. |
| Cross-drive moves | Copy → verify size → remove source (no data loss if the copy fails). |

## Features

* **Scanner** - nested folders, external drives (any path you can open). Shows file count, total size, type breakdown, largest files and largest folders.
* **Duplicates** - size → partial hash → full SHA-256, so only real byte-identical files are grouped. Optional perceptual hashing (pHash via `imagehash`) finds visually similar images. You tick what to keep in each group.
* **Smart categories** - Documents, Pictures, Videos, Audio, Code, Archives, plus keyword-based Finance/Invoices, School, Work and Projects/Notes. Images go to `Pictures/<year>` (EXIF date when present), `Pictures/Vacation`, `Pictures/Screenshots`. Add **custom categories** (keyword → folder) in the *Categories* tab; they override the built-ins.
* **Rename assistant** - `IMG_9382.JPG` → `2026-09-28_Photo_9382.jpg` (date from EXIF, else file date; a meaningful parent folder such as *Cambodia Trip* becomes part of the name). Also tidies `Copy of x`, `x - Copy`, doubled separators. Suggestions are part of the plan: untick or **Edit** any row.
* **Cleanup suggestions** - empty folders, empty files, temp/partial downloads, `.bak/.old` files, installers untouched for 90+ days. Nothing is ticked by default.
* **History / Undo** - per-batch journal; undo the latest batch or any selected batch.
* **UI** - PySide6, dark/light theme, drag-and-drop a folder onto the window, tables, image preview panel, progress bars, all heavy work on background threads with a Cancel button.
* **AI is optional.** Everything above works offline. If you set `FILEFLOW_AI_KEY` (and optionally `FILEFLOW_AI_URL`, `FILEFLOW_AI_MODEL` for any OpenAI-compatible endpoint) a checkbox appears that asks the model for folder hints for files the rules couldn't classify. Only file *names* are sent; the result still goes through the Preview Plan.

## Run it (Windows)

```bat
run.bat
```
(creates a `.venv`, installs `requirements.txt`, starts the app). Or manually:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_fileflow.py
```
On macOS/Linux: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python run_fileflow.py`.

Workflow: drop a folder → *Overview* → **Build Preview Plan** → review/untick/**Edit** → **Apply** (confirm) → **Undo** if needed.
The default scope is *Loose files only* (files directly in the folder). Choose *Everything* to also pull files out of sub-folders (this flattens them - check the preview).

## Tests

The core is tested with the standard library, so no extra packages are required:

```bat
python -m unittest discover -s tests -t . -v
```
(`pytest` also works.) Covered: scanning, empty/protected folders, duplicate detection (incl. files that differ only after the partial-hash window), categories, rename suggestions, conflict handling, "planning touches nothing", apply → undo restoring the exact original tree, no-overwrite, undo with changed files, quarantine/rmdir undo, history persistence. A headless UI smoke test runs when PySide6 is installed.

## Build the Windows EXE

```bat
build_exe.bat
```
Installs dev requirements, runs the tests, then runs PyInstaller. Output: `dist\FileFlow\FileFlow.exe` (zip the `dist\FileFlow` folder to share). Add `--onefile` to the `pyinstaller` line in the script for a single file (slower start-up). Build on Windows - PyInstaller does not cross-compile.

## Project layout

```
fileflow/core/   scanner, duplicates, categorizer, renamer, planner, operations (+undo), history (SQLite), cleanup, metadata, ai
fileflow/ui/     main_window, workers (QThread), themes
tests/           unittest suite
```
The history database lives in `%LOCALAPPDATA%\FileFlow\history.db` (override with `FILEFLOW_HOME`).

## Known limits

* Operations on files that are open/locked by another program can fail; they are reported and skipped, never forced.
* Perceptual matching compares all images in memory-bucketed pairs; it is fast for thousands of images but not designed for millions.
* Undo of a batch is best-effort if you changed the files afterwards - those files are left alone and listed.
