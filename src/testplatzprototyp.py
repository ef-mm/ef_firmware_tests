import importlib.metadata
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk

REPO_URL = "https://github.com/ef-mm/ef_firmware_tests.git"
GERAETE_DIR = "geraete"
SHARED_DIR = "shared"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARBEITSVERZEICHNIS = os.path.join(SCRIPT_DIR, "Arbeitsverzeichnis")
CONFIG_PATH = os.path.join(ARBEITSVERZEICHNIS, "config.json")


class TestplatzApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Testplatz")
        self.geometry("800x600")
        self._temp_dir = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_start_screen()

    def _on_close(self):
        self._cleanup_temp_dir()
        self.destroy()

    def _cleanup_temp_dir(self):
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def _clear(self):
        for widget in self.winfo_children():
            widget.destroy()

    def show_start_screen(self):
        self._cleanup_temp_dir()
        self._clear()
        frame = tk.Frame(self)
        frame.pack(expand=True)

        button = tk.Button(
            frame,
            text="Arbeitsplatz einrichten",
            command=self.show_arbeitsplatz_screen,
        )
        button.pack(padx=20, pady=20)

        if self._read_config():
            tests_button = tk.Button(
                frame, text="Tests starten", command=self.show_test_run_screen
            )
            tests_button.pack(padx=20, pady=(0, 20))

    def _read_config(self):
        if not os.path.isfile(CONFIG_PATH):
            return None
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("geraet") and data.get("variante"):
            return data
        return None

    def show_test_run_screen(self):
        self._clear()
        frame = tk.Frame(self)
        frame.pack(expand=True, fill="both", padx=20, pady=20)

        tk.Label(frame, text="Testausfuehrung:").pack(anchor="w")

        text_frame = tk.Frame(frame)
        text_frame.pack(expand=True, fill="both", pady=(10, 0))
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        self.terminal_text = tk.Text(
            text_frame,
            bg="black",
            fg="white",
            state="disabled",
            yscrollcommand=scrollbar.set,
        )
        self.terminal_text.pack(expand=True, fill="both")
        scrollbar.config(command=self.terminal_text.yview)

        back_button = tk.Button(frame, text="Zurueck", command=self.show_start_screen)
        back_button.pack(pady=(10, 0))

        self._run_tests_in_terminal()

    def _run_tests_in_terminal(self):
        config = self._read_config()
        tests_path = os.path.join(
            ARBEITSVERZEICHNIS, GERAETE_DIR, config["geraet"], config["variante"], "Tests"
        )
        requirements_path = self._find_requirements_path()

        output_queue = queue.Queue()

        def worker():
            try:
                self._ensure_dependencies_installed(requirements_path, output_queue)
                test_files = self._find_test_files(tests_path)
                if not test_files:
                    output_queue.put(f"Keine .py-Dateien in {tests_path} gefunden.\n")
                for test_file in test_files:
                    output_queue.put(f"$ pytest {test_file}\n\n")
                    process = subprocess.Popen(
                        [sys.executable, "-m", "pytest", test_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    for line in process.stdout:
                        output_queue.put(line)
                    process.wait()
                    output_queue.put("\n")
            except Exception as exc:
                output_queue.put(f"Fehler beim Ausfuehren der Tests:\n{exc}\n")
            finally:
                output_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_test_output(output_queue)

    @staticmethod
    def _find_test_files(tests_path):
        if not os.path.isdir(tests_path):
            return []
        return sorted(
            os.path.join(tests_path, name)
            for name in os.listdir(tests_path)
            if name.endswith(".py")
        )

    @staticmethod
    def _find_requirements_path():
        """Bevorzugt die requirements.txt aus dem ausgecheckten Arbeitsverzeichnis."""
        candidate = os.path.join(ARBEITSVERZEICHNIS, "requirements.txt")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(os.path.dirname(SCRIPT_DIR), "requirements.txt")
        return candidate if os.path.isfile(candidate) else None

    def _ensure_dependencies_installed(self, requirements_path, output_queue):
        if not requirements_path:
            output_queue.put("Keine requirements.txt gefunden, Abhaengigkeitspruefung uebersprungen.\n\n")
            return

        output_queue.put(f"Pruefe Abhaengigkeiten aus {requirements_path} ...\n")
        missing = self._find_missing_packages(requirements_path)
        if not missing:
            output_queue.put("Alle Abhaengigkeiten sind bereits installiert.\n\n")
            return

        output_queue.put(f"Installiere fehlende Abhaengigkeiten: {', '.join(missing)}\n")
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", requirements_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            output_queue.put(line)
        process.wait()
        output_queue.put("\n")

    @staticmethod
    def _find_missing_packages(requirements_path):
        missing = []
        with open(requirements_path, "r", encoding="utf-8") as requirements_file:
            for line in requirements_file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
                if not name:
                    continue
                try:
                    importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    missing.append(name)
        return missing

    def _poll_test_output(self, output_queue):
        try:
            while True:
                line = output_queue.get_nowait()
                if line is None:
                    return
                self._append_terminal_text(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_test_output, output_queue)

    def _append_terminal_text(self, text):
        self.terminal_text.configure(state="normal")
        self.terminal_text.insert("end", text)
        self.terminal_text.see("end")
        self.terminal_text.configure(state="disabled")

    def show_arbeitsplatz_screen(self):
        self._clear()
        frame = tk.Frame(self)
        frame.pack(expand=True, fill="both", padx=20, pady=20)

        tk.Label(frame, text="Geraet auswaehlen:").pack(pady=(0, 10))

        # Zeigt eine Wartemeldung waehrend des (kurzen) Git-Sparse-Checkouts an
        self.update_idletasks()
        config = self.cget("cursor")
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            geraete_namen = self._fetch_geraete_verzeichnisse()
        except Exception as exc:
            messagebox.showerror("Fehler", f"Verzeichnisse konnten nicht geladen werden:\n{exc}")
            geraete_namen = []
        finally:
            self.config(cursor=config)

        self.geraet_var = tk.StringVar()
        geraet_combobox = ttk.Combobox(
            frame, textvariable=self.geraet_var, values=geraete_namen, state="readonly"
        )
        geraet_combobox.pack(fill="x")
        geraet_combobox.bind("<<ComboboxSelected>>", self._on_geraet_selected)

        tk.Label(frame, text="Variante auswaehlen:").pack(pady=(20, 10))
        self.variante_var = tk.StringVar()
        self.variante_combobox = ttk.Combobox(
            frame, textvariable=self.variante_var, values=[], state="readonly"
        )
        self.variante_combobox.pack(fill="x")

        self.einrichten_button = tk.Button(
            frame, text="Einrichtung", command=self._on_einrichten
        )
        self.geraet_var.trace_add("write", self._update_einrichten_button)
        self.variante_var.trace_add("write", self._update_einrichten_button)

        if geraete_namen:
            geraet_combobox.current(0)
            self._on_geraet_selected()

        back_button = tk.Button(frame, text="Zurueck", command=self.show_start_screen)
        back_button.pack(pady=(20, 0))

    def _on_geraet_selected(self, event=None):
        geraet = self.geraet_var.get()
        try:
            varianten = self._list_subdirs(GERAETE_DIR, geraet)
        except Exception as exc:
            messagebox.showerror("Fehler", f"Varianten konnten nicht geladen werden:\n{exc}")
            varianten = []

        self.variante_combobox.configure(values=varianten)
        self.variante_var.set(varianten[0] if varianten else "")

    def _update_einrichten_button(self, *_args):
        if self.geraet_var.get() and self.variante_var.get():
            self.einrichten_button.pack(pady=(20, 0))
        else:
            self.einrichten_button.pack_forget()

    def _on_einrichten(self):
        combined = "/".join([GERAETE_DIR, self.geraet_var.get(), self.variante_var.get()])
        try:
            os.makedirs(ARBEITSVERZEICHNIS, exist_ok=True)
            if not os.path.isdir(os.path.join(ARBEITSVERZEICHNIS, ".git")):
                self._run_git(
                    ["clone", "--filter=blob:none", "--no-checkout", "--sparse", REPO_URL, ARBEITSVERZEICHNIS]
                )
            self._run_git(["sparse-checkout", "set", SHARED_DIR, combined], cwd=ARBEITSVERZEICHNIS)
            self._run_git(["checkout", "main"], cwd=ARBEITSVERZEICHNIS)
        except Exception as exc:
            messagebox.showerror("Fehler", f"Einrichtung fehlgeschlagen:\n{exc}")
            return

        with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
            json.dump(
                {"geraet": self.geraet_var.get(), "variante": self.variante_var.get()},
                config_file,
                indent=2,
            )

        messagebox.showinfo("Erfolg", f"Arbeitsplatz eingerichtet: {combined}")

    def _fetch_geraete_verzeichnisse(self):
        """Klont den geraete-Ordner per Sparse-Checkout und listet dessen Unterverzeichnisse."""
        self._cleanup_temp_dir()
        self._temp_dir = tempfile.mkdtemp(prefix="ef_sparse_")
        self._run_git(
            ["clone", "--filter=blob:none", "--no-checkout", "--sparse", REPO_URL, self._temp_dir]
        )
        self._run_git(["sparse-checkout", "set", GERAETE_DIR], cwd=self._temp_dir)
        self._run_git(["checkout"], cwd=self._temp_dir)

        return self._list_subdirs(GERAETE_DIR)

    def _list_subdirs(self, *path_parts):
        """Listet die Unterverzeichnisse unterhalb von path_parts im geklonten Repo."""
        if not self._temp_dir:
            return []
        path = os.path.join(self._temp_dir, *path_parts)
        if not os.path.isdir(path):
            return []
        return sorted(
            name for name in os.listdir(path) if os.path.isdir(os.path.join(path, name))
        )

    @staticmethod
    def _run_git(args, cwd=None):
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} fehlgeschlagen")
        return result


def main():
    app = TestplatzApp()
    app.mainloop()


if __name__ == "__main__":
    main()
