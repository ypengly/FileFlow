from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.ai import AIError, ai_configured, ai_hints_for
from ..core.categorizer import CustomRule
from ..core.cleanup import find_cleanup
from ..core.duplicates import find_exact_duplicates, find_similar_images, perceptual_available
from ..core.filetypes import ext_category
from ..core.history import History
from ..core.metadata import image_info
from ..core.operations import Op, apply_ops, ops_from_plan, quarantine_ops, undo_batch
from ..core.planner import PlanItem, build_plan, resolve_conflicts, summarize
from ..core.scanner import ScanResult, scan_folder
from ..core.utils import QUARANTINE_DIR, human_size, sanitize_parts
from .themes import apply_theme
from .workers import TaskThread

RO = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
PATH_ROLE = Qt.ItemDataRole.UserRole
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def ro_item(text, path=None, right=False) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setFlags(RO)
    if path is not None:
        it.setData(PATH_ROLE, str(path))
    if right:
        it.setTextAlignment(RIGHT)
    return it


def check_item(checked: bool, path=None) -> QTableWidgetItem:
    it = QTableWidgetItem()
    it.setFlags(RO | Qt.ItemFlag.ItemIsUserCheckable)
    it.setCheckState(CHECKED if checked else UNCHECKED)
    if path is not None:
        it.setData(PATH_ROLE, str(path))
    return it


def make_table(headers: list[str], stretch: int) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    hh = t.horizontalHeader()
    for i in range(len(headers)):
        hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == stretch
                                else QHeaderView.ResizeMode.ResizeToContents)
    return t


