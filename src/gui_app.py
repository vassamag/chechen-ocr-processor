from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Chechen OCR Processor GUI"
APP_VERSION = "v0.1-txt"


class ChechenOCRGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_TITLE} {APP_VERSION}")
        self.geometry("820x560")
        self.minsize(760, 500)

        self.project_root = Path(__file__).resolve().parents[1]
        self.src_dir = self.project_root / "src"
        self.pipeline_path = self.src_dir / "run_pipeline.py"

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.base_name_var = tk.StringVar(value="processed")
        self.status_var = tk.StringVar(value="Ready")

        self.current_process: subprocess.Popen[str] | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(
            root,
            text="Chechen OCR Processor",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            root,
            text="TXT post-processing version. Input: raw OCR .txt -> Output: corrected text and reports.",
        )
        subtitle.pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(root)
        form.pack(fill=tk.X)

        # Input TXT
        ttk.Label(form, text="Input TXT:").grid(row=0, column=0, sticky="w", pady=4)
        input_entry = ttk.Entry(form, textvariable=self.input_var)
        input_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(form, text="Choose...", command=self.choose_input).grid(
            row=0, column=2, sticky="ew", pady=4
        )

        # Output folder
        ttk.Label(form, text="Output folder:").grid(row=1, column=0, sticky="w", pady=4)
        output_entry = ttk.Entry(form, textvariable=self.output_var)
        output_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(form, text="Choose...", command=self.choose_output).grid(
            row=1, column=2, sticky="ew", pady=4
        )

        # Base name
        ttk.Label(form, text="Base name:").grid(row=2, column=0, sticky="w", pady=4)
        base_entry = ttk.Entry(form, textvariable=self.base_name_var, width=24)
        base_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        form.columnconfigure(1, weight=1)

        buttons = ttk.Frame(root)
        buttons.pack(fill=tk.X, pady=(10, 8))

        self.run_button = ttk.Button(
            buttons,
            text="Run processor",
            command=self.run_pipeline,
        )
        self.run_button.pack(side=tk.LEFT)

        self.open_button = ttk.Button(
            buttons,
            text="Open output folder",
            command=self.open_output_folder,
        )
        self.open_button.pack(side=tk.LEFT, padx=(8, 0))

        self.clear_button = ttk.Button(
            buttons,
            text="Clear log",
            command=self.clear_log,
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        status_frame = ttk.Frame(root)
        status_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )

        log_label = ttk.Label(root, text="Log:")
        log_label.pack(anchor="w")

        log_frame = ttk.Frame(root)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            wrap="none",
            height=18,
            font=("Consolas", 10),
        )

        y_scrollbar = ttk.Scrollbar(
            log_frame,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
        )

        x_scrollbar = ttk.Scrollbar(
            log_frame,
            orient=tk.HORIZONTAL,
            command=self.log_text.xview,
        )

        self.log_text.configure(
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set,
        )

        self.log_text.grid(row=0, column=0, sticky="nsew")
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        x_scrollbar.grid(row=1, column=0, sticky="ew")

        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log(
            f"{APP_TITLE} {APP_VERSION}\n"
            f"Project root: {self.project_root}\n"
            f"Pipeline: {self.pipeline_path}\n"
        )

    def choose_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose raw OCR TXT file",
            filetypes=[
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)

            if not self.output_var.get():
                input_path = Path(path)
                default_out = input_path.parent / f"{input_path.stem}_processed_output"
                self.output_var.set(str(default_out))

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_var.set(path)

    def open_output_folder(self) -> None:
        out = self.output_var.get().strip()
        if not out:
            messagebox.showwarning(
                "No output folder",
                "Please choose an output folder first.",
            )
            return

        out_path = Path(out)
        out_path.mkdir(parents=True, exist_ok=True)

        try:
            os.startfile(str(out_path))
        except Exception as exc:
            messagebox.showerror(
                "Error",
                f"Could not open output folder:\n{exc}",
            )

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)

    def log(self, text: str) -> None:
        self.log_text.insert(tk.END, text)
        if not text.endswith("\n"):
            self.log_text.insert(tk.END, "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

    def validate_inputs(self) -> tuple[Path, Path, str] | None:
        input_text = self.input_var.get().strip()
        output_text = self.output_var.get().strip()
        base_name = self.base_name_var.get().strip() or "processed"

        if not input_text:
            messagebox.showwarning(
                "Missing input",
                "Please choose an input TXT file.",
            )
            return None

        input_path = Path(input_text)

        if not input_path.exists():
            messagebox.showerror(
                "Input not found",
                f"Input file not found:\n{input_path}",
            )
            return None

        if input_path.suffix.lower() != ".txt":
            answer = messagebox.askyesno(
                "Non-TXT file",
                "The selected file does not have .txt extension.\nContinue anyway?",
            )
            if not answer:
                return None

        if not output_text:
            messagebox.showwarning(
                "Missing output folder",
                "Please choose an output folder.",
            )
            return None

        output_path = Path(output_text)

        if not self.pipeline_path.exists():
            messagebox.showerror(
                "Pipeline not found",
                f"run_pipeline.py not found:\n{self.pipeline_path}",
            )
            return None

        return input_path, output_path, base_name

    def run_pipeline(self) -> None:
        validated = self.validate_inputs()
        if validated is None:
            return

        input_path, output_path, base_name = validated

        output_path.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            str(self.pipeline_path),
            "--input",
            str(input_path),
            "--out-dir",
            str(output_path),
            "--base-name",
            base_name,
        ]

        self.run_button.configure(state=tk.DISABLED)
        self.status_var.set("Running...")
        self.log("\n" + "=" * 80)
        self.log("Starting processor")
        self.log("Command:")
        self.log(" ".join(command))
        self.log("=" * 80)

        thread = threading.Thread(
            target=self._run_process_thread,
            args=(command,),
            daemon=True,
        )
        thread.start()

    def _run_process_thread(self, command: list[str]) -> None:
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self.current_process = process

            assert process.stdout is not None

            for line in process.stdout:
                self.after(0, self.log, line.rstrip("\n"))

            return_code = process.wait()

            if return_code == 0:
                self.after(0, self._process_success)
            else:
                self.after(0, self._process_failed, return_code)

        except Exception as exc:
            self.after(0, self._process_exception, exc)

    def _process_success(self) -> None:
        self.status_var.set("Done")
        self.run_button.configure(state=tk.NORMAL)
        self.log("\nDONE")
        messagebox.showinfo("Done", "Processing finished successfully.")

    def _process_failed(self, return_code: int) -> None:
        self.status_var.set("Failed")
        self.run_button.configure(state=tk.NORMAL)
        self.log(f"\nFAILED with exit code {return_code}")
        messagebox.showerror(
            "Failed",
            f"Processing failed with exit code {return_code}.",
        )

    def _process_exception(self, exc: Exception) -> None:
        self.status_var.set("Error")
        self.run_button.configure(state=tk.NORMAL)
        self.log(f"\nERROR: {exc}")
        messagebox.showerror("Error", str(exc))


def main() -> None:
    app = ChechenOCRGui()
    app.mainloop()


if __name__ == "__main__":
    main()