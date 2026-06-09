#!/usr/bin/env python3
"""
================================================================================
  NEC2 Antenna Length Optimizer — Graphical Front-End
  Wraps nec2_length_optimizer.py with a full tkinter GUI.
  Works on Windows and Linux (Python 3.8+, tkinter built-in).

  Usage:
    python nec2_optimizer_gui.py
  Or double-click on Windows.

  The optimizer script (nec2_length_optimizer.py) must be in the same
  directory OR on PYTHONPATH.
================================================================================
"""

import locale
import os
import re
import sys
import shutil
import threading
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────

BAND_CENTRE_FREQ_MHZ = {
    "2200m": 0.1365,  "630m": 0.475,   "160m": 1.850,   "80m": 3.650,
    "60m":   5.350,   "40m": 7.100,    "30m": 10.125,   "20m": 14.175,
    "17m":   18.118,  "15m": 21.225,   "12m": 24.940,   "10m": 28.500,
    "6m":    50.200,  "4m":  70.200,   "2m":  144.200,  "70cm": 432.100,
    "23cm":  1296.200,
}
KNOWN_BANDS = sorted(BAND_CENTRE_FREQ_MHZ.keys())
UNUN_RATIOS = [1, 1.5, 2, 3, 4, 6, 9, 12, 16, 25, 27, 36, 49, 64]


def _detect_ui_lang() -> str:
    """Return 'es' if system locale is Spanish, else 'en'."""
    try:
        lang = locale.getdefaultlocale()[0] or ""
    except Exception:
        lang = ""
    return "es" if lang.lower().startswith("es") else "en"


def _find_optimizer_script() -> "str | None":
    here = Path(__file__).parent
    candidate = here / "nec2_length_optimizer.py"
    if candidate.is_file():
        return str(candidate)
    for d in sys.path:
        p = Path(d) / "nec2_length_optimizer.py"
        if p.is_file():
            return str(p)
    return None


def _find_nec2c() -> str:
    for name in ("nec2c", "nec2c-mpich"):
        p = shutil.which(name)
        if p:
            return p
    for p in ("/usr/bin/nec2c", "/usr/local/bin/nec2c",
              "/opt/nec2c/bin/nec2c", "/opt/homebrew/bin/nec2c"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


# ── Translations ──────────────────────────────────────────────────────────

STRINGS = {
    "en": {
        # Window & header
        "title":              "NEC2 Antenna Length Optimizer GUI",
        "header_title":       "NEC2 Antenna Length Optimizer",
        "header_subtitle":    "  •  Interactive GUI",
        "optimizer_script":   "Optimizer script:",
        "browse":             "Browse…",
        "font_label":         "Font:",
        # Notebook tabs
        "tab_input":          "  Band / Source  ",
        "tab_search":         "  Search Range  ",
        "tab_physics":        "  Physics  ",
        "tab_output":         "  Output Files  ",
        "tab_run":            "  Run  ",
        # Tab: Band / Source
        "band_source_lf":     "Band Source",
        "load_csv":           "Load from CSV file",
        "enter_manual":       "Enter bands manually",
        "csv_file":           "CSV file:",
        "bands_label":        "Bands (comma-separated):",
        "known_prefix":       "Known: ",
        "freqs_label":        "Frequencies (MHz, optional):",
        "freqs_hint":         ("Leave empty for known amateur bands (auto-resolved). "
                               "Required only for unrecognised band names."),
        "wire_len":           "Starting wire length (m):",
        "cp_len":             "Starting CP length (m):",
        "active_bands_lf":    "Active Bands (VSWR Scoring)",
        "active_bands_desc":  ("Override which bands are scored for VSWR. "
                               "Leave empty to use the 'active' column from the CSV, "
                               "or to activate all bands when using manual mode."),
        "active_bands":       "Active bands:",
        "active_bands_eg":    "(e.g.  40m,20m)",
        "unun_lf":            "UnUn Transformer Ratio",
        "unun_label":         "UnUn ratio:",
        "unun_hint":          ":1   (e.g. 9 for 9:1 UnUn)",
        "optlang_lf":         "Optimizer Language",
        "optlang_label":      "Language:",
        "optlang_hint":       "auto = detected from system locale",
        # Tab: Search Range
        "margin_lf":          "Auto-derived Margin",
        "margin_label":       "Search margin (±):",
        "margin_hint":        "m   Applied around the CSV/manual wire & CP starting lengths.",
        "wire_range_lf":      "Wire Length Range  (overrides margin)",
        "leave_empty_wire":   "Leave min/max empty to use margin.",
        "cp_range_lf":        "Counterpoise Length Range  (overrides margin)",
        "leave_empty_cp":     "Leave min/max empty to use margin.",
        "retry_lf":           "Auto-retry on Boundary Hit",
        "max_retries":        "Max retries:",
        "retry_hint":         "If best candidate hits min/max, shift window and re-run (0 = disabled).",
        "report_opts_lf":     "Report Options",
        "top_n":              "Top N candidates in report:",
        # Tab: Physics
        "nec2_engine_lf":     "NEC2 Engine",
        "eval_mode":          "Evaluation mode:",
        "auto_mode":          "Auto (NEC2 if found, else empirical)",
        "nec2_mode":          "NEC2 (requires nec2c binary)",
        "empirical_mode":     "Empirical only (fast, no binary needed)",
        "nec2c_binary":       "nec2c binary:",
        "auto_detect_btn":    "Auto-detect",
        "nec2c_hint":         "Leave empty for automatic discovery.",
        "antenna_geom_lf":    "Antenna Geometry",
        "wire_height_lbl":    "wire-height:",
        "cp_height_lbl":      "cp-height:",
        "wire_height_hint":   "Antenna wire height above ground  (default 8 m)",
        "cp_height_hint":     "Counterpoise height above ground  (default 0.5 m)",
        "cp_orient_lf":       "Counterpoise Orientation",
        "both_cp":            "Both (simulate horizontal & vertical)",
        "horizontal_cp":      "Horizontal only",
        "vertical_cp":        "Vertical only",
        "ground_lf":          "Ground Parameters",
        "conductivity":       "Conductivity (σ):",
        "cond_unit":          "S/m   (0.005 = average ground)",
        "permittivity":       "Permittivity (εᵣ):",
        "perm_hint":          "(13 = average ground)",
        "quick_presets":      "Quick presets:",
        "preset_poor":        "Very poor (rock/desert)",
        "preset_avg":         "Average ground",
        "preset_good":        "Good ground",
        "preset_excel":       "Excellent (farm land)",
        "preset_salt":        "Salt water",
        "misc_lf":            "Misc Flags",
        "quiet_flag":         "quiet  (suppress progress output)",
        "no_interact":        "no-interactive  (don't prompt; exit on missing inputs)",
        # Tab: Output Files
        "workdir_lf":         "Working / Output Directory",
        "outdir_label":       "Output directory:",
        "workdir_hint":       "The optimizer will be launched with this as the working directory.",
        "outfiles_lf":        "Output File Names",
        "txt_tip":            "Ranked text report",
        "png_tip":            "Score heat map + VSWR bar charts",
        "csv_tip":            "Best candidate in band-analysis CSV format",
        "nec_tip":            "NEC2 input deck for best geometry",
        "rad_tip":            "Radiation pattern PNG (NEC2 mode only)",
        # Tab: Run
        "cmd_preview_lf":     "Command Preview",
        "refresh_preview":    "Refresh preview",
        "run_btn":            "▶  Run Optimizer",
        "stop_btn":           "■  Stop",
        "idle":               "Idle",
        "console_lf":         "Console Output",
        "clear_btn":          "Clear",
        # Runtime messages
        "running":            "Running…",
        "stopped":            "Stopped by user",
        "finished_ok":        "Finished successfully ✓",
        "exit_code":          "Process exited with code {rc}",
        "thread_error":       "Error: {e}",
        # Dialogs
        "script_nf_title":    "Script not found",
        "script_nf_msg":      ("Optimizer script not found:\n{script}\n\n"
                               "Please set the correct path on the 'Band / Source' tab."),
        "cfg_err_title":      "Configuration error",
        "dir_err_title":      "Directory error",
        "dir_err_msg":        "Cannot create output directory:\n{e}",
        "done_title":         "Done",
        "done_msg":           "Optimization complete!\n\nOpen report file?\n{report}",
        # Parameter hint descriptions (shown right of each label)
        "hint_wire_len":       "total radiating element length",
        "hint_cp_len":         "counterpoise / ground radial length",
        "hint_margin":         "±search window around starting length",
        "hint_wire_min":       "minimum wire length to test",
        "hint_wire_max":       "maximum wire length to test",
        "hint_wire_step":      "grid step between wire lengths",
        "hint_cp_min":         "minimum CP length to test",
        "hint_cp_max":         "maximum CP length to test",
        "hint_cp_step":        "grid step between CP lengths",
        "hint_max_retries":    "retry count when best hits boundary",
        "hint_top_n":          "candidates listed in text report",
        "hint_wire_height":    "antenna wire height above ground",
        "hint_cp_height":      "counterpoise height above ground",
        "hint_conductivity":   "soil conductivity in S/m",
        "hint_permittivity":   "relative permittivity (dielectric constant)",
        "hint_unun":           "impedance transformation ratio n:1",
        "hint_out_txt":        "ranked results text report",
        "hint_out_png":        "score heat-map + VSWR bar charts",
        "hint_out_csv":        "best candidate in CSV format",
        "hint_out_nec":        "NEC2 input deck for best geometry",
        "hint_out_rad":        "radiation pattern PNG (NEC2 only)",
        # Language toggle button label (shows the OTHER language to switch to)
        "lang_switch":        "ES",
    },
    "es": {
        # Ventana y cabecera
        "title":              "Optimizador de Longitud de Antenas NEC2 - GUI",
        "header_title":       "Optimizador de Longitud de Antenas NEC2",
        "header_subtitle":    "  •  GUI Interactiva",
        "optimizer_script":   "Script optimizador:",
        "browse":             "Examinar…",
        "font_label":         "Fuente:",
        # Pestañas
        "tab_input":          "  Banda / Fuente  ",
        "tab_search":         "  Rango de Búsqueda  ",
        "tab_physics":        "  Física  ",
        "tab_output":         "  Archivos de Salida  ",
        "tab_run":            "  Ejecutar  ",
        # Pestaña: Banda / Fuente
        "band_source_lf":     "Fuente de Bandas",
        "load_csv":           "Cargar desde archivo CSV",
        "enter_manual":       "Ingresar bandas manualmente",
        "csv_file":           "Archivo CSV:",
        "bands_label":        "Bandas (separadas por coma):",
        "known_prefix":       "Conocidas: ",
        "freqs_label":        "Frecuencias (MHz, opcional):",
        "freqs_hint":         ("Dejar vacío para bandas amateur conocidas (auto). "
                               "Requerido sólo para nombres de banda no reconocidos."),
        "wire_len":           "Longitud inicial del hilo (m):",
        "cp_len":             "Longitud inicial del CP (m):",
        "active_bands_lf":    "Bandas Activas (Puntuación VSWR)",
        "active_bands_desc":  ("Anula qué bandas se puntúan para el VSWR. "
                               "Dejar vacío para usar la columna 'active' del CSV, "
                               "o activar todas en modo manual."),
        "active_bands":       "Bandas activas:",
        "active_bands_eg":    "(ej.  40m,20m)",
        "unun_lf":            "Relación del Transformador UnUn",
        "unun_label":         "Relación UnUn:",
        "unun_hint":          ":1   (ej. 9 para UnUn 9:1)",
        "optlang_lf":         "Idioma del Optimizador",
        "optlang_label":      "Idioma:",
        "optlang_hint":       "auto = detectado del idioma del sistema",
        # Pestaña: Rango de Búsqueda
        "margin_lf":          "Margen Derivado Automáticamente",
        "margin_label":       "Margen de búsqueda (±):",
        "margin_hint":        "m   Aplicado alrededor de las longitudes iniciales de hilo y CP.",
        "wire_range_lf":      "Rango de Longitud del Hilo  (anula margen)",
        "leave_empty_wire":   "Dejar mín/máx vacío para usar el margen.",
        "cp_range_lf":        "Rango de Longitud del Contrapeso  (anula margen)",
        "leave_empty_cp":     "Dejar mín/máx vacío para usar el margen.",
        "retry_lf":           "Reintento Automático al Alcanzar el Límite",
        "max_retries":        "Reintentos máximos:",
        "retry_hint":         "Si el mejor candidato alcanza el mín/máx, desplazar ventana y re-ejecutar (0 = desactivado).",
        "report_opts_lf":     "Opciones del Informe",
        "top_n":              "Top N candidatos en el informe:",
        # Pestaña: Física
        "nec2_engine_lf":     "Motor NEC2",
        "eval_mode":          "Modo de evaluación:",
        "auto_mode":          "Auto (NEC2 si disponible, si no empírico)",
        "nec2_mode":          "NEC2 (requiere binario nec2c)",
        "empirical_mode":     "Sólo empírico (rápido, sin binario)",
        "nec2c_binary":       "Binario nec2c:",
        "auto_detect_btn":    "Auto-detectar",
        "nec2c_hint":         "Dejar vacío para descubrimiento automático.",
        "antenna_geom_lf":    "Geometría de la Antena",
        "wire_height_lbl":    "wire-height:",
        "cp_height_lbl":      "cp-height:",
        "wire_height_hint":   "Altura del hilo de antena sobre el suelo  (por defecto 8 m)",
        "cp_height_hint":     "Altura del contrapeso sobre el suelo  (por defecto 0,5 m)",
        "cp_orient_lf":       "Orientación del Contrapeso",
        "both_cp":            "Ambos (simular horizontal y vertical)",
        "horizontal_cp":      "Sólo horizontal",
        "vertical_cp":        "Sólo vertical",
        "ground_lf":          "Parámetros del Suelo",
        "conductivity":       "Conductividad (σ):",
        "cond_unit":          "S/m   (0,005 = suelo promedio)",
        "permittivity":       "Permitividad (εᵣ):",
        "perm_hint":          "(13 = suelo promedio)",
        "quick_presets":      "Preajustes rápidos:",
        "preset_poor":        "Muy pobre (roca/desierto)",
        "preset_avg":         "Suelo promedio",
        "preset_good":        "Suelo bueno",
        "preset_excel":       "Excelente (tierra de cultivo)",
        "preset_salt":        "Agua salada",
        "misc_lf":            "Opciones Varias",
        "quiet_flag":         "quiet  (suprimir salida de progreso)",
        "no_interact":        "no-interactive  (sin preguntas; salir si faltan entradas)",
        # Pestaña: Archivos de Salida
        "workdir_lf":         "Directorio de Trabajo / Salida",
        "outdir_label":       "Directorio de salida:",
        "workdir_hint":       "El optimizador se ejecutará con este como directorio de trabajo.",
        "outfiles_lf":        "Nombres de Archivos de Salida",
        "txt_tip":            "Informe de texto ordenado",
        "png_tip":            "Mapa de calor + gráficos VSWR",
        "csv_tip":            "Mejor candidato en formato CSV de análisis de banda",
        "nec_tip":            "Archivo de entrada NEC2 para la mejor geometría",
        "rad_tip":            "PNG de patrón de radiación (sólo modo NEC2)",
        # Pestaña: Ejecutar
        "cmd_preview_lf":     "Vista Previa del Comando",
        "refresh_preview":    "Actualizar vista previa",
        "run_btn":            "▶  Ejecutar Optimizador",
        "stop_btn":           "■  Detener",
        "idle":               "Inactivo",
        "console_lf":         "Salida de Consola",
        "clear_btn":          "Limpiar",
        # Mensajes en tiempo de ejecución
        "running":            "Ejecutando…",
        "stopped":            "Detenido por el usuario",
        "finished_ok":        "Finalizado con éxito ✓",
        "exit_code":          "El proceso terminó con código {rc}",
        "thread_error":       "Error: {e}",
        # Diálogos
        "script_nf_title":    "Script no encontrado",
        "script_nf_msg":      ("Script optimizador no encontrado:\n{script}\n\n"
                               "Establezca la ruta correcta en la pestaña 'Banda / Fuente'."),
        "cfg_err_title":      "Error de configuración",
        "dir_err_title":      "Error de directorio",
        "dir_err_msg":        "No se puede crear el directorio de salida:\n{e}",
        "done_title":         "Completado",
        "done_msg":           "¡Optimización completada!\n\n¿Abrir archivo de informe?\n{report}",
        # Descripciones de parámetros (se muestran a la derecha de cada etiqueta)
        "hint_wire_len":       "longitud total del elemento radiante",
        "hint_cp_len":         "longitud del contrapeso / radial de tierra",
        "hint_margin":         "±ventana de búsqueda alrededor de la longitud inicial",
        "hint_wire_min":       "longitud mínima de hilo a probar",
        "hint_wire_max":       "longitud máxima de hilo a probar",
        "hint_wire_step":      "paso de grilla entre longitudes de hilo",
        "hint_cp_min":         "longitud mínima de CP a probar",
        "hint_cp_max":         "longitud máxima de CP a probar",
        "hint_cp_step":        "paso de grilla entre longitudes de CP",
        "hint_max_retries":    "reintentos cuando el mejor alcanza el límite",
        "hint_top_n":          "candidatos listados en el informe de texto",
        "hint_wire_height":    "altura del hilo de antena sobre el suelo",
        "hint_cp_height":      "altura del contrapeso sobre el suelo",
        "hint_conductivity":   "conductividad del suelo en S/m",
        "hint_permittivity":   "permitividad relativa (constante dieléctrica)",
        "hint_unun":           "relación de transformación de impedancia n:1",
        "hint_out_txt":        "informe de texto con resultados ordenados",
        "hint_out_png":        "mapa de calor de puntuación + gráficos VSWR",
        "hint_out_csv":        "mejor candidato en formato CSV",
        "hint_out_nec":        "archivo de entrada NEC2 para mejor geometría",
        "hint_out_rad":        "PNG de patrón de radiación (solo NEC2)",
        # Botón de idioma (muestra el OTRO idioma al que se cambiará)
        "lang_switch":        "EN",
    },
}


# ── Colour constants ───────────────────────────────────────────────────────

BG        = "#DBD1BD"   # warm beige — main background
BG2       = "#D0C6B2"   # slightly darker panels
BG3       = "#C8BEA8"   # notebook tab background
ENTRY_BG  = "#EDE8DF"   # entry / text-area background
BORDER    = "#C0C0C0"   # light gray borders (all borders)
FG        = "#000000"   # black text
FG2       = "#555555"   # muted / secondary text
ACCENT    = "#1A4A8A"   # dark blue accent
ACCENT2   = "#1A5E1A"   # dark green — success
WARN      = "#7A5500"   # dark amber — warnings
ERR       = "#8A1515"   # dark red — errors
BTN_BG    = "#C4BAA8"   # browse / secondary button background
BTN_HOV   = "#B0A898"   # browse button hover

# Console-output tag colours (must be readable on ENTRY_BG)
TAG_WARN  = "#7A5500"
TAG_ERR   = "#8A1515"
TAG_OK    = "#1A5E1A"
TAG_HEAD  = "#1A4A8A"

_FF   = "Segoe UI"  if sys.platform == "win32" else "DejaVu Sans"
_FFM  = "Consolas"  if sys.platform == "win32" else "DejaVu Sans Mono"
_BASE = 10          # default font size


# ── Main Application ───────────────────────────────────────────────────────

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.resizable(True, True)
        self.minsize(920, 640)

        # Shared font objects — mutated in-place so all widgets update together
        self._font_obj      = tkfont.Font(family=_FF,  size=_BASE)
        self._font_obj_mono = tkfont.Font(family=_FFM, size=_BASE)

        self._process: "subprocess.Popen | None" = None
        self._thread:  "threading.Thread | None" = None
        self._running  = False

        self._script_path = _find_optimizer_script()

        # ── i18n & font state ────────────────────────────────────────────
        self._ui_lang  = _detect_ui_lang()
        self._font_sz  = _BASE
        self._tw: list = []   # list of callables that refresh one UI string

        self._build_style()
        self._build_ui()
        self._apply_language()   # set all text + window title
        self._auto_detect_nec2c()

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 980, 760
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ── Translation helpers ───────────────────────────────────────────────

    def t(self, key: str, **kw) -> str:
        """Return translated string for key, formatted with kw."""
        s = STRINGS[self._ui_lang].get(key, key)
        return s.format(**kw) if kw else s

    def _reg(self, widget, key: str):
        """Register a widget for language updates (via widget.config(text=…))."""
        self._tw.append(lambda w=widget, k=key: w.config(text=self.t(k)))
        return widget

    def _reg_fn(self, fn):
        """Register an arbitrary callable for language/font updates."""
        self._tw.append(fn)
        return fn

    def _apply_language(self):
        """Update window title + all registered widget texts."""
        self.title(self.t("title"))
        for fn in self._tw:
            try:
                fn()
            except Exception:
                pass
        # Notebook tabs (stored indices)
        for idx, key in self._tab_keys:
            try:
                self._nb.tab(idx, text=self.t(key))
            except Exception:
                pass

    def _toggle_lang(self):
        self._ui_lang = "es" if self._ui_lang == "en" else "en"
        self._apply_language()

    # ── Font helpers ──────────────────────────────────────────────────────

    def _font(self, variant="main"):
        sz = self._font_sz
        if variant == "mono":
            return self._font_obj_mono   # shared object, mutated in _apply_fonts
        if variant == "h1":
            return (_FF, sz + 2, "bold")
        if variant == "bold":
            return (_FF, sz, "bold")
        if variant == "label":
            return (_FF, sz)
        # "main" — return shared object so tk.Text widgets auto-update
        return self._font_obj

    def _apply_fonts(self):
        # ── Step 1: mutate shared Font objects FIRST ─────────────────────
        # _font() returns these objects, so styles below pick up the new size
        self._font_obj.configure(family=_FF,  size=self._font_sz)
        self._font_obj_mono.configure(family=_FFM, size=self._font_sz)

        # ── Step 2: update ttk styles (uses tuples so size must be explicit)
        sz   = self._font_sz
        st   = ttk.Style(self)
        st.configure(".",                 font=(_FF,  sz))
        st.configure("TLabel",            font=(_FF,  sz))
        st.configure("Bold.TLabel",       font=(_FF,  sz + 2, "bold"))
        st.configure("Muted.TLabel",      font=(_FF,  sz))
        st.configure("TLabelframe.Label", font=(_FF,  sz))
        st.configure("TNotebook.Tab",     font=(_FF,  sz))
        st.configure("Accent.TButton",    font=(_FF,  sz, "bold"))
        st.configure("Stop.TButton",      font=(_FF,  sz, "bold"))
        st.configure("Browse.TButton",    font=(_FF,  sz))
        st.configure("Lang.TButton",      font=(_FF,  sz, "bold"))
        st.configure("FontCtrl.TButton",  font=(_FF,  sz, "bold"))
        st.configure("TEntry",            font=(_FF,  sz))
        st.configure("TSpinbox",          font=(_FF,  sz))
        st.configure("TCombobox",         font=(_FF,  sz))
        st.configure("TCheckbutton",      font=(_FF,  sz))
        st.configure("TRadiobutton",      font=(_FF,  sz))

        # ── Step 3: plain tk widgets — must be updated explicitly ────────
        mono = (_FFM, sz)
        if hasattr(self, "_cmd_text"):
            self._cmd_text.config(font=mono)
        if hasattr(self, "_console"):
            self._console.config(font=mono)
        if hasattr(self, "_font_sz_lbl"):
            self._font_sz_lbl.config(text=str(self._font_sz))

    def _font_up(self):
        if self._font_sz < 20:
            self._font_sz += 1
            self._apply_fonts()

    def _font_down(self):
        if self._font_sz > 7:
            self._font_sz -= 1
            self._apply_fonts()

    # ── Style ─────────────────────────────────────────────────────────────

    def _build_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")

        st.configure(".",
            background=BG, foreground=FG,
            fieldbackground=ENTRY_BG,
            font=self._font(),
            relief="flat",
            bordercolor=BORDER,
        )
        st.configure("TFrame",   background=BG)
        st.configure("TLabel",   background=BG, foreground=FG,  font=self._font("label"))
        st.configure("Bold.TLabel",  background=BG, foreground=ACCENT, font=self._font("h1"))
        st.configure("Muted.TLabel", background=BG, foreground=FG2,    font=self._font("label"))
        st.configure("TEntry",
            fieldbackground=ENTRY_BG, foreground=FG,
            insertcolor=FG, relief="solid", borderwidth=1,
            bordercolor=BORDER,
        )
        st.configure("TSpinbox",
            fieldbackground=ENTRY_BG, foreground=FG,
            insertcolor=FG, relief="solid", borderwidth=1,
            bordercolor=BORDER,
        )
        st.configure("TCombobox",
            fieldbackground=ENTRY_BG, foreground=FG,
            selectbackground=ACCENT, selectforeground=BG,
            relief="solid", borderwidth=1, bordercolor=BORDER,
        )
        st.map("TCombobox",
            fieldbackground=[("readonly", ENTRY_BG)],
            foreground=[("readonly", FG)],
        )
        st.configure("TCheckbutton",
            background=BG, foreground=FG,
            indicatorcolor=ENTRY_BG, bordercolor=BORDER,
        )
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TRadiobutton",
            background=BG, foreground=FG,
            indicatorcolor=ENTRY_BG, bordercolor=BORDER,
        )
        st.map("TRadiobutton", background=[("active", BG)])
        st.configure("TLabelframe",
            background=BG, foreground=FG,
            bordercolor=BORDER, relief="solid", borderwidth=1,
        )
        st.configure("TLabelframe.Label", background=BG, foreground=FG, font=self._font())
        st.configure("TNotebook",     background=BG2, borderwidth=1, bordercolor=BORDER)
        st.configure("TNotebook.Tab",
            background=BG3, foreground=FG2,
            padding=(12, 5), font=self._font(),
            bordercolor=BORDER,
        )
        st.map("TNotebook.Tab",
            background=[("selected", BG),    ("active", BG2)],
            foreground=[("selected", ACCENT), ("active", FG)],
        )
        st.configure("TScrollbar",
            background=BG2, troughcolor=BG,
            arrowcolor=FG2, bordercolor=BORDER,
        )
        st.configure("TProgressbar", background=ACCENT, troughcolor=BG3, bordercolor=BORDER)
        st.configure("TSeparator",   background=BORDER)

        # Action buttons
        st.configure("Accent.TButton",
            background=ACCENT, foreground=BG,
            relief="solid", padding=(14, 8), font=self._font("bold"),
            bordercolor=BORDER,
        )
        st.map("Accent.TButton",
            background=[("active", "#2560AA"), ("disabled", BG3)],
            foreground=[("disabled", FG2)],
        )
        st.configure("Stop.TButton",
            background=ERR, foreground=BG,
            relief="solid", padding=(14, 8), font=self._font("bold"),
            bordercolor=BORDER,
        )
        st.map("Stop.TButton", background=[("active", "#AA2020")])

        # Browse / secondary buttons
        st.configure("Browse.TButton",
            background=BTN_BG, foreground=FG,
            relief="solid", padding=(6, 4), bordercolor=BORDER,
        )
        st.map("Browse.TButton", background=[("active", BTN_HOV)])

        # Language toggle button
        st.configure("Lang.TButton",
            background=BTN_BG, foreground=ACCENT,
            relief="solid", padding=(6, 4), font=self._font("bold"),
            bordercolor=BORDER,
        )
        st.map("Lang.TButton", background=[("active", BTN_HOV)])

        # Font size control buttons
        st.configure("FontCtrl.TButton",
            background=BTN_BG, foreground=FG,
            relief="solid", padding=(4, 2), font=self._font("bold"),
            bordercolor=BORDER,
        )
        st.map("FontCtrl.TButton", background=[("active", BTN_HOV)])

    # ── UI Structure ──────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header row ───────────────────────────────────────────────────
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=16, pady=(10, 4))

        self._hdr_title_lbl = ttk.Label(hdr, style="Bold.TLabel")
        self._hdr_title_lbl.pack(side="left")
        self._reg(self._hdr_title_lbl, "header_title")

        self._hdr_sub_lbl = ttk.Label(hdr, style="Muted.TLabel")
        self._hdr_sub_lbl.pack(side="left", pady=(3, 0))
        self._reg(self._hdr_sub_lbl, "header_subtitle")

        # Right-side controls: language toggle, then font size
        self._lang_btn = ttk.Button(hdr, style="Lang.TButton",
                                    command=self._toggle_lang)
        self._lang_btn.pack(side="right", padx=(6, 0))
        self._reg(self._lang_btn, "lang_switch")

        ttk.Button(hdr, text="+", style="FontCtrl.TButton",
                   command=self._font_up).pack(side="right", padx=(2, 0))

        self._font_sz_lbl = ttk.Label(hdr, text=str(self._font_sz),
                                       foreground=FG2, width=3,
                                       anchor="center")
        self._font_sz_lbl.pack(side="right")

        ttk.Button(hdr, text="−", style="FontCtrl.TButton",
                   command=self._font_down).pack(side="right", padx=(6, 2))

        self._font_prefix_lbl = ttk.Label(hdr, style="Muted.TLabel")
        self._font_prefix_lbl.pack(side="right", padx=(16, 0))
        self._reg(self._font_prefix_lbl, "font_label")

        # ── Script path row ──────────────────────────────────────────────
        spf = ttk.Frame(self)
        spf.pack(fill="x", padx=16, pady=2)

        self._script_row_lbl = ttk.Label(spf, width=18)
        self._script_row_lbl.pack(side="left")
        self._reg(self._script_row_lbl, "optimizer_script")

        self._script_var = tk.StringVar(value=self._script_path or "")
        ttk.Entry(spf, textvariable=self._script_var, width=60).pack(side="left", padx=(4, 4))

        self._browse_script_btn = ttk.Button(spf, style="Browse.TButton",
                                              command=self._browse_script)
        self._browse_script_btn.pack(side="left")
        self._reg(self._browse_script_btn, "browse")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=6)

        # ── Notebook ─────────────────────────────────────────────────────
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        self._tab_input   = ttk.Frame(self._nb, padding=10)
        self._tab_search  = ttk.Frame(self._nb, padding=10)
        self._tab_physics = ttk.Frame(self._nb, padding=10)
        self._tab_output  = ttk.Frame(self._nb, padding=10)
        self._tab_run     = ttk.Frame(self._nb, padding=10)

        # Add tabs with placeholder text; real text set by _apply_language
        for tab in (self._tab_input, self._tab_search,
                    self._tab_physics, self._tab_output, self._tab_run):
            self._nb.add(tab, text="")

        # Map tab indices → translation keys
        self._tab_keys = [
            (0, "tab_input"),
            (1, "tab_search"),
            (2, "tab_physics"),
            (3, "tab_output"),
            (4, "tab_run"),
        ]

        self._build_tab_input()
        self._build_tab_search()
        self._build_tab_physics()
        self._build_tab_output()
        self._build_tab_run()

    # ── Tab: Band / Source ────────────────────────────────────────────────

    def _build_tab_input(self):
        t = self._tab_input

        # Band source selector
        src_lf = ttk.LabelFrame(t, padding=8)
        src_lf.pack(fill="x", pady=(0, 8))
        self._reg(src_lf, "band_source_lf")

        self._src_mode = tk.StringVar(value="manual")

        self._rb_csv = ttk.Radiobutton(src_lf, variable=self._src_mode,
                                        value="csv", command=self._toggle_src)
        self._rb_csv.grid(row=0, column=0, sticky="w", padx=(0, 20))
        self._reg(self._rb_csv, "load_csv")

        self._rb_man = ttk.Radiobutton(src_lf, variable=self._src_mode,
                                        value="manual", command=self._toggle_src)
        self._rb_man.grid(row=0, column=1, sticky="w")
        self._reg(self._rb_man, "enter_manual")

        # CSV frame
        self._csv_frame = ttk.Frame(src_lf)
        self._csv_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self._csv_lbl = ttk.Label(self._csv_frame)
        self._csv_lbl.pack(side="left")
        self._reg(self._csv_lbl, "csv_file")

        self._csv_var = tk.StringVar()
        ttk.Entry(self._csv_frame, textvariable=self._csv_var, width=50).pack(side="left", padx=(4, 4))

        self._browse_csv_btn = ttk.Button(self._csv_frame, style="Browse.TButton",
                                           command=self._browse_csv)
        self._browse_csv_btn.pack(side="left")
        self._reg(self._browse_csv_btn, "browse")

        # Manual frame
        self._manual_frame = ttk.Frame(src_lf)
        self._manual_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self._bands_lbl = ttk.Label(self._manual_frame)
        self._bands_lbl.grid(row=0, column=0, sticky="w")
        self._reg(self._bands_lbl, "bands_label")

        self._bands_var = tk.StringVar(value="40m,20m,15m")
        ttk.Entry(self._manual_frame, textvariable=self._bands_var, width=40).grid(
            row=0, column=1, padx=6, sticky="ew")

        self._known_bands_lbl = ttk.Label(self._manual_frame, style="Muted.TLabel",
                                           wraplength=480)
        self._known_bands_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self._reg_fn(lambda: self._known_bands_lbl.config(
            text=self.t("known_prefix") + ", ".join(KNOWN_BANDS)))

        self._freqs_lbl = ttk.Label(self._manual_frame)
        self._freqs_lbl.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._reg(self._freqs_lbl, "freqs_label")

        self._freqs_var = tk.StringVar()
        ttk.Entry(self._manual_frame, textvariable=self._freqs_var, width=40).grid(
            row=2, column=1, padx=6, pady=(6, 0), sticky="ew")

        self._freqs_hint_lbl = ttk.Label(self._manual_frame, style="Muted.TLabel", wraplength=480)
        self._freqs_hint_lbl.grid(row=3, column=0, columnspan=2, sticky="w")
        self._reg(self._freqs_hint_lbl, "freqs_hint")

        self._wire_len_lbl = ttk.Label(self._manual_frame)
        self._wire_len_lbl.grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._reg(self._wire_len_lbl, "wire_len")

        self._wire_len_var = tk.StringVar(value="21.0")
        ttk.Entry(self._manual_frame, textvariable=self._wire_len_var, width=12).grid(
            row=4, column=1, padx=6, pady=(6, 0), sticky="w")
        _wl_hint = ttk.Label(self._manual_frame, foreground=ACCENT)
        _wl_hint.grid(row=4, column=2, sticky="w", padx=(4, 0), pady=(6, 0))
        self._reg(_wl_hint, "hint_wire_len")

        self._cp_len_lbl = ttk.Label(self._manual_frame)
        self._cp_len_lbl.grid(row=5, column=0, sticky="w", pady=(4, 0))
        self._reg(self._cp_len_lbl, "cp_len")

        self._cp_len_var = tk.StringVar(value="5.0")
        ttk.Entry(self._manual_frame, textvariable=self._cp_len_var, width=12).grid(
            row=5, column=1, padx=6, pady=(4, 0), sticky="w")
        _cpl_hint = ttk.Label(self._manual_frame, foreground=ACCENT)
        _cpl_hint.grid(row=5, column=2, sticky="w", padx=(4, 0), pady=(4, 0))
        self._reg(_cpl_hint, "hint_cp_len")

        # Active Bands
        ab_lf = ttk.LabelFrame(t, padding=8)
        ab_lf.pack(fill="x", pady=(0, 8))
        self._reg(ab_lf, "active_bands_lf")

        self._ab_desc_lbl = ttk.Label(ab_lf)
        self._ab_desc_lbl.pack(anchor="w")
        self._reg(self._ab_desc_lbl, "active_bands_desc")

        abf2 = ttk.Frame(ab_lf)
        abf2.pack(fill="x", pady=(4, 0))

        self._ab_lbl = ttk.Label(abf2)
        self._ab_lbl.pack(side="left")
        self._reg(self._ab_lbl, "active_bands")

        self._active_bands_var = tk.StringVar()
        ttk.Entry(abf2, textvariable=self._active_bands_var, width=36).pack(side="left", padx=6)

        self._ab_eg_lbl = ttk.Label(abf2, style="Muted.TLabel")
        self._ab_eg_lbl.pack(side="left")
        self._reg(self._ab_eg_lbl, "active_bands_eg")

        # UnUn ratio
        unun_lf = ttk.LabelFrame(t, padding=8)
        unun_lf.pack(fill="x", pady=(0, 8))
        self._reg(unun_lf, "unun_lf")

        uf = ttk.Frame(unun_lf)
        uf.pack(anchor="w")

        self._unun_lbl = ttk.Label(uf)
        self._unun_lbl.pack(side="left")
        self._reg(self._unun_lbl, "unun_label")

        self._unun_var = tk.StringVar(value="9")
        ttk.Combobox(uf, textvariable=self._unun_var, width=8,
                     values=[str(r) for r in UNUN_RATIOS]).pack(side="left", padx=6)

        self._unun_hint_lbl = ttk.Label(uf, style="Muted.TLabel")
        self._unun_hint_lbl.pack(side="left")
        self._reg(self._unun_hint_lbl, "unun_hint")

        self._toggle_src()

    def _toggle_src(self):
        if self._src_mode.get() == "csv":
            self._csv_frame.grid()
            self._manual_frame.grid_remove()
        else:
            self._csv_frame.grid_remove()
            self._manual_frame.grid()

    # ── Tab: Search Range ─────────────────────────────────────────────────

    def _build_tab_search(self):
        t = self._tab_search

        def _entry_row(parent, lbl_key, var, row, unit="m", width=10):
            lbl = ttk.Label(parent)
            lbl.grid(row=row, column=0, sticky="w", pady=3)
            self._reg(lbl, lbl_key)
            ttk.Entry(parent, textvariable=var, width=width).grid(
                row=row, column=1, padx=6, pady=3, sticky="w")
            ttk.Label(parent, text=unit, style="Muted.TLabel").grid(
                row=row, column=2, sticky="w")

        # Margin
        mg_lf = ttk.LabelFrame(t, padding=8)
        mg_lf.pack(fill="x", pady=(0, 8))
        self._reg(mg_lf, "margin_lf")

        mf = ttk.Frame(mg_lf)
        mf.pack(anchor="w")

        self._margin_lbl = ttk.Label(mf)
        self._margin_lbl.pack(side="left")
        self._reg(self._margin_lbl, "margin_label")

        self._margin_var = tk.StringVar(value="2.0")
        ttk.Entry(mf, textvariable=self._margin_var, width=8).pack(side="left", padx=6)

        self._margin_hint_lbl = ttk.Label(mf, style="Muted.TLabel")
        self._margin_hint_lbl.pack(side="left")
        self._reg(self._margin_hint_lbl, "margin_hint")
        _mg_pdesc = ttk.Label(mf, foreground=ACCENT)
        _mg_pdesc.pack(side="left", padx=(8, 0))
        self._reg(_mg_pdesc, "hint_margin")

        # Wire range
        wr_lf = ttk.LabelFrame(t, padding=8)
        wr_lf.pack(fill="x", pady=(0, 8))
        self._reg(wr_lf, "wire_range_lf")

        self._wire_min_var  = tk.StringVar()
        self._wire_max_var  = tk.StringVar()
        self._wire_step_var = tk.StringVar(value="0.25")

        # Static labels for the fixed CLI flags
        _wire_range_hints = ["hint_wire_min", "hint_wire_max", "hint_wire_step"]
        for row_i, (flag, var, hint_key) in enumerate([
            ("wire-min:",  self._wire_min_var,  "hint_wire_min"),
            ("wire-max:",  self._wire_max_var,  "hint_wire_max"),
            ("wire-step:", self._wire_step_var, "hint_wire_step"),
        ]):
            ttk.Label(wr_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
            ttk.Entry(wr_lf, textvariable=var, width=10).grid(
                row=row_i, column=1, padx=6, pady=3, sticky="w")
            ttk.Label(wr_lf, text="m", style="Muted.TLabel").grid(
                row=row_i, column=2, sticky="w")
            _wh = ttk.Label(wr_lf, foreground=ACCENT)
            _wh.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
            self._reg(_wh, hint_key)

        self._wire_empty_lbl = ttk.Label(wr_lf, style="Muted.TLabel")
        self._wire_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._reg(self._wire_empty_lbl, "leave_empty_wire")

        # CP range
        cp_lf = ttk.LabelFrame(t, padding=8)
        cp_lf.pack(fill="x", pady=(0, 8))
        self._reg(cp_lf, "cp_range_lf")

        self._cp_min_var  = tk.StringVar()
        self._cp_max_var  = tk.StringVar()
        self._cp_step_var = tk.StringVar(value="0.25")

        for row_i, (flag, var, hint_key) in enumerate([
            ("cp-min:",  self._cp_min_var,  "hint_cp_min"),
            ("cp-max:",  self._cp_max_var,  "hint_cp_max"),
            ("cp-step:", self._cp_step_var, "hint_cp_step"),
        ]):
            ttk.Label(cp_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
            ttk.Entry(cp_lf, textvariable=var, width=10).grid(
                row=row_i, column=1, padx=6, pady=3, sticky="w")
            ttk.Label(cp_lf, text="m", style="Muted.TLabel").grid(
                row=row_i, column=2, sticky="w")
            _ch = ttk.Label(cp_lf, foreground=ACCENT)
            _ch.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
            self._reg(_ch, hint_key)

        self._cp_empty_lbl = ttk.Label(cp_lf, style="Muted.TLabel")
        self._cp_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._reg(self._cp_empty_lbl, "leave_empty_cp")

        # Retry
        rt_lf = ttk.LabelFrame(t, padding=8)
        rt_lf.pack(fill="x", pady=(0, 8))
        self._reg(rt_lf, "retry_lf")

        rtf = ttk.Frame(rt_lf)
        rtf.pack(anchor="w")

        self._retry_lbl = ttk.Label(rtf)
        self._retry_lbl.pack(side="left")
        self._reg(self._retry_lbl, "max_retries")

        self._retry_var = tk.StringVar(value="0")
        ttk.Spinbox(rtf, from_=0, to=10, textvariable=self._retry_var, width=5).pack(
            side="left", padx=6)

        self._retry_hint_lbl = ttk.Label(rtf, style="Muted.TLabel")
        self._retry_hint_lbl.pack(side="left")
        self._reg(self._retry_hint_lbl, "retry_hint")
        _rt_pdesc = ttk.Label(rtf, foreground=ACCENT)
        _rt_pdesc.pack(side="left", padx=(8, 0))
        self._reg(_rt_pdesc, "hint_max_retries")

        # Top-N
        tn_lf = ttk.LabelFrame(t, padding=8)
        tn_lf.pack(fill="x", pady=(0, 8))
        self._reg(tn_lf, "report_opts_lf")

        tnf = ttk.Frame(tn_lf)
        tnf.pack(anchor="w")

        self._topn_lbl = ttk.Label(tnf)
        self._topn_lbl.pack(side="left")
        self._reg(self._topn_lbl, "top_n")

        self._topn_var = tk.StringVar(value="20")
        ttk.Spinbox(tnf, from_=5, to=200, textvariable=self._topn_var, width=6).pack(
            side="left", padx=6)
        _tn_pdesc = ttk.Label(tnf, foreground=ACCENT)
        _tn_pdesc.pack(side="left", padx=(8, 0))
        self._reg(_tn_pdesc, "hint_top_n")

    # ── Tab: Physics ──────────────────────────────────────────────────────

    def _build_tab_physics(self):
        t = self._tab_physics

        # NEC2 engine
        nec_lf = ttk.LabelFrame(t, padding=8)
        nec_lf.pack(fill="x", pady=(0, 8))
        self._reg(nec_lf, "nec2_engine_lf")

        mf = ttk.Frame(nec_lf)
        mf.pack(fill="x")

        self._eval_mode_lbl = ttk.Label(mf)
        self._eval_mode_lbl.pack(side="left")
        self._reg(self._eval_mode_lbl, "eval_mode")

        self._mode_var = tk.StringVar(value="auto")
        self._rb_auto = ttk.Radiobutton(mf, variable=self._mode_var, value="auto")
        self._rb_auto.pack(side="left", padx=(12, 0))
        self._reg(self._rb_auto, "auto_mode")

        self._rb_nec2 = ttk.Radiobutton(mf, variable=self._mode_var, value="nec2")
        self._rb_nec2.pack(side="left", padx=(12, 0))
        self._reg(self._rb_nec2, "nec2_mode")

        self._rb_emp = ttk.Radiobutton(mf, variable=self._mode_var, value="empirical")
        self._rb_emp.pack(side="left", padx=(12, 0))
        self._reg(self._rb_emp, "empirical_mode")

        nf = ttk.Frame(nec_lf)
        nf.pack(fill="x", pady=(8, 0))

        self._nec2c_lbl = ttk.Label(nf)
        self._nec2c_lbl.pack(side="left")
        self._reg(self._nec2c_lbl, "nec2c_binary")

        self._nec2c_var = tk.StringVar()
        ttk.Entry(nf, textvariable=self._nec2c_var, width=48).pack(side="left", padx=4)

        self._browse_nec_btn = ttk.Button(nf, style="Browse.TButton",
                                           command=self._browse_nec2c)
        self._browse_nec_btn.pack(side="left")
        self._reg(self._browse_nec_btn, "browse")

        self._auto_detect_btn = ttk.Button(nf, style="Browse.TButton",
                                            command=self._auto_detect_nec2c)
        self._auto_detect_btn.pack(side="left", padx=(6, 0))
        self._reg(self._auto_detect_btn, "auto_detect_btn")

        self._nec2c_hint_lbl = ttk.Label(nec_lf, style="Muted.TLabel")
        self._nec2c_hint_lbl.pack(anchor="w", pady=(2, 0))
        self._reg(self._nec2c_hint_lbl, "nec2c_hint")

        # Antenna geometry
        hgt_lf = ttk.LabelFrame(t, padding=8)
        hgt_lf.pack(fill="x", pady=(0, 8))
        self._reg(hgt_lf, "antenna_geom_lf")

        self._wire_height_var = tk.StringVar(value="8.0")
        self._cp_height_var   = tk.StringVar(value="0.5")

        for row_i, (key_lbl, var, key_hint) in enumerate([
            ("wire_height_lbl", self._wire_height_var, "wire_height_hint"),
            ("cp_height_lbl",   self._cp_height_var,   "cp_height_hint"),
        ]):
            lbl = ttk.Label(hgt_lf)
            lbl.grid(row=row_i, column=0, sticky="w", pady=3)
            self._reg(lbl, key_lbl)
            ttk.Entry(hgt_lf, textvariable=var, width=10).grid(
                row=row_i, column=1, padx=6, pady=3, sticky="w")
            ttk.Label(hgt_lf, text="m", style="Muted.TLabel").grid(
                row=row_i, column=2, sticky="w")
            hint_lbl = ttk.Label(hgt_lf, foreground=ACCENT)
            hint_lbl.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
            self._reg(hint_lbl, key_hint)

        # Counterpoise orientation
        cp_lf = ttk.LabelFrame(t, padding=8)
        cp_lf.pack(fill="x", pady=(0, 8))
        self._reg(cp_lf, "cp_orient_lf")

        self._cp_type_var = tk.StringVar(value="both")
        cpf = ttk.Frame(cp_lf)
        cpf.pack(anchor="w")

        self._rb_both = ttk.Radiobutton(cpf, variable=self._cp_type_var, value="both")
        self._rb_both.pack(side="left", padx=(0, 16))
        self._reg(self._rb_both, "both_cp")

        self._rb_horiz = ttk.Radiobutton(cpf, variable=self._cp_type_var, value="horizontal")
        self._rb_horiz.pack(side="left", padx=(0, 16))
        self._reg(self._rb_horiz, "horizontal_cp")

        self._rb_vert = ttk.Radiobutton(cpf, variable=self._cp_type_var, value="vertical")
        self._rb_vert.pack(side="left")
        self._reg(self._rb_vert, "vertical_cp")

        # Ground parameters
        gnd_lf = ttk.LabelFrame(t, padding=8)
        gnd_lf.pack(fill="x", pady=(0, 8))
        self._reg(gnd_lf, "ground_lf")

        gf = ttk.Frame(gnd_lf)
        gf.pack(anchor="w")

        self._cond_lbl = ttk.Label(gf)
        self._cond_lbl.grid(row=0, column=0, sticky="w", pady=3)
        self._reg(self._cond_lbl, "conductivity")

        self._ground_cond_var = tk.StringVar(value="0.005")
        ttk.Entry(gf, textvariable=self._ground_cond_var, width=10).grid(
            row=0, column=1, padx=6, pady=3)

        self._cond_unit_lbl = ttk.Label(gf, style="Muted.TLabel")
        self._cond_unit_lbl.grid(row=0, column=2, sticky="w")
        self._reg(self._cond_unit_lbl, "cond_unit")

        self._perm_lbl = ttk.Label(gf)
        self._perm_lbl.grid(row=1, column=0, sticky="w", pady=3)
        self._reg(self._perm_lbl, "permittivity")

        self._ground_diel_var = tk.StringVar(value="13.0")
        ttk.Entry(gf, textvariable=self._ground_diel_var, width=10).grid(
            row=1, column=1, padx=6, pady=3)

        self._perm_hint_lbl = ttk.Label(gf, style="Muted.TLabel")
        self._perm_hint_lbl.grid(row=1, column=2, sticky="w")
        self._reg(self._perm_hint_lbl, "perm_hint")

        # Quick presets
        presets_frame = ttk.Frame(gnd_lf)
        presets_frame.pack(anchor="w", pady=(4, 0))

        self._presets_prefix_lbl = ttk.Label(presets_frame, style="Muted.TLabel")
        self._presets_prefix_lbl.pack(side="left")
        self._reg(self._presets_prefix_lbl, "quick_presets")

        PRESETS = [
            ("preset_poor",  "0.001", "5"),
            ("preset_avg",   "0.005", "13"),
            ("preset_good",  "0.010", "20"),
            ("preset_excel", "0.030", "25"),
            ("preset_salt",  "5.000", "80"),
        ]
        self._preset_btns = []
        for key, cond, diel in PRESETS:
            btn = ttk.Button(presets_frame, style="Browse.TButton",
                             command=lambda c=cond, d=diel: (
                                 self._ground_cond_var.set(c),
                                 self._ground_diel_var.set(d)))
            btn.pack(side="left", padx=(6, 0))
            self._preset_btns.append((btn, key))
            self._reg(btn, key)

        # Misc flags
        misc_lf = ttk.LabelFrame(t, padding=8)
        misc_lf.pack(fill="x", pady=(0, 8))
        self._reg(misc_lf, "misc_lf")

        self._quiet_var       = tk.BooleanVar(value=True)
        self._no_interact_var = tk.BooleanVar(value=True)

        self._cb_quiet = ttk.Checkbutton(misc_lf, variable=self._quiet_var)
        self._cb_quiet.pack(anchor="w")
        self._reg(self._cb_quiet, "quiet_flag")

        self._cb_no_interact = ttk.Checkbutton(misc_lf, variable=self._no_interact_var)
        self._cb_no_interact.pack(anchor="w")
        self._reg(self._cb_no_interact, "no_interact")

    # ── Tab: Output Files ─────────────────────────────────────────────────

    def _build_tab_output(self):
        t = self._tab_output

        wd_lf = ttk.LabelFrame(t, padding=8)
        wd_lf.pack(fill="x", pady=(0, 8))
        self._reg(wd_lf, "workdir_lf")

        wdf = ttk.Frame(wd_lf)
        wdf.pack(fill="x")

        self._outdir_lbl = ttk.Label(wdf)
        self._outdir_lbl.pack(side="left")
        self._reg(self._outdir_lbl, "outdir_label")

        self._outdir_var = tk.StringVar(value=str(Path.home()))
        ttk.Entry(wdf, textvariable=self._outdir_var, width=52).pack(side="left", padx=4)

        self._browse_outdir_btn = ttk.Button(wdf, style="Browse.TButton",
                                              command=self._browse_outdir)
        self._browse_outdir_btn.pack(side="left")
        self._reg(self._browse_outdir_btn, "browse")

        self._workdir_hint_lbl = ttk.Label(wd_lf, style="Muted.TLabel")
        self._workdir_hint_lbl.pack(anchor="w", pady=(2, 0))
        self._reg(self._workdir_hint_lbl, "workdir_hint")

        of_lf = ttk.LabelFrame(t, padding=8)
        of_lf.pack(fill="x", pady=(0, 8))
        self._reg(of_lf, "outfiles_lf")

        self._out_txt_var = tk.StringVar(value="optimizer_report.txt")
        self._out_png_var = tk.StringVar(value="optimizer_plot.png")
        self._out_csv_var = tk.StringVar(value="optimizer_best.csv")
        self._out_nec_var = tk.StringVar(value="best_antenna.nec")
        self._out_rad_var = tk.StringVar(value="radiation_diagrams.png")

        out_rows = [
            ("out-txt:",       self._out_txt_var, "hint_out_txt"),
            ("out-png:",       self._out_png_var, "hint_out_png"),
            ("out-csv:",       self._out_csv_var, "hint_out_csv"),
            ("out-nec:",       self._out_nec_var, "hint_out_nec"),
            ("out-radiation:", self._out_rad_var, "hint_out_rad"),
        ]
        for row_i, (flag, var, hint_key) in enumerate(out_rows):
            ttk.Label(of_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
            ttk.Entry(of_lf, textvariable=var, width=30).grid(
                row=row_i, column=1, padx=6, pady=3, sticky="ew")
            hint_lbl = ttk.Label(of_lf, foreground=ACCENT)
            hint_lbl.grid(row=row_i, column=2, sticky="w", padx=(8, 0))
            self._reg(hint_lbl, hint_key)
            of_lf.columnconfigure(1, weight=1)

    # ── Tab: Run ──────────────────────────────────────────────────────────

    def _build_tab_run(self):
        t = self._tab_run

        # Command preview
        cmd_lf = ttk.LabelFrame(t, padding=8)
        cmd_lf.pack(fill="both", expand=True, pady=(0, 8))
        self._reg(cmd_lf, "cmd_preview_lf")

        self._cmd_text = tk.Text(cmd_lf, height=4, wrap="word", state="disabled",
                                  bg=ENTRY_BG, fg=FG, font=self._font("mono"),
                                  relief="solid", insertbackground=FG,
                                  highlightbackground=BORDER, highlightthickness=1)
        self._cmd_text.pack(fill="both", expand=True)

        self._refresh_btn = ttk.Button(cmd_lf, style="Browse.TButton",
                                        command=self._refresh_cmd)
        self._refresh_btn.pack(anchor="e", pady=(4, 0))
        self._reg(self._refresh_btn, "refresh_preview")

        # Run / Stop buttons
        btn_frame = ttk.Frame(t)
        btn_frame.pack(fill="x", pady=(0, 8))

        self._run_btn = ttk.Button(btn_frame, style="Accent.TButton", command=self._run)
        self._run_btn.pack(side="left", padx=(0, 10))
        self._reg(self._run_btn, "run_btn")

        self._stop_btn = ttk.Button(btn_frame, style="Stop.TButton",
                                     command=self._stop, state="disabled")
        self._stop_btn.pack(side="left")
        self._reg(self._stop_btn, "stop_btn")

        self._status_lbl = ttk.Label(btn_frame, foreground=FG2)
        self._status_lbl.pack(side="left", padx=16)
        self._reg_fn(lambda: self._status_lbl.config(text=self.t("idle"))
                     if self._status_lbl.cget("text") in
                        (STRINGS["en"]["idle"], STRINGS["es"]["idle"])
                     else None)

        # Progress bar
        self._progress = ttk.Progressbar(t, mode="indeterminate", length=400)
        self._progress.pack(fill="x", pady=(0, 8))

        # Console output
        con_lf = ttk.LabelFrame(t, padding=4)
        con_lf.pack(fill="both", expand=True)
        self._reg(con_lf, "console_lf")

        self._console = scrolledtext.ScrolledText(
            con_lf, wrap="none", state="disabled",
            bg=ENTRY_BG, fg=FG,
            font=self._font("mono"), relief="solid",
            insertbackground=FG,
            highlightbackground=BORDER, highlightthickness=1,
        )
        self._console.pack(fill="both", expand=True)
        self._console.tag_config("warn",  foreground=TAG_WARN)
        self._console.tag_config("error", foreground=TAG_ERR)
        self._console.tag_config("ok",    foreground=TAG_OK)
        self._console.tag_config("head",  foreground=TAG_HEAD)

        self._clear_btn = ttk.Button(con_lf, style="Browse.TButton",
                                      command=self._clear_console)
        self._clear_btn.pack(anchor="e", pady=(2, 0))
        self._reg(self._clear_btn, "clear_btn")

        # Initialise idle status label
        self._set_status_key("idle")
        self._refresh_cmd()

    # ── Browse helpers ────────────────────────────────────────────────────

    def _browse_script(self):
        p = filedialog.askopenfilename(
            title="Select nec2_length_optimizer.py",
            filetypes=[("Python script", "*.py"), ("All files", "*")],
        )
        if p:
            self._script_var.set(p)

    def _browse_csv(self):
        p = filedialog.askopenfilename(
            title="Select band CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*")],
        )
        if p:
            self._csv_var.set(p)

    def _browse_nec2c(self):
        p = filedialog.askopenfilename(
            title="Select nec2c binary",
            filetypes=[("Executable", "*"), ("All files", "*")],
        )
        if p:
            self._nec2c_var.set(p)

    def _auto_detect_nec2c(self):
        found = _find_nec2c()
        if found:
            self._nec2c_var.set(found)

    def _browse_outdir(self):
        p = filedialog.askdirectory(title="Select output directory")
        if p:
            self._outdir_var.set(p)

    # ── Command builder ───────────────────────────────────────────────────

    def _build_cmd(self) -> list:
        script = self._script_var.get().strip()
        if not script:
            raise ValueError("Optimizer script path is not set.")

        cmd = [sys.executable, script]

        # Band source
        if self._src_mode.get() == "csv":
            csv_p = self._csv_var.get().strip()
            if csv_p:
                cmd += ["--csv", csv_p]
        else:
            bands = self._bands_var.get().strip()
            if bands:
                cmd += ["--bands", bands]
            freqs = self._freqs_var.get().strip()
            if freqs:
                cmd += ["--freqs", freqs]
            wl = self._wire_len_var.get().strip()
            if wl:
                cmd += ["--wire-len", wl]
            cp = self._cp_len_var.get().strip()
            if cp:
                cmd += ["--cp-len", cp]

        ab = self._active_bands_var.get().strip()
        if ab:
            cmd += ["--active-bands", ab]

        unun = self._unun_var.get().strip()
        if unun:
            cmd += ["--unun", unun]

        cmd += ["--mode", self._mode_var.get()]

        nec2c = self._nec2c_var.get().strip()
        if nec2c:
            cmd += ["--nec2c", nec2c]

        margin = self._margin_var.get().strip()
        if margin:
            cmd += ["--margin", margin]

        for flag, var in (
            ("--wire-min",  self._wire_min_var),
            ("--wire-max",  self._wire_max_var),
            ("--wire-step", self._wire_step_var),
            ("--cp-min",    self._cp_min_var),
            ("--cp-max",    self._cp_max_var),
            ("--cp-step",   self._cp_step_var),
        ):
            v = var.get().strip()
            if v:
                cmd += [flag, v]

        retry = self._retry_var.get().strip()
        if retry and retry != "0":
            cmd += ["--retry", retry]

        topn = self._topn_var.get().strip()
        if topn:
            cmd += ["--top-n", topn]

        wh = self._wire_height_var.get().strip()
        if wh:
            cmd += ["--wire-height", wh]
        cph = self._cp_height_var.get().strip()
        if cph:
            cmd += ["--cp-height", cph]
        cmd += ["--cp-type", self._cp_type_var.get()]

        gc = self._ground_cond_var.get().strip()
        if gc:
            cmd += ["--ground-cond", gc]
        gd = self._ground_diel_var.get().strip()
        if gd:
            cmd += ["--ground-diel", gd]

        for flag, var in (
            ("--out-txt",       self._out_txt_var),
            ("--out-png",       self._out_png_var),
            ("--out-csv",       self._out_csv_var),
            ("--out-nec",       self._out_nec_var),
            ("--out-radiation", self._out_rad_var),
        ):
            v = var.get().strip()
            if v:
                cmd += [flag, v]

        if self._quiet_var.get():
            cmd += ["--quiet"]
        if self._no_interact_var.get():
            cmd += ["--no-interactive"]

        # Always pass the current GUI language to the optimizer
        cmd += ["--lang", self._ui_lang]

        return cmd

    def _refresh_cmd(self):
        try:
            cmd = self._build_cmd()
            display = " ".join(cmd)
        except Exception as e:
            display = f"(error building command: {e})"
        self._cmd_text.config(state="normal")
        self._cmd_text.delete("1.0", "end")
        self._cmd_text.insert("end", display)
        self._cmd_text.config(state="disabled")

    # ── Console helpers ───────────────────────────────────────────────────

    def _log(self, text: str, tag: str = ""):
        self._console.config(state="normal")
        if not tag:
            low = text.lower()
            if any(k in low for k in ("error", "failed", "✗", "traceback")):
                tag = "error"
            elif any(k in low for k in ("warning", "warn", "⚠")):
                tag = "warn"
            elif any(k in low for k in ("✓", "saved", "done", "★", "best")):
                tag = "ok"
            elif text.startswith("═") or text.startswith("──"):
                tag = "head"
        self._console.insert("end", text, tag)
        self._console.see("end")
        self._console.config(state="disabled")

    def _clear_console(self):
        self._console.config(state="normal")
        self._console.delete("1.0", "end")
        self._console.config(state="disabled")

    def _set_status_key(self, key: str, color: str = FG2, **kw):
        self._status_lbl.config(text=self.t(key, **kw), foreground=color)

    def _set_status_text(self, text: str, color: str = FG2):
        self._status_lbl.config(text=text, foreground=color)

    # ── Run / Stop ────────────────────────────────────────────────────────

    def _run(self):
        if self._running:
            return
        try:
            cmd = self._build_cmd()
        except ValueError as e:
            messagebox.showerror(self.t("cfg_err_title"), str(e))
            return

        script = self._script_var.get().strip()
        if not os.path.isfile(script):
            messagebox.showerror(
                self.t("script_nf_title"),
                self.t("script_nf_msg", script=script),
            )
            return

        self._refresh_cmd()
        self._clear_console()
        self._log(f"Command: {' '.join(cmd)}\n\n", "head")

        outdir = self._outdir_var.get().strip() or None
        if outdir and not os.path.isdir(outdir):
            try:
                os.makedirs(outdir, exist_ok=True)
            except Exception as e:
                messagebox.showerror(
                    self.t("dir_err_title"),
                    self.t("dir_err_msg", e=e),
                )
                return

        self._running = True
        self._run_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._progress.start(15)
        self._set_status_key("running", ACCENT)

        self._thread = threading.Thread(
            target=self._run_in_thread, args=(cmd, outdir), daemon=True
        )
        self._thread.start()

    def _run_in_thread(self, cmd: list, cwd: "str | None"):
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                bufsize=1,
            )
            for line in self._process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                self.after(0, self._log, clean)

            self._process.wait()
            rc = self._process.returncode
            if rc == 0:
                self.after(0, self._run_finished, True,
                           self.t("finished_ok"))
            else:
                self.after(0, self._run_finished, False,
                           self.t("exit_code", rc=rc))
        except Exception as e:
            self.after(0, self._run_finished, False,
                       self.t("thread_error", e=e))
        finally:
            self._process = None

    def _run_finished(self, success: bool, msg: str):
        self._running = False
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._progress.stop()
        color = ACCENT2 if success else ERR
        self._set_status_text(msg, color)
        self._log(f"\n{'─' * 60}\n{msg}\n", "ok" if success else "error")

        if success:
            outdir = self._outdir_var.get().strip() or os.getcwd()
            report = os.path.join(outdir, self._out_txt_var.get().strip())
            if os.path.isfile(report):
                if messagebox.askyesno(
                    self.t("done_title"),
                    self.t("done_msg", report=report),
                ):
                    self._open_file(report)

    def _stop(self):
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass
        self._set_status_key("stopped", WARN)
        self._running = False
        self._run_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._progress.stop()

    @staticmethod
    def _open_file(path: str):
        import platform
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