def fill(table: QTableWidget, rows: list[list[QTableWidgetItem]]) -> None:
    table.setUpdatesEnabled(False)
    table.clearContents()
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, item in enumerate(row):
            table.setItem(r, c, item)
    table.setUpdatesEnabled(True)


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class MainWindow(QMainWindow):
    def __init__(self, history: History | None = None, dark: bool = True):
        super().__init__()
        self.setWindowTitle("FileFlow - safe file organizer")
        self.resize(1250, 780)
        self.setAcceptDrops(True)
        self.history = history or History()
        self.scan: ScanResult | None = None
        self.plan: list[PlanItem] = []
        self.dup_groups = []
        self.suggestions = []
        self._thread: TaskThread | None = None
        self._action_widgets: list[QWidget] = []
        self._build_ui(dark)
        self._load_rules()
        self._refresh_history()
        self._set_busy(False)

    # ------------------------------------------------------------------ UI construction
    def _btn(self, text, slot, tip="") -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        if tip:
            b.setToolTip(tip)
        self._action_widgets.append(b)
        return b

    def _build_ui(self, dark: bool) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)

        top = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Drop a folder here, or choose one...")
        self.btn_browse = self._btn("Browse...", self.on_browse)
        self.btn_scan = self._btn("Scan", self.on_scan)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.chk_dark = QCheckBox("Dark theme")
        self.chk_dark.setChecked(dark)
        self.chk_dark.toggled.connect(self.on_theme)
        for w in (self.folder_edit, self.btn_browse, self.btn_scan, self.btn_cancel, self.chk_dark):
            top.addWidget(w)
        top.setStretch(0, 1)
        v.addLayout(top)

        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self._build_overview()
        self._build_plan_tab()
        self._build_dups_tab()
        self._build_cleanup_tab()
        self._build_history_tab()
        self._build_rules_tab()

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status = QLabel("Ready. Nothing is moved, renamed or deleted until you confirm.")
        sb = self.statusBar()
        sb.addWidget(self.status, 1)
        sb.addPermanentWidget(self.progress)
        self.progress.setMaximumWidth(260)

        dock = QDockWidget("Preview", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.preview_img = QLabel("No selection")
        self.preview_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_img.setMinimumSize(280, 220)
        self.preview_txt = QPlainTextEdit()
        self.preview_txt.setReadOnly(True)
        pl.addWidget(self.preview_img)
        pl.addWidget(self.preview_txt, 1)
        dock.setWidget(pw)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _hook_preview(self, table: QTableWidget) -> None:
        def changed():
            rows = table.selectionModel().selectedRows()
            if rows:
                it = table.item(rows[0].row(), 0)
                if it is not None and it.data(PATH_ROLE):
                    self.show_preview(Path(it.data(PATH_ROLE)))
        table.itemSelectionChanged.connect(changed)

    def _build_overview(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        self.lbl_summary = QLabel("No folder scanned yet.")
        self.lbl_summary.setWordWrap(True)
        l.addWidget(self.lbl_summary)
        l.addWidget(QLabel("File types"))
        self.tbl_types = make_table(["Type", "Files", "Size", "Share"], 0)
        self.tbl_types.setMaximumHeight(210)
        l.addWidget(self.tbl_types)
        l.addWidget(QLabel("Largest files"))
        self.tbl_large = make_table(["File", "Size", "Modified", "Folder"], 3)
        self._hook_preview(self.tbl_large)
        l.addWidget(self.tbl_large, 2)
        l.addWidget(QLabel("Largest folders"))
        self.tbl_folders = make_table(["Folder", "Size", "Files"], 0)
        l.addWidget(self.tbl_folders, 1)
        self.tabs.addTab(w, "Overview")

    def _build_plan_tab(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        opts = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Organize into (defaults to the scanned folder)")
        b = self._btn("Destination...", self.on_pick_dest)
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItem("Loose files only", "loose")
        self.cmb_scope.addItem("Everything (flattens sub-folders)", "all")
        self.chk_rename = QCheckBox("Suggest cleaner names")
        self.chk_rename.setChecked(True)
        self.chk_ai = QCheckBox("AI hints for unclassified files")
        self.chk_ai.setEnabled(ai_configured())
        self.chk_ai.setToolTip("Optional. Set FILEFLOW_AI_KEY to enable. Only file names are sent." if
                               not ai_configured() else "Only file names are sent to your AI endpoint.")
        self.btn_build = self._btn("Build Preview Plan", self.on_build_plan)
        for x in (self.dest_edit, b, self.cmb_scope, self.chk_rename, self.chk_ai, self.btn_build):
            opts.addWidget(x)
        opts.setStretch(0, 1)
        l.addLayout(opts)
        self.lbl_plan = QLabel("No plan yet. Scan a folder, then build a preview.")
        l.addWidget(self.lbl_plan)
        self.tbl_plan = make_table(["Apply", "Action", "From", "To", "Why"], 3)
        self.tbl_plan.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl_plan.cellDoubleClicked.connect(lambda *_: self.on_edit())
        self._hook_preview(self.tbl_plan)
        l.addWidget(self.tbl_plan, 1)
        row = QHBoxLayout()
        self.btn_apply = self._btn("Apply", self.on_apply, "Move/rename the ticked files (asks first)")
        self.btn_reject = self._btn("Reject", self.on_reject, "Discard this plan; nothing changes")
        self.btn_edit = self._btn("Edit", self.on_edit, "Change the destination of the selected rows")
        self.btn_undo = self._btn("Undo", self.on_undo_last, "Roll back the most recent operation")
        for x in (self.btn_apply, self.btn_reject, self.btn_edit, self.btn_undo):
            row.addWidget(x)
        row.addStretch(1)
        l.addLayout(row)
        self.tabs.addTab(w, "Preview Plan")

    def _build_dups_tab(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        row = QHBoxLayout()
        self.btn_dups = self._btn("Find duplicates", self.on_find_dups)
        self.chk_percep = QCheckBox("Also find similar images (perceptual hash)")
        ok = perceptual_available()
        self.chk_percep.setEnabled(ok)
        if not ok:
            self.chk_percep.setToolTip("Install 'imagehash' and 'Pillow' to enable")
        self.btn_keep_old = self._btn("Keep oldest", lambda: self._dup_keep("oldest"))
        self.btn_keep_new = self._btn("Keep newest", lambda: self._dup_keep("newest"))
        self.btn_dup_apply = self._btn("Quarantine unticked copies", self.on_dup_apply,
                                       "Moves unticked files into a quarantine folder (undoable)")
        for x in (self.btn_dups, self.chk_percep, self.btn_keep_old, self.btn_keep_new, self.btn_dup_apply):
            row.addWidget(x)
        row.addStretch(1)
        l.addLayout(row)
        l.addWidget(QLabel("Tick the files you want to KEEP in each group. Unticked copies are moved to "
                           f"'{QUARANTINE_DIR}' (not deleted) and can be restored with Undo."))
        self.tree_dups = QTreeWidget()
        self.tree_dups.setHeaderLabels(["Keep", "File", "Size", "Modified", "Folder"])
        self.tree_dups.setColumnWidth(1, 300)
        self.tree_dups.itemSelectionChanged.connect(self._dup_selected)
        l.addWidget(self.tree_dups, 1)
        self.tabs.addTab(w, "Duplicates")

    def _build_cleanup_tab(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel("Suggestions only - nothing is ticked by default. Ticked files go to a quarantine "
                           "folder (not deleted); ticked empty folders are removed. Both can be undone."))
        self.tbl_clean = make_table(["Select", "Type", "Path", "Size", "Why"], 2)
        self._hook_preview(self.tbl_clean)
        l.addWidget(self.tbl_clean, 1)
        row = QHBoxLayout()
        row.addWidget(self._btn("Select all", lambda: self._clean_select(True)))
        row.addWidget(self._btn("Select none", lambda: self._clean_select(False)))
        row.addWidget(self._btn("Clean up selected", self.on_clean_apply))
        row.addStretch(1)
        l.addLayout(row)
        self.tabs.addTab(w, "Cleanup")

    def _build_history_tab(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        self.tbl_hist = make_table(["ID", "When", "What", "Operations", "Status"], 2)
        self.tbl_hist.itemSelectionChanged.connect(self._hist_selected)
        l.addWidget(self.tbl_hist, 1)
        self.tbl_ops = make_table(["Kind", "From", "To", "Status"], 1)
        l.addWidget(self.tbl_ops, 1)
        row = QHBoxLayout()
        row.addWidget(self._btn("Undo selected operation batch", self.on_undo_selected))
        row.addWidget(self._btn("Refresh", self._refresh_history))
        row.addStretch(1)
        l.addLayout(row)
        self.tabs.addTab(w, "History / Undo")

    def _build_rules_tab(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel("Custom categories: if a file or folder name contains the keyword, the file is "
                           "planned into that folder (e.g. 'acme' -> Work/Acme). Custom rules win over built-ins."))
        self.tbl_rules = make_table(["Keyword", "Destination folder"], 1)
        l.addWidget(self.tbl_rules, 1)
        row = QHBoxLayout()
        self.rule_kw = QLineEdit()
        self.rule_kw.setPlaceholderText("keyword")
        self.rule_dest = QLineEdit()
        self.rule_dest.setPlaceholderText("Folder/Sub-folder")
        row.addWidget(self.rule_kw)
        row.addWidget(self.rule_dest, 1)
        row.addWidget(self._btn("Add rule", self.on_add_rule))
        row.addWidget(self._btn("Remove selected", self.on_remove_rule))
        l.addLayout(row)
        self.tabs.addTab(w, "Categories")
        self.rules: list[CustomRule] = []

    # ------------------------------------------------------------------ task plumbing
    def _set_busy(self, busy: bool) -> None:
        for w in self._action_widgets:
            w.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.chk_percep.setEnabled(not busy and perceptual_available())

    def run_task(self, fn, on_done, title: str) -> None:
        if self._thread is not None:
            return
        self._set_busy(True)
        self.status.setText(title)
        self.progress.setRange(0, 0)
        th = TaskThread(fn, self)
        self._thread = th
        th.progress.connect(self._on_progress)
        th.done.connect(lambda res: self._task_finished(on_done, res))
        th.failed.connect(self._task_failed)
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(cur)
        else:
            self.progress.setRange(0, 0)
        if msg:
            self.status.setText(msg[-110:])

    def _end_task(self) -> None:
        self._thread = None
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._set_busy(False)

    def _task_finished(self, cb, res) -> None:
        self._end_task()
        cb(res)

    def _task_failed(self, tb: str) -> None:
        self._end_task()
        self.status.setText("Task failed")
        QMessageBox.critical(self, "FileFlow", f"Something went wrong:\n\n{tb[-1500:]}")

    def on_cancel(self) -> None:
        if self._thread:
            self._thread.cancel_event.set()
            self.status.setText("Cancelling...")

    def closeEvent(self, e) -> None:
        if self._thread:
            self._thread.cancel_event.set()
            self._thread.wait(5000)
        super().closeEvent(e)

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------ drag & drop, folder, theme
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.exists():
                self.folder_edit.setText(str(p if p.is_dir() else p.parent))
                self.on_scan()
                break

    def on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder to organize", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)
            self.on_scan()

    def on_pick_dest(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Organize into...", self.dest_edit.text() or self.folder_edit.text())
        if d:
            self.dest_edit.setText(d)

    def on_theme(self, dark: bool) -> None:
        apply_theme(QApplication.instance(), dark)
        self.history.set_setting("theme", "dark" if dark else "light")

    # ------------------------------------------------------------------ scan + overview
    def on_scan(self) -> None:
        root = Path(self.folder_edit.text().strip())
        if not root.is_dir():
            QMessageBox.warning(self, "FileFlow", "Please choose an existing folder.")
            return
        self.run_task(lambda p, c: scan_folder(root, p, c), self._scan_done, f"Scanning {root} ...")

    def _scan_done(self, res: ScanResult) -> None:
        self.scan = res
        self.plan, self.dup_groups = [], []
        self.suggestions = find_cleanup(res)
        self._fill_overview()
        self._fill_plan()
        self._fill_dups()
        self._fill_cleanup()
        note = " (cancelled - partial results)" if res.cancelled else ""
        self.status.setText(f"Scan complete: {len(res.files)} files, {human_size(res.total_size)}{note}")

    def _fill_overview(self) -> None:
        s = self.scan
        text = (f"<b>{len(s.files):,}</b> files · <b>{human_size(s.total_size)}</b> · "
                f"{len(s.empty_dirs)} empty folders · {len(s.protected_dirs)} project folder(s) left untouched"
                f" · {len(s.errors)} unreadable item(s)")
        self.lbl_summary.setText(text)
        total = max(s.total_size, 1)
        fill(self.tbl_types, [[ro_item(c), ro_item(f"{n:,}", right=True), ro_item(human_size(b), right=True),
                               ro_item(f"{b * 100 / total:.1f}%", right=True)] for c, n, b in s.type_breakdown()])
        fill(self.tbl_large, [[ro_item(f.path.name, f.path), ro_item(human_size(f.size), right=True),
                               ro_item(fmt_time(f.mtime)), ro_item(f.path.parent)] for f in s.largest_files(100)])
        fill(self.tbl_folders, [[ro_item(p.relative_to(s.root)), ro_item(human_size(b), right=True),
                                 ro_item(n, right=True)] for p, b, n in s.folder_sizes(50)])

    # ------------------------------------------------------------------ preview plan
    def on_build_plan(self) -> None:
        if not self.scan:
            QMessageBox.information(self, "FileFlow", "Scan a folder first.")
            return
        scan, rules = self.scan, list(self.rules)
        dest = self.dest_edit.text().strip() or None
        scope = self.cmb_scope.currentData()
        rename = self.chk_rename.isChecked()
        use_ai = self.chk_ai.isChecked() and ai_configured()

        def job(p, c):
            hints, warn = {}, ""
            if use_ai:
                try:
                    from ..core.categorizer import classify  # only unclassified files go to the AI
                    from datetime import datetime as dt
                    cand = [f for f in scan.files if not f.protected and classify(f.path, dt.now()).fallback]
                    hints = ai_hints_for(cand)
                except AIError as e:
                    warn = f"AI hints skipped: {e}"
            return build_plan(scan, dest, rules, scope, rename, hints, p, c), warn

        self.run_task(job, self._plan_done, "Building preview plan ...")

    def _plan_done(self, result) -> None:
        self.plan, warn = result
        self._fill_plan()
        self.tabs.setCurrentIndex(1)
        self.status.setText(warn or "Preview ready - review it, then press Apply. Nothing has changed yet.")

    def _sync_plan_checks(self) -> None:
        for r, it in enumerate(self.plan):
            cell = self.tbl_plan.item(r, 0)
            if cell is not None:
                it.enabled = cell.checkState() == CHECKED

    def _rel(self, p: Path, base: Path | None) -> str:
        try:
            return str(p.relative_to(base)) if base else str(p)
        except ValueError:
            return str(p)

    def _fill_plan(self) -> None:
        src_root = self.scan.root if self.scan else None
        dst_root = Path(self.dest_edit.text().strip()) if self.dest_edit.text().strip() else src_root
        fill(self.tbl_plan, [[check_item(i.enabled, i.src), ro_item(i.action),
                              ro_item(self._rel(i.src, src_root)), ro_item(self._rel(i.dst, dst_root)),
                              ro_item(i.reason)] for i in self.plan])
        self.lbl_plan.setText(f"<b>{summarize(self.plan)}</b> (untick rows to exclude them)" if self.plan
                              else "No plan yet. Scan a folder, then build a preview.")

    def on_reject(self) -> None:
        self.plan = []
        self._fill_plan()
        self.status.setText("Plan rejected. No files were changed.")

    def on_edit(self) -> None:
        rows = sorted({i.row() for i in self.tbl_plan.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "FileFlow", "Select one or more rows to edit.")
            return
        self._sync_plan_checks()
        if len(rows) == 1:
            item = self.plan[rows[0]]
            text, ok = QInputDialog.getText(self, "Edit destination",
                                            "New full destination path (folder + file name):", text=str(item.dst))
            if not ok or not text.strip():
                return
            new = Path(text.strip())
            if not new.is_absolute():
                new = (Path(self.dest_edit.text().strip() or self.scan.root)) / new
            if new.name in ("", ".", ".."):
                QMessageBox.warning(self, "FileFlow", "That is not a valid file path.")
                return
            item.dst = new
        else:
            d = QFileDialog.getExistingDirectory(self, f"Move {len(rows)} selected files to...",
                                                 self.dest_edit.text() or str(self.scan.root))
            if not d:
                return
            for r in rows:
                self.plan[r].dst = Path(d) / self.plan[r].src.name
        resolve_conflicts(self.plan)
        self._fill_plan()

    def on_apply(self) -> None:
        self._sync_plan_checks()
        items = [i for i in self.plan if i.enabled]
        if not items:
            QMessageBox.information(self, "FileFlow", "There is nothing to apply.")
            return
        moved = sum(1 for i in items if i.action != "rename")
        renamed = sum(1 for i in items if i.action != "move")
        if not self._confirm("Apply this plan?",
                             f"{moved} file(s) will be moved and {renamed} renamed.\n\n"
                             "Nothing is deleted and nothing is overwritten.\n"
                             "Every change is recorded so you can Undo it.\n\nProceed?"):
            return
        root = self.scan.root
        ops = ops_from_plan(items)
        self.run_task(lambda p, c: apply_ops(self.history, ops, f"Organize {root.name}", root, p, c),
                      lambda r: self._after_apply(r, "Plan applied"), "Applying plan ...")

    def _after_apply(self, res, title: str) -> None:
        msg = f"{res.done} operation(s) completed."
        for label, lst in (("Skipped", res.skipped), ("Failed", res.failed)):
            if lst:
                msg += f"\n\n{label} ({len(lst)}):\n" + "\n".join(f"- {Path(a).name}: {b}" for a, b in lst[:8])
        if res.done:
            msg += "\n\nYou can undo this from the Undo button or the History tab."
        QMessageBox.information(self, title, msg)
        self._refresh_history()
        self.plan = []
        if self.folder_edit.text().strip():
            self.on_scan()

    # ------------------------------------------------------------------ duplicates
    def on_find_dups(self) -> None:
        if not self.scan:
            QMessageBox.information(self, "FileFlow", "Scan a folder first.")
            return
        files, percep = self.scan.files, self.chk_percep.isChecked()

        def job(p, c):
            groups = find_exact_duplicates(files, p, c)
            if percep and not c.is_set():
                groups += find_similar_images(files, 5, groups, p, c)
            return groups

        self.run_task(job, self._dups_done, "Hashing files ...")

    def _dups_done(self, groups) -> None:
        self.dup_groups = groups
        self._fill_dups()
        self.tabs.setCurrentIndex(2)
        wasted = sum(g.wasted for g in groups if g.kind == "exact")
        self.status.setText(f"{len(groups)} duplicate group(s); {human_size(wasted)} reclaimable from exact copies.")

    def _fill_dups(self) -> None:
        t = self.tree_dups
        t.clear()
        for g in self.dup_groups:
            if g.kind == "exact":
                title = (f"Possible duplicate ×{len(g.paths)} · Size: {human_size(g.sizes[0])} · "
                         f"Hash: {g.key[:16]}…")
            else:
                title = f"Similar images ×{len(g.paths)} · {g.key}"
            parent = QTreeWidgetItem([ "", title, "", "", ""])
            t.addTopLevelItem(parent)
            for i, (p, size) in enumerate(zip(g.paths, g.sizes)):
                try:
                    mt = fmt_time(p.stat().st_mtime)
                except OSError:
                    mt = "?"
                child = QTreeWidgetItem(["", p.name, human_size(size), mt, str(p.parent)])
                child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, CHECKED if i == 0 else UNCHECKED)
                child.setData(1, PATH_ROLE, str(p))
                parent.addChild(child)
            parent.setExpanded(True)

    def _dup_selected(self) -> None:
        items = self.tree_dups.selectedItems()
        if items and items[0].data(1, PATH_ROLE):
            self.show_preview(Path(items[0].data(1, PATH_ROLE)))

    def _dup_keep(self, mode: str) -> None:
        t = self.tree_dups
        for gi in range(t.topLevelItemCount()):
            parent = t.topLevelItem(gi)
            stats = []
            for ci in range(parent.childCount()):
                p = Path(parent.child(ci).data(1, PATH_ROLE))
                try:
                    stats.append((p.stat().st_mtime, ci))
                except OSError:
                    stats.append((float("inf"), ci))
            pick = (min(stats) if mode == "oldest" else max(stats))[1]
            for ci in range(parent.childCount()):
                parent.child(ci).setCheckState(0, CHECKED if ci == pick else UNCHECKED)

    def on_dup_apply(self) -> None:
        t, remove, bad = self.tree_dups, [], 0
        for gi in range(t.topLevelItemCount()):
            parent = t.topLevelItem(gi)
            kids = [parent.child(i) for i in range(parent.childCount())]
            if not any(k.checkState(0) == CHECKED for k in kids):
                bad += 1
            remove += [Path(k.data(1, PATH_ROLE)) for k in kids if k.checkState(0) != CHECKED]
        if bad:
            QMessageBox.warning(self, "FileFlow", f"{bad} group(s) have no file ticked to keep. "
                                "Tick at least one file per group.")
            return
        if not remove:
            QMessageBox.information(self, "FileFlow", "Everything is ticked - nothing to quarantine.")
            return
        if not self._confirm("Quarantine duplicates?",
                             f"{len(remove)} file(s) will be moved to '{QUARANTINE_DIR}' inside the scanned "
                             "folder. They are NOT deleted and can be restored with Undo.\n\nProceed?"):
            return
        root = self.scan.root
        ops = quarantine_ops(root, remove)
        self.run_task(lambda p, c: apply_ops(self.history, ops, "Quarantine duplicates", root, p, c),
                      lambda r: self._after_apply(r, "Duplicates quarantined"), "Quarantining ...")

    # ------------------------------------------------------------------ cleanup
    def _fill_cleanup(self) -> None:
        fill(self.tbl_clean, [[check_item(False, s.path), ro_item(s.kind), ro_item(s.path),
                               ro_item(human_size(s.size), right=True), ro_item(s.reason)]
                              for s in self.suggestions])

    def _clean_select(self, on: bool) -> None:
        for r in range(self.tbl_clean.rowCount()):
            self.tbl_clean.item(r, 0).setCheckState(CHECKED if on else UNCHECKED)

    def on_clean_apply(self) -> None:
        ops_files, ops_dirs = [], []
        for r, s in enumerate(self.suggestions):
            if self.tbl_clean.item(r, 0).checkState() == CHECKED:
                (ops_dirs if s.kind == "empty_dir" else ops_files).append(s.path)
        if not (ops_files or ops_dirs):
            QMessageBox.information(self, "FileFlow", "Tick the items you want to clean up first.")
            return
        if not self._confirm("Clean up?", f"{len(ops_files)} file(s) will be moved to quarantine and "
                             f"{len(ops_dirs)} empty folder(s) removed. All of this can be undone.\n\nProceed?"):
            return
        root = self.scan.root
        ops = quarantine_ops(root, ops_files) + [Op("rmdir", d) for d in ops_dirs]
        self.run_task(lambda p, c: apply_ops(self.history, ops, "Cleanup", root, p, c),
                      lambda r: self._after_apply(r, "Cleanup done"), "Cleaning up ...")

    # ------------------------------------------------------------------ history / undo
    def _refresh_history(self) -> None:
        rows = self.history.batches()
        fill(self.tbl_hist, [[ro_item(r["id"], r["id"]), ro_item(r["created"].replace("T", " ")),
                              ro_item(r["label"]), ro_item(r["op_count"], right=True),
                              ro_item("Undone" if r["undone"] else "Active")] for r in rows])
        fill(self.tbl_ops, [])

    def _selected_batch(self) -> int | None:
        rows = self.tbl_hist.selectionModel().selectedRows()
        return int(self.tbl_hist.item(rows[0].row(), 0).text()) if rows else None

    def _hist_selected(self) -> None:
        b = self._selected_batch()
        if b is None:
            return
        ops = self.history.ops(b)
        fill(self.tbl_ops, [[ro_item(o["kind"]), ro_item(o["src"]), ro_item(o["dst"] or ""),
                             ro_item(o["status"])] for o in ops])

    def on_undo_last(self) -> None:
        b = self.history.latest_undoable()
        if b is None:
            QMessageBox.information(self, "FileFlow", "There is nothing to undo.")
            return
        self._undo(b)

    def on_undo_selected(self) -> None:
        b = self._selected_batch()
        if b is None:
            QMessageBox.information(self, "FileFlow", "Select a batch in the list first.")
            return
        self._undo(b)

    def _undo(self, batch_id: int) -> None:
        if not self._confirm("Undo?", f"Restore every file from operation batch #{batch_id} to where it "
                             "was before?\nFiles you changed since will be left alone and reported."):
            return

        def done(res):
            msg = f"{res.restored} item(s) restored."
            if res.skipped:
                msg += f"\n\nLeft in place ({len(res.skipped)}):\n" + "\n".join(
                    f"- {Path(a).name}: {b}" for a, b in res.skipped[:8])
            QMessageBox.information(self, "Undo", msg)
            self._refresh_history()
            if self.folder_edit.text().strip():
                self.on_scan()

        self.run_task(lambda p, c: undo_batch(self.history, batch_id, p, c), done, "Undoing ...")

    # ------------------------------------------------------------------ custom categories
    def _load_rules(self) -> None:
        try:
            raw = json.loads(self.history.get_setting("custom_rules", "[]"))
        except json.JSONDecodeError:
            raw = []
        self.rules = [CustomRule(k, tuple(d)) for k, d in raw if k and d]
        self._fill_rules()

    def _fill_rules(self) -> None:
        fill(self.tbl_rules, [[ro_item(r.keyword), ro_item("/".join(r.dest))] for r in self.rules])

    def _save_rules(self) -> None:
        self.history.set_setting("custom_rules", json.dumps([[r.keyword, list(r.dest)] for r in self.rules]))
        self._fill_rules()

    def on_add_rule(self) -> None:
        kw = self.rule_kw.text().strip()
        parts = sanitize_parts(self.rule_dest.text().replace("\\", "/").split("/"))
        if not kw or not parts:
            QMessageBox.warning(self, "FileFlow", "Enter a keyword and a destination folder.")
            return
        self.rules.append(CustomRule(kw, parts))
        self.rule_kw.clear()
        self.rule_dest.clear()
        self._save_rules()

    def on_remove_rule(self) -> None:
        rows = sorted({i.row() for i in self.tbl_rules.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.rules[r]
        self._save_rules()

    # ------------------------------------------------------------------ preview panel
    def show_preview(self, path: Path) -> None:
        lines = [f"Name:   {path.name}", f"Folder: {path.parent}"]
        try:
            st = path.stat()
            lines += [f"Size:   {human_size(st.st_size)}", f"Modified: {fmt_time(st.st_mtime)}",
                      f"Type:   {ext_category(path.suffix.lower())}"]
        except OSError:
            lines.append("(file not accessible)")
        pix = QPixmap(str(path)) if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"} else None
        if pix is not None and not pix.isNull():
            self.preview_img.setPixmap(pix.scaled(280, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
            info = image_info(path)
            if info.size:
                lines.append(f"Dimensions: {info.size[0]} x {info.size[1]}")
            if info.taken:
                lines.append(f"Taken:  {info.taken:%Y-%m-%d %H:%M:%S}")
            if info.camera:
                lines.append(f"Camera: {info.camera}")
        else:
            self.preview_img.setPixmap(QPixmap())
            self.preview_img.setText("No image preview")
        self.preview_txt.setPlainText("\n".join(lines))
