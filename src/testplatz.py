"""Testplatz-Hauptanwendung mit webseiten-aehnlichem Look, rein als Desktop-App (tkinter)."""

import importlib.metadata
import io
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import cairosvg
import requests
from dotenv import load_dotenv
from PIL import Image, ImageTk

from keycloak_auth import DEFAULT_REDIRECT_URI, KeycloakAuthError, KeycloakAuthenticator

load_dotenv()  # liest z.B. KEYCLOAK_CLIENT_SECRET aus einer lokalen .env-Datei

BG_COLOR = "#0d1117"
CARD_COLOR = "#161b22"
ACCENT_COLOR = "#2f81f7"
ACCENT_HOVER = "#1f6feb"
TEXT_COLOR = "#e6edf3"
MUTED_TEXT = "#8b949e"
ERROR_COLOR = "#f85149"

FONT_FAMILY = "Helvetica"

KEYCLOAK_ISSUER_URL = os.environ.get("KEYCLOAK_ISSUER_URL", "https://sso.embedded-future.de/realms/nl_test")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "ef_test_service_web")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET")
KEYCLOAK_REDIRECT_URI = os.environ.get("KEYCLOAK_REDIRECT_URI", DEFAULT_REDIRECT_URI)
KEYCLOAK_LOGO_URL = os.environ.get(
    "KEYCLOAK_LOGO_URL", "https://www.newlift.de/assets/images/9/newlift-logo-07b8e79e.svg"
)
REST_API_BASE_URL = os.environ.get("REST_API_BASE_URL", "https://sso.embedded-future.de/restapi/api/v1")

REPO_URL = os.environ.get("TESTPLATZ_REPO_URL", "https://github.com/ef-mm/ef_firmware_tests.git")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARBEITSVERZEICHNIS = os.path.join(SCRIPT_DIR, "Arbeitsverzeichnis")


class HoverButton(tk.Button):
    """Button mit Hover-Effekt, wie man ihn von Webseiten-Buttons kennt."""

    def __init__(self, master, bg, hover_bg, **kwargs):
        super().__init__(
            master,
            bg=bg,
            activebackground=hover_bg,
            relief="flat",
            bd=0,
            cursor="hand2",
            **kwargs,
        )
        self._bg = bg
        self._hover_bg = hover_bg
        self.bind("<Enter>", lambda _e: self.configure(bg=self._hover_bg))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._bg))


class TestplatzApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Testplatz")
        self.geometry("1600x1050")
        self.configure(bg=BG_COLOR)
        self._active_canvas = None
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", lambda _e: self._scroll_active_canvas(-1))
        self.bind_all("<Button-5>", lambda _e: self._scroll_active_canvas(1))
        self.auth = KeycloakAuthenticator(
            issuer_url=KEYCLOAK_ISSUER_URL,
            client_id=KEYCLOAK_CLIENT_ID,
            client_secret=KEYCLOAK_CLIENT_SECRET,
            redirect_uri=KEYCLOAK_REDIRECT_URI,
        )
        self._build_navbar()
        self.content = tk.Frame(self, bg=BG_COLOR)
        self.content.pack(expand=True, fill="both")
        self.show_login_page()

    def _build_navbar(self):
        self.navbar = tk.Frame(self, bg=CARD_COLOR, height=60)
        self.navbar.pack(side="top", fill="x")
        self.navbar_title_label = tk.Label(
            self.navbar,
            text="Testplatz",
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 18, "bold"),
        )
        self.navbar_title_label.pack(side="left", padx=24, pady=12)

        self.navbar_status_label = tk.Label(
            self.navbar, text="Nicht angemeldet", bg=CARD_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10)
        )
        self.navbar_status_label.pack(side="right", padx=(0, 12))
        self.logout_button = HoverButton(
            self.navbar,
            bg=CARD_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Abmelden",
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 9, "bold"),
            padx=10,
            pady=4,
            command=self._on_logout,
        )

        self.navbar_logo_label = tk.Label(self.navbar, bg=CARD_COLOR)
        self.navbar_logo_label.place(relx=0.5, rely=0.5, anchor="center")
        self._load_navbar_logo()

    def _load_navbar_logo(self):
        result_queue = queue.Queue()

        def worker():
            try:
                logo_url = None
                for get_logo_url in (self.auth.get_admin_client_logo_url, self.auth.get_login_page_logo_url):
                    try:
                        logo_url = get_logo_url()
                    except (requests.RequestException, KeycloakAuthError):
                        logo_url = None
                    if logo_url:
                        break
                logo_url = logo_url or KEYCLOAK_LOGO_URL

                response = requests.get(logo_url, timeout=10)
                response.raise_for_status()
                is_svg = "svg" in response.headers.get("Content-Type", "") or logo_url.lower().endswith(".svg")
                if is_svg:
                    png_bytes = cairosvg.svg2png(bytestring=response.content, output_height=36)
                    image = Image.open(io.BytesIO(png_bytes))
                else:
                    image = Image.open(io.BytesIO(response.content))
                    image.thumbnail((200, 36))
                result_queue.put(image)
            except Exception as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_navbar_logo(result_queue)

    def _poll_navbar_logo(self, result_queue):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_navbar_logo, result_queue)
            return

        if isinstance(result, Exception):
            return

        self.navbar_logo_image = ImageTk.PhotoImage(result)
        self.navbar_logo_label.configure(image=self.navbar_logo_image)

    def _set_logged_in_state(self, logged_in):
        if logged_in:
            self.navbar_status_label.configure(text="Angemeldet", fg=TEXT_COLOR)
            self.logout_button.pack(side="right", padx=(0, 24))
        else:
            self.navbar_status_label.configure(text="Nicht angemeldet", fg=MUTED_TEXT)
            self.logout_button.pack_forget()

    def _on_logout(self):
        self.auth.logout()
        self._set_logged_in_state(False)
        self.show_login_page()

    def _set_navbar_title(self, title):
        self.navbar_title_label.configure(text=title)

    def _clear_content(self):
        self._active_canvas = None
        self._page_canvas = None
        for widget in self.content.winfo_children():
            widget.destroy()

    def _on_mousewheel(self, event):
        self._scroll_active_canvas(-1 if event.delta > 0 else 1)

    def _scroll_active_canvas(self, direction):
        if self._active_canvas is not None and self._active_canvas.winfo_exists():
            self._active_canvas.yview_scroll(direction, "units")

    def show_login_page(self):
        self._clear_content()
        self._set_navbar_title("Testplatz")
        content = self.content

        tk.Label(
            content,
            text="Anmeldung erforderlich",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 22, "bold"),
        ).pack(pady=(80, 10))

        tk.Label(
            content,
            text="Bitte melden Sie sich ueber Keycloak an, um den Testplatz zu nutzen.",
            bg=BG_COLOR,
            fg=MUTED_TEXT,
            font=(FONT_FAMILY, 12),
        ).pack(pady=(0, 30))

        self.login_status_label = tk.Label(
            content, text="", bg=BG_COLOR, fg=ERROR_COLOR, font=(FONT_FAMILY, 10), wraplength=500
        )
        self.login_status_label.pack(pady=(0, 20))

        self.login_button = HoverButton(
            content,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Mit Keycloak anmelden",
            fg="white",
            font=(FONT_FAMILY, 11, "bold"),
            padx=24,
            pady=12,
            command=self._start_login,
        )
        self.login_button.pack()

    def _start_login(self):
        self.login_button.configure(state="disabled", text="Anmeldung laeuft, bitte im Browser fortfahren ...")
        self.login_status_label.configure(text="")

        result_queue = queue.Queue()

        def worker():
            try:
                self.auth.login()
                result_queue.put(None)
            except (KeycloakAuthError, requests.RequestException) as exc:
                result_queue.put(str(exc))

        threading.Thread(target=worker, daemon=True).start()
        self._poll_login_result(result_queue)

    def _poll_login_result(self, result_queue):
        try:
            error = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_login_result, result_queue)
            return

        if error:
            self.login_button.configure(state="normal", text="Mit Keycloak anmelden")
            self.login_status_label.configure(text=error)
            return

        self._set_logged_in_state(True)
        self.show_main_page()

    def show_main_page(self):
        self._clear_content()
        self._set_navbar_title("Testplatz")
        content = self.content

        tk.Label(
            content,
            text="Was moechten Sie tun?",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 22, "bold"),
        ).pack(pady=(60, 10))

        tk.Label(
            content,
            text="Waehlen Sie eine der folgenden Optionen aus.",
            bg=BG_COLOR,
            fg=MUTED_TEXT,
            font=(FONT_FAMILY, 12),
        ).pack(pady=(0, 40))

        cards = tk.Frame(content, bg=BG_COLOR)
        cards.pack()

        self._build_card(
            cards,
            column=0,
            title="Assembly erzeugen",
            description="Erstellt eine neue Assembly auf Basis eines Templates.",
            command=self.show_assembly_page,
        )
        self._build_card(
            cards,
            column=1,
            title="Assembly bearbeiten",
            description="Erlaubt den Austausch von Komponenten einer bestehenden Assembly.",
            command=self.show_assembly_edit_page,
        )
        self._build_card(
            cards,
            column=2,
            title="Test starten",
            description="Fuehrt die Testsuite fuer das ausgewaehlte Assembly aus.",
            command=self.show_test_page,
        )

    def _build_card(self, parent, column, title, description, command):
        card = tk.Frame(parent, bg=CARD_COLOR, padx=30, pady=30, highlightthickness=0)
        card.grid(row=0, column=column, padx=20, pady=10, sticky="n")

        tk.Label(
            card,
            text=title,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 16, "bold"),
        ).pack(pady=(0, 10))

        tk.Label(
            card,
            text=description,
            bg=CARD_COLOR,
            fg=MUTED_TEXT,
            font=(FONT_FAMILY, 10),
            wraplength=220,
            justify="center",
        ).pack(pady=(0, 20))

        HoverButton(
            card,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text=title,
            fg="white",
            font=(FONT_FAMILY, 11, "bold"),
            padx=20,
            pady=10,
            command=command,
        ).pack()

    def _build_subpage(self, title, show_scrollbar=True):
        self._clear_content()
        self._set_navbar_title(title)
        content = self.content

        body_container = tk.Frame(content, bg=BG_COLOR)
        body_container.pack(expand=True, fill="both")

        canvas = tk.Canvas(body_container, bg=BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(body_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        if show_scrollbar:
            scrollbar.pack(side="right", fill="y")

        body = tk.Frame(canvas, bg=BG_COLOR)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(body_window, width=e.width))
        self._active_canvas = canvas
        self._page_canvas = canvas

        footer = tk.Frame(content, bg=BG_COLOR)
        footer.pack(side="bottom", fill="x", pady=20)
        HoverButton(
            footer,
            bg=CARD_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Zurueck",
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 10, "bold"),
            padx=16,
            pady=8,
            command=self.show_main_page,
        ).pack()

        return body

    def _create_scrollable_column(self, parent, height):
        """Erzeugt eine Spalte mit fester Hoehe; die Scrollbar erscheint nur bei Inhalt > height."""
        container = tk.Frame(parent, bg=BG_COLOR, height=height)
        container.pack_propagate(False)

        canvas = tk.Canvas(container, bg=BG_COLOR, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG_COLOR)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if inner.winfo_reqheight() > height:
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()
                canvas.yview_moveto(0)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(inner_window, width=e.width))
        canvas.bind("<Enter>", lambda _e: setattr(self, "_active_canvas", canvas))
        canvas.bind("<Leave>", lambda _e: setattr(self, "_active_canvas", self._page_canvas))

        return container, inner

    def _call_rest_api(self, path, method="GET", json_body=None):
        """Ruft einen REST-Endpunkt mit dem Keycloak-Bearer-Token auf."""
        headers = self.auth.get_auth_header()
        response = requests.request(
            method, f"{REST_API_BASE_URL}/{path.lstrip('/')}", headers=headers, json=json_body, timeout=10
        )
        if not response.ok:
            raise RuntimeError(f"REST-API-Fehler ({response.status_code}): {response.text}")
        return response.json()

    @staticmethod
    def _artikel_bezeichnung(artikel):
        return ".".join(str(artikel[key]) for key in ("art_bez", "art_var", "art_rev"))

    def show_assembly_page(self):
        body = self._build_subpage("Assembly erzeugen")
        tk.Label(
            body,
            text="Artikel auswaehlen:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", padx=60, pady=(40, 10))

        self.artikel_var = tk.StringVar()
        self.artikel_combobox = ttk.Combobox(
            body, textvariable=self.artikel_var, state="readonly", width=40
        )
        self.artikel_combobox.pack(anchor="w", padx=60)
        self.artikel_combobox.bind("<<ComboboxSelected>>", self._on_artikel_selected)

        status_label = tk.Label(
            body, text="Lade Artikel ...", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10), wraplength=600
        )
        status_label.pack(pady=(10, 20))

        self.serial_container = tk.Frame(body, bg=BG_COLOR)
        self.serial_container.pack(fill="x", padx=60)

        self._load_artikel_options(status_label)

    def _load_artikel_options(self, status_label):
        result_queue = queue.Queue()

        def worker():
            try:
                result_queue.put(self._call_rest_api("artikel"))
            except (KeycloakAuthError, requests.RequestException) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_artikel_options(result_queue, status_label)

    def _poll_artikel_options(self, result_queue, status_label):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_artikel_options, result_queue, status_label)
            return

        if isinstance(result, Exception):
            status_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Laden der Artikel:\n{result}")
            return

        bezeichnungen = [self._artikel_bezeichnung(artikel) for artikel in result]
        self.artikel_combobox.configure(values=bezeichnungen)
        if bezeichnungen:
            self.artikel_combobox.set("")
            status_label.configure(text="")
        else:
            status_label.configure(fg=MUTED_TEXT, text="Keine Artikel gefunden.")

    def _on_artikel_selected(self, event=None):
        bezeichnung = self.artikel_var.get()
        for widget in self.serial_container.winfo_children():
            widget.destroy()
        if not bezeichnung:
            return

        loading_label = tk.Label(
            self.serial_container, text="Lade Artikeldetails ...", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10)
        )
        loading_label.pack(anchor="w")

        result_queue = queue.Queue()

        def worker():
            try:
                result_queue.put(self._call_rest_api(f"artikel/{bezeichnung}"))
            except (KeycloakAuthError, requests.RequestException) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_artikel_details(result_queue, loading_label)

    def _poll_artikel_details(self, result_queue, loading_label):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_artikel_details, result_queue, loading_label)
            return

        if isinstance(result, Exception):
            loading_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Laden des Artikels:\n{result}")
            return

        loading_label.destroy()
        self._build_serial_field(result)

    def _build_serial_field(self, artikel):
        self.current_artikel = artikel
        self.serial_fields = {}

        self.assembly_status_label = tk.Label(
            self.serial_container, text="", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10), wraplength=600, justify="left"
        )
        self.complete_button = HoverButton(
            self.serial_container,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Zusammenbau abschliessen",
            fg="white",
            font=(FONT_FAMILY, 11, "bold"),
            padx=20,
            pady=10,
            command=self._start_assembly_completion,
        )

        self._add_serial_entry(
            key="hauptartikel",
            label_text="Seriennummer (Hauptartikel)",
            sn_opts_list=artikel.get("sn_opts") or [],
            art_id=artikel["art_id"],
        )

        komponenten = artikel.get("besteht aus") or []
        if komponenten:
            tk.Label(
                self.serial_container,
                text="Bestandteile:",
                bg=BG_COLOR,
                fg=TEXT_COLOR,
                font=(FONT_FAMILY, 12, "bold"),
            ).pack(anchor="w", pady=(20, 6))

        for komponente in komponenten:
            bezeichnung = self._artikel_bezeichnung(komponente)
            key = komponente.get("art_partof_id", bezeichnung)
            self._add_serial_entry(
                key=key,
                label_text=f"Seriennummer ({bezeichnung})",
                sn_opts_list=komponente.get("sn_opts") or [],
                art_id=komponente["art_id"],
            )

        self.assembly_status_label.pack(anchor="w", pady=(10, 0))
        self._update_complete_button()

    def _add_serial_entry(self, key, label_text, sn_opts_list, art_id):
        sn_opts = sn_opts_list[0] if sn_opts_list else {}
        mandatory = bool(sn_opts.get("art_sn_opts_mandatory"))
        pattern = sn_opts.get("art_sn_opts_pattern") or ""

        frame = tk.Frame(self.serial_container, bg=BG_COLOR)
        frame.pack(fill="x", pady=(0, 12), anchor="w")

        tk.Label(
            frame,
            text=label_text + (" *" if mandatory else ""),
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 11),
        ).pack(anchor="w")

        serial_var = tk.StringVar()
        entry = tk.Entry(
            frame,
            textvariable=serial_var,
            font=(FONT_FAMILY, 11),
            width=40,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat",
            highlightthickness=1,
            highlightbackground=MUTED_TEXT,
            highlightcolor=ACCENT_COLOR,
        )
        entry.pack(anchor="w", pady=(6, 4), ipady=4)

        hint_label = tk.Label(
            frame, text="", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 9), justify="left", wraplength=500
        )
        hint_label.pack(anchor="w")

        field = {
            "var": serial_var,
            "entry": entry,
            "hint": hint_label,
            "mandatory": mandatory,
            "pattern": pattern,
            "art_id": art_id,
            "valid": not mandatory,
        }
        self.serial_fields[key] = field

        serial_var.trace_add("write", lambda *_args, field=field: self._validate_serial_field(field))
        self._validate_serial_field(field)

    def _validate_serial_field(self, field):
        value = field["var"].get()
        if not value:
            valid = not field["mandatory"]
            message = "Seriennummer ist erforderlich." if field["mandatory"] else ""
        elif field["pattern"]:
            try:
                valid = re.fullmatch(field["pattern"], value) is not None
            except re.error:
                valid = False
            message = "" if valid else f"Seriennummer muss dem Muster '{field['pattern']}' entsprechen."
        else:
            valid, message = True, ""

        field["valid"] = valid
        color = ACCENT_COLOR if valid else ERROR_COLOR
        field["entry"].configure(highlightbackground=color, highlightcolor=color)
        field["hint"].configure(text=message, fg=MUTED_TEXT if valid else ERROR_COLOR)
        self._update_complete_button()

    def _update_complete_button(self):
        if not getattr(self, "complete_button", None) or not self.complete_button.winfo_exists():
            return
        if self.serial_fields and all(field["valid"] for field in self.serial_fields.values()):
            self.complete_button.pack(pady=(20, 0))
        else:
            self.complete_button.pack_forget()

    def _start_assembly_completion(self):
        self.complete_button.configure(state="disabled", text="Zusammenbau wird angelegt ...")
        self.assembly_status_label.configure(fg=MUTED_TEXT, text="")

        result_queue = queue.Queue()

        def worker():
            try:
                hauptartikel_field = self.serial_fields["hauptartikel"]
                assembly = self._call_rest_api(
                    "assemblies",
                    method="POST",
                    json_body={
                        "assemblies_fk_art_id": hauptartikel_field["art_id"],
                        "assemblies_sn": hauptartikel_field["var"].get(),
                        "assemblies_iteration": 1,
                    },
                )
                assemblies_id = assembly["assemblies_id"]

                for key, field in self.serial_fields.items():
                    if key == "hauptartikel":
                        continue
                    self._call_rest_api(
                        "assemblies_parts",
                        method="POST",
                        json_body={
                            "assemblies_parts_fk_assemblies_id": assemblies_id,
                            "assemblies_parts_fk_art_id": field["art_id"],
                            "assemblies_parts_sn": field["var"].get() or None,
                        },
                    )
                result_queue.put(assemblies_id)
            except (KeycloakAuthError, requests.RequestException, RuntimeError) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_assembly_completion(result_queue)

    def _poll_assembly_completion(self, result_queue):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_assembly_completion, result_queue)
            return

        if isinstance(result, Exception):
            self.complete_button.configure(state="normal", text="Zusammenbau abschliessen")
            self.assembly_status_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Anlegen des Zusammenbaus:\n{result}")
            return

        self.complete_button.configure(state="disabled", text="Zusammenbau abgeschlossen")
        self.assembly_status_label.configure(
            fg=TEXT_COLOR, text=f"Zusammenbau erfolgreich angelegt (Assembly-ID: {result})."
        )

    def show_assembly_edit_page(self):
        body = self._build_subpage("Assembly bearbeiten")
        tk.Label(
            body,
            text="Assembly auswaehlen:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", padx=60, pady=(40, 10))

        self.edit_assembly_var = tk.StringVar()
        self.edit_assembly_combobox = ttk.Combobox(
            body, textvariable=self.edit_assembly_var, state="readonly", width=40
        )
        self.edit_assembly_combobox.pack(anchor="w", padx=60)
        self.edit_assembly_combobox.bind("<<ComboboxSelected>>", self._on_edit_assembly_selected)

        status_label = tk.Label(
            body, text="Lade Assemblies ...", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10), wraplength=600
        )
        status_label.pack(pady=(10, 20))

        self.edit_container = tk.Frame(body, bg=BG_COLOR)
        self.edit_container.pack(fill="x", padx=60)

        self._load_assemblies_for_edit(status_label)

    def _load_assemblies_for_edit(self, status_label):
        result_queue = queue.Queue()

        def worker():
            try:
                artikel_list = self._call_rest_api("artikel")
                assemblies_list = self._call_rest_api("assemblies")
                result_queue.put((artikel_list, assemblies_list))
            except (KeycloakAuthError, requests.RequestException, RuntimeError) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_assemblies_for_edit(result_queue, status_label)

    def _poll_assemblies_for_edit(self, result_queue, status_label):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_assemblies_for_edit, result_queue, status_label)
            return

        if isinstance(result, Exception):
            status_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Laden der Assemblies:\n{result}")
            return

        artikel_list, assemblies_list = result
        self.edit_artikel_bezeichnung_by_id = {
            artikel["art_id"]: self._artikel_bezeichnung(artikel) for artikel in artikel_list
        }
        self.edit_assemblies_list = assemblies_list
        self.edit_assembly_combobox.configure(values=[assembly["assemblies_sn"] for assembly in assemblies_list])
        self.edit_assembly_combobox.set("")
        status_label.configure(text="" if assemblies_list else "Keine Assemblies gefunden.", fg=MUTED_TEXT)

    def _on_edit_assembly_selected(self, event=None):
        for widget in self.edit_container.winfo_children():
            widget.destroy()

        index = self.edit_assembly_combobox.current()
        if index < 0 or index >= len(self.edit_assemblies_list):
            return
        assembly = self.edit_assemblies_list[index]

        loading_label = tk.Label(
            self.edit_container, text="Lade Details ...", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10)
        )
        loading_label.pack(anchor="w")

        result_queue = queue.Queue()

        def worker():
            try:
                art_ids = {assembly["assemblies_fk_art_id"]} | {
                    part["assemblies_parts_fk_art_id"] for part in assembly.get("parts") or []
                }
                sn_opts_by_art_id = {}
                for art_id in art_ids:
                    bezeichnung = self.edit_artikel_bezeichnung_by_id.get(art_id)
                    if not bezeichnung:
                        continue
                    details = self._call_rest_api(f"artikel/{bezeichnung}")
                    sn_opts_list = details.get("sn_opts") or []
                    sn_opts_by_art_id[art_id] = sn_opts_list[0] if sn_opts_list else {}
                result_queue.put(sn_opts_by_art_id)
            except (KeycloakAuthError, requests.RequestException, RuntimeError) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_edit_assembly_details(result_queue, assembly, loading_label)

    def _poll_edit_assembly_details(self, result_queue, assembly, loading_label):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_edit_assembly_details, result_queue, assembly, loading_label)
            return

        if isinstance(result, Exception):
            loading_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Laden der Details:\n{result}")
            return

        loading_label.destroy()
        self._build_edit_assembly_view(assembly, result)

    def _build_edit_assembly_view(self, assembly, sn_opts_by_art_id):
        self.edit_current_assembly = assembly
        self.edit_old_iteration = assembly["assemblies_iteration"]
        self.edit_fields = {}

        bezeichnung = self.edit_artikel_bezeichnung_by_id.get(assembly["assemblies_fk_art_id"], "Unbekannter Artikel")
        tk.Label(
            self.edit_container,
            text=f"Geraet: {bezeichnung}",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(10, 4))

        tk.Label(
            self.edit_container,
            text=f"Iteration: {assembly['assemblies_iteration']}",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(0, 10))

        for part in assembly.get("parts") or []:
            self._build_edit_part_entry(part, sn_opts_by_art_id.get(part["assemblies_parts_fk_art_id"], {}))

        self.edit_status_label = tk.Label(
            self.edit_container, text="", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10),
            wraplength=600, justify="left",
        )
        self.edit_status_label.pack(anchor="w", pady=(10, 0))

        self.edit_assembly_button = HoverButton(
            self.edit_container,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Assembly aendern",
            fg="white",
            font=(FONT_FAMILY, 11, "bold"),
            padx=20,
            pady=10,
            command=self._on_edit_assembly_submit,
        )
        self._update_edit_assembly_button()

    def _build_edit_part_entry(self, part, sn_opts):
        mandatory = bool(sn_opts.get("art_sn_opts_mandatory"))
        pattern = sn_opts.get("art_sn_opts_pattern") or ""
        part_bezeichnung = self.edit_artikel_bezeichnung_by_id.get(
            part["assemblies_parts_fk_art_id"], "Unbekannter Artikel"
        )

        frame = tk.Frame(self.edit_container, bg=BG_COLOR)
        frame.pack(fill="x", pady=(0, 12), anchor="w")

        tk.Label(
            frame,
            text=part_bezeichnung + (" *" if mandatory else ""),
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 11),
        ).pack(anchor="w")

        entry_row = tk.Frame(frame, bg=BG_COLOR)
        entry_row.pack(anchor="w", pady=(6, 4))

        serial_var = tk.StringVar(value=part.get("assemblies_parts_sn") or "")
        entry = tk.Entry(
            entry_row,
            textvariable=serial_var,
            font=(FONT_FAMILY, 11),
            width=40,
            bg=CARD_COLOR,
            fg=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            relief="flat",
            highlightthickness=1,
            highlightbackground=MUTED_TEXT,
            highlightcolor=ACCENT_COLOR,
            state="readonly",
        )
        entry.pack(side="left", ipady=4)

        hint_label = tk.Label(frame, text="", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 9))
        hint_label.pack(anchor="w")

        field = {
            "var": serial_var,
            "entry": entry,
            "hint": hint_label,
            "mandatory": mandatory,
            "pattern": pattern,
            "art_id": part["assemblies_parts_fk_art_id"],
            "valid": True,
            "edited": False,
        }
        self.edit_fields[part["assemblies_parts_id"]] = field

        def on_change_click():
            entry.configure(state="normal")
            field["edited"] = True
            serial_var.set("")
            entry.focus_set()

        change_button = HoverButton(
            entry_row,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Aendern",
            fg="white",
            font=(FONT_FAMILY, 9, "bold"),
            padx=10,
            pady=4,
            command=on_change_click,
        )
        change_button.pack(side="left", padx=(10, 0))

        serial_var.trace_add("write", lambda *_args, field=field: self._validate_edit_field(field))

    def _validate_edit_field(self, field):
        if not field["edited"]:
            return
        value = field["var"].get()
        if not value:
            valid = not field["mandatory"]
            message = "Seriennummer ist erforderlich." if field["mandatory"] else ""
        elif field["pattern"]:
            try:
                valid = re.fullmatch(field["pattern"], value) is not None
            except re.error:
                valid = False
            message = "" if valid else f"Seriennummer muss dem Muster '{field['pattern']}' entsprechen."
        else:
            valid, message = True, ""

        field["valid"] = valid
        color = ACCENT_COLOR if valid else ERROR_COLOR
        field["entry"].configure(highlightbackground=color, highlightcolor=color)
        field["hint"].configure(text=message, fg=MUTED_TEXT if valid else ERROR_COLOR)
        self._update_edit_assembly_button()

    def _update_edit_assembly_button(self):
        if not getattr(self, "edit_assembly_button", None) or not self.edit_assembly_button.winfo_exists():
            return
        edited_fields = [field for field in self.edit_fields.values() if field["edited"]]
        if edited_fields and all(field["valid"] for field in edited_fields):
            self.edit_assembly_button.pack(pady=(20, 0))
        else:
            self.edit_assembly_button.pack_forget()

    def _on_edit_assembly_submit(self):
        self.edit_assembly_button.configure(state="disabled", text="Assembly wird geaendert ...")
        self.edit_status_label.configure(fg=MUTED_TEXT, text="")

        assembly = self.edit_current_assembly
        old_iteration = self.edit_old_iteration
        new_iteration = old_iteration + 1
        edited_fields = {
            parts_id: field for parts_id, field in self.edit_fields.items() if field["edited"]
        }

        result_queue = queue.Queue()

        def worker():
            try:
                self._call_rest_api(
                    f"assemblies/{assembly['assemblies_id']}",
                    method="PUT",
                    json_body={
                        "assemblies_fk_art_id": assembly["assemblies_fk_art_id"],
                        "assemblies_sn": assembly["assemblies_sn"],
                        "assemblies_iteration": new_iteration,
                    },
                )

                for part in assembly.get("parts") or []:
                    self._call_rest_api(
                        "assemblies_parts_hist",
                        method="POST",
                        json_body={
                            "assemblies_parts_hist_fk_assemblies_id": assembly["assemblies_id"],
                            "assemblies_parts_hist_fk_art_id": part["assemblies_parts_fk_art_id"],
                            "assemblies_parts_hist_sn": part.get("assemblies_parts_sn"),
                            "assemblies_parts_hist_iteration": old_iteration,
                        },
                    )

                for parts_id, field in edited_fields.items():
                    self._call_rest_api(
                        f"assemblies_parts/{parts_id}",
                        method="PUT",
                        json_body={"assemblies_parts_sn": field["var"].get() or None},
                    )

                result_queue.put(new_iteration)
            except (KeycloakAuthError, requests.RequestException, RuntimeError) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_edit_assembly_submit(result_queue)

    def _poll_edit_assembly_submit(self, result_queue):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_edit_assembly_submit, result_queue)
            return

        if isinstance(result, Exception):
            self.edit_assembly_button.configure(state="normal", text="Assembly aendern")
            self.edit_status_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Aendern der Assembly:\n{result}")
            return

        self.edit_assembly_button.configure(state="disabled", text="Assembly geaendert")
        self.edit_status_label.configure(
            fg=TEXT_COLOR, text=f"Assembly erfolgreich geaendert (neue Iteration: {result})."
        )

    def show_test_page(self):
        body = self._build_subpage("Test starten", show_scrollbar=False)

        columns = tk.Frame(body, bg=BG_COLOR)
        columns.pack(fill="x", padx=40, pady=(20, 0))
        for column_index in range(2):
            columns.columnconfigure(column_index, weight=1, uniform="test_columns")

        left_container, left_column = self._create_scrollable_column(columns, height=400)
        left_container.grid(row=0, column=0, sticky="new", padx=20)

        middle_container, middle_column = self._create_scrollable_column(columns, height=400)
        middle_container.grid(row=0, column=1, sticky="new", padx=20)

        tk.Label(
            left_column,
            text="Assembly auswaehlen:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(0, 10))

        self.assembly_var = tk.StringVar()
        self.assembly_combobox = ttk.Combobox(
            left_column, textvariable=self.assembly_var, state="readonly", width=40
        )
        self.assembly_combobox.pack(anchor="w")
        self.assembly_combobox.bind("<<ComboboxSelected>>", self._on_assembly_selected)

        status_label = tk.Label(
            left_column, text="Lade Assemblies ...", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10), wraplength=350
        )
        status_label.pack(anchor="w", pady=(10, 20))

        self.assembly_detail_container = tk.Frame(left_column, bg=BG_COLOR)
        self.assembly_detail_container.pack(fill="x", anchor="w")

        tk.Label(
            middle_column,
            text="Arbeitsplatz:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(0, 10))

        self.arbeitsplatz_button = HoverButton(
            middle_column,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Arbeitsplatz einrichten",
            fg="white",
            font=(FONT_FAMILY, 10, "bold"),
            padx=14,
            command=self._on_arbeitsplatz_einrichten,
        )

        self.arbeitsplatz_spacer = tk.Label(
            middle_column, text="", bg=BG_COLOR, fg=MUTED_TEXT, font=(FONT_FAMILY, 10)
        )
        self.arbeitsplatz_spacer.pack(anchor="w", pady=(10, 20))

        self.arbeitsplatz_info_frame = tk.Frame(middle_column, bg=BG_COLOR)
        self.arbeitsplatz_info_frame.pack(fill="x", anchor="w")

        test_actions_frame = tk.Frame(body, bg=BG_COLOR)
        test_actions_frame.pack(fill="x", padx=40, pady=(20, 0))

        self.run_tests_button = HoverButton(
            test_actions_frame,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Tests ausfuehren",
            fg="white",
            font=(FONT_FAMILY, 10, "bold"),
            padx=14,
            pady=6,
            command=self._on_run_tests,
        )

        self.load_firmware_button = HoverButton(
            test_actions_frame,
            bg=ACCENT_COLOR,
            hover_bg=ACCENT_HOVER,
            text="Firmware laden",
            fg="white",
            font=(FONT_FAMILY, 10, "bold"),
            padx=14,
            pady=6,
            command=self._on_load_firmware,
        )

        terminal_frame = tk.Frame(body, bg=BG_COLOR)
        terminal_frame.pack(fill="both", expand=True, padx=40, pady=(10, 20))

        tk.Label(
            terminal_frame,
            text="Testausfuehrung:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(0, 10))

        terminal_text_frame = tk.Frame(terminal_frame, bg=BG_COLOR)
        terminal_text_frame.pack(fill="both", expand=True)
        terminal_scrollbar = tk.Scrollbar(terminal_text_frame)
        terminal_scrollbar.pack(side="right", fill="y")
        self.test_terminal_text = tk.Text(
            terminal_text_frame,
            bg="black",
            fg="white",
            height=15,
            state="disabled",
            yscrollcommand=terminal_scrollbar.set,
        )
        self.test_terminal_text.pack(side="left", fill="both", expand=True)
        terminal_scrollbar.config(command=self.test_terminal_text.yview)

        self._load_assemblies(status_label)

    def _load_assemblies(self, status_label):
        result_queue = queue.Queue()

        def worker():
            try:
                artikel_list = self._call_rest_api("artikel")
                assemblies_list = self._call_rest_api("assemblies")
                result_queue.put((artikel_list, assemblies_list))
            except (KeycloakAuthError, requests.RequestException, RuntimeError) as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_assemblies(result_queue, status_label)

    def _poll_assemblies(self, result_queue, status_label):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_assemblies, result_queue, status_label)
            return

        if isinstance(result, Exception):
            status_label.configure(fg=ERROR_COLOR, text=f"Fehler beim Laden der Assemblies:\n{result}")
            return

        artikel_list, assemblies_list = result
        self.artikel_bezeichnung_by_id = {
            artikel["art_id"]: self._artikel_bezeichnung(artikel) for artikel in artikel_list
        }
        self.assemblies_list = assemblies_list
        self.assembly_combobox.configure(values=[assembly["assemblies_sn"] for assembly in assemblies_list])
        self.assembly_combobox.set("")
        status_label.configure(text="" if assemblies_list else "Keine Assemblies gefunden.", fg=MUTED_TEXT)

    def _on_assembly_selected(self, event=None):
        for widget in self.assembly_detail_container.winfo_children():
            widget.destroy()

        index = self.assembly_combobox.current()
        if index < 0 or index >= len(self.assemblies_list):
            return
        assembly = self.assemblies_list[index]

        bezeichnung = self.artikel_bezeichnung_by_id.get(assembly["assemblies_fk_art_id"], "Unbekannter Artikel")
        self.selected_geraeteklasse, _, geraetespezifikation = bezeichnung.partition(".")
        self.selected_geraetespezifikation = geraetespezifikation.replace(".", "")
        self.arbeitsplatz_button.configure(
            state="normal",
            text="Arbeitsplatz updaten" if self._arbeitsverzeichnis_vorhanden() else "Arbeitsplatz einrichten",
        )
        self.arbeitsplatz_button.pack(anchor="w", before=self.arbeitsplatz_spacer)
        self._update_arbeitsplatz_info()
        self._update_test_action_buttons()
        tk.Label(
            self.assembly_detail_container,
            text=f"Artikel: {bezeichnung}",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(10, 4))

        tk.Label(
            self.assembly_detail_container,
            text=f"Iteration: {assembly['assemblies_iteration']}",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(0, 10))

        parts = assembly.get("parts") or []
        if parts:
            tk.Label(
                self.assembly_detail_container,
                text="Teile:",
                bg=BG_COLOR,
                fg=TEXT_COLOR,
                font=(FONT_FAMILY, 12, "bold"),
            ).pack(anchor="w", pady=(0, 6))

            for part in parts:
                part_bezeichnung = self.artikel_bezeichnung_by_id.get(
                    part["assemblies_parts_fk_art_id"], "Unbekannter Artikel"
                )
                serial = part.get("assemblies_parts_sn") or "-"
                tk.Label(
                    self.assembly_detail_container,
                    text=f"{part_bezeichnung}: {serial}",
                    bg=BG_COLOR,
                    fg=MUTED_TEXT,
                    font=(FONT_FAMILY, 10),
                ).pack(anchor="w")

    def _arbeitsverzeichnis_vorhanden(self):
        target_dir = os.path.join(
            ARBEITSVERZEICHNIS, "geraete", self.selected_geraeteklasse, self.selected_geraetespezifikation
        )
        return os.path.isdir(target_dir) and bool(os.listdir(target_dir))

    def _update_arbeitsplatz_info(self):
        for widget in self.arbeitsplatz_info_frame.winfo_children():
            widget.destroy()
        if not self._arbeitsverzeichnis_vorhanden():
            return

        target_dir = os.path.join(
            ARBEITSVERZEICHNIS, "geraete", self.selected_geraeteklasse, self.selected_geraetespezifikation
        )
        firmware_dir = os.path.join(target_dir, "Firmware")
        tests_dir = os.path.join(target_dir, "Tests")
        firmware_dateien = sorted(os.listdir(firmware_dir)) if os.path.isdir(firmware_dir) else []
        test_dateien = (
            sorted(name for name in os.listdir(tests_dir) if not name.startswith("__"))
            if os.path.isdir(tests_dir)
            else []
        )

        tk.Label(
            self.arbeitsplatz_info_frame,
            text=f"Firmware: {', '.join(firmware_dateien) if firmware_dateien else '-'}",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(10, 4))

        tk.Label(
            self.arbeitsplatz_info_frame, text="", bg=BG_COLOR, fg=TEXT_COLOR, font=(FONT_FAMILY, 12)
        ).pack(anchor="w")

        tk.Label(
            self.arbeitsplatz_info_frame,
            text="Tests:",
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w", pady=(10, 6))

        for test_datei in test_dateien or ["-"]:
            tk.Label(
                self.arbeitsplatz_info_frame,
                text=test_datei,
                bg=BG_COLOR,
                fg=MUTED_TEXT,
                font=(FONT_FAMILY, 10),
            ).pack(anchor="w")

    def _on_arbeitsplatz_einrichten(self):
        self.arbeitsplatz_button.configure(state="disabled", text="Arbeitsplatz wird eingerichtet ...")

        geraeteklasse = self.selected_geraeteklasse
        geraetespezifikation = self.selected_geraetespezifikation
        result_queue = queue.Queue()

        def worker():
            try:
                combined = "/".join(["geraete", geraeteklasse, geraetespezifikation])
                os.makedirs(ARBEITSVERZEICHNIS, exist_ok=True)
                if not os.path.isdir(os.path.join(ARBEITSVERZEICHNIS, ".git")):
                    self._run_git(
                        ["clone", "--filter=blob:none", "--no-checkout", "--sparse", REPO_URL, ARBEITSVERZEICHNIS]
                    )
                self._run_git(["sparse-checkout", "set", "shared", combined], cwd=ARBEITSVERZEICHNIS)
                self._run_git(["checkout", "main"], cwd=ARBEITSVERZEICHNIS)

                target_dir = os.path.join(ARBEITSVERZEICHNIS, "geraete", geraeteklasse, geraetespezifikation)
                result_queue.put(os.path.isdir(target_dir) and bool(os.listdir(target_dir)))
            except Exception as exc:
                result_queue.put(exc)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_arbeitsplatz_einrichten(result_queue)

    def _poll_arbeitsplatz_einrichten(self, result_queue):
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_arbeitsplatz_einrichten, result_queue)
            return

        if isinstance(result, Exception):
            self.arbeitsplatz_button.configure(state="normal", text="Arbeitsplatz einrichten")
            messagebox.showerror("Fehler", f"Arbeitsplatz konnte nicht eingerichtet werden:\n{result}")
        elif result:
            self.arbeitsplatz_button.configure(state="normal", text="Arbeitsplatz updaten")
            self._update_arbeitsplatz_info()
            self._update_test_action_buttons()
            messagebox.showinfo("Erfolg", "Update erfolgreich")
        else:
            self.arbeitsplatz_button.configure(state="normal", text="Arbeitsplatz einrichten")
            messagebox.showerror("Fehler", "Verzeichnis nach dem Checkout nicht gefunden oder leer.")

    @staticmethod
    def _run_git(args, cwd=None):
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} fehlgeschlagen")
        return result

    def _update_test_action_buttons(self):
        if self._arbeitsverzeichnis_vorhanden():
            self.load_firmware_button.pack(side="right")
            self.run_tests_button.pack(side="right", padx=(0, 10))
        else:
            self.run_tests_button.pack_forget()
            self.load_firmware_button.pack_forget()

    def _on_load_firmware(self):
        self._clear_test_terminal()
        self._append_test_terminal_text("Hier koennte einmal Firmware geflasht werden\n")

    def _clear_test_terminal(self):
        self.test_terminal_text.configure(state="normal")
        self.test_terminal_text.delete("1.0", "end")
        self.test_terminal_text.configure(state="disabled")

    def _append_test_terminal_text(self, text):
        self.test_terminal_text.configure(state="normal")
        self.test_terminal_text.insert("end", text)
        self.test_terminal_text.see("end")
        self.test_terminal_text.configure(state="disabled")

    def _on_run_tests(self):
        self.run_tests_button.configure(state="disabled")
        self._clear_test_terminal()

        target_dir = os.path.join(
            ARBEITSVERZEICHNIS, "geraete", self.selected_geraeteklasse, self.selected_geraetespezifikation
        )
        tests_dir = os.path.join(target_dir, "Tests")
        requirements_path = os.path.join(target_dir, "Requirements.txt")
        output_queue = queue.Queue()

        def worker():
            try:
                self._ensure_test_dependencies(requirements_path, output_queue)
                test_files = (
                    sorted(
                        os.path.join(tests_dir, name)
                        for name in os.listdir(tests_dir)
                        if name.endswith(".py")
                    )
                    if os.path.isdir(tests_dir)
                    else []
                )
                if not test_files:
                    output_queue.put(f"Keine .py-Dateien in {tests_dir} gefunden.\n")
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
                output_queue.put(f"Fehler bei der Testausfuehrung:\n{exc}\n")
            finally:
                output_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()
        self._poll_test_terminal_output(output_queue)

    def _ensure_test_dependencies(self, requirements_path, output_queue):
        if not os.path.isfile(requirements_path):
            output_queue.put("Keine Requirements.txt gefunden, Abhaengigkeitspruefung uebersprungen.\n\n")
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

    def _poll_test_terminal_output(self, output_queue):
        try:
            while True:
                line = output_queue.get_nowait()
                if line is None:
                    self.run_tests_button.configure(state="normal")
                    return
                self._append_test_terminal_text(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_test_terminal_output, output_queue)


def main():
    app = TestplatzApp()
    app.mainloop()


if __name__ == "__main__":
    main()
