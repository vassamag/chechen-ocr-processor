"""
app.py

Desktop GUI for chechen_ocr, built on Tkinter (stdlib -- no extra
dependency beyond the system Tk package). Wraps ChechenOcrProcessor
(single file: image/PDF/TXT/DOCX) and BatchProcessor (a whole
directory) with a review workflow the person can edit directly in the
table, instead of round-tripping through a CSV file by hand.

Scope for this version: single-file/batch processing with an explicit
source-engine selector (Tesseract-scan vs pre-recognized-by-Vision),
no in-app Vision-API key management UI yet (Vision recognition itself
is expected to happen elsewhere, e.g. ocr_book_directory.py; this app
only applies the correction pipeline to already-recognized text or to
a scan you OCR right here with Tesseract). No TTS/translation (kept
out on purpose -- see project discussion). A web version (Streamlit)
is a plausible later addition sharing the same chechen_ocr API
underneath; this module holds none of the business logic itself, only
presentation, so that stays possible without duplicating anything.

All slow work (OCR, PDF rasterization, correction) runs in a
background thread via processing.run_in_background -- Tkinter widgets
are only ever touched from the main thread, via periodic queue
polling (see _poll_queue). This is the standard safe pattern for
mixing Tkinter with background work.
"""

from __future__ import annotations

import csv
import functools
import logging
import queue
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .. import __version__
from ..batch import BatchProcessor, BatchResult
from ..config import Settings
from ..ocr.tesseract_engine import TesseractEngine
from ..processor import ChechenOcrProcessor, ProcessedDocument
from ..review import apply_review_rows, build_review_rows
from ..review.apply_review_table import WORD_CHARS
from ..review.schema import REVIEW_CSV_FIELDNAMES
from .processing import JobDone, LogMessage, QueueLogHandler, run_in_background
from .review_model import TREEVIEW_COLUMNS, VALID_DECISIONS, ReviewTableModel

logger = logging.getLogger(__name__)

SUSPICIOUS_TAG = "suspicious_highlight"
APPLIED_TAG = "applied_highlight"

SUPPORTED_FILETYPES = [
    ("Supported files", "*.txt *.docx *.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif"),
    ("All files", "*.*"),
]


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app: App):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.app = app

        pad: dict[str, Any] = {"padx": 8, "pady": 4}

        ttk.Label(self, text="Rules directory (leave empty for bundled default):").grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        self.rules_dir_entry = ttk.Entry(self, textvariable=app.rules_dir_var, width=50)
        self.rules_dir_entry.grid(row=1, column=0, **pad)
        ttk.Button(self, text="Browse...", command=self._browse_rules_dir).grid(
            row=1, column=1, **pad
        )

        ttk.Label(self, text="Tesseract binary path (leave empty for PATH lookup):").grid(
            row=2, column=0, columnspan=2, sticky="w", **pad
        )
        self.tesseract_entry = ttk.Entry(self, textvariable=app.tesseract_cmd_var, width=50)
        self.tesseract_entry.grid(row=3, column=0, **pad)
        ttk.Button(self, text="Browse...", command=self._browse_tesseract).grid(
            row=3, column=1, **pad
        )

        ttk.Label(self, text="OCR language (Tesseract code, e.g. rus):").grid(
            row=4, column=0, sticky="w", **pad
        )
        ttk.Entry(self, textvariable=app.lang_var, width=15).grid(
            row=4, column=1, sticky="w", **pad
        )

        ttk.Label(self, text="PDF rasterization DPI:").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(self, textvariable=app.pdf_dpi_var, width=15).grid(
            row=5, column=1, sticky="w", **pad
        )

        ttk.Button(self, text="Close", command=self.destroy).grid(
            row=6, column=0, columnspan=2, pady=8
        )

    def _browse_rules_dir(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.app.rules_dir_var.set(path)

    def _browse_tesseract(self) -> None:
        path = filedialog.askopenfilename()
        if path:
            self.app.tesseract_cmd_var.set(path)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Chechen OCR Desktop (chechen_ocr v{__version__})")
        root.geometry("980x680")

        self.current_path: Path | None = None
        self.is_batch: bool = False
        self.doc: ProcessedDocument | None = None
        self.batch_result: BatchResult | None = None
        self.review_model: ReviewTableModel | None = None

        self.rules_dir_var = tk.StringVar(value="")
        self.tesseract_cmd_var = tk.StringVar(value="")
        self.lang_var = tk.StringVar(value=Settings.default().default_lang)
        self.pdf_dpi_var = tk.IntVar(value=300)
        # "tesseract" applies the Tesseract-lookalike-pattern correctors
        # (DirectPalochkaLookalikes/PatternBasedPalochka/CommonWordFixList)
        # and skips InternalCapitalizationFix. "openai_vision" is the
        # opposite: skips the Tesseract-specific patterns, enables
        # InternalCapitalizationFix. Use "openai_vision" for any text
        # that was already recognized by a Vision-capable model (e.g.
        # ocr_book_directory.py output), even when loading it here as
        # plain .txt with no fresh OCR happening in this app at all --
        # this setting does not trigger any recognition step, it only
        # selects which correction rules apply to text you already have.
        self.ocr_engine_var = tk.StringVar(value="tesseract")

        self._message_queue: queue.Queue = queue.Queue()
        self._log_handler = QueueLogHandler(self._message_queue)
        self._log_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logging.getLogger("chechen_ocr").addHandler(self._log_handler)
        logging.getLogger("chechen_ocr").setLevel(logging.INFO)

        self._configure_style()
        self._build_menu()
        self._build_layout()
        self._poll_queue()

    def _configure_style(self) -> None:
        """Tab strip defaults are very cramped (tabs touch each other,
        text touches the tab edge) -- add breathing room. Treeview
        defaults have almost no visual separation between the header
        row and the body, or between columns.

        Windows' native theme ('vista'/'winnative') mostly ignores
        custom relief/border/background settings on Treeview.Heading --
        it draws headers using native OS routines regardless of what
        ttk style options say, which is why the previous attempt at
        this (relief='raised', borderwidth=1) had no visible effect on
        Windows even though it worked under Linux/Xvfb during testing.
        'clam' is a fully ttk-drawn theme (not delegated to the OS) and
        actually honors these settings, so it's switched to explicitly
        here rather than relying on the platform default."""
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TNotebook", tabmargins=[2, 4, 2, 0])
        style.configure("TNotebook.Tab", padding=[14, 6])

        style.configure("Treeview", rowheight=26, bordercolor="#999999", borderwidth=1)
        style.configure(
            "Treeview.Heading",
            background="#dcdcdc",
            relief="raised",
            borderwidth=2,
            padding=[6, 5],
        )
        style.map("Treeview.Heading", background=[("active", "#c8c8c8")])
        style.map("Treeview", background=[("selected", "#3874d8")])

    # -- layout -----------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open File...", command=self.on_open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Open Batch Directory...", command=self.on_open_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Export Corrected TXT...", command=self.on_export_txt)
        file_menu.add_command(label="Export DOCX (highlighted)...", command=self.on_export_docx)
        file_menu.add_command(label="Export Review CSV...", command=self.on_export_review_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Configure...", command=self.on_open_settings)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.on_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind_all("<Control-o>", lambda _event: self.on_open_file())

    def _build_layout(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        self.path_label = ttk.Label(top, text="No file selected", anchor="w")
        self.path_label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(top, mode="indeterminate", length=140)
        self.progress.pack(side="right", padx=8)
        self.process_button = ttk.Button(
            top, text="Process", command=self.on_process, state="disabled"
        )
        self.process_button.pack(side="right")

        engine_frame = ttk.Frame(top)
        engine_frame.pack(side="right", padx=(0, 12))
        ttk.Label(engine_frame, text="Source:").pack(side="left", padx=(0, 4))
        ttk.Radiobutton(
            engine_frame,
            text="Scan (Tesseract)",
            variable=self.ocr_engine_var,
            value="tesseract",
        ).pack(side="left")
        ttk.Radiobutton(
            engine_frame,
            text="Pre-recognized (Vision)",
            variable=self.ocr_engine_var,
            value="openai_vision",
        ).pack(side="left")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.log_text = self._make_text_tab("Log")
        self._build_corrected_text_tab()
        self._build_suspicious_tab()
        self._build_metrics_tab()
        self._build_per_file_tab()

    def _make_text_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.notebook, padding=6)
        text = tk.Text(frame, wrap="word", state="disabled", padx=8, pady=6, relief="flat")
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.notebook.add(frame, text=title)
        return text

    def _build_corrected_text_tab(self) -> None:
        """
        Unlike the read-only Log/Metrics tabs, this one is editable --
        some OCR errors (dropped letters, run-together words) don't fit
        the "replace this one flagged word" model the Suspicious Words
        tab covers; a person needs to fix the sentence by hand. Manual
        edits here are NOT re-analyzed for new suspicious words or
        re-scored in Metrics -- they're taken as final once saved.

        Still-pending suspicious words are highlighted the same yellow
        used in the Suspicious Words context panel, and words just
        fixed via "Apply All Reviewed Changes" are highlighted green --
        finding them by eye in a full page of text was the whole
        problem this was added to solve (see project discussion).
        """
        frame = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(frame, text="Corrected Text")

        toolbar = ttk.Frame(frame)
        toolbar.pack(side="top", fill="x", pady=(0, 6))
        ttk.Label(
            toolbar,
            text="Editable -- fix anything the Suspicious Words table couldn't "
            "(dropped letters, run-together words, etc.)",
        ).pack(side="left")
        ttk.Button(toolbar, text="Save Edits", command=self.on_save_corrected_text).pack(
            side="right"
        )

        legend = ttk.Frame(frame)
        legend.pack(side="top", fill="x", pady=(0, 4))
        tk.Label(legend, text="  ", background="#fff3a0").pack(side="left")
        ttk.Label(legend, text="still flagged").pack(side="left", padx=(4, 12))
        tk.Label(legend, text="  ", background="#b6f2b6").pack(side="left")
        ttk.Label(legend, text="just fixed").pack(side="left", padx=(4, 0))

        text_frame = ttk.Frame(frame)
        text_frame.pack(side="top", fill="both", expand=True)
        self.corrected_text = tk.Text(text_frame, wrap="word", padx=8, pady=6, relief="flat")
        self.corrected_text.tag_configure(SUSPICIOUS_TAG, background="#fff3a0")
        self.corrected_text.tag_configure(APPLIED_TAG, background="#b6f2b6")
        scrollbar = ttk.Scrollbar(text_frame, command=self.corrected_text.yview)
        self.corrected_text.configure(yscrollcommand=scrollbar.set)
        self.corrected_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_suspicious_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(frame, text="Suspicious Words")

        table_frame = ttk.Frame(frame)
        table_frame.pack(side="top", fill="both", expand=True)

        self.tree = ttk.Treeview(
            table_frame, columns=TREEVIEW_COLUMNS, show="headings", selectmode="browse"
        )
        self.tree.tag_configure("oddrow", background="#f2f2f2")
        self.tree.tag_configure("evenrow", background="#ffffff")
        widths = {
            "id": 40,
            "page": 60,
            "word": 140,
            "reason": 200,
            "candidates": 160,
            "decision": 80,
            "replacement": 140,
        }
        for col in TREEVIEW_COLUMNS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths.get(col, 100))
        self.tree.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        context_frame = ttk.Frame(frame, padding=(0, 6))
        context_frame.pack(side="top", fill="x")
        ttk.Label(context_frame, text="Context (select a row above):").pack(side="top", anchor="w")
        self.context_text = tk.Text(
            context_frame,
            wrap="word",
            height=4,
            state="disabled",
            padx=8,
            pady=6,
            relief="solid",
            borderwidth=1,
        )
        self.context_text.tag_configure("flagged_word", background="#fff3a0", font=("", 10, "bold"))
        self.context_text.pack(side="top", fill="x")

        self.candidates_frame = ttk.Frame(context_frame, padding=(0, 4, 0, 0))
        self.candidates_frame.pack(side="top", fill="x")

        edit_frame = ttk.Frame(frame, padding=8)
        edit_frame.pack(side="bottom", fill="x")

        ttk.Label(edit_frame, text="Decision:").grid(row=0, column=0, sticky="w")
        self.decision_var = tk.StringVar(value="pending")
        self.decision_combo = ttk.Combobox(
            edit_frame,
            textvariable=self.decision_var,
            values=VALID_DECISIONS,
            state="readonly",
            width=12,
        )
        self.decision_combo.grid(row=0, column=1, padx=4)

        ttk.Label(edit_frame, text="Replacement:").grid(row=0, column=2, sticky="w")
        self.replacement_var = tk.StringVar()
        ttk.Entry(edit_frame, textvariable=self.replacement_var, width=30).grid(
            row=0, column=3, padx=4
        )

        ttk.Button(edit_frame, text="Save Row", command=self.on_save_row).grid(
            row=0, column=4, padx=4
        )
        ttk.Button(
            edit_frame, text="Apply All Reviewed Changes", command=self.on_apply_review
        ).grid(row=0, column=5, padx=12)

    def _build_metrics_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="Metrics")
        self.metrics_text = tk.Text(
            frame, wrap="word", state="disabled", padx=8, pady=6, relief="flat"
        )
        self.metrics_text.pack(fill="both", expand=True)

    def _build_per_file_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(frame, text="Per-File (Batch)")
        columns = (
            "index",
            "filename",
            "word_count",
            "correction_count",
            "suspicious_count",
            "suspicious_ratio",
        )
        self.per_file_tree = ttk.Treeview(frame, columns=columns, show="headings")
        self.per_file_tree.tag_configure("oddrow", background="#f2f2f2")
        self.per_file_tree.tag_configure("evenrow", background="#ffffff")
        for col in columns:
            self.per_file_tree.heading(col, text=col)
        self.per_file_tree.pack(fill="both", expand=True)

    # -- helpers ----------------------------------------------------

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_text_widget(self, widget: tk.Text, content: str, keep_editable: bool = False) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        if not keep_editable:
            widget.configure(state="disabled")

    def _highlight_words(self, words: list[str], tag: str) -> None:
        """
        Tags every whole-word occurrence of each word in `words`
        within self.corrected_text with `tag`. Uses the same word-
        boundary logic as the actual replacement step
        (review.apply_review_table.WORD_CHARS) so highlighting matches
        exactly what would (or did) get replaced -- not, say, this
        word as a substring of some longer word.
        """
        content = self.corrected_text.get("1.0", "end-1c")
        for word in words:
            if not word:
                continue
            pattern = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(word)}(?![{WORD_CHARS}])")
            for match in pattern.finditer(content):
                self.corrected_text.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def _refresh_corrected_text_highlights(
        self, pending_words: list[str], applied_words: list[str]
    ) -> None:
        self.corrected_text.tag_remove(SUSPICIOUS_TAG, "1.0", "end")
        self.corrected_text.tag_remove(APPLIED_TAG, "1.0", "end")
        self._highlight_words(pending_words, SUSPICIOUS_TAG)
        self._highlight_words(applied_words, APPLIED_TAG)

    def _build_processor(
        self, rules_dir_value: str, tesseract_cmd_value: str, lang_value: str
    ) -> ChechenOcrProcessor:
        """
        Builds a ChechenOcrProcessor from plain string values (not
        Tkinter variables) so this can safely run inside a background
        thread -- tk.StringVar/IntVar.get() must only ever be called
        from the main thread; calling them from a worker thread can
        hang or deadlock. Callers read the Tk variables on the main
        thread and pass plain values in (see on_process()).
        """
        rules_dir = Path(rules_dir_value) if rules_dir_value else Settings.default().rules_dir
        tesseract_cmd = tesseract_cmd_value or None
        settings = Settings(
            rules_dir=rules_dir, tesseract_cmd=tesseract_cmd, default_lang=lang_value
        )
        engine = TesseractEngine(tesseract_cmd=tesseract_cmd)
        return ChechenOcrProcessor(settings=settings, ocr_engine=engine)

    # -- event handlers -----------------------------------------------

    def on_open_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=SUPPORTED_FILETYPES)
        if not path:
            return
        self.current_path = Path(path)
        self.is_batch = False
        self.path_label.config(text=str(self.current_path))
        self.process_button.config(state="normal")

    def on_open_directory(self) -> None:
        path = filedialog.askdirectory()
        if not path:
            return
        self.current_path = Path(path)
        self.is_batch = True
        self.path_label.config(text=f"[batch] {self.current_path}")
        self.process_button.config(state="normal")

    def on_open_settings(self) -> None:
        SettingsDialog(self.root, self)

    def on_about(self) -> None:
        messagebox.showinfo(
            "About",
            f"Chechen OCR Desktop\nchechen_ocr v{__version__}\n"
            "Source selector: choose 'Scan (Tesseract)' for images/PDFs "
            "you're OCR'ing here, or 'Pre-recognized (Vision)' for text "
            "already produced by a Vision-capable model elsewhere "
            "(e.g. ocr_book_directory.py) -- this only changes which "
            "correction rules apply, it never triggers OCR by itself.",
        )

    def on_process(self) -> None:
        if self.current_path is None:
            return
        self.process_button.config(state="disabled")
        self.progress.start(10)
        self._append_log(f"Processing {self.current_path} ...")

        path = self.current_path
        is_batch = self.is_batch
        # Read Tk variables on the main thread -- tk.StringVar/IntVar.get()
        # must not be called from the background thread (see
        # _build_processor's docstring).
        rules_dir_value = self.rules_dir_var.get().strip()
        tesseract_cmd_value = self.tesseract_cmd_var.get().strip()
        lang_value = self.lang_var.get()
        dpi = self.pdf_dpi_var.get()
        engine_name_value = self.ocr_engine_var.get()

        def work() -> tuple[str, Any]:
            processor = self._build_processor(rules_dir_value, tesseract_cmd_value, lang_value)
            if is_batch:
                batch = BatchProcessor(processor)
                return ("batch", batch.process_directory(path, ocr_engine_name=engine_name_value))

            suffix = path.suffix.lower()
            if suffix == ".txt":
                doc = processor.process_text(
                    path.read_text(encoding="utf-8", errors="replace"),
                    ocr_engine_name=engine_name_value,
                )
            elif suffix == ".docx":
                doc = processor.process_docx(path)
            elif suffix == ".pdf":
                doc = processor.process_pdf(path, dpi=dpi)
            else:
                doc = processor.process_image(path)
            return ("single", doc)

        run_in_background(work, self._message_queue)

    def on_tree_select(self, _event: Any = None) -> None:
        if self.review_model is None:
            return
        selection = self.tree.selection()
        if not selection:
            return
        item = self.review_model.find_by_id(selection[0])
        if item:
            self.decision_var.set(item.decision)

            replacement = item.replacement
            if not replacement:
                # Not yet edited -- default the Replacement field to the
                # best (first) suggested candidate, so the common case
                # (the top candidate is simply correct) needs no typing
                # and no extra click, just confirming Decision=replace
                # and Save Row. A different candidate is still one
                # click away via the buttons below.
                candidates = [c.strip() for c in item.row.candidates.split(",") if c.strip()]
                replacement = candidates[0] if candidates else ""

            self.replacement_var.set(replacement)
            self._set_context_display(item.row.corrected_context, item.row.word)
            self._set_candidate_buttons(item.row.candidates)

    def _set_context_display(self, context: str, word: str) -> None:
        """
        Shows the sentence/line the flagged word came from, with the
        word itself highlighted -- picking the right candidate is hard
        even for a native speaker without seeing how the word is
        actually used (see project discussion).
        """
        self.context_text.configure(state="normal")
        self.context_text.delete("1.0", "end")

        if not context:
            self.context_text.insert("1.0", "(no context available)")
        else:
            before, marker, after = context.partition(f"[[{word}]]")
            self.context_text.insert("end", before)
            if marker:
                self.context_text.insert("end", word, "flagged_word")
                self.context_text.insert("end", after)
            else:
                # Fallback: markers didn't match exactly (shouldn't
                # normally happen) -- show the raw context unhighlighted
                # rather than hide it.
                self.context_text.insert("end", context.replace("[[", "").replace("]]", ""))

        self.context_text.configure(state="disabled")

    def _set_candidate_buttons(self, candidates_str: str) -> None:
        for widget in self.candidates_frame.winfo_children():
            widget.destroy()

        candidates = [c.strip() for c in candidates_str.split(",") if c.strip()]
        if not candidates:
            return

        ttk.Label(self.candidates_frame, text="Candidates:").pack(side="left", padx=(0, 6))
        for candidate in candidates:
            ttk.Button(
                self.candidates_frame,
                text=candidate,
                command=functools.partial(self._select_candidate, candidate),
            ).pack(side="left", padx=2)

    def _select_candidate(self, candidate: str) -> None:
        self.replacement_var.set(candidate)

    def on_save_row(self) -> None:
        if self.review_model is None:
            return
        selection = self.tree.selection()
        if not selection:
            return
        row_id = selection[0]
        self.review_model.set_decision(row_id, self.decision_var.get())
        self.review_model.set_replacement(row_id, self.replacement_var.get())
        item = self.review_model.find_by_id(row_id)
        if item:
            self.tree.item(row_id, values=item.display_values())

    def on_save_corrected_text(self) -> None:
        """
        Persists whatever is currently typed in the Corrected Text
        tab into self.doc.corrected_text. Deliberately does NOT
        re-run suspicious-word detection or recompute Metrics on the
        edited text -- a manual edit is treated as final, the same
        way applying reviewed CSV changes is. If you want the
        suspicious-word list to reflect the edit, re-process the
        source file instead.
        """
        if self.doc is None:
            messagebox.showwarning("Nothing to save", "Process a file first.")
            return

        new_text = self.corrected_text.get("1.0", "end-1c")
        self.doc = ProcessedDocument(
            corrected_text=new_text,
            raw_text=self.doc.raw_text,
            corrections=self.doc.corrections,
            suspicious=self.doc.suspicious,
        )
        if self.review_model is not None:
            self._refresh_corrected_text_highlights(
                pending_words=[item.row.word for item in self.review_model.items],
                applied_words=[],
            )
        self._append_log("Saved manual edits to corrected text.")
        messagebox.showinfo(
            "Saved",
            "Manual edits saved. Note: the Suspicious Words table and Metrics "
            "still reflect the text before this edit.",
        )

    def on_apply_review(self) -> None:
        if self.doc is None or self.review_model is None:
            messagebox.showwarning("Nothing to apply", "Process a file first.")
            return
        rows = self.review_model.as_apply_dicts()
        new_text, results = apply_review_rows(self.doc.corrected_text, rows)
        applied = sum(1 for r in results if r.status == "applied")

        self.doc = ProcessedDocument(
            corrected_text=new_text,
            raw_text=self.doc.raw_text,
            corrections=self.doc.corrections,
            suspicious=self.doc.suspicious,
        )
        self._set_text_widget(self.corrected_text, new_text, keep_editable=True)

        pending_words = []
        applied_words = []
        for item, result in zip(self.review_model.items, results, strict=True):
            if result.status == "applied":
                applied_words.append(result.replacement)
            else:
                pending_words.append(item.row.word)
        self._refresh_corrected_text_highlights(pending_words, applied_words)

        self._append_log(f"Applied {applied} reviewed change(s).")
        messagebox.showinfo("Applied", f"{applied} change(s) applied to the corrected text.")

    def on_export_txt(self) -> None:
        if self.doc is None:
            messagebox.showwarning("No result", "Process a file first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt")
        if not path:
            return
        Path(path).write_text(self.doc.corrected_text, encoding="utf-8")
        self._append_log(f"Wrote {path}")

    def on_export_docx(self) -> None:
        if self.doc is None:
            messagebox.showwarning("No result", "Process a file first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".docx")
        if not path:
            return
        processor = self._build_processor(
            self.rules_dir_var.get().strip(),
            self.tesseract_cmd_var.get().strip(),
            self.lang_var.get(),
        )
        processor.export_docx(self.doc, Path(path))
        self._append_log(f"Wrote {path}")

    def on_export_review_csv(self) -> None:
        if self.review_model is None:
            messagebox.showwarning("No result", "Process a file first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        if not path:
            return
        with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REVIEW_CSV_FIELDNAMES)
            writer.writeheader()
            for row_dict in self.review_model.as_apply_dicts():
                writer.writerow(row_dict)
        self._append_log(f"Wrote {path}")

    # -- background job completion -----------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._message_queue.get_nowait()
                if isinstance(msg, LogMessage):
                    self._append_log(msg.text)
                elif isinstance(msg, JobDone):
                    self._on_job_done(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_job_done(self, msg: JobDone) -> None:
        self.progress.stop()
        self.process_button.config(state="normal")

        if msg.error is not None:
            self._append_log(f"ERROR: {msg.error}")
            messagebox.showerror("Processing failed", str(msg.error))
            return

        kind, result = msg.result
        if kind == "batch":
            self.batch_result = result
            self.doc = result.doc
            self._set_per_file(result)
        else:
            self.batch_result = None
            self.doc = result

        self._set_text_widget(self.corrected_text, self.doc.corrected_text, keep_editable=True)
        self._set_suspicious(self.doc)
        self._set_metrics(self.doc, self.batch_result)
        if self.review_model is not None:
            self._refresh_corrected_text_highlights(
                pending_words=[item.row.word for item in self.review_model.items],
                applied_words=[],
            )
        self._append_log("Done.")

    def _set_suspicious(self, doc: ProcessedDocument) -> None:
        rows = build_review_rows(doc.raw_text, doc.corrected_text, doc.suspicious)
        self.review_model = ReviewTableModel.from_rows(rows)

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        for i, item in enumerate(self.review_model.items):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert(
                "", "end", iid=str(item.row.id), values=item.display_values(), tags=(tag,)
            )

        self._set_context_display("", "")
        self._set_candidate_buttons("")

    def _set_metrics(self, doc: ProcessedDocument, batch_result: BatchResult | None) -> None:
        from ..metrics import compute_metrics

        metrics = compute_metrics(doc.corrected_text, doc.corrections, len(doc.suspicious))
        lines = [
            f"Total words: {metrics.total_words}",
            f"Total corrections: {metrics.total_corrections}",
            f"Suspicious words: {metrics.suspicious_count} ({metrics.suspicious_ratio:.1%})",
            f"Unconverted lookalikes remaining: {metrics.unconverted_lookalike_count}",
            "",
            "Corrections by rule:",
        ]
        for rule, count in sorted(metrics.corrections_by_rule.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {rule}: {count}")

        if batch_result is not None:
            lines.append("")
            lines.append(
                f"Batch: {len(batch_result.per_file)} file(s) processed, "
                f"{len(batch_result.skipped_files)} skipped"
            )

        self._set_text_widget(self.metrics_text, "\n".join(lines))

    def _set_per_file(self, batch_result: BatchResult) -> None:
        for item_id in self.per_file_tree.get_children():
            self.per_file_tree.delete(item_id)
        for i, f in enumerate(batch_result.worst_files):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.per_file_tree.insert(
                "",
                "end",
                values=(
                    f.index,
                    f.filename,
                    f.word_count,
                    f.correction_count,
                    f.suspicious_count,
                    f"{f.suspicious_ratio:.1%}",
                ),
                tags=(tag,),
            )


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
