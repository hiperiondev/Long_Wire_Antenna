#!/usr/bin/env python3
"""
=============================================================================
  NEC2 Antenna Length Optimizer
  Author: LU3VEA (CC0 v1.0)

  Searches for the optimal antenna wire length AND counterpoise length
  that minimise aggregate VSWR across all active bands defined in a CSV.

  For each candidate (wire_len, cp_len) pair the script:
    1. Writes a NEC2 .nec input deck  (horizontal CP + vertical CP)
    2. Runs nec2c to produce a .out file
    3. Parses the .out file internally
    4. Computes the aggregate score  (penalised VSWR, avoidance, CP delta)
    5. Tracks the Pareto-optimal candidates

  At the end it writes:
    • A ranked text report     (optimizer_report.txt)
    • A scatter plot PNG       (optimizer_plot.png)
    • A ready-to-use CSV       (optimizer_best.csv)

  Usage (with CSV):
    python nec2_length_optimizer.py --csv my_bands.csv [options]

  Usage (without CSV):
    # Known bands — --freqs is optional (centre frequency auto-resolved):
    python nec2_length_optimizer.py --bands 40m,20m,15m \\
        --wire-len 21.0 --cp-len 5.0 --unun 9 [options]

    # Custom/unknown bands — --freqs required:
    python nec2_length_optimizer.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \\
        --wire-len 21.0 --cp-len 5.0 --unun 9 [options]

  Active band selection:
    python nec2_length_optimizer.py --csv my_bands.csv --active-bands 40m,20m
    python nec2_length_optimizer.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \\
        --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0

  python nec2_length_optimizer.py --help

  NEC2C binary discovery (in order):
    1. --nec2c /path/to/nec2c      (explicit CLI flag)
    2. $NEC2C environment variable
    3. PATH  (nec2c, nec2c-mpich, xnec2c)
    4. Common install paths: /usr/bin, /usr/local/bin, /opt/nec2c/bin, etc.
    5. Interactive prompt (if --no-interactive is NOT set)
=============================================================================
"""

import os
import re
import sys
import csv
import math
import shutil
import argparse
import textwrap
import tempfile
import subprocess
import itertools
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── optional pretty-printing ──────────────────────────────────────────────
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

try:
    from colorama import Fore, Style, init as _cinit
    _cinit(autoreset=True)
    HAS_COLOR = True
except ImportError:
    class _C:
        RED = YELLOW = GREEN = CYAN = MAGENTA = BLUE = WHITE = BRIGHT = RESET_ALL = ""
    Fore = Style = _C()
    HAS_COLOR = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from mpl_toolkits.mplot3d import Axes3D          # noqa: F401 – registers '3d' projection
    import matplotlib.cm as _mpl_cm
    import matplotlib.colors as _mpl_colors
    # colormaps registry: available as matplotlib.cm.colormaps (≥3.7) or
    # matplotlib.colormaps (≥3.5); fall back to get_cmap for older installs.
    if not hasattr(_mpl_cm, "colormaps"):
        import matplotlib as _matplotlib
        if hasattr(_matplotlib, "colormaps"):
            _mpl_cm.colormaps = _matplotlib.colormaps
        else:
            class _CmapShim:
                def __getitem__(self, name): return _mpl_cm.get_cmap(name)
            _mpl_cm.colormaps = _CmapShim()
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ═══════════════════════════════════════════════════════════════════════════
# INTERNATIONALISATION  (i18n)
# ═══════════════════════════════════════════════════════════════════════════
#
# Language is resolved at startup via:
#   1. --lang {en|es}  CLI flag  (highest priority)
#   2. System locale  (LC_ALL / LC_MESSAGES / LANG environment variables)
#   3. Default: English
#
# All user-visible text goes through  T("key")  which returns the string
# for the active language.  Positional format-string placeholders ({0}, {1})
# are supported:  T("key").format(val1, val2)
# ─────────────────────────────────────────────────────────────────────────

import locale as _locale

_LANG = "en"   # module-level; set by _init_lang() in main()

def _detect_locale_lang() -> str:
    """Return 'es' if the system locale looks Spanish, else 'en'."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var, "")
        if val:
            code = val.lower().split(".")[0].split("@")[0]
            if code.startswith("es"):
                return "es"
            if code[:2] in ("en", "fr", "de", "pt", "it", "nl", "pl", "ru",
                            "zh", "ja", "ko", "ar", "tr"):
                return "en"   # any other explicit non-Spanish → English
    try:
        loc = _locale.getlocale()[0] or ""
        if loc.lower().startswith("es"):
            return "es"
    except Exception:
        pass
    return "en"

def _init_lang(lang_arg: str = "") -> None:
    """Set the active language.  Call once from main() after arg-parse."""
    global _LANG
    if lang_arg in ("en", "es"):
        _LANG = lang_arg
    else:
        _LANG = _detect_locale_lang()

# ── Translation catalogue ─────────────────────────────────────────────────

_STRINGS: Dict[str, Dict[str, str]] = {
    # ── startup banner ───────────────────────────────────────────────────
    "banner_title": {
        "en": "NEC2 Antenna Length Optimizer",
        "es": "Optimizador de Longitud de Antena NEC2",
    },
    # ── nec2c discovery ──────────────────────────────────────────────────
    "nec2c_not_found_path": {
        "en": "  --nec2c path not found or not executable: {0}",
        "es": "  La ruta --nec2c no existe o no es ejecutable: {0}",
    },
    "nec2c_found_env": {
        "en": "  nec2c found via $NEC2C → {0}",
        "es": "  nec2c encontrado vía $NEC2C → {0}",
    },
    "nec2c_found_path": {
        "en": "  nec2c found on PATH → {0}",
        "es": "  nec2c encontrado en PATH → {0}",
    },
    "nec2c_found": {
        "en": "  nec2c found → {0}",
        "es": "  nec2c encontrado → {0}",
    },
    "nec2c_not_found_auto": {
        "en": "  nec2c binary not found automatically.",
        "es": "  El binario nec2c no se encontró automáticamente.",
    },
    "nec2c_options": {
        "en": "  Options:",
        "es": "  Opciones:",
    },
    "nec2c_install_apt": {
        "en": "    • Install:  sudo apt install nec2c   (Debian/Ubuntu)",
        "es": "    • Instalar: sudo apt install nec2c   (Debian/Ubuntu)",
    },
    "nec2c_install_brew": {
        "en": "    •           brew install nec2c        (macOS / Homebrew)",
        "es": "    •           brew install nec2c        (macOS / Homebrew)",
    },
    "nec2c_rerun": {
        "en": "    • Re-run with:  --nec2c /full/path/to/nec2c",
        "es": "    • Ejecutar con: --nec2c /ruta/completa/a/nec2c",
    },
    "nec2c_env": {
        "en": "    • Set env var:  export NEC2C=/full/path/to/nec2c",
        "es": "    • Variable env: export NEC2C=/ruta/completa/a/nec2c",
    },
    "nec2c_prompt": {
        "en": "  Enter path to nec2c binary (or press Enter to skip NEC2 runs): ",
        "es": "  Ingrese la ruta al binario nec2c (o Enter para omitir NEC2): ",
    },
    "nec2c_bad_path": {
        "en": "  Path not found or not executable: {0}",
        "es": "  Ruta no encontrada o no ejecutable: {0}",
    },
    "nec2c_fallback_empirical": {
        "en": "  nec2c not found — falling back to empirical mode.",
        "es": "  nec2c no encontrado — cambiando a modo empírico.",
    },
    "nec2c_required": {
        "en": "  --mode nec2 requires nec2c binary.  Use --nec2c PATH or install nec2c.",
        "es": "  --mode nec2 requiere el binario nec2c.  Use --nec2c RUTA o instale nec2c.",
    },
    # ── CSV loading ──────────────────────────────────────────────────────
    "csv_not_found": {
        "en": "  CSV not found: {0}",
        "es": "  Archivo CSV no encontrado: {0}",
    },
    "csv_format_european": {
        "en": "  CSV format    : European locale (';' sep, ',' decimal) — normalised",
        "es": "  Formato CSV   : Localización europea (sep ';', dec ',') — normalizado",
    },
    "csv_format_standard": {
        "en": "  CSV format    : standard (',' sep, '.' decimal)",
        "es": "  Formato CSV   : estándar (sep ',', dec '.')",
    },
    "csv_locale_detection_failed": {
        "en": "  CSV locale detection failed ({0}); trying direct load.",
        "es": "  Detección de localización CSV fallida ({0}); cargando directamente.",
    },
    "csv_loading": {
        "en": "  Loading CSV: {0}",
        "es": "  Cargando CSV: {0}",
    },
    "csv_load_failed": {
        "en": "  Failed to load CSV: {0}",
        "es": "  Error al cargar CSV: {0}",
    },
    "csv_missing_cols": {
        "en": "  CSV is missing recommended columns: {0}",
        "es": "  El CSV no tiene las columnas recomendadas: {0}",
    },
    "csv_missing_cols2": {
        "en": "   Script will continue but some comparisons may be limited.",
        "es": "   El script continuará pero algunas comparaciones pueden ser limitadas.",
    },
    # ── CLI errors ───────────────────────────────────────────────────────
    "err_no_csv": {
        "en": "  ERROR: --csv was not provided.  The following arguments are required:",
        "es": "  ERROR: No se proporcionó --csv.  Los siguientes argumentos son requeridos:",
    },
    "err_supply_csv_or_args": {
        "en": "  Supply --csv OR all of the arguments above.",
        "es": "  Proporcione --csv O todos los argumentos anteriores.",
    },
    "err_freqs_nonnumeric": {
        "en": "  ERROR: --freqs contains a non-numeric value: {0}",
        "es": "  ERROR: --freqs contiene un valor no numérico: {0}",
    },
    "err_bands_freqs_mismatch": {
        "en": "  ERROR: --bands has {0} entries but --freqs has {1} entries.  They must match one-to-one.",
        "es": "  ERROR: --bands tiene {0} entradas pero --freqs tiene {1}.  Deben coincidir uno a uno.",
    },
    "freqs_explicit": {
        "en": "  Frequencies   : explicit via --freqs",
        "es": "  Frecuencias   : explícitas vía --freqs",
    },
    "err_unknown_bands": {
        "en": "  ERROR: --freqs was not supplied and the following band name(s) are not in the built-in frequency table:",
        "es": "  ERROR: no se suministró --freqs y los siguientes nombres de banda no están en la tabla integrada:",
    },
    "known_bands": {
        "en": "  Known bands: {0}",
        "es": "  Bandas conocidas: {0}",
    },
    "supply_freqs": {
        "en": "  Supply --freqs with one frequency per band to use custom names.",
        "es": "  Proporcione --freqs con una frecuencia por banda para usar nombres personalizados.",
    },
    "freqs_auto": {
        "en": "  Frequencies   : auto-resolved from band names (use --freqs to override)",
        "es": "  Frecuencias   : resueltas automáticamente de los nombres de banda (use --freqs para anular)",
    },
    "warn_active_bands_unknown": {
        "en": "  ⚠  --active-bands contains names not in --bands: {0}.  They will be ignored.",
        "es": "  ⚠  --active-bands contiene nombres que no están en --bands: {0}.  Se ignorarán.",
    },
    "band_source_cli": {
        "en": "  Band source   : command-line (no CSV)",
        "es": "  Fuente de bandas: línea de comandos (sin CSV)",
    },
    "bands_defined": {
        "en": "  Bands defined : {0}  ({1})",
        "es": "  Bandas definidas: {0}  ({1})",
    },
    "warn_active_bands_not_in_csv": {
        "en": "  ⚠  --active-bands contains names not in CSV: {0}.  They will be ignored.",
        "es": "  ⚠  --active-bands contiene nombres que no están en el CSV: {0}.  Se ignorarán.",
    },
    "active_bands_overridden": {
        "en": "  Active bands  : overridden by --active-bands → {0}",
        "es": "  Bandas activas: reemplazadas por --active-bands → {0}",
    },
    "no_active_bands": {
        "en": "  No active bands found.  Set the 'active' column to YES in the CSV, or use --active-bands,  or omit --active-bands to activate all --bands.",
        "es": "  No se encontraron bandas activas.  Establezca la columna 'active' en SÍ en el CSV, o use --active-bands, u omita --active-bands para activar todas las --bands.",
    },
    "active_bands": {
        "en": "  Active bands  : {0} of {1}  ({2})",
        "es": "  Bandas activas: {0} de {1}  ({2})",
    },
    "frequencies": {
        "en": "  Frequencies   : {0}",
        "es": "  Frecuencias   : {0}",
    },
    # ── UnUn prompts ─────────────────────────────────────────────────────
    "err_no_unun": {
        "en": "  No --unun supplied and no CSV to read it from.  Use --unun RATIO (e.g. --unun 9).",
        "es": "  No se proporcionó --unun y no hay CSV de donde leerlo.  Use --unun RELACION (ej: --unun 9).",
    },
    "unun_prompt": {
        "en": "  UnUn ratio (e.g. 9 for 9:1) [9]: ",
        "es": "  Relación UnUn (ej. 9 para 9:1) [9]: ",
    },
    "unun_from_csv": {
        "en": "  UnUn ratio    : {0:.1f}:1  (from CSV)",
        "es": "  Relación UnUn : {0:.1f}:1  (del CSV)",
    },
    "err_no_unun_in_csv": {
        "en": "  No unun_ratio in CSV; supply --unun.",
        "es": "  No hay unun_ratio en el CSV; proporcione --unun.",
    },
    "err_multiple_unun": {
        "en": "  Multiple unun_ratio values in CSV ({0}). Supply --unun explicitly.",
        "es": "  Hay múltiples valores unun_ratio en el CSV ({0}). Proporcione --unun explícitamente.",
    },
    "unun_multi_prompt": {
        "en": "  Multiple UnUn values in CSV {0}.  Which to use? [{1}]: ",
        "es": "  Múltiples valores UnUn en el CSV {0}.  ¿Cuál usar? [{1}]: ",
    },
    "unun_ratio": {
        "en": "  UnUn ratio    : {0:.1f}:1",
        "es": "  Relación UnUn : {0:.1f}:1",
    },
    # ── search range / grid ──────────────────────────────────────────────
    "search_margin": {
        "en": "  Search margin : ±{0} m around {1} wire {2:.3f} m  (use --margin to change)",
        "es": "  Margen búsqueda: ±{0} m alrededor del hilo {1} de {2:.3f} m  (use --margin para cambiar)",
    },
    "wire_min": {
        "en": "  --wire-min    : {0} m",
        "es": "  --wire-min    : {0} m",
    },
    "wire_max": {
        "en": "  --wire-max    : {0} m",
        "es": "  --wire-max    : {0} m",
    },
    "cp_margin": {
        "en": "  CP margin     : ±{0} m around {1} CP {2:.3f} m  (use --margin to change)",
        "es": "  Margen CP     : ±{0} m alrededor del CP {1} de {2:.3f} m  (use --margin para cambiar)",
    },
    "cp_min": {
        "en": "  --cp-min      : {0} m",
        "es": "  --cp-min      : {0} m",
    },
    "cp_max": {
        "en": "  --cp-max      : {0} m",
        "es": "  --cp-max      : {0} m",
    },
    "wire_height": {
        "en": "  --wire-height : {0} m  {1}",
        "es": "  --wire-height : {0} m  {1}",
    },
    "wire_height_from_csv": {
        "en": "(from CSV)",
        "es": "(del CSV)",
    },
    "wire_height_default": {
        "en": "(default; use --wire-height to override)",
        "es": "(valor por defecto; use --wire-height para anular)",
    },
    "cp_height": {
        "en": "  --cp-height   : {0} m  {1}",
        "es": "  --cp-height   : {0} m  {1}",
    },
    "cp_height_from_csv": {
        "en": "(from CSV)",
        "es": "(del CSV)",
    },
    "cp_height_default": {
        "en": "(default; use --cp-height to override)",
        "es": "(valor por defecto; use --cp-height para anular)",
    },
    "grid_size": {
        "en": "  Grid size     : {0} (wire) × (cp) pairs",
        "es": "  Tamaño grilla : {0} pares (hilo) × (CP)",
    },
    "cp_types": {
        "en": "  CP types      : {0}",
        "es": "  Tipos CP      : {0}",
    },
    # ── sweep progress ───────────────────────────────────────────────────
    "sweep_starting": {
        "en": "  Starting {0} sweep …",
        "es": "  Iniciando barrido {0} …",
    },
    "sweep_empirical_pct": {
        "en": "  Empirical sweep {0:3d}% ({1}/{2})  w={3:.2f} m  cp={4:.2f} m",
        "es": "  Barrido empírico {0:3d}% ({1}/{2})  h={3:.2f} m  cp={4:.2f} m",
    },
    "sweep_empirical_done": {
        "en": "  Empirical sweep 100% ({0}/{0}) — done.         ",
        "es": "  Barrido empírico 100% ({0}/{0}) — completado.  ",
    },
    "sweep_nec2_progress": {
        "en": "  NEC2 {0:4d}/{1}  wire={2:.2f} m  cp={3:.2f} m  ({4})",
        "es": "  NEC2 {0:4d}/{1}  hilo={2:.2f} m  cp={3:.2f} m  ({4})",
    },
    "sweep_nec2_done": {
        "en": "  NEC2 sweep complete. {0} runs processed.           ",
        "es": "  Barrido NEC2 completado. {0} ejecuciones procesadas.",
    },
    "warn_nec2_failed_cp": {
        "en": "  ⚠  NEC2 failed for {0} CP at wire={1:.3f} m / cp={2:.3f} m — only {3} orientation scored.",
        "es": "  ⚠  NEC2 falló para CP {0} en hilo={1:.3f} m / cp={2:.3f} m — solo orientación {3} evaluada.",
    },
    "warn_empirical_cp_forced": {
        "en": "  Note: empirical model ignores CP geometry for VSWR; cp_type forced to 'horizontal' for the cp-avoidance label (CP length avoidance is still evaluated for all bands).",
        "es": "  Nota: el modelo empírico ignora la geometría del CP para VSWR; cp_type forzado a 'horizontal' (la evaluación de evitación de CP sigue activa para todas las bandas).",
    },
    "sweep_complete": {
        "en": "  Sweep complete.  {0} candidates evaluated.",
        "es": "  Barrido completado.  {0} candidatos evaluados.",
    },
    "pareto_count": {
        "en": "  Pareto-optimal candidates: {0}",
        "es": "  Candidatos Pareto-óptimos: {0}",
    },
    # ── best candidate display ───────────────────────────────────────────
    "best_candidate": {
        "en": "★ BEST CANDIDATE:",
        "es": "★ MEJOR CANDIDATO:",
    },
    "combined_score": {
        "en": "    Combined score  = {0:.4f}",
        "es": "    Puntuación comb.= {0:.4f}",
    },
    "vswr_penalty": {
        "en": "    VSWR penalty    = {0:.4f}",
        "es": "    Penalización ROS= {0:.4f}",
    },
    "avoidance_mean": {
        "en": "    Avoidance mean  = {0:.4f}",
        "es": "    Evitación media = {0:.4f}",
    },
    # ── boundary warnings ────────────────────────────────────────────────
    "warn_wire_at_max": {
        "en": "⚠  WIRE LENGTH at search maximum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be longer. Re-run with a larger --wire-max or increase --margin.",
        "es": "⚠  LONGITUD DE HILO en el máximo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser mayor. Re-ejecute con --wire-max mayor o aumente --margin.",
    },
    "warn_wire_at_min": {
        "en": "⚠  WIRE LENGTH at search minimum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be shorter. Re-run with a smaller --wire-min or increase --margin.",
        "es": "⚠  LONGITUD DE HILO en el mínimo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser menor. Re-ejecute con --wire-min menor o aumente --margin.",
    },
    "warn_cp_at_max": {
        "en": "⚠  CP LENGTH at search maximum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be longer. Re-run with a larger --cp-max or increase --margin.",
        "es": "⚠  LONGITUD CP en el máximo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser mayor. Re-ejecute con --cp-max mayor o aumente --margin.",
    },
    "warn_cp_at_min": {
        "en": "⚠  CP LENGTH at search minimum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be shorter. Re-run with a smaller --cp-min or increase --margin.",
        "es": "⚠  LONGITUD CP en el mínimo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser menor. Re-ejecute con --cp-min menor o aumente --margin.",
    },
    # ── retry messages ──────────────────────────────────────────────────
    "retry_wire_expanding_max": {
        "en": "  🔁  --retry: wire boundary at maximum — expanding upper bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite de hilo en máximo — expandiendo límite superior a {0:.3f} m (reintento {1}/{2})",
    },
    "retry_wire_expanding_min": {
        "en": "  🔁  --retry: wire boundary at minimum — expanding lower bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite de hilo en mínimo — expandiendo límite inferior a {0:.3f} m (reintento {1}/{2})",
    },
    "retry_cp_expanding_max": {
        "en": "  🔁  --retry: CP boundary at maximum — expanding upper bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite CP en máximo — expandiendo límite superior a {0:.3f} m (reintento {1}/{2})",
    },
    "retry_cp_expanding_min": {
        "en": "  🔁  --retry: CP boundary at minimum — expanding lower bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite CP en mínimo — expandiendo límite inferior a {0:.3f} m (reintento {1}/{2})",
    },
    "retry_new_best": {
        "en": "  ✔  --retry: new best after retry — wire = {0:.3f} m   cp = {1:.3f} m   score = {2:.4f}",
        "es": "  ✔  --retry: nuevo mejor tras reintento — hilo = {0:.3f} m   cp = {1:.3f} m   puntuación = {2:.4f}",
    },
    "retry_no_improvement": {
        "en": "  ℹ  --retry: no improvement found — keeping previous best (wire = {0:.3f} m, cp = {1:.3f} m).",
        "es": "  ℹ  --retry: sin mejora encontrada — manteniendo mejor previo (hilo = {0:.3f} m, cp = {1:.3f} m).",
    },
    "retry_converged": {
        "en": "  ✔  --retry: boundary no longer hit — converged after {0} retry(s).",
        "es": "  ✔  --retry: límite ya no alcanzado — convergido tras {0} reintento(s).",
    },
    # ── impedance table header ───────────────────────────────────────────
    "impedance_header": {
        "en": "  Impedance — antenna side & transmitter side (UnUn {0:.0f}:1):",
        "es": "  Impedancia — lado antena y lado transmisor (UnUn {0:.0f}:1):",
    },
    # ── UnUn analysis display ────────────────────────────────────────────
    "optimising_unun": {
        "en": "  Optimising UnUn ratio for best geometry …",
        "es": "  Optimizando relación UnUn para la mejor geometría …",
    },
    "unun_analysis_header": {
        "en": "  UnUn Analysis (best geometry: {0:.3f} m / {1:.3f} m):",
        "es": "  Análisis UnUn (mejor geometría: {0:.3f} m / {1:.3f} m):",
    },
    "unun_current": {
        "en": "    Current ratio    : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Relación actual  : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
    },
    "unun_best_std": {
        "en": "    Best standard    : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Mejor estándar   : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
    },
    "unun_continuous": {
        "en": "    Continuous opt.  : {0:.2f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Óptimo continuo  : {0:.2f}:1  (penalización ROS agregada {1:.4f})",
    },
    "unun_switch_recommend": {
        "en": "    → Consider switching to {0:.0f}:1 UnUn for better match.",
        "es": "    → Considere cambiar a UnUn {0:.0f}:1 para mejor adaptación.",
    },
    "unun_current_optimal": {
        "en": "    → Current {0:.0f}:1 is optimal among standard ratios.",
        "es": "    → La relación actual {0:.0f}:1 es óptima entre las estándar.",
    },
    # ── output files ─────────────────────────────────────────────────────
    "writing_outputs": {
        "en": "  Writing outputs …",
        "es": "  Escribiendo resultados …",
    },
    "report_saved": {
        "en": "  📄  Report saved → {0}",
        "es": "  📄  Informe guardado → {0}",
    },
    "csv_best_saved": {
        "en": "  📋  Best-candidate CSV → {0}  (UnUn {1:.0f}:1)",
        "es": "  📋  CSV mejor candidato → {0}  (UnUn {1:.0f}:1)",
    },
    "csv_export_recommended_unun": {
        "en": "  ℹ  CSV export uses recommended UnUn {0:.0f}:1 (instead of {1:.0f}:1)",
        "es": "  ℹ  CSV exportado usa UnUn recomendado {0:.0f}:1 (en vez de {1:.0f}:1)",
    },
    "warn_rankings_unun": {
        "en": "  ⚠  Rankings above were computed with {0:.0f}:1 UnUn.",
        "es": "  ⚠  Las clasificaciones anteriores se calcularon con UnUn {0:.0f}:1.",
    },
    "rerun_with_unun": {
        "en": "     Re-run with --unun {0:.0f} to rank candidates under the recommended ratio.",
        "es": "     Re-ejecute con --unun {0:.0f} para clasificar candidatos con la relación recomendada.",
    },
    "radiation_generating": {
        "en": "  Generating radiation diagrams (full RP sweep) …",
        "es": "  Generando diagramas de radiación (barrido RP completo) …",
    },
    "radiation_nec2_only": {
        "en": "  ℹ  Radiation diagrams require NEC2 mode (current mode: {0}) — skipped.",
        "es": "  ℹ  Los diagramas de radiación requieren modo NEC2 (modo actual: {0}) — omitido.",
    },
    "radiation_saved": {
        "en": "  📻  Radiation diagrams saved → {0}",
        "es": "  📻  Diagramas de radiación guardados → {0}",
    },
    "plot_saved": {
        "en": "  📊  Optimizer plot saved → {0}",
        "es": "  📊  Gráfico del optimizador guardado → {0}",
    },
    "matplotlib_missing": {
        "en": "  matplotlib not available — skipping plot.",
        "es": "  matplotlib no disponible — omitiendo gráfico.",
    },
    "done": {
        "en": "  Done.",
        "es": "  Listo.",
    },
    # ── radiation pattern warnings ───────────────────────────────────────
    "warn_no_rp_data": {
        "en": "  ⚠  No radiation pattern data parsed — check NEC2 output format.",
        "es": "  ⚠  No se parsearon datos de patrón de radiación — verifique el formato de salida de NEC2.",
    },
    "warn_no_rp_freq": {
        "en": "  ⚠  No parsed RP freq within 0.5 MHz of {0:.4f} MHz — skipping {1}.",
        "es": "  ⚠  Sin frecuencia RP parseada a 0.5 MHz de {0:.4f} MHz — omitiendo {1}.",
    },
    "warn_no_rp_bands": {
        "en": "  ⚠  No bands produced usable radiation pattern data — skipping plot.",
        "es": "  ⚠  Ninguna banda produjo datos de patrón utilizables — omitiendo gráfico.",
    },
    # ── plot labels ──────────────────────────────────────────────────────
    "plot_title": {
        "en": "NEC2 Antenna Length Optimizer Results",
        "es": "Resultados del Optimizador de Antena NEC2",
    },
    "plot_colorbar": {
        "en": "Combined score (lower=better)",
        "es": "Puntuación combinada (menor=mejor)",
    },
    "plot_pareto_label": {
        "en": "Pareto front",
        "es": "Frente de Pareto",
    },
    "plot_best_label": {
        "en": "Best",
        "es": "Mejor",
    },
    "plot_xlabel_wire": {
        "en": "Wire length (m)",
        "es": "Longitud de hilo (m)",
    },
    "plot_ylabel_cp": {
        "en": "Counterpoise length (m)",
        "es": "Longitud de contrapeso (m)",
    },
    "plot_heatmap_title": {
        "en": "Combined Score Heat Map",
        "es": "Mapa de calor de puntuación combinada",
    },
    "plot_vswr_xlabel": {
        "en": "VSWR penalty mean+1.5×worst (lower=better)",
        "es": "Penalización ROS media+1.5×peor (menor=mejor)",
    },
    "plot_avoidance_ylabel": {
        "en": "Active-band avoidance (higher=better)",
        "es": "Evitación banda activa (mayor=mejor)",
    },
    "plot_pareto_title": {
        "en": "Pareto Space (active bands)",
        "es": "Espacio de Pareto (bandas activas)",
    },
    "plot_vswr_ylabel": {
        "en": "VSWR (Tx side)",
        "es": "ROS (lado Tx)",
    },
    "plot_dB_norm": {
        "en": "dB (normalised)",
        "es": "dB (normalizado)",
    },
    "plot_azimuth": {
        "en": "{0} Azimuth\n{1}",
        "es": "{0} Azimut\n{1}",
    },
    "plot_radiation_title": {
        "en": "Radiation Diagrams — Wire {0:.2f} m / CP {1:.2f} m ({2})",
        "es": "Diagramas de Radiación — Hilo {0:.2f} m / CP {1:.2f} m ({2})",
    },
    # ── report strings ───────────────────────────────────────────────────
    "report_title": {
        "en": "NEC2 ANTENNA LENGTH OPTIMIZER REPORT",
        "es": "INFORME DEL OPTIMIZADOR DE LONGITUD DE ANTENA NEC2",
    },
    "report_mode": {
        "en": "Evaluation mode : {0}",
        "es": "Modo de evaluación: {0}",
    },
    "report_unun": {
        "en": "UnUn ratio      : {0:.1f}:1",
        "es": "Relación UnUn   : {0:.1f}:1",
    },
    "report_wire_range": {
        "en": "Wire range      : {0:.2f} m … {1:.2f} m  step {2:.3f} m",
        "es": "Rango de hilo   : {0:.2f} m … {1:.2f} m  paso {2:.3f} m",
    },
    "report_cp_range": {
        "en": "CP range        : {0:.2f} m … {1:.2f} m  step {2:.3f} m",
        "es": "Rango de CP     : {0:.2f} m … {1:.2f} m  paso {2:.3f} m",
    },
    "report_wire_geom_sloped_summary": {
        "en": "Wire geometry   : SLOPED  (far-end height = {0:.4f} m)",
        "es": "Geometría hilo  : SLOPED  (altura extremo lejano = {0:.4f} m)",
    },
    "report_wire_geom_horizontal": {
        "en": "Wire geometry   : horizontal (flat)",
        "es": "Geometría hilo  : horizontal (plano)",
    },
    "report_wire_geom_sloped_detail": {
        "en": "Wire geometry   : SLOPED  (feedpoint z={0:.3f} m → far end z={1:.4f} m)",
        "es": "Geometría hilo  : SLOPED  (punto alimentación z={0:.3f} m → extremo lejano z={1:.4f} m)",
    },
    "report_wire_geom_horizontal_const": {
        "en": "Wire geometry   : horizontal (flat, z = constant)",
        "es": "Geometría hilo  : horizontal (plano, z = constante)",
    },
    "report_active_bands": {
        "en": "Active bands    : {0} of {1}  ({2})  (* = scored for VSWR)",
        "es": "Bandas activas  : {0} de {1}  ({2})  (* = evaluadas para ROS)",
    },
    "report_total_candidates": {
        "en": "Total candidates: {0}",
        "es": "Total candidatos: {0}",
    },
    "report_top_n_header": {
        "en": "TOP {0} CANDIDATES  (lower combined score = better)",
        "es": "TOP {0} CANDIDATOS  (menor puntuación combinada = mejor)",
    },
    "report_pareto_header": {
        "en": "PARETO-OPTIMAL FRONT  ({0} candidates)",
        "es": "FRENTE PARETO-ÓPTIMO  ({0} candidatos)",
    },
    "report_pareto_note": {
        "en": "Candidates not dominated on both VSWR-penalty and avoidance score.",
        "es": "Candidatos no dominados en penalización ROS y puntuación de evitación.",
    },
    "report_best_header": {
        "en": "BEST CANDIDATE — DETAILED BREAKDOWN",
        "es": "MEJOR CANDIDATO — DESGLOSE DETALLADO",
    },
    "report_wire_len": {
        "en": "Wire length   : {0:.3f} m",
        "es": "Longitud hilo : {0:.3f} m",
    },
    "report_cp_len": {
        "en": "CP length     : {0:.3f} m   ({1} orientation)",
        "es": "Longitud CP   : {0:.3f} m   (orientación {1})",
    },
    "report_combined_score": {
        "en": "Combined score: {0:.4f}",
        "es": "Puntuación comb: {0:.4f}",
    },
    "report_vswr_penalty": {
        "en": "VSWR penalty  : {0:.4f}  (mean VSWR penalty across active bands; score_combined = mean + 1.5×worst − bonuses)",
        "es": "Penaliz. ROS  : {0:.4f}  (media de penalización ROS en bandas activas; score_combined = media + 1.5×peor − bonos)",
    },
    "report_avoidance_act": {
        "en": "Avoidance(act): {0:.4f}  (mean across ACTIVE bands — used in score_combined)",
        "es": "Evitación(act): {0:.4f}  (media en bandas ACTIVAS — usada en score_combined)",
    },
    "report_avoidance_all": {
        "en": "Avoidance(all): {0:.4f}  (mean across ALL bands in CSV — shown for reference)",
        "es": "Evitación(all): {0:.4f}  (media en TODAS las bandas del CSV — referencia)",
    },
    "report_nec2_used": {
        "en": "NEC2 data used: {0}",
        "es": "Datos NEC2 usados: {0}",
    },
    "report_nec2_yes": {
        "en": "YES",
        "es": "SÍ",
    },
    "report_nec2_no": {
        "en": "NO — empirical model only",
        "es": "NO — solo modelo empírico",
    },
    "report_warn_wire_max": {
        "en": "⚠  WIRE at search maximum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be longer.  Re-run with larger --wire-max or increase --margin.",
        "es": "⚠  HILO en el máximo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser mayor.  Re-ejecute con --wire-max mayor o aumente --margin.",
    },
    "report_warn_wire_min": {
        "en": "⚠  WIRE at search minimum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be shorter.  Re-run with smaller --wire-min or increase --margin.",
        "es": "⚠  HILO en el mínimo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser menor.  Re-ejecute con --wire-min menor o aumente --margin.",
    },
    "report_warn_cp_max": {
        "en": "⚠  CP at search maximum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be longer.  Re-run with larger --cp-max or increase --margin.",
        "es": "⚠  CP en el máximo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser mayor.  Re-ejecute con --cp-max mayor o aumente --margin.",
    },
    "report_warn_cp_min": {
        "en": "⚠  CP at search minimum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be shorter.  Re-run with smaller --cp-min or increase --margin.",
        "es": "⚠  CP en el mínimo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser menor.  Re-ejecute con --cp-min menor o aumente --margin.",
    },
    "report_per_band": {
        "en": "Per-band results:",
        "es": "Resultados por banda:",
    },
    "report_per_band_hdr": {
        "en": "  {'Band':>8}  {'Active':>6}  {'VSWR(Tx)':>9}  {'Avoid':>8}  {'Rating':>22}  {'VSWR label'}",
        "es": "  {'Banda':>8}  {'Activa':>6}  {'ROS(Tx)':>9}  {'Evit':>8}  {'Calificación':>22}  {'Etiqueta ROS'}",
    },
    "report_per_band_imp": {
        "en": "Per-band impedance (antenna side and transmitter side):",
        "es": "Impedancia por banda (lado antena y lado transmisor):",
    },
    "report_unun_note": {
        "en": "  (UnUn {0:.0f}:1 — antenna-side Z divided by {0:.0f} to give Tx-side Z)",
        "es": "  (UnUn {0:.0f}:1 — Z lado antena dividida por {0:.0f} para obtener Z lado Tx)",
    },
    "report_unun_section": {
        "en": "UnUn RATIO ANALYSIS  (for best antenna geometry)",
        "es": "ANÁLISIS DE RELACIÓN UnUn  (para la mejor geometría de antena)",
    },
    "report_unun_used": {
        "en": "Used UnUn ratio (this run) : {0:.1f}:1",
        "es": "Relación UnUn usada (esta ejecución): {0:.1f}:1",
    },
    "report_unun_cont_hit_upper": {
        "en": "  ⚠ HIT UPPER BOUND — true optimum may be >100:1",
        "es": "  ⚠ LÍMITE SUPERIOR ALCANZADO — el óptimo real puede ser >100:1",
    },
    "report_unun_cont_hit_lower": {
        "en": "  ⚠ HIT LOWER BOUND — try no transformer",
        "es": "  ⚠ LÍMITE INFERIOR ALCANZADO — pruebe sin transformador",
    },
    "report_unun_continuous": {
        "en": "Continuous optimum         : {0:.2f}:1  (aggregate VSWR penalty {1:.4f}){2}",
        "es": "Óptimo continuo            : {0:.2f}:1  (penalización ROS agregada {1:.4f}){2}",
    },
    "report_unun_best_std": {
        "en": "Best standard ratio        : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "Mejor relación estándar    : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
    },
    "report_unun_improve": {
        "en": "  → Switching to {0:.0f}:1 improves aggregate VSWR penalty by {1:.4f}  ({2:.1f} %)",
        "es": "  → Cambiar a {0:.0f}:1 mejora la penalización ROS agregada en {1:.4f}  ({2:.1f} %)",
    },
    "report_unun_rerank": {
        "en": "  ⚠  Rankings in this report were computed with {0:.0f}:1.",
        "es": "  ⚠  Las clasificaciones de este informe se calcularon con {0:.0f}:1.",
    },
    "report_unun_rerun": {
        "en": "     Re-run with --unun {0:.0f} to rank candidates under the recommended ratio.",
        "es": "     Re-ejecute con --unun {0:.0f} para clasificar candidatos con la relación recomendada.",
    },
    "report_unun_already_optimal": {
        "en": "  → Current ratio {0:.0f}:1 is already optimal among standard values.",
        "es": "  → La relación actual {0:.0f}:1 ya es óptima entre los valores estándar.",
    },
    "report_std_sweep": {
        "en": "Standard ratio sweep:",
        "es": "Barrido de relaciones estándar:",
    },
    "report_ant_impedance": {
        "en": "Antenna-side impedance (independent of UnUn ratio):",
        "es": "Impedancia lado antena (independiente de la relación UnUn):",
    },
    "report_perband_optimal": {
        "en": "Per-band optimal ratio (independent, continuous):",
        "es": "Relación óptima por banda (independiente, continua):",
    },
    "report_perband_conflict_note": {
        "en": "Note: per-band ratios optimise each band independently and may",
        "es": "Nota: las relaciones por banda optimizan cada banda de forma independiente y pueden",
    },
    "report_perband_conflict_note2": {
        "en": "      conflict with each other.  The aggregate score above is the",
        "es": "      entrar en conflicto entre sí.  La puntuación agregada anterior es la",
    },
    "report_perband_conflict_note3": {
        "en": "      correct metric for a single multi-band UnUn.",
        "es": "      métrica correcta para un UnUn multibanda único.",
    },
    "report_physical_header": {
        "en": "PHYSICAL INTERPRETATION",
        "es": "INTERPRETACIÓN FÍSICA",
    },
    "report_end": {
        "en": "END OF OPTIMIZER REPORT",
        "es": "FIN DEL INFORME DEL OPTIMIZADOR",
    },
    # ── physical interpretation notes ────────────────────────────────────
    "note1_title": {
        "en": "Wire length selection",
        "es": "Selección de longitud del hilo",
    },
    "note1_body": {
        "en": ("The optimal wire avoids landing on ANY multiple of λ/4 on ALL bands in the CSV"
               " simultaneously — including those marked inactive for VSWR scoring.  Resonances"
               " occur at every λ/4 step: λ/4 (low Z / current max), λ/2 (high Z / voltage max),"
               " 3λ/4 (low Z again), λ (high Z), etc.  The avoidance score is the fractional"
               " distance to the NEAREST λ/4 multiple across all bands;"
               " maximum achievable = 0.25 (midway between resonances) = ★★★ EXCELLENT."
               " Values below 0.06 flag RESONANCE RISK."),
        "es": ("El hilo óptimo evita caer en CUALQUIER múltiplo de λ/4 en TODAS las bandas del CSV"
               " simultáneamente — incluyendo las marcadas como inactivas para ROS.  Las resonancias"
               " ocurren en cada paso λ/4: λ/4 (Z baja / máx. corriente), λ/2 (Z alta / máx. voltaje),"
               " 3λ/4 (Z baja de nuevo), λ (Z alta), etc.  La puntuación de evitación es la distancia"
               " fraccional al múltiplo λ/4 MÁS CERCANO en todas las bandas;"
               " máximo alcanzable = 0.25 (punto medio entre resonancias) = ★★★ EXCELENTE."
               " Valores inferiores a 0.06 indican RIESGO DE RESONANCIA."),
    },
    "note2_title": {
        "en": "Counterpoise length selection",
        "es": "Selección de longitud del contrapeso",
    },
    "note2_body": {
        "en": ("The counterpoise acts as the missing half of the antenna system.  A length near"
               " λ/4 at the operating frequency (or an odd multiple thereof: 3λ/4, 5λ/4 …)"
               " provides a low-impedance return path and is actively rewarded by the optimizer."
               " Lengths near an even multiple of λ/4 (i.e. λ/2, λ, 3λ/2 …) produce a"
               " high-impedance return path and receive no reward.  This bonus is intentionally"
               " small relative to the VSWR term so that CP resonance can nudge a close pair of"
               " candidates but cannot override a poor VSWR match."),
        "es": ("El contrapeso actúa como la mitad faltante del sistema de antena.  Una longitud"
               " cercana a λ/4 en la frecuencia de operación (o un múltiplo impar: 3λ/4, 5λ/4 …)"
               " proporciona un camino de retorno de baja impedancia y es recompensado por el optimizador."
               " Longitudes cercanas a un múltiplo par de λ/4 (λ/2, λ, 3λ/2 …) producen un camino de"
               " retorno de alta impedancia y no reciben recompensa.  Este bono es intencionalmente"
               " pequeño respecto al término ROS para que la resonancia del CP pueda influir entre"
               " candidatos cercanos pero no anule una mala adaptación de ROS."),
    },
    "note3_title": {
        "en": "VSWR after UnUn",
        "es": "ROS después del UnUn",
    },
    "note3_body": {
        "en": ("All VSWR values shown are referred to the TRANSMITTER side (50 Ω coaxial)"
               " AFTER the {0:.0f}:1 UnUn.  The antenna-side impedance is divided"
               " by {0:.0f} before computing VSWR.  A well-chosen UnUn ratio can"
               " improve or worsen match: if VSWR is poor on every band consider trying"
               " 4:1 or 16:1 instead of {0:.0f}:1."),
        "es": ("Todos los valores de ROS mostrados corresponden al lado del TRANSMISOR (coaxial 50 Ω)"
               " DESPUÉS del UnUn {0:.0f}:1.  La impedancia del lado antena se divide"
               " por {0:.0f} antes de calcular el ROS.  Una relación UnUn bien elegida puede"
               " mejorar o empeorar la adaptación: si el ROS es pobre en todas las bandas,"
               " considere probar 4:1 o 16:1 en lugar de {0:.0f}:1."),
    },
    "note4_title": {
        "en": "NEC2 vs empirical",
        "es": "NEC2 vs. empírico",
    },
    "note4_body": {
        "en": ("When nec2c is available, the optimizer runs a full Sommerfeld-Norton ground"
               " simulation for each candidate.  Without NEC2, the empirical formulas"
               " R = 50·80^cos²(π·L/λ½) and X = 1500·sin(2π·L/λ½) are used.  The empirical"
               " model overestimates impedance accuracy near resonances; NEC2 results are"
               " always preferred.  Cross-validate with a VNA on the bench."),
        "es": ("Cuando nec2c está disponible, el optimizador ejecuta una simulación completa de"
               " tierra Sommerfeld-Norton para cada candidato.  Sin NEC2 se usan las fórmulas"
               " empíricas R = 50·80^cos²(π·L/λ½) y X = 1500·sin(2π·L/λ½).  El modelo empírico"
               " sobreestima la precisión de impedancia cerca de resonancias; los resultados NEC2"
               " siempre son preferidos.  Valide con un VNA en el banco."),
    },
    "note5_title": {
        "en": "Next steps",
        "es": "Próximos pasos",
    },
    "note5_body": {
        "en": ("1. Validate with a VNA before cutting the final wire."
               "  2. If VSWR > 3 on any priority band, try a different UnUn ratio or add"
               "   a second CP radial cut to λ/4 for that specific band."
               "  3. Re-run with a finer --wire-step / --cp-step around the best candidate"
               "   to refine the optimum within a narrower window."),
        "es": ("1. Valide con un VNA antes de cortar el hilo final."
               "  2. Si ROS > 3 en alguna banda prioritaria, pruebe una relación UnUn diferente"
               "   o agregue un segundo radial de CP cortado a λ/4 para esa banda específica."
               "  3. Re-ejecute con --wire-step / --cp-step más finos alrededor del mejor candidato"
               "   para refinar el óptimo en una ventana más estrecha."),
    },
    # ── avoidance ratings ────────────────────────────────────────────────
    "rating_excellent": {
        "en": "★★★ EXCELLENT",
        "es": "★★★ EXCELENTE",
    },
    "rating_good": {
        "en": "★★  GOOD",
        "es": "★★  BUENO",
    },
    "rating_marginal": {
        "en": "★   MARGINAL",
        "es": "★   MARGINAL",
    },
    "rating_risk": {
        "en": "✗   RESONANCE RISK",
        "es": "✗   RIESGO DE RESONANCIA",
    },
    # ── VSWR quality labels ──────────────────────────────────────────────
    "vswr_excellent": {
        "en": "EXCELLENT",
        "es": "EXCELENTE",
    },
    "vswr_good": {
        "en": "GOOD",
        "es": "BUENO",
    },
    "vswr_marginal": {
        "en": "MARGINAL",
        "es": "MARGINAL",
    },
    "vswr_poor": {
        "en": "POOR",
        "es": "POBRE",
    },
    # ── argparse description ─────────────────────────────────────────────
    "ap_description": {
        "en": textwrap.dedent("""\
            NEC2 Antenna Length Optimizer
            ─────────────────────────────
            Searches (wire_len, cp_len) combinations and ranks them by aggregate
            VSWR across all active bands.

            BAND SOURCE (choose one):
              With CSV  :  --csv my_bands.csv
              Without CSV:  --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
                            (--freqs optional for known amateur bands; auto centre freq used)
                            --bands custom1,custom2 --freqs 7.1,14.2 --wire-len 21.0 --cp-len 5.0
                            (--freqs required for unrecognised band names)

            ACTIVE BANDS:
              --active-bands 40m,20m   Override CSV 'active' column, or restrict
                                       which bands are scored for VSWR when using
                                       --bands/--freqs directly.

            By default the search window is ±2 m around the wire and CP lengths.
            Use --margin to widen it, or --wire-min/max and --cp-min/max for
            explicit bounds.

            Two evaluation modes:
              empirical  — fast, uses the same R/X formulas as the spreadsheet
              nec2       — accurate, runs nec2c for each candidate geometry

            NEC2C BINARY DISCOVERY (automatic, in order):
              1. --nec2c /path/to/nec2c
              2. $NEC2C environment variable
              3. PATH  (nec2c, nec2c-mpich)
              4. Hard-coded paths (/usr/bin, /usr/local/bin, /opt/nec2c/bin …)
              5. Interactive prompt

            OUTPUT FILES:
              optimizer_report.txt  — ranked table + Pareto front + interpretation
              optimizer_plot.png    — score heat map + per-band VSWR bar charts
              optimizer_best.csv    — best candidate in band-analysis CSV format
        """),
        "es": textwrap.dedent("""\
            Optimizador de Longitud de Antena NEC2
            ──────────────────────────────────────
            Busca combinaciones (longitud_hilo, longitud_CP) y las clasifica por
            ROS agregado en todas las bandas activas.

            FUENTE DE BANDAS (elegir una):
              Con CSV     :  --csv mis_bandas.csv
              Sin CSV     :  --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
                             (--freqs opcional para bandas amateur conocidas; usa freq. central auto)
                             --bands custom1,custom2 --freqs 7.1,14.2 --wire-len 21.0 --cp-len 5.0
                             (--freqs requerido para nombres de banda no reconocidos)

            BANDAS ACTIVAS:
              --active-bands 40m,20m   Reemplaza la columna 'active' del CSV, o
                                       restringe qué bandas se evalúan para ROS al
                                       usar --bands/--freqs directamente.

            Por defecto la ventana de búsqueda es ±2 m alrededor de las longitudes
            de hilo y CP.  Use --margin para ampliarla, o --wire-min/max y
            --cp-min/max para límites explícitos.

            Dos modos de evaluación:
              empirical  — rápido, usa las mismas fórmulas R/X que la planilla
              nec2       — preciso, ejecuta nec2c para cada geometría candidata

            DESCUBRIMIENTO DEL BINARIO NEC2C (automático, en orden):
              1. --nec2c /ruta/a/nec2c
              2. Variable de entorno $NEC2C
              3. PATH  (nec2c, nec2c-mpich)
              4. Rutas fijas (/usr/bin, /usr/local/bin, /opt/nec2c/bin …)
              5. Solicitud interactiva

            ARCHIVOS DE SALIDA:
              optimizer_report.txt  — tabla clasificada + frente de Pareto + interpretación
              optimizer_plot.png    — mapa de calor + gráficos de barras ROS por banda
              optimizer_best.csv    — mejor candidato en formato CSV de análisis de banda
        """),
    },
    # ── argparse argument help strings ───────────────────────────────────
    "ap_csv": {
        "en": "Band CSV (optional). If omitted, supply --bands, --freqs, --wire-len, and --cp-len.",
        "es": "CSV de bandas (opcional). Si se omite, proporcione --bands, --freqs, --wire-len y --cp-len.",
    },
    "ap_bands": {
        "en": "Comma-separated band names, e.g. '40m,20m,15m'. Required when --csv is not supplied.",
        "es": "Nombres de banda separados por coma, ej. '40m,20m,15m'. Requerido si no se usa --csv.",
    },
    "ap_freqs": {
        "en": ("Comma-separated centre frequencies in MHz, one per band. "
               "Optional when all --bands names are recognised amateur-radio bands. "
               "Required only for unrecognised band names."),
        "es": ("Frecuencias centrales en MHz separadas por coma, una por banda. "
               "Opcional cuando todos los nombres en --bands son bandas amateur reconocidas. "
               "Requerido sólo para nombres de banda no reconocidos."),
    },
    "ap_wire_len": {
        "en": "Starting wire length in metres for the search window centre. Required when --csv is not supplied.",
        "es": "Longitud inicial del hilo en metros para el centro de la ventana de búsqueda. Requerido si no se usa --csv.",
    },
    "ap_cp_len": {
        "en": "Starting counterpoise length in metres for the search window centre. Required when --csv is not supplied.",
        "es": "Longitud inicial del contrapeso en metros para el centro de la ventana de búsqueda. Requerido si no se usa --csv.",
    },
    "ap_active_bands": {
        "en": ("Comma-separated list of band names to mark as active for VSWR scoring. "
               "Overrides the 'active' column in the CSV."),
        "es": ("Lista de nombres de banda separados por coma para marcar como activas en la evaluación de ROS. "
               "Reemplaza la columna 'active' del CSV."),
    },
    "ap_unun": {
        "en": "UnUn ratio (e.g. 9 for 9:1).  Default: read from CSV.",
        "es": "Relación UnUn (ej. 9 para 9:1).  Por defecto: leída del CSV.",
    },
    "ap_mode": {
        "en": "Evaluation mode (default: auto = nec2 if binary found, else empirical).",
        "es": "Modo de evaluación (por defecto: auto = nec2 si se encuentra el binario, si no empírico).",
    },
    "ap_nec2c": {
        "en": "Explicit path to nec2c binary.  Overrides auto-discovery.",
        "es": "Ruta explícita al binario nec2c.  Reemplaza el descubrimiento automático.",
    },
    "ap_margin": {
        "en": ("Search radius in metres around the CSV wire and CP lengths "
               "(default 2.0 m).  Overridden by explicit --wire-min/max or --cp-min/max."),
        "es": ("Radio de búsqueda en metros alrededor de las longitudes de hilo y CP del CSV "
               "(por defecto 2.0 m).  Es reemplazado por --wire-min/max o --cp-min/max explícitos."),
    },
    "ap_wire_min": {
        "en": "Minimum wire length to search (metres).",
        "es": "Longitud mínima de hilo a buscar (metros).",
    },
    "ap_wire_max": {
        "en": "Maximum wire length to search (metres).",
        "es": "Longitud máxima de hilo a buscar (metros).",
    },
    "ap_wire_step": {
        "en": "Wire length step size (metres, default 0.25).",
        "es": "Tamaño de paso de longitud de hilo (metros, por defecto 0.25).",
    },
    "ap_cp_min": {
        "en": "Minimum counterpoise length (metres).",
        "es": "Longitud mínima del contrapeso (metros).",
    },
    "ap_cp_max": {
        "en": "Maximum counterpoise length (metres).",
        "es": "Longitud máxima del contrapeso (metros).",
    },
    "ap_cp_step": {
        "en": "Counterpoise length step size (metres, default 0.25).",
        "es": "Tamaño de paso de longitud del contrapeso (metros, por defecto 0.25).",
    },
    "ap_wire_height": {
        "en": "Antenna wire height above ground (metres). Default: height from CSV, or {0} m if not in CSV.",
        "es": "Altura del hilo de antena sobre el suelo (metros). Por defecto: altura del CSV, o {0} m si no está en el CSV.",
    },
    "ap_cp_height": {
        "en": "Counterpoise height above ground (metres). Default: CP height from CSV, or 0.5 m if not in CSV.",
        "es": "Altura del contrapeso sobre el suelo (metros). Por defecto: altura CP del CSV, o 0.5 m si no está en el CSV.",
    },
    "ap_cp_type": {
        "en": "Counterpoise orientation(s) to simulate (default: both).",
        "es": "Orientación(es) del contrapeso a simular (por defecto: ambas).",
    },
    "ap_ground_cond": {
        "en": "Ground conductivity S/m (default {0}).",
        "es": "Conductividad del suelo en S/m (por defecto {0}).",
    },
    "ap_ground_diel": {
        "en": "Ground relative permittivity (default {0}).",
        "es": "Permitividad relativa del suelo (por defecto {0}).",
    },
    "ap_top_n": {
        "en": "Number of top candidates to show in report (default 20).",
        "es": "Número de mejores candidatos a mostrar en el informe (por defecto 20).",
    },
    "ap_out_txt": {
        "en": "Output report filename (default: optimizer_report.txt).",
        "es": "Nombre del archivo de informe de salida (por defecto: optimizer_report.txt).",
    },
    "ap_out_png": {
        "en": "Output plot filename (default: optimizer_plot.png).",
        "es": "Nombre del archivo de gráfico de salida (por defecto: optimizer_plot.png).",
    },
    "ap_out_csv": {
        "en": "Best-candidate CSV output (default: optimizer_best.csv).",
        "es": "Salida CSV del mejor candidato (por defecto: optimizer_best.csv).",
    },
    "ap_out_nec": {
        "en": ("NEC2 deck for the best antenna geometry (default: best_antenna.nec). "
               "Includes full RP radiation-pattern cards per active band."),
        "es": ("Deck NEC2 para la mejor geometría de antena (por defecto: best_antenna.nec). "
               "Incluye tarjetas RP de patrón de radiación completo por banda activa."),
    },
    "ap_out_radiation": {
        "en": "Radiation diagram PNG for all active bands (default: radiation_diagrams.png).",
        "es": "PNG de diagramas de radiación para todas las bandas activas (por defecto: radiation_diagrams.png).",
    },
    "ap_retry": {
        "en": ("If the best candidate hits a search boundary (wire or CP at min/max), "
               "automatically re-run the sweep up to N times, shifting the window "
               "in the direction suggested by the warning (best+margin for 'may be "
               "longer', best-margin for 'may be shorter').  Default: 0 (disabled)."),
        "es": ("Si el mejor candidato alcanza un límite de búsqueda (hilo o CP en min/max), "
               "re-ejecuta el barrido automáticamente hasta N veces, desplazando la ventana "
               "en la dirección sugerida por la advertencia (mejor+margen para 'puede ser "
               "mayor', mejor-margen para 'puede ser menor').  Por defecto: 0 (desactivado)."),
    },
    "ap_no_interactive": {
        "en": "Do not prompt interactively for missing inputs; exit with error instead.",
        "es": "No solicitar entradas faltantes de forma interactiva; salir con error en su lugar.",
    },
    "ap_quiet": {
        "en": "Suppress progress output.",
        "es": "Suprimir la salida de progreso.",
    },
    "ap_lang": {
        "en": "Interface language: en (English) or es (Español). Default: auto-detect from system locale.",
        "es": "Idioma de la interfaz: en (English) o es (Español). Por defecto: detección automática del locale del sistema.",
    },
    # ── hardcoded strings in main() ──────────────────────────────────────
    "radiation_nec2_only_inline": {
        "en": "  ℹ  Radiation diagrams require NEC2 mode (current mode: {0}) — skipped.",
        "es": "  ℹ  Los diagramas de radiación requieren modo NEC2 (modo actual: {0}) — omitido.",
    },
    "err_no_unun_nocsv_inline": {
        "en": "  No --unun supplied and no CSV to read it from.  Use --unun RATIO (e.g. --unun 9).",
        "es": "  No se proporcionó --unun y no hay CSV de donde leerlo.  Use --unun RELACION (ej: --unun 9).",
    },
}


def T(key: str) -> str:
    """Return the translated string for *key* in the active language."""
    entry = _STRINGS.get(key)
    if entry is None:
        return f"[{key}]"        # missing key — show visibly
    return entry.get(_LANG) or entry.get("en", f"[{key}]")



# ═══════════════════════════════════════════════════════════════════════════
# INLINED DATA STRUCTURES  (from nec2_vs_calc_analyzer)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FreqPoint:
    """One frequency-domain data point from a NEC2 output file."""
    freq_mhz:   float = 0.0
    R_ohm:      float = 0.0        # feedpoint resistance
    X_ohm:      float = 0.0        # feedpoint reactance
    gain_dbi:   float = 0.0        # max azimuth/elevation gain (dBi)
    toa_deg:    float = 90.0       # take-off angle (degrees, 90=horizon)
    efficiency: float = 1.0        # radiation efficiency (0–1)
    vswr50:     float = 99.0       # VSWR ref 50 Ω

    @property
    def Z_mag(self):
        return math.hypot(self.R_ohm, self.X_ohm)

    @property
    def Z_phase_deg(self):
        return math.degrees(math.atan2(self.X_ohm, self.R_ohm))

    @property
    def refl_coeff_mag(self):
        Z0 = 50.0
        num = math.hypot(self.R_ohm - Z0, self.X_ohm)
        den = math.hypot(self.R_ohm + Z0, self.X_ohm)
        return num / den if den else 1.0

    def compute_vswr50(self):
        g = self.refl_coeff_mag
        return (1 + g) / (1 - g) if g < 1 else 999.0


@dataclass
class NEC2Run:
    """Parsed results from one complete NEC2 output file."""
    label:      str = ""
    filepath:   str = ""
    wire_len_m: float = 0.0
    cp_len_m:   float = 0.0
    cp_type:    str = ""           # "horizontal" | "vertical" | "none"
    freqs:      List[FreqPoint] = field(default_factory=list)

    def freq_map(self, decimals: int = 4) -> Dict[float, FreqPoint]:
        return {round(fp.freq_mhz, decimals): fp for fp in self.freqs}


@dataclass
class CalcRow:
    """One band row from the spreadsheet CSV."""
    band:           str   = ""
    freq_mhz:       float = 0.0
    active:         bool  = False
    lambda_half_m:  float = 0.0
    lambda_qtr_m:   float = 0.0
    wire_len_m:     float = 0.0
    L_over_lhalf:   float = 0.0    # L / (λ/2)
    R_wire_ohm:     float = 0.0    # empirical: 50·80^cos²(π·L/λ½)
    X_wire_ohm:     float = 0.0    # empirical: 1500·sin(2π·L/λ½)
    vswr_no_cp:     float = 0.0    # VSWR without counterpoise
    vswr_with_cp:   float = 0.0    # VSWR with counterpoise correction
    Z_eff_ohm:      float = 0.0    # Z_wire + Zcp
    Zcp_ohm:        float = 0.0    # counterpoise impedance (series)
    unun_ratio:     float = 1.0
    avoidance_score:float = 0.0
    quality_rating: str   = ""
    cp_len_m:       float = 0.0
    cp_height_m:    float = 0.0
    wire_height_m:  float = 0.0    # antenna wire height above ground
    num_radials:    int   = 1


# ═══════════════════════════════════════════════════════════════════════════
# INLINED NEC2 OUTPUT PARSER  (from nec2_vs_calc_analyzer)
# ═══════════════════════════════════════════════════════════════════════════

# Compiled patterns
_RE_FREQ    = re.compile(r'FREQUENCY\s*=\s*([\d.E+\-]+)\s*MHZ',       re.IGNORECASE)
_RE_FREQ2   = re.compile(r'FREQ\s*=\s*([\d.E+\-]+)\s*MHZ',            re.IGNORECASE)
_RE_FREQ3   = re.compile(r'\*+\s*FREQUENCY\s*=\s*([\d.E+\-]+)\s*MHZ', re.IGNORECASE)
_RE_FREQ4   = re.compile(r'Frequency\s*=\s*([\d.E+\-]+)\s*MHz',       re.IGNORECASE)
_RE_FREQ5   = re.compile(r'^\s*([\d.]{3,})\s+MHZ\b', re.IGNORECASE | re.MULTILINE)
_RE_FREQ6   = re.compile(r'FREQUENCY\s*:\s*([\d.E+\-]+)\s*MHz', re.IGNORECASE)

_ALL_FREQ_RES = [_RE_FREQ, _RE_FREQ2, _RE_FREQ3, _RE_FREQ4, _RE_FREQ5, _RE_FREQ6]

_RE_IMPEDANCE = re.compile(
    r'IMPEDANCE\s*=\s*\(\s*([\-\d.E+]+)\s*,\s*([\-\d.E+]+)\s*\)', re.IGNORECASE)

_RE_ANTINPUT_SECTION = re.compile(r'ANTENNA INPUT PARAMETERS', re.IGNORECASE)
_RE_ANTINPUT = re.compile(
    r'^\s*\d+\s+\d+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+'
    r'([\-\d.E+]+)\s+([\-\d.E+]+)',
    re.IGNORECASE | re.MULTILINE)

_RE_ZIN_ROW = re.compile(
    r'(?:INPUT\s+IMPEDANCE|ZIN)\s*[\s\-:=]+([\-\d.Ee+]+)\s*[+j]?\s*([\-\d.Ee+]+)',
    re.IGNORECASE)

_RE_Z_TABLE = re.compile(
    r'Z\s*=\s*([\-\d.E+]+)\s*([+\-])\s*j\s*([\d.E+]+)', re.IGNORECASE)

_RE_GAIN_DB  = re.compile(r'POWER\s+GAIN\s*=\s*([\-\d.E+]+)\s*DB',   re.IGNORECASE)
_RE_GAIN_MAX = re.compile(r'MAXIMUM\s+GAIN\s*=\s*([\-\d.E+]+)\s*DB', re.IGNORECASE)
_RE_EFF = re.compile(
    r'(?:RADIATION\s+EFFICIENCY|EFFICIENCY)\s*=\s*([\d.E+\-]+)', re.IGNORECASE)
_RE_WIRE_CM = re.compile(r'Wire\s+length:\s*([\d.]+)\s*m',             re.IGNORECASE)
_RE_CP_CM   = re.compile(
    r'Counterpoise(?:\s*\(vertical\))?\s*:\s*([\d.]+)\s*m',            re.IGNORECASE)
_RE_CP_VERT = re.compile(r'counterpoise\s*\(vertical\)',                re.IGNORECASE)

_RE_RP_SECTION = re.compile(r'[-]{4,}\s*RADIATION PATTERNS\s*[-]{4,}', re.IGNORECASE)
_RE_RP_ROW = re.compile(
    r'^\s*((?:90(?:\.0+)?|[0-8]?\d(?:\.\d+)?))\s+(\d{1,3}(?:\.\d+)?)\s+'
    r'([\-\d.]+)\s+[\-\d.]+\s+([\-\d.]+)',
    re.MULTILINE)


def _safe_float(s: str) -> float:
    """Parse a NEC2 scientific-notation float safely."""
    try:
        return float(s.replace('D', 'E').replace('d', 'e'))
    except ValueError:
        return 0.0


def _parse_cp_from_nec_deck(out_filepath: str, run: NEC2Run,
                              explicit_nec_path: Optional[str] = None):
    """
    Try to find a companion .nec input deck and parse CP length from GW cards.
    Wire 1 is assumed to be the antenna; Wire 2 (if present) is the CP.
    Also detects CP type (horizontal vs vertical) from z-coordinates.
    """
    nec_path = None
    if explicit_nec_path and os.path.isfile(explicit_nec_path):
        nec_path = explicit_nec_path
    else:
        base = os.path.splitext(out_filepath)[0]
        for ext in ('.nec', '.NEC', '.inp', '.INP'):
            candidate = base + ext
            if os.path.isfile(candidate):
                nec_path = candidate
                break
    if nec_path is None:
        return

    wires = []
    slope_end_z: Optional[float] = None
    try:
        with open(nec_path, 'r', errors='replace') as fh:
            for line in fh:
                # Detect slope comment written by write_nec_deck / write_best_nec_deck
                cm_slope = re.match(
                    r'CM\s+Wire\s+slope\s+end\s+z:\s*([\d.Ee+\-]+)\s*m',
                    line, re.IGNORECASE)
                if cm_slope:
                    try:
                        slope_end_z = float(cm_slope.group(1))
                    except ValueError:
                        pass
                m = re.match(
                    r'GW\s+(\d+)\s+\d+\s+'
                    r'([\d.\-Ee+]+)\s+([\d.\-Ee+]+)\s+([\d.\-Ee+]+)\s+'
                    r'([\d.\-Ee+]+)\s+([\d.\-Ee+]+)\s+([\d.\-Ee+]+)',
                    line, re.IGNORECASE)
                if m:
                    tag = int(m.group(1))
                    x1, y1, z1 = float(m.group(2)), float(m.group(3)), float(m.group(4))
                    x2, y2, z2 = float(m.group(5)), float(m.group(6)), float(m.group(7))
                    length = math.sqrt((x2-x1)**2 + (y2-y1)**2 + (z2-z1)**2)
                    dz = abs(z2 - z1)
                    wires.append({'tag': tag, 'length': length, 'dz': dz,
                                  'z1': z1, 'z2': z2})
                if re.match(r'^RP\b', line, re.IGNORECASE):
                    run._has_rp_card = True
    except OSError:
        return

    if not wires:
        return

    cp_wires = [w for w in wires if w['tag'] != 1]
    if not cp_wires:
        return

    cp = max(cp_wires, key=lambda w: w['length'])
    run.cp_len_m = round(cp['length'], 3)

    if cp['length'] > 0 and cp['dz'] / cp['length'] > 0.6:
        run.cp_type = 'vertical'
    else:
        run.cp_type = 'horizontal'

    # Store slope metadata so callers can record it in CandidateResult
    if slope_end_z is not None:
        run._wire_slope_end_m = slope_end_z

    run._cp_from_deck = True


def _parse_nec2_fallback(text: str, run: NEC2Run):
    """Fallback when no FREQUENCY= markers found with any pattern."""
    imp_matches = list(_RE_IMPEDANCE.finditer(text))

    if not imp_matches:
        imp_matches = list(_RE_Z_TABLE.finditer(text))
        use_z_table = True
    else:
        use_z_table = False

    freq_matches = []
    seen_positions = set()
    for pat in _ALL_FREQ_RES:
        for m in pat.finditer(text):
            if m.start() not in seen_positions:
                seen_positions.add(m.start())
                freq_matches.append(m)
    freq_matches.sort(key=lambda x: x.start())

    for m in imp_matches:
        fp = FreqPoint()
        if use_z_table:
            fp.R_ohm = _safe_float(m.group(1))
            sign     = 1.0 if m.group(2) == '+' else -1.0
            fp.X_ohm = sign * _safe_float(m.group(3))
        else:
            fp.R_ohm = _safe_float(m.group(1))
            fp.X_ohm = _safe_float(m.group(2))
        candidates = [f for f in freq_matches if f.start() < m.start()]
        if candidates:
            fp.freq_mhz = round(float(candidates[-1].group(1)), 4)
        else:
            # No frequency marker found before this impedance block — skip it
            # rather than emitting a FreqPoint with freq_mhz=0.0 that will
            # silently miss every tolerance check in the scoring engine.
            continue
        fp.vswr50 = fp.compute_vswr50()
        run.freqs.append(fp)


def parse_nec2_output(filepath: str, debug: bool = False,
                      explicit_nec_path: Optional[str] = None) -> NEC2Run:
    """Parse a NEC2 .out file produced by nec2c, 4nec2, xnec2c, or EZNEC export."""
    run = NEC2Run(filepath=filepath)
    run._has_rp_card = False
    run._cp_from_deck = False

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"NEC2 file not found: {filepath}")

    with open(filepath, 'r', errors='replace') as fh:
        text = fh.read()

    run._has_rp_card = bool(
        re.search(r'DATA\s+CARD[^\n]*\bRP\b', text, re.IGNORECASE) or
        re.search(r'^\s*RP\b',                text, re.IGNORECASE | re.MULTILINE)
    )

    if debug:
        print(f"\n{'─'*60}")
        print(f"  DEBUG: first 60 lines of {filepath}")
        print(f"{'─'*60}")
        for i, line in enumerate(text.splitlines()[:60], 1):
            print(f"  {i:3d}: {repr(line)}")
        print(f"{'─'*60}\n")

    m = _RE_WIRE_CM.search(text)
    if m:
        run.wire_len_m = float(m.group(1))
    m = _RE_CP_CM.search(text)
    if m:
        run.cp_len_m = float(m.group(1))
    if _RE_CP_VERT.search(text):
        run.cp_type = "vertical"
    elif run.cp_len_m > 0:
        run.cp_type = "horizontal"
    else:
        run.cp_type = "none"

    _parse_cp_from_nec_deck(filepath, run, explicit_nec_path=explicit_nec_path)

    freq_positions: List[Tuple[int, float]] = []
    for pattern in _ALL_FREQ_RES:
        candidates = [(m.start(), float(m.group(1)))
                      for m in pattern.finditer(text)]
        if len(candidates) > len(freq_positions):
            freq_positions = candidates

    if debug and not freq_positions:
        print("  DEBUG: No frequency markers found with any pattern.")
        print("  DEBUG: Check the file format against the patterns in _ALL_FREQ_RES.")

    if not freq_positions:
        _parse_nec2_fallback(text, run)
        return run

    freq_positions.append((len(text), 0.0))

    for idx, (pos, freq_mhz) in enumerate(freq_positions[:-1]):
        block = text[pos: freq_positions[idx + 1][0]]
        fp = FreqPoint(freq_mhz=round(freq_mhz, 4))

        # Method 1: IMPEDANCE = (R, X)
        m = _RE_IMPEDANCE.search(block)
        if m:
            fp.R_ohm = _safe_float(m.group(1))
            fp.X_ohm = _safe_float(m.group(2))

        # Method 2: ANTENNA INPUT PARAMETERS table
        if fp.R_ohm == 0.0:
            sec_m = _RE_ANTINPUT_SECTION.search(block)
            antinput_text = block[sec_m.start():] if sec_m else ""
            curr_pos = antinput_text.find('CURRENTS AND LOCATION')
            if curr_pos < 0:
                curr_pos = antinput_text.upper().find('CURRENTS AND LOCATION')
            search_text = antinput_text[:curr_pos] if curr_pos >= 0 else antinput_text
            m = _RE_ANTINPUT.search(search_text)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                fp.X_ohm = _safe_float(m.group(2))

        # Method 3: ZIN label
        if fp.R_ohm == 0.0:
            m = _RE_ZIN_ROW.search(block)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                fp.X_ohm = _safe_float(m.group(2))

        # Method 4: Z = R +j X table
        if fp.R_ohm == 0.0:
            m = _RE_Z_TABLE.search(block)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                sign     = 1.0 if m.group(2) == '+' else -1.0
                fp.X_ohm = sign * _safe_float(m.group(3))

        # --- gain ---
        m = _RE_GAIN_MAX.search(block)
        if m:
            fp.gain_dbi = _safe_float(m.group(1))
        else:
            m = _RE_GAIN_DB.search(block)
            if m:
                fp.gain_dbi = _safe_float(m.group(1))

        # --- radiation efficiency ---
        m = _RE_EFF.search(block)
        if m:
            fp.efficiency = _safe_float(m.group(1))
            if fp.efficiency > 1.5:
                fp.efficiency /= 100.0

        # --- RP table ---
        rp_gains: List[Tuple[float, float, float]] = []
        rp_sec_m = _RE_RP_SECTION.search(block)
        rp_search_text = block[rp_sec_m.start():] if rp_sec_m else ""
        for rm in _RE_RP_ROW.finditer(rp_search_text):
            theta = _safe_float(rm.group(1))
            phi   = _safe_float(rm.group(2))
            gain  = _safe_float(rm.group(4))
            if gain <= -200.0:
                continue
            rp_gains.append((theta, phi, gain))

        if rp_gains:
            best_rp = max(rp_gains, key=lambda t: t[2])
            fp.gain_dbi = best_rp[2]
            fp.toa_deg = 90.0 - best_rp[0]

        fp.vswr50 = fp.compute_vswr50()
        run.freqs.append(fp)

    return run


# ═══════════════════════════════════════════════════════════════════════════
# INLINED CSV READER  (from nec2_vs_calc_analyzer)
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_CSV_COLS = {
    "band", "freq_mhz", "active",
    "lambda_half_m", "wire_len_m",
    "r_wire_ohm", "x_wire_ohm",
    "vswr_no_cp",
}

OPTIONAL_CSV_COLS = {
    "lambda_qtr_m", "L_over_lhalf",
    "vswr_with_cp", "Z_eff_ohm", "Zcp_ohm",
    "unun_ratio", "avoidance_score", "quality_rating",
    "cp_len_m", "cp_height_m", "wire_height_m", "num_radials",
}


def _col(row: dict, name: str, default=None):
    """Get value from CSV row, case-insensitively."""
    for k, v in row.items():
        if k.strip().lower() == name.lower():
            return v.strip() if isinstance(v, str) else v
    return default


def _flt(row: dict, name: str, default: float = 0.0) -> float:
    v = _col(row, name, None)
    if v is None or str(v).strip() in ("", "—", "-", "N/A", "n/a"):
        return default
    s = str(v).strip()
    if re.fullmatch(r'-?[\d]+([,.]\d+)?', s):
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return default


def _bool_yes(v) -> bool:
    if v is None:
        return False
    return str(v).strip().upper() in ("YES", "Y", "TRUE", "1", "ACTIVE")


def load_csv(filepath: str) -> List[CalcRow]:
    rows: List[CalcRow] = []

    with open(filepath, newline='', encoding='utf-8-sig') as probe:
        first_line = probe.readline()
    delimiter = ';' if ';' in first_line else ','

    with open(filepath, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        cols_lower = {c.strip().lower() for c in (reader.fieldnames or [])}
        missing = REQUIRED_CSV_COLS - cols_lower
        if missing:
            print(f"\n{Fore.YELLOW}" + T("csv_missing_cols").format(missing))
            print(T("csv_missing_cols2") + f"{Style.RESET_ALL}\n")
        for raw in reader:
            cr = CalcRow()
            cr.band            = _col(raw, "band", "")
            cr.freq_mhz        = _flt(raw, "freq_mhz")
            cr.active          = _bool_yes(_col(raw, "active", "NO"))
            cr.lambda_half_m   = _flt(raw, "lambda_half_m")
            cr.lambda_qtr_m    = _flt(raw, "lambda_qtr_m")
            cr.wire_len_m      = _flt(raw, "wire_len_m")
            cr.L_over_lhalf    = _flt(raw, "L_over_lhalf")
            cr.R_wire_ohm      = _flt(raw, "R_wire_ohm")
            cr.X_wire_ohm      = _flt(raw, "X_wire_ohm")
            cr.vswr_no_cp      = _flt(raw, "vswr_no_cp",  default=0.0)
            cr.vswr_with_cp    = _flt(raw, "vswr_with_cp", default=0.0)
            cr.Z_eff_ohm       = _flt(raw, "Z_eff_ohm",   default=0.0)
            cr.Zcp_ohm         = _flt(raw, "Zcp_ohm",     default=0.0)
            cr.unun_ratio      = _flt(raw, "unun_ratio",  default=1.0)
            cr.avoidance_score = _flt(raw, "avoidance_score", default=0.0)
            cr.quality_rating  = _col(raw, "quality_rating", "")
            cr.cp_len_m        = _flt(raw, "cp_len_m",    default=0.0)
            cr.cp_height_m     = _flt(raw, "cp_height_m", default=0.0)
            cr.wire_height_m   = _flt(raw, "wire_height_m", default=0.0)
            cr.num_radials     = int(_flt(raw, "num_radials", default=1))

            if cr.freq_mhz > 0:
                c_mhz = 299.792458
                lambda_half_exact = (c_mhz / cr.freq_mhz) * 0.5
                cr.L_over_lhalf = cr.wire_len_m / lambda_half_exact

            if cr.L_over_lhalf > 0:
                # Compute empirical R/X only when the CSV did not supply them.
                # Overwriting valid CSV values with the empirical formula would
                # discard any measured or NEC2-derived data the user provided.
                if cr.R_wire_ohm == 0.0 and cr.X_wire_ohm == 0.0:
                    arg = math.pi * cr.L_over_lhalf
                    cr.R_wire_ohm = 50 * (80 ** (math.cos(arg) ** 2))
                    cr.X_wire_ohm = 1500 * math.sin(2 * arg)
                # Always recompute vswr_no_cp from the (possibly CSV-supplied) impedance.
                _g5 = math.hypot(cr.R_wire_ohm - 50, cr.X_wire_ohm) / \
                      math.hypot(cr.R_wire_ohm + 50, cr.X_wire_ohm)
                cr.vswr_no_cp = (1 + _g5) / (1 - _g5) if _g5 < 1 else 999.0

            if cr.L_over_lhalf > 0:
                # Use λ/4 units: L_over_lqtr = 2 × L_over_lhalf
                L_over_lqtr = cr.L_over_lhalf * 2.0
                frac = L_over_lqtr % 1.0
                computed_score = min(min(frac, 1.0 - frac), 0.25)
                cr._computed_avoidance = computed_score
            else:
                cr._computed_avoidance = cr.avoidance_score

            rows.append(cr)

    # Note: _computed_avoidance is a diagnostic attribute set above for each row.
    # score_candidate() recomputes avoidance from wire geometry at runtime, so
    # this pre-computed value is not used in the optimisation loop.  It remains
    # available for callers that want a quick CSV-level estimate without running
    # a full sweep (e.g. pre-flight sanity checks).
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS & DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════

C_MHZ = 299.792458          # speed of light / 1e6
WIRE_RADIUS_M = 0.001       # 1 mm copper wire
DEFAULT_HEIGHT_M = 8.0      # antenna wire height above ground
DEFAULT_GROUND_COND = 0.005 # S/m  (average ground)
DEFAULT_GROUND_DIEL = 13.0  # relative permittivity
SEGS_PER_HALF_WAVE = 21     # NEC2 segments per half wavelength

# NEC2C search paths (searched in order after PATH)
NEC2C_SEARCH_PATHS = [
    "/usr/bin/nec2c",
    "/usr/local/bin/nec2c",
    "/opt/nec2c/bin/nec2c",
    "/opt/homebrew/bin/nec2c",
    "/usr/bin/nec2c-mpich",
    "/usr/local/bin/nec2c-mpich",
]

NEC2C_NAMES = ["nec2c", "nec2c-mpich"]   # tried on PATH

# ── Amateur-radio band → ITU centre frequency (MHz) ──────────────────────
BAND_CENTRE_FREQ_MHZ: Dict[str, float] = {
    # LF / MF
    "2200m": 0.1365,
    "630m":  0.475,
    # HF
    "160m":  1.850,
    "80m":   3.650,
    "60m":   5.350,
    "40m":   7.100,
    "30m":  10.125,
    "20m":  14.175,
    "17m":  18.118,
    "15m":  21.225,
    "12m":  24.940,
    "10m":  28.500,
    "6m":   50.200,
    # VHF / UHF
    "4m":   70.200,
    "2m":  144.200,
    "70cm": 432.100,
    "23cm": 1296.200,
}


def _lookup_band_freq(name: str) -> Optional[float]:
    """
    Return the centre frequency in MHz for a named amateur band.
    Accepts the band name case-insensitively and with or without the
    trailing 'm'.  Returns None when the name is not in the table.
    """
    key = name.strip().lower()
    if key in BAND_CENTRE_FREQ_MHZ:
        return BAND_CENTRE_FREQ_MHZ[key]
    if key + "m" in BAND_CENTRE_FREQ_MHZ:
        return BAND_CENTRE_FREQ_MHZ[key + "m"]
    return None


def _avoidance_rating(score: float) -> str:
    """
    Map a resonance-avoidance score to a human-readable label.

    Thresholds calibrated for the corrected avoidance formula where the
    maximum achievable value is 0.25 (midway between two λ/4 resonances):
      ≥ 0.20  → ★★★ EXCELLENT
      ≥ 0.12  → ★★  GOOD
      ≥ 0.06  → ★   MARGINAL
      < 0.06  → ✗   RESONANCE RISK
    """
    if score >= 0.20:
        return T("rating_excellent")
    elif score >= 0.12:
        return T("rating_good")
    elif score >= 0.06:
        return T("rating_marginal")
    else:
        return T("rating_risk")


# ═══════════════════════════════════════════════════════════════════════════
# NEC2C BINARY DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════

def find_nec2c(explicit: Optional[str] = None,
               interactive: bool = True) -> Optional[str]:
    """
    Locate the nec2c binary.

    Priority:
      1. explicit CLI --nec2c path
      2. $NEC2C environment variable
      3. PATH search (nec2c, nec2c-mpich)
      4. Common hard-coded install paths
      5. Interactive prompt (if interactive=True)
    Returns the resolved absolute path or None.
    """
    def _check(p: str) -> Optional[str]:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return os.path.abspath(p)
        return None

    if explicit:
        r = _check(explicit)
        if r:
            return r
        print(f"{Fore.RED}" + T("nec2c_not_found_path").format(explicit) + f"{Style.RESET_ALL}")

    env_path = os.environ.get("NEC2C", "")
    r = _check(env_path)
    if r:
        print(f"  {Fore.CYAN}" + T("nec2c_found_env").format(r) + f"{Style.RESET_ALL}")
        return r

    for name in NEC2C_NAMES:
        r = shutil.which(name)
        if r:
            print(f"  {Fore.CYAN}" + T("nec2c_found_path").format(r) + f"{Style.RESET_ALL}")
            return r

    for p in NEC2C_SEARCH_PATHS:
        r = _check(p)
        if r:
            print(f"  {Fore.CYAN}" + T("nec2c_found").format(r) + f"{Style.RESET_ALL}")
            return r

    if interactive:
        print(f"\n{Fore.YELLOW}  nec2c binary not found automatically.{Style.RESET_ALL}")
        print("  Options:")
        print("    • Install:  sudo apt install nec2c   (Debian/Ubuntu)")
        print("    •           brew install nec2c        (macOS / Homebrew)")
        print("    • Re-run with:  --nec2c /full/path/to/nec2c")
        print("    • Set env var:  export NEC2C=/full/path/to/nec2c")
        ans = input(f"\n{Fore.CYAN}" + T("nec2c_prompt") + f"{Style.RESET_ALL}").strip()
        if ans:
            r = _check(ans)
            if r:
                return r
            print(f"{Fore.RED}" + T("nec2c_bad_path").format(ans) + f"{Style.RESET_ALL}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# NEC2 DECK WRITER
# ═══════════════════════════════════════════════════════════════════════════

def _segs(length_m: float, highest_freq_mhz: float) -> int:
    """Return an odd number of segments appropriate for the wire length.

    Odd segment count is preferred for NEC2 numerical stability and to give
    a well-defined physical centre segment.  The source (EX card) is placed
    at segment 1 (the near end / feedpoint junction), not the centre segment.
    """
    lambda_half = C_MHZ / (2.0 * highest_freq_mhz) if highest_freq_mhz else 10.0
    n = max(7, int(length_m / lambda_half * SEGS_PER_HALF_WAVE))
    return n if n % 2 == 1 else n + 1


def write_nec_deck(
    nec_path: str,
    wire_len_m: float,
    cp_len_m: float,
    cp_type: str,           # "horizontal" | "vertical"
    freqs_mhz: List[float],
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,  # None → horizontal (z_far = wire_height_m)
    cp_height_m: float = 0.5,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
) -> None:
    """
    Write a minimal NEC2 input deck for an end-fed long wire with one
    counterpoise wire.

    Wire geometry (antenna, Wire 1):
      Horizontal (wire_slope_end_m is None):
        z = wire_height_m throughout; x = 0 .. wire_len_m
      Sloping (wire_slope_end_m is not None):
        Near end (feedpoint): x=0, z=wire_height_m
        Far end             : x=h_proj, z=wire_slope_end_m
        where h_proj = sqrt(wire_len_m² − rise²) and rise = wire_height_m − z_far.

    Source (EX): first segment of Wire 1 (the near/feedpoint end).
    """
    highest_f = max(freqs_mhz)
    segs_ant = _segs(wire_len_m, highest_f)
    segs_cp  = max(5, _segs(cp_len_m, highest_f))

    # ── Resolve Wire-1 far-end coordinates ───────────────────────────────
    z_near = wire_height_m
    if wire_slope_end_m is not None:
        z_far = max(float(wire_slope_end_m), wire_radius_m)   # NEC2 floor: ≥ wire radius
        rise  = z_near - z_far
        if rise > wire_len_m:
            raise ValueError(
                f"wire_height_m ({wire_height_m:.3f} m) − slope_end ({z_far:.4f} m) "
                f"= {rise:.3f} m exceeds wire_len_m ({wire_len_m:.3f} m); "
                "wire cannot reach the specified far-end height."
            )
        x_far = math.sqrt(max(0.0, wire_len_m**2 - rise**2))
    else:
        z_far = z_near
        x_far = wire_len_m

    # GE flag: 1 = ground plane present (required for GN Sommerfeld-Norton ground to take effect).
    # NEC2 ignores the GN card when GE=0 (free space).  We always write a GN card, so GE must
    # always be 1.  The special case z_far < 0.01 (wire end essentially at ground level) does
    # not change this — it only means no elevated wire-end stub is needed.
    ge_flag = 1

    with open(nec_path, "w") as fh:
        fh.write(f"CM NEC2 Long Wire Optimizer Deck\n")
        fh.write(f"CM Wire length: {wire_len_m:.3f} m\n")
        fh.write(f"CM Counterpoise ({cp_type}): {cp_len_m:.3f} m  height: {cp_height_m:.2f} m\n")
        if cp_height_m >= wire_height_m:
            # CP height at or above antenna height: place CP at antenna height level.
            # This avoids a zero-length or negative-length drop wire.
            cp_height_m = wire_height_m
            fh.write(f"CM WARNING: cp_height_m >= wire_height_m; CP placed at wire height.\n")
        if wire_slope_end_m is not None:
            fh.write(f"CM Wire slope end z: {z_far:.4f} m\n")
        fh.write("CE\n")

        fh.write(f"GW 1 {segs_ant} "
                 f"0.0 0.0 {z_near:.3f} "
                 f"{x_far:.3f} 0.0 {z_far:.4f} "
                 f"{wire_radius_m:.5f}\n")

        if cp_type == "horizontal":
            drop_len = wire_height_m - cp_height_m
            if drop_len > 0.01:
                segs_drop = max(5, _segs(drop_len, highest_f))
                fh.write(f"GW 2 {segs_drop} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
                fh.write(f"GW 3 {segs_cp} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{-cp_len_m:.3f} 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
            else:
                fh.write(f"GW 2 {segs_cp} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"{-cp_len_m:.3f} 0.0 {wire_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
        else:  # vertical
            cp_bottom_z = max(cp_height_m, wire_height_m - cp_len_m)
            vert_len    = max(0.0, wire_height_m - cp_bottom_z)
            horiz_rem   = max(0.0, cp_len_m - vert_len)
            if vert_len > 0.01:
                segs_cp_v = max(5, _segs(vert_len, highest_f))
                if segs_cp_v % 2 == 0:
                    segs_cp_v += 1
                fh.write(f"GW 2 {segs_cp_v} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"0.0 0.0 {cp_bottom_z:.3f} "
                         f"{wire_radius_m:.5f}\n")
            if horiz_rem > 0.01:
                segs_cp_h = max(3, _segs(horiz_rem, highest_f))
                if segs_cp_h % 2 == 0:
                    segs_cp_h += 1
                fh.write(f"GW 3 {segs_cp_h} "
                         f"0.0 0.0 {cp_bottom_z:.3f} "
                         f"{-horiz_rem:.3f} 0.0 {cp_bottom_z:.3f} "
                         f"{wire_radius_m:.5f}\n")

        fh.write(f"GE {ge_flag}\n")
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        for f in freqs_mhz:
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            # XQ triggers execution and writes ANTENNA INPUT PARAMETERS (impedance).
            # No RP card needed for impedance-only sweep runs — removing it
            # eliminates redundant pattern computation and speeds up the sweep.
            fh.write("XQ\n")
        fh.write("EN\n")


# ═══════════════════════════════════════════════════════════════════════════
# RUN NEC2C
# ═══════════════════════════════════════════════════════════════════════════

def run_nec2c(binary: str, nec_path: str, out_path: str,
              timeout: int = 60) -> bool:
    """
    Run nec2c:  nec2c -i INPUT -o OUTPUT
    Returns True on success, False on failure.
    """
    try:
        result = subprocess.run(
            [binary, "-i", nec_path, "-o", out_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return False
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CandidateResult:
    """Score for one (wire_len, cp_len) candidate pair."""
    wire_len_m: float
    cp_len_m:   float
    cp_type:    str       # "horizontal" | "vertical" | "both"

    # Per-band VSWR seen by the transmitter (post-UnUn)
    band_vswr: Dict[str, float] = field(default_factory=dict)
    band_avoidance: Dict[str, float] = field(default_factory=dict)

    # Per-band antenna-side impedance  (R_ant, X_ant) in Ω
    band_R_ant: Dict[str, float] = field(default_factory=dict)
    band_X_ant: Dict[str, float] = field(default_factory=dict)
    # Per-band Tx-side impedance after UnUn  (R_in, X_in) in Ω
    band_R_tx:  Dict[str, float] = field(default_factory=dict)
    band_X_tx:  Dict[str, float] = field(default_factory=dict)
    # Source tag per band: "NEC2-H", "NEC2-V", or "empirical"
    band_imp_src: Dict[str, str] = field(default_factory=dict)
    # CP orientation that produced the lowest VSWR per band ("H", "V", or "empirical")
    band_cp_src: Dict[str, str] = field(default_factory=dict)

    # Aggregate scores (lower = better)
    score_vswr:      float = 999.0
    score_vswr_raw:  float = 999.0
    score_avoidance: float = 0.0
    score_avoidance_active: float = 0.0
    score_combined:  float = 999.0

    nec2_ok:    bool = True
    note:       str  = ""

    # Sloping wire: z of the far (non-feedpoint) end; None = horizontal wire
    wire_slope_end_m: Optional[float] = None


def _vswr_score_single(vswr: float) -> float:
    """
    Map a VSWR value to a penalty score:
      ≤1.5 → 0, ≤3.0 → linear 0–1, ≤6.0 → linear 1–3, >6 → 3 + log

    The segment ≤6.0 must reach exactly 3.0 at vswr=6.0:
      (6.0 - 3.0) / 1.5 = 2.0  → total = 1.0 + 2.0 = 3.0 ✓
    """
    if vswr <= 1.5:
        return 0.0
    elif vswr <= 3.0:
        return (vswr - 1.5) / 1.5
    elif vswr <= 6.0:
        return 1.0 + (vswr - 3.0) / 1.5
    else:
        return 3.0 + math.log10(vswr / 6.0) * 5.0


def score_candidate(
    wire_len_m: float,
    cp_len_m: float,
    calc_rows: List[CalcRow],
    unun_ratio: float,
    run_h: Optional[NEC2Run] = None,
    run_v: Optional[NEC2Run] = None,
    cp_type_hint: str = "horizontal",
    nec2_strict: bool = False,
) -> CandidateResult:
    """
    Compute the aggregate quality score for a candidate geometry.

    VSWR scoring: active bands only (bands with active=YES in the CSV).
    Avoidance scoring: ALL bands in the CSV, regardless of active flag.

    If NEC2 run results are provided they are used; otherwise the empirical
    formulas are used as a fast fallback — UNLESS nec2_strict=True, in which
    case any band whose frequency is not found in the NEC2 output is marked
    as failed (VSWR=999, nec2_ok=False) rather than silently falling back.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        raise ValueError("No active bands in CSV")

    res = CandidateResult(wire_len_m=wire_len_m, cp_len_m=cp_len_m,
                          cp_type=cp_type_hint,
                          nec2_ok=(run_h is not None or run_v is not None))

    vswr_penalties = []
    avoidances = []

    # ── VSWR scoring: ACTIVE bands only ────────────────────────────────
    for cr in active:
        freq = cr.freq_mhz

        best_vswr = None
        best_R: Optional[float] = None
        best_X: Optional[float] = None
        imp_src = "empirical"

        for run, src_tag in [(run_h, "NEC2-H"), (run_v, "NEC2-V")]:
            if run is None:
                continue
            fmap = run.freq_map()
            if not fmap:
                continue
            key = min(fmap.keys(), key=lambda k: abs(k - freq))
            _tol = max(0.15, min(0.75, 0.04 * freq))
            if abs(key - freq) > _tol:
                continue
            fp = fmap[key]
            R_ant, X_ant = fp.R_ohm, fp.X_ohm
            # An n:1 impedance transformer scales BOTH R and X by 1/n
            if unun_ratio > 1.0:
                R_in = R_ant / unun_ratio
                X_in = X_ant / unun_ratio   # X must also be divided by n
            else:
                R_in, X_in = R_ant, X_ant
            g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
            v = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
            if best_vswr is None or v < best_vswr:
                best_vswr = v
                best_R, best_X = R_ant, X_ant
                imp_src = src_tag

        if best_vswr is None:
            if nec2_strict:
                best_vswr = 999.0
                best_R    = math.nan
                best_X    = math.nan
                imp_src   = "NEC2-MISS"
                res.nec2_ok = False
                res.note  += f" NEC2 miss@{freq}MHz"
            else:
                lhalf = C_MHZ / (2.0 * freq) if freq else 1.0
                ratio_l = wire_len_m / lhalf if lhalf else 0.0
                arg = math.pi * ratio_l
                cos2 = math.cos(arg) ** 2
                best_R = max(1.0, 50.0 * (80.0 ** cos2))
                best_X = 1500.0 * math.sin(2.0 * arg)
                if unun_ratio > 1.0:
                    R_in_emp = best_R / unun_ratio
                    X_in_emp = best_X / unun_ratio
                else:
                    R_in_emp, X_in_emp = best_R, best_X
                _g = math.hypot(R_in_emp - 50, X_in_emp) / math.hypot(R_in_emp + 50, X_in_emp)
                best_vswr = (1 + _g) / (1 - _g) if _g < 1 else 999.0
                res.nec2_ok = False
                imp_src = "empirical"

        res.band_R_ant[cr.band]   = round(best_R, 2) if not math.isnan(best_R) else math.nan
        res.band_X_ant[cr.band]   = round(best_X, 2) if not math.isnan(best_X) else math.nan
        res.band_imp_src[cr.band] = imp_src
        if imp_src == "NEC2-H":
            res.band_cp_src[cr.band] = "H"
        elif imp_src == "NEC2-V":
            res.band_cp_src[cr.band] = "V"
        else:
            res.band_cp_src[cr.band] = "empirical"

        if math.isnan(best_R) or math.isnan(best_X):
            res.band_R_tx[cr.band] = 0.0
            res.band_X_tx[cr.band] = 0.0
        elif unun_ratio > 1.0:
            res.band_R_tx[cr.band] = round(best_R / unun_ratio, 3)
            res.band_X_tx[cr.band] = round(best_X / unun_ratio, 3)
        else:
            res.band_R_tx[cr.band] = round(best_R, 3)
            res.band_X_tx[cr.band] = round(best_X, 3)

        res.band_vswr[cr.band] = round(best_vswr, 3)
        vswr_penalties.append(_vswr_score_single(best_vswr))

    # ── Store impedances for INACTIVE bands ────────────────────────────
    _src_votes = list(res.band_cp_src.values())
    _dominant_cp = (("H" if _src_votes.count("H") >= _src_votes.count("V")
                    else "V") if _src_votes else "H")
    _inactive_run_order = (
        [(run_h, "NEC2-H"), (run_v, "NEC2-V")] if _dominant_cp == "H"
        else [(run_v, "NEC2-V"), (run_h, "NEC2-H")]
    )
    inactive = [r for r in calc_rows if not r.active]
    for cr in inactive:
        if cr.band in res.band_R_ant:
            continue
        freq = cr.freq_mhz
        found_R: Optional[float] = None
        found_X: Optional[float] = None
        found_src = "empirical"
        for run, src_tag in _inactive_run_order:
            if run is None:
                continue
            fmap = run.freq_map()
            if not fmap:
                continue
            key = min(fmap.keys(), key=lambda k: abs(k - freq))
            _tol = max(0.15, min(0.75, 0.04 * freq))
            if abs(key - freq) > _tol:
                continue
            fp = fmap[key]
            found_R, found_X = fp.R_ohm, fp.X_ohm
            found_src = src_tag
            break
        if found_R is None and not nec2_strict:
            lhalf = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio_l = wire_len_m / lhalf if lhalf else 0.0
            arg = math.pi * ratio_l
            cos2 = math.cos(arg) ** 2
            found_R = max(1.0, 50.0 * (80.0 ** cos2))
            found_X = 1500.0 * math.sin(2.0 * arg)
            found_src = "empirical"
        if found_R is not None:
            res.band_R_ant[cr.band]   = round(found_R, 2)
            res.band_X_ant[cr.band]   = round(found_X, 2)
            res.band_imp_src[cr.band] = found_src

    # ── Avoidance score: computed over ALL bands in the CSV ─────────────
    for cr in calc_rows:
        freq = cr.freq_mhz
        lambda_qtr = C_MHZ / (4.0 * freq)          # λ/4 — resonances occur at every multiple
        ratio = wire_len_m / lambda_qtr             # how many λ/4 nodes does wire_len span?
        frac = ratio % 1.0
        avoidance = min(frac, 1.0 - frac)           # 0 = at node; max = 0.5 mid-way between λ/4 nodes (clamped to 0.25 below)
        # Clamp to the theoretical maximum of 0.25 (midway between two adjacent λ/4 resonances)
        avoidance = min(avoidance, 0.25)
        res.band_avoidance[cr.band] = round(avoidance, 4)
        avoidances.append(avoidance)

    # Counterpoise λ/4 proximity bonus (active bands only)
    # Reward cp lengths near ODD multiples of λ/4 (1×, 3×, 5× …) — low-impedance return.
    # Even multiples (λ/2, λ, …) give high-impedance return and receive no bonus.
    cp_lambda_quarter_scores = []
    for cr in active:
        lq = C_MHZ / (4.0 * cr.freq_mhz)
        cp_ratio = cp_len_m / lq           # how many λ/4 units is the CP?
        # Map to distance from nearest odd multiple: (cp_ratio mod 2) centred on 1
        mod2 = cp_ratio % 2.0              # 0…2: odd multiples fall near 1, even near 0 or 2
        dist_from_odd = abs(mod2 - 1.0)   # 0 = exactly odd λ/4; 1 = exactly even λ/4
        cp_score = 0.25 * math.cos(math.pi * dist_from_odd / 2.0) ** 2
        cp_lambda_quarter_scores.append(cp_score)

    n = len(vswr_penalties)
    mean_vswr_penalty   = sum(vswr_penalties) / n if n else 999.0
    worst_vswr_penalty  = max(vswr_penalties) if vswr_penalties else 999.0
    res.score_vswr      = mean_vswr_penalty
    res.score_vswr_raw  = mean_vswr_penalty + 1.5 * worst_vswr_penalty
    res.score_avoidance = sum(avoidances) / len(avoidances) if avoidances else 0.0

    active_avoidances = [res.band_avoidance[cr.band] for cr in active
                         if cr.band in res.band_avoidance]
    res.score_avoidance_active = (sum(active_avoidances) / len(active_avoidances)
                                  if active_avoidances else 0.0)

    cp_avoid_mean = (sum(cp_lambda_quarter_scores) / len(cp_lambda_quarter_scores)
                     if cp_lambda_quarter_scores else 0.0)

    res.score_combined = (mean_vswr_penalty
                          + 1.5 * worst_vswr_penalty
                          - 0.5 * res.score_avoidance_active
                          - 0.1 * cp_avoid_mean)

    return res


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH GRID BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_search_grid(
    wire_min: float,
    wire_max: float,
    wire_step: float,
    cp_min: float,
    cp_max: float,
    cp_step: float,
) -> List[Tuple[float, float]]:
    """Return all (wire_len, cp_len) grid combinations to evaluate.

    Points are clamped to [wire_min, wire_max] / [cp_min, cp_max] so that
    non-integer step sizes (e.g. 0.3 m over a 2 m range) never produce
    candidates outside the requested bounds.
    """
    n_w = round((wire_max - wire_min) / wire_step)
    wires = [round(min(wire_min + i * wire_step, wire_max), 3) for i in range(n_w + 1)]

    n_c = round((cp_max - cp_min) / cp_step)
    cps = [round(min(cp_min + i * cp_step, cp_max), 3) for i in range(n_c + 1)]

    return list(itertools.product(wires, cps))


# ═══════════════════════════════════════════════════════════════════════════
# EMPIRICAL-ONLY SWEEP  (fast, no NEC2)
# ═══════════════════════════════════════════════════════════════════════════

def empirical_sweep(
    grid: List[Tuple[float, float]],
    calc_rows: List[CalcRow],
    unun_ratio: float,
    cp_type: str,
    wire_slope_end_m: Optional[float] = None,  # None → horizontal
    verbose: bool = False,
) -> List[CandidateResult]:
    if wire_slope_end_m is not None:
        print(f"\n  {Fore.YELLOW}WARNING: --wire-slope-end-height is set but mode is empirical. "
              f"Empirical impedance formulas assume a horizontal wire and will give "
              f"inaccurate results for a sloped geometry. "
              f"Re-run with --mode nec2 for accurate results.{Style.RESET_ALL}\n")
    results = []
    total = len(grid)
    for i, (w, c) in enumerate(grid):
        if verbose and i % max(1, total // 20) == 0:
            pct = i * 100 // total
            print(T("sweep_empirical_pct").format(pct, i, total, w, c), end="\r")
        r = score_candidate(w, c, calc_rows, unun_ratio, cp_type_hint=cp_type)
        r.wire_slope_end_m = wire_slope_end_m
        results.append(r)
    if verbose:
        print(T("sweep_empirical_done").format(total))
    return results


# ═══════════════════════════════════════════════════════════════════════════
# NEC2 SWEEP  (slower, accurate)
# ═══════════════════════════════════════════════════════════════════════════

def nec2_sweep(
    grid: List[Tuple[float, float]],
    calc_rows: List[CalcRow],
    unun_ratio: float,
    nec2c_bin: str,
    wire_height_m: float,
    cp_height_m: float,
    ground_cond: float,
    ground_diel: float,
    cp_types: List[str],
    wire_slope_end_m: Optional[float] = None,  # None → horizontal wire
    verbose: bool = True,
) -> List[CandidateResult]:
    """
    Full NEC2 sweep.  For each (wire, cp) pair we run nec2c for each
    cp_type requested, then score with NEC2 impedance data.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        raise ValueError("No active bands in CSV")
    freqs  = [cr.freq_mhz for cr in calc_rows]   # ALL bands

    results: List[CandidateResult] = []
    total = len(grid) * len(cp_types)
    done  = 0

    with tempfile.TemporaryDirectory(prefix="nec2opt_") as tmpdir:
        for w, c in grid:
            runs_by_type: Dict[str, Optional[NEC2Run]] = {}

            for cpt in cp_types:
                done += 1
                if verbose:
                    print(T("sweep_nec2_progress").format(done, total, w, c, cpt), end="\r")

                tag   = f"w{w:.3f}_c{c:.3f}_{cpt}"
                nec_p = os.path.join(tmpdir, tag + ".nec")
                out_p = os.path.join(tmpdir, tag + ".out")

                write_nec_deck(
                    nec_path=nec_p,
                    wire_len_m=w,
                    cp_len_m=c,
                    cp_type=cpt,
                    freqs_mhz=freqs,
                    wire_height_m=wire_height_m,
                    wire_slope_end_m=wire_slope_end_m,
                    cp_height_m=cp_height_m,
                    ground_cond=ground_cond,
                    ground_diel=ground_diel,
                )

                ok = run_nec2c(nec2c_bin, nec_p, out_p)
                if ok:
                    try:
                        run = parse_nec2_output(out_p, debug=False,
                                                explicit_nec_path=nec_p)
                        if run is not None and not run.freq_map():
                            run = None
                        runs_by_type[cpt] = run
                    except Exception:
                        runs_by_type[cpt] = None
                else:
                    runs_by_type[cpt] = None

            run_h = runs_by_type.get("horizontal")
            run_v = runs_by_type.get("vertical")

            def _cp_actual_label(cpt: str, w_h: float, c_h: float, c_len: float) -> str:
                if cpt != "vertical":
                    return cpt
                avail_drop = w_h - c_h
                return "vertical" if c_len <= avail_drop + 0.01 else "L-shaped"

            if len(cp_types) == 1:
                actual_label = _cp_actual_label(cp_types[0], wire_height_m, cp_height_m, c)
                cand = score_candidate(
                    wire_len_m=w,
                    cp_len_m=c,
                    calc_rows=calc_rows,
                    unun_ratio=unun_ratio,
                    run_h=run_h,
                    run_v=run_v,
                    cp_type_hint=actual_label,
                    nec2_strict=True,
                )
                cand.wire_slope_end_m = wire_slope_end_m
                results.append(cand)
            else:
                candidates_this = []
                for cpt, r_h, r_v in [
                    ("horizontal", run_h, None),
                    ("vertical",   None,  run_v),
                ]:
                    if runs_by_type.get(cpt) is None:
                        sibling = "vertical" if cpt == "horizontal" else "horizontal"
                        if runs_by_type.get(sibling) is not None:
                            print("\n" + T("warn_nec2_failed_cp").format(cpt, w, c, sibling), flush=True)
                        continue
                    actual_label_dual = _cp_actual_label(cpt, wire_height_m,
                                                           cp_height_m, c)
                    c_cand = score_candidate(
                        wire_len_m=w,
                        cp_len_m=c,
                        calc_rows=calc_rows,
                        unun_ratio=unun_ratio,
                        run_h=r_h,
                        run_v=r_v,
                        cp_type_hint=actual_label_dual,
                        nec2_strict=True,
                    )
                    c_cand.wire_slope_end_m = wire_slope_end_m
                    candidates_this.append(c_cand)

                if not candidates_this:
                    cand = CandidateResult(
                        wire_len_m=w, cp_len_m=c, cp_type="both",
                        score_combined=999.0, score_vswr_raw=999.0,
                        score_vswr=999.0, score_avoidance=0.0,
                        nec2_ok=False, note="NEC2 failed (both orientations)",
                        wire_slope_end_m=wire_slope_end_m,
                    )
                    results.append(cand)
                else:
                    best_cand = min(candidates_this, key=lambda r: r.score_combined)
                    results.append(best_cand)

    if verbose:
        print(T("sweep_nec2_done").format(total))

    return results


# ═══════════════════════════════════════════════════════════════════════════
# RESULT RANKING & PARETO
# ═══════════════════════════════════════════════════════════════════════════

def rank_results(results: List[CandidateResult]) -> List[CandidateResult]:
    return sorted(results, key=lambda r: r.score_combined)


def pareto_front(results: List[CandidateResult]) -> List[CandidateResult]:
    """
    Return Pareto-optimal candidates: those not dominated on
    (score_vswr_raw, score_avoidance_active).  Lower score_vswr_raw AND
    higher active-band avoidance = better.

    Algorithm (O(n log n)):
      1. Sort by score_vswr_raw ascending (ties: avoidance descending).
      2. Sweep left to right keeping track of the maximum avoidance seen so far.
         A candidate is Pareto-optimal iff no earlier candidate (equal or lower
         VSWR penalty) already has equal or higher avoidance.  Equivalently,
         a new candidate joins the front whenever its avoidance exceeds ALL
         avoidances seen so far — guaranteeing it cannot be dominated.
    """
    if not results:
        return []
    # Sort ascending by VSWR penalty; ties broken by descending avoidance
    sorted_r = sorted(results,
                      key=lambda r: (r.score_vswr_raw, -r.score_avoidance_active))
    pareto: List[CandidateResult] = []
    max_avoid_so_far = -float("inf")
    for r in sorted_r:
        # r is dominated iff some earlier entry has vswr_raw ≤ r.vswr_raw
        # (guaranteed by sort) AND avoidance ≥ r.avoidance.
        # r escapes domination only if its avoidance exceeds every prior avoidance.
        if r.score_avoidance_active > max_avoid_so_far:
            pareto.append(r)
            max_avoid_so_far = r.score_avoidance_active
        elif r.score_avoidance_active == max_avoid_so_far and pareto:
            # Equal avoidance: include r only if its vswr equals the previous
            # front member's vswr (i.e., they are tied on both axes — neither
            # dominates the other).
            if abs(pareto[-1].score_vswr_raw - r.score_vswr_raw) < 1e-9:
                pareto.append(r)
    return pareto


# ═══════════════════════════════════════════════════════════════════════════
# UnUn OPTIMISER
# ═══════════════════════════════════════════════════════════════════════════

STANDARD_UNUN_RATIOS: List[float] = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0,
                                      12.0, 16.0, 25.0, 27.0, 36.0, 49.0, 64.0]

@dataclass
class UnUnResult:
    """Outcome of the UnUn sweep for one antenna geometry."""
    ratio_band_vswr: Dict[float, Dict[str, float]] = field(default_factory=dict)
    ratio_score: Dict[float, float] = field(default_factory=dict)

    best_standard_ratio: float = 9.0
    best_standard_score: float = 999.0
    best_continuous_ratio: float = 9.0
    best_continuous_score: float = 999.0

    per_band_best_ratio: Dict[str, float] = field(default_factory=dict)
    per_band_best_vswr:  Dict[str, float] = field(default_factory=dict)

    band_impedances: List[Tuple[str, float, float]] = field(default_factory=list)


def _vswr_for_ratio(R_ant: float, X_ant: float, n: float,
                    z0: float = 50.0) -> float:
    """
    Compute VSWR at the transmitter (Z0=50Ω) through an n:1 impedance
    transformer (ideal UnUn / balun).
    """
    if n <= 0:
        return 999.0
    if math.isnan(R_ant) or math.isnan(X_ant):
        return 999.0
    R_in = R_ant / n
    X_in = X_ant / n
    denom = math.hypot(R_in + z0, X_in)
    if denom < 1e-12:
        return 999.0
    gamma = math.hypot(R_in - z0, X_in) / denom
    if gamma >= 1.0:
        return 999.0
    return (1.0 + gamma) / (1.0 - gamma)


def _aggregate_vswr_penalty(band_impedances: List[Tuple[str, float, float]],
                              n: float, z0: float = 50.0) -> float:
    """Compute the aggregate VSWR penalty for a given UnUn ratio n."""
    if not band_impedances:
        return 999.0
    penalties = []
    for _band, R, X in band_impedances:
        v = _vswr_for_ratio(R, X, n, z0)
        penalties.append(_vswr_score_single(v))
    mean_pen  = sum(penalties) / len(penalties)
    worst_pen = max(penalties)
    return mean_pen + 1.5 * worst_pen


def _golden_section_min(f, lo: float, hi: float,
                         tol: float = 1e-4) -> Tuple[float, float]:
    """Find the minimum of scalar function f on [lo, hi]."""
    n_coarse = 200
    step = (hi - lo) / n_coarse
    best_x = lo
    best_v = f(lo)
    prev_x = lo
    best_lo_r, best_hi_r = lo, lo + step
    for i in range(1, n_coarse + 1):
        x = lo + i * step
        v = f(x)
        if v < best_v:
            best_v = v
            best_x = x
            best_lo_r = prev_x
            best_hi_r = min(x + step, hi)
        prev_x = x

    phi = (math.sqrt(5) - 1) / 2
    a, b = best_lo_r, best_hi_r
    c = b - phi * (b - a)
    d = a + phi * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(100):
        if abs(b - a) < tol:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = f(d)
    x = (a + b) / 2
    v = f(x)
    return (x, v) if v <= best_v else (best_x, best_v)


def find_best_unun(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    current_unun: float,
    run_h: Optional["NEC2Run"] = None,
    run_v: Optional["NEC2Run"] = None,
    z0: float = 50.0,
    nec2_strict: bool = False,
) -> UnUnResult:
    """
    Given the best antenna geometry (wire_len, cp_len), sweep UnUn ratios
    to find which one minimises aggregate VSWR across all active bands.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        return UnUnResult()

    band_impedances: List[Tuple[str, float, float]] = []

    for cr in active:
        freq = cr.freq_mhz
        R_ant: Optional[float] = None
        X_ant: Optional[float] = None

        if cr.band in best.band_R_ant and cr.band in best.band_X_ant:
            R_ant = best.band_R_ant[cr.band]
            X_ant = best.band_X_ant[cr.band]
            if math.isnan(R_ant) or math.isnan(X_ant):
                R_ant = None
                X_ant = None

        if R_ant is None and (run_h is not None or run_v is not None):
            best_R_local: Optional[float] = None
            best_X_local: Optional[float] = None
            best_vswr_local: float = 999.0
            for run in [run_h, run_v]:
                if run is None:
                    continue
                fmap = run.freq_map()
                if not fmap:
                    continue
                key = min(fmap.keys(), key=lambda k: abs(k - freq))
                _tol = max(0.15, min(0.75, 0.04 * freq))
                if abs(key - freq) > _tol:
                    continue
                fp = fmap[key]
                cand_vswr = _vswr_for_ratio(fp.R_ohm, fp.X_ohm, current_unun)
                if best_R_local is None or cand_vswr < best_vswr_local:
                    best_vswr_local = cand_vswr
                    best_R_local = fp.R_ohm
                    best_X_local = fp.X_ohm
            R_ant = best_R_local
            X_ant = best_X_local

        if R_ant is None:
            if nec2_strict:
                band_impedances.append((cr.band, math.nan, math.nan))
                continue
            lhalf = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio = best.wire_len_m / lhalf if lhalf else 0.0
            arg = math.pi * ratio
            cos2 = math.cos(arg) ** 2
            R_ant = max(1.0, 50.0 * (80.0 ** cos2))
            X_ant = 1500.0 * math.sin(2.0 * arg)

        band_impedances.append((cr.band, R_ant, X_ant))

    if not band_impedances:
        return UnUnResult()

    result = UnUnResult()
    result.band_impedances = band_impedances

    ratios_to_sweep: List[float] = list(STANDARD_UNUN_RATIOS)
    if current_unun not in ratios_to_sweep:
        ratios_to_sweep = sorted(ratios_to_sweep + [current_unun])

    for n in ratios_to_sweep:
        bv: Dict[str, float] = {}
        for band, R, X in band_impedances:
            bv[band] = round(_vswr_for_ratio(R, X, n, z0), 3)
        result.ratio_band_vswr[n] = bv
        result.ratio_score[n] = _aggregate_vswr_penalty(band_impedances, n, z0)

    best_std = min(STANDARD_UNUN_RATIOS, key=lambda n: result.ratio_score[n])
    result.best_standard_ratio = best_std
    result.best_standard_score = result.ratio_score[best_std]

    def _obj(n: float) -> float:
        return _aggregate_vswr_penalty(band_impedances, n, z0)

    cont_n, cont_score = _golden_section_min(_obj, 1.0, 100.0)
    result.best_continuous_ratio = round(cont_n, 2)
    result.best_continuous_score = round(cont_score, 4)

    _BOUNDARY_TOL = 0.5
    if cont_n <= 1.0 + _BOUNDARY_TOL:
        import warnings
        warnings.warn(
            f"UnUn continuous optimum ({cont_n:.2f}:1) is at the lower search bound "
            "(1.0:1). The true optimum may be a direct connection (no transformer). "
            "Re-run without an UnUn if that makes physical sense.",
            RuntimeWarning, stacklevel=2,
        )
    elif cont_n >= 100.0 - _BOUNDARY_TOL:
        import warnings
        warnings.warn(
            f"UnUn continuous optimum ({cont_n:.2f}:1) hit the upper search bound "
            "(100.0:1). The true minimum-VSWR ratio may be even higher. "
            "Inspect the antenna-side impedance and consider a custom winding ratio.",
            RuntimeWarning, stacklevel=2,
        )

    for band, R, X in band_impedances:
        def _band_obj(n: float, _R=R, _X=X) -> float:
            return _vswr_for_ratio(_R, _X, n, z0)
        n_opt, _ = _golden_section_min(_band_obj, 1.0, 100.0)
        result.per_band_best_ratio[band] = round(n_opt, 2)
        result.per_band_best_vswr[band]  = round(_vswr_for_ratio(R, X, n_opt, z0), 3)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# REPORT WRITER
# ═══════════════════════════════════════════════════════════════════════════

def write_report(
    ranked: List[CandidateResult],
    pareto: List[CandidateResult],
    calc_rows: List[CalcRow],
    unun_ratio: float,
    wire_range: Tuple[float, float, float],
    cp_range:   Tuple[float, float, float],
    mode: str,
    out_path: str,
    unun_result: Optional[UnUnResult] = None,
    total_candidates: int = 0,
    wire_height_m: float = DEFAULT_HEIGHT_M,
) -> str:
    active = [r for r in calc_rows if r.active]
    bands  = [cr.band for cr in active]

    SEP  = "═" * 80
    lines = []

    def h1(t):
        lines.extend(["", SEP, f"  {t}", SEP])

    def h2(t):
        lines.extend(["", f"  ── {t} " + "─" * max(2, 74 - len(t))])

    def ln(t=""):
        lines.append(f"  {t}")

    h1(T("report_title"))
    ln(T("report_mode").format(mode.upper()))
    ln(T("report_unun").format(unun_ratio))
    ln(T("report_wire_range").format(wire_range[0], wire_range[1], wire_range[2]))
    ln(T("report_cp_range").format(cp_range[0], cp_range[1], cp_range[2]))

    # Show slope geometry if any ranked result carries it
    _any_slope = next((r.wire_slope_end_m for r in ranked if r.wire_slope_end_m is not None), None)
    if _any_slope is not None:
        ln(T("report_wire_geom_sloped_summary").format(_any_slope))
    else:
        ln(T("report_wire_geom_horizontal"))
    all_bands_list  = [cr.band for cr in calc_rows]
    active_band_set = set(cr.band for cr in active)
    band_labels = [f"{b}(*)" if b in active_band_set else b for b in all_bands_list]
    ln(T("report_active_bands").format(len(active), len(calc_rows), ', '.join(band_labels)))

    display_total = total_candidates if total_candidates > 0 else len(ranked)
    ln(T("report_total_candidates").format(display_total))
    lines.append("")

    # ── TOP 20 RANKING ───────────────────────────────────────────────────
    top_n = len(ranked)
    h1(T("report_top_n_header").format(top_n))
    header = (f"  {'#':>3}  {'Wire(m)':>8}  {'CP(m)':>7}  {'CP type':>10}  "
              f"{'Score':>7}  {'meanPen':>9}  {'1.5xWpen':>9}  {'-0.5xAv(a)':>10}  {'-0.1xCPbon':>11}  "
              + "  ".join(f"{b:>7}" for b in bands)
              + "  NEC2")
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))

    for rank, r in enumerate(ranked[:top_n], 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        nec_flag = "✓" if r.nec2_ok else "emp"
        # Use stored score_vswr_raw (= mean + 1.5×worst) to avoid re-deriving from
        # rounded band_vswr values — prevents accumulation of rounding error.
        _mean_vswr_pen     = r.score_vswr           # stored mean penalty
        _worst_pen_weighted = r.score_vswr_raw - r.score_vswr  # 1.5 × worst
        # CP bonus contribution = score_vswr_raw − 0.5×avoid_active − score_combined
        _cp_bonus_deduction = -(r.score_vswr_raw
                                - 0.5 * r.score_avoidance_active
                                - r.score_combined)
        lines.append(
            f"  {rank:3d}  {r.wire_len_m:8.3f}  {r.cp_len_m:7.3f}  {r.cp_type:>10}  "
            f"{r.score_combined:7.3f}  {_mean_vswr_pen:9.3f}  {_worst_pen_weighted:9.3f}  "
            f"{-0.5*r.score_avoidance_active:10.4f}  {_cp_bonus_deduction:11.4f}  "
            f"{band_cols}  {nec_flag}"
        )

    # ── PARETO FRONT ─────────────────────────────────────────────────────
    h1(T("report_pareto_header").format(len(pareto)))
    ln(T("report_pareto_note"))
    lines.append("")
    pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
    for rank, r in enumerate(pareto_ranked, 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        lines.append(
            f"  {rank:3d}  wire={r.wire_len_m:.3f} m  cp={r.cp_len_m:.3f} m"
            f"  ({r.cp_type})  score={r.score_combined:.3f}"
            f"  VSWR=[{band_cols}]"
            f"  avoid_active={r.score_avoidance_active:.4f}"
            f"  avoid_all={r.score_avoidance:.4f}"
        )

    # ── BEST CANDIDATE DETAIL ────────────────────────────────────────────
    if ranked:
        best = ranked[0]
        h1(T("report_best_header"))
        ln(T("report_wire_len").format(best.wire_len_m))
        ln(T("report_cp_len").format(best.cp_len_m, best.cp_type))
        if best.wire_slope_end_m is not None:
            ln(T("report_wire_geom_sloped_detail").format(wire_height_m, best.wire_slope_end_m))
        else:
            ln(T("report_wire_geom_horizontal_const"))
        ln(T("report_combined_score").format(best.score_combined))
        ln(T("report_vswr_penalty").format(best.score_vswr))
        ln(T("report_avoidance_act").format(best.score_avoidance_active))
        ln(T("report_avoidance_all").format(best.score_avoidance))
        ln(T("report_nec2_used").format(T("report_nec2_yes") if best.nec2_ok else T("report_nec2_no")))

        _tol_r = 1e-6
        _wmin, _wmax, _ = wire_range
        _cmin, _cmax, _ = cp_range
        _hits_wire = sum(
            1 for r in ranked[:5]
            if abs(r.wire_len_m - _wmin) < _tol_r or abs(r.wire_len_m - _wmax) < _tol_r
        )
        _hits_cp = sum(
            1 for r in ranked[:5]
            if abs(r.cp_len_m - _cmin) < _tol_r or abs(r.cp_len_m - _cmax) < _tol_r
        )
        if abs(best.wire_len_m - _wmax) < _tol_r:
            ln(T("report_warn_wire_max").format(_wmax, _hits_wire))
        elif abs(best.wire_len_m - _wmin) < _tol_r:
            ln(T("report_warn_wire_min").format(_wmin, _hits_wire))
        if abs(best.cp_len_m - _cmax) < _tol_r:
            ln(T("report_warn_cp_max").format(_cmax, _hits_cp))
        elif abs(best.cp_len_m - _cmin) < _tol_r:
            ln(T("report_warn_cp_min").format(_cmin, _hits_cp))
        lines.append("")

        ln(T("report_per_band"))
        _hdr_b = f"  {'Band':>8}  {'Active':>6}  {'VSWR(Tx)':>9}  {'Avoid':>8}  {'Rating':>22}  VSWR"
        ln(_hdr_b)
        ln("  " + "─" * 80)

        for cr in calc_rows:
            b = cr.band
            a = best.band_avoidance.get(b, 0.0)
            rating = _avoidance_rating(a)
            act_flag = "YES" if cr.active else "no"
            if cr.active:
                v = best.band_vswr.get(b, 999.0)
                if v <= 1.5:
                    vlabel = T("vswr_excellent")
                elif v <= 3.0:
                    vlabel = T("vswr_good")
                elif v <= 6.0:
                    vlabel = T("vswr_marginal")
                else:
                    vlabel = T("vswr_poor")
                ln(f"  {b:>8}  {act_flag:>6}  {v:9.2f}  {a:8.4f}  {rating:>22}  {vlabel}")
            else:
                ln(f"  {b:>8}  {act_flag:>6}  {'—':>9}  {a:8.4f}  {rating:>22}  —")

        lines.append("")
        ln(T("report_per_band_imp"))
        ln(f"  {'Band':>8}  {'freq MHz':>9}  "
           f"{'R_ant Ω':>9}  {'X_ant Ω':>9}  {'|Z_ant|Ω':>10}  "
           f"{'R_tx Ω':>8}  {'X_tx Ω':>8}  {'|Z_tx|Ω':>9}  "
           f"{'VSWR':>6}  {'Source':>10}")
        ln("  " + "─" * 100)
        for cr in active:
            b    = cr.band
            f    = cr.freq_mhz
            R_a  = best.band_R_ant.get(b, 0.0)
            X_a  = best.band_X_ant.get(b, 0.0)
            R_t  = best.band_R_tx.get(b, 0.0)
            X_t  = best.band_X_tx.get(b, 0.0)
            Z_a  = math.hypot(R_a, X_a)
            Z_t  = math.hypot(R_t, X_t)
            v    = best.band_vswr.get(b, 999.0)
            src  = best.band_imp_src.get(b, "?")
            ln(f"  {b:>8}  {f:9.4f}  "
               f"{R_a:9.1f}  {X_a:+9.1f}  {Z_a:10.1f}  "
               f"{R_t:8.2f}  {X_t:+8.2f}  {Z_t:9.2f}  "
               f"{v:6.2f}  {src:>10}")
        ln(T("report_unun_note").format(unun_ratio))

    # ── UnUn OPTIMISATION ────────────────────────────────────────────────
    if unun_result is not None:
        h1(T("report_unun_section"))
        ln(T("report_unun_used").format(unun_ratio))

        cont_n = unun_result.best_continuous_ratio
        boundary_note = ""
        if cont_n >= 99.5:
            boundary_note = T("report_unun_cont_hit_upper")
        elif cont_n <= 1.5:
            boundary_note = T("report_unun_cont_hit_lower")
        ln(T("report_unun_continuous").format(cont_n, unun_result.best_continuous_score, boundary_note))

        std_n = unun_result.best_standard_ratio
        std_score = unun_result.best_standard_score
        ln(T("report_unun_best_std").format(std_n, std_score))

        cur_score = unun_result.ratio_score[unun_ratio]
        if cur_score > 0:
            delta = cur_score - std_score
            pct = 100.0 * delta / cur_score
            if delta > 0.001:
                ln(T("report_unun_improve").format(std_n, delta, pct))
                if abs(std_n - unun_ratio) > 0.5:
                    ln(T("report_unun_rerank").format(unun_ratio))
                    ln(T("report_unun_rerun").format(std_n))
            else:
                ln(T("report_unun_already_optimal").format(unun_ratio))

        lines.append("")

        ln(T("report_std_sweep"))
        hdr_bands = "  ".join(f"{'VSWR@'+b:>9}" for b in bands)
        ln(f"  {'Ratio':>6}  {'Score':>7}  {hdr_bands}")
        ln("  " + "─" * (6 + 2 + 7 + 2 + max(0, 11 * len(bands))))
        for n in sorted(unun_result.ratio_score.keys()):
            score = unun_result.ratio_score[n]
            bv_cols = "  ".join(
                f"{unun_result.ratio_band_vswr[n].get(b, 999):9.2f}" for b in bands
            )
            marker = " ◄ BEST" if n == std_n else (
                     " ← CURRENT" if n == unun_ratio else "")
            ratio_str = f"{n:.4g}"
            ln(f"  {ratio_str:>5}:1  {score:7.4f}  {bv_cols}{marker}")

        if unun_result.band_impedances:
            lines.append("")
            ln(T("report_ant_impedance"))
            ln(f"  {'Band':>8}  {'R_ant Ω':>9}  {'X_ant Ω':>9}  {'|Z_ant| Ω':>10}  {'θ °':>7}")
            ln("  " + "─" * 52)
            for bname, R_a, X_a in unun_result.band_impedances:
                Z_a   = math.hypot(R_a, X_a)
                theta = math.degrees(math.atan2(X_a, R_a))
                ln(f"  {bname:>8}  {R_a:9.1f}  {X_a:+9.1f}  {Z_a:10.1f}  {theta:+7.1f}")

        lines.append("")
        ln(T("report_perband_optimal"))
        ln(f"  {'Band':>8}  {'Best ratio':>12}  {'VSWR':>7}")
        ln("  " + "─" * 34)
        for b in bands:
            opt_n = unun_result.per_band_best_ratio.get(b, None)
            opt_v = unun_result.per_band_best_vswr.get(b, None)
            opt_n_str = f"{opt_n:10.2f}:1" if opt_n is not None else f"{'N/A (no NEC2)':>11}"
            opt_v_str = f"{opt_v:7.3f}"    if opt_v is not None else f"{'---':>7}"
            ln(f"  {b:>8}  {opt_n_str}  {opt_v_str}")

        lines.append("")
        ln(T("report_perband_conflict_note"))
        ln(T("report_perband_conflict_note2"))
        ln(T("report_perband_conflict_note3"))

    # ── PHYSICAL INTERPRETATION ──────────────────────────────────────────
    h1(T("report_physical_header"))
    notes = [
        (T("note1_title"), T("note1_body")),
        (T("note2_title"), T("note2_body")),
        (T("note3_title"), T("note3_body").format(unun_ratio)),
        (T("note4_title"), T("note4_body")),
        (T("note5_title"), T("note5_body")),
    ]
    for i, (title, body) in enumerate(notes, 1):
        ln(f"{i}. {title}")
        for line in textwrap.wrap(body, width=74):
            ln(f"   {line}")
        lines.append("")

    h1(T("report_end"))

    report_text = "\n".join(lines)

    clean = re.sub(r'\x1b\[[0-9;]*m', '', report_text)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(clean)

    return report_text


# ═══════════════════════════════════════════════════════════════════════════
# CSV EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _recompute_vswr(R_ant: float, X_ant: float, unun_ratio: float,
                    z0: float = 50.0) -> float:
    """Recompute Tx-side VSWR for given antenna impedance and UnUn ratio."""
    if math.isnan(R_ant) or math.isnan(X_ant):
        return 999.0
    if unun_ratio > 1.0:
        R_in = R_ant / unun_ratio
        X_in = X_ant / unun_ratio
    else:
        R_in, X_in = R_ant, X_ant
    denom = math.hypot(R_in + z0, X_in)
    if denom < 1e-12:
        return 999.0
    gamma = math.hypot(R_in - z0, X_in) / denom
    if gamma >= 1.0:
        return 999.0
    return round((1.0 + gamma) / (1.0 - gamma), 3)


def export_best_csv(
    best: CandidateResult,
    calc_rows: List[CalcRow],
    unun_ratio: float,
    out_path: str,
) -> None:
    """
    Write a CSV pre-filled with the best wire/CP lengths.
    Columns are compatible with the standard band-analysis CSV format.

    Column notes:
      vswr_no_cp   — antenna-side VSWR (no UnUn, empirical formula, no CP correction)
      vswr_with_cp — Tx-side VSWR after UnUn (best stored impedance or empirical fallback)
      R_wire_ohm / X_wire_ohm — antenna-side impedance (NEC2 if available, else empirical)
    """
    fieldnames = [
        "band", "freq_mhz", "active", "lambda_half_m", "lambda_qtr_m",
        "wire_len_m", "L_over_lhalf", "R_wire_ohm", "X_wire_ohm",
        "vswr_no_cp", "vswr_with_cp", "Z_eff_ohm", "Zcp_ohm",
        "unun_ratio", "avoidance_score", "quality_rating",
        "cp_len_m", "cp_height_m", "num_radials",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for cr in calc_rows:
            freq = cr.freq_mhz
            lhalf = C_MHZ / (2.0 * freq) if freq else 0.0
            w = best.wire_len_m

            _stored_R = best.band_R_ant.get(cr.band)
            _stored_X = best.band_X_ant.get(cr.band)
            if (_stored_R is not None and _stored_X is not None
                    and not math.isnan(_stored_R) and not math.isnan(_stored_X)):
                R = _stored_R
                X = _stored_X
            else:
                ratio_emp = w / lhalf if lhalf else 0.0
                arg = math.pi * ratio_emp
                cos2 = math.cos(arg) ** 2
                R = max(1.0, 50 * (80 ** cos2))
                X = 1500 * math.sin(2 * arg)

            lhalf_emp = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio_emp = w / lhalf_emp if lhalf_emp else 0.0
            arg_emp = math.pi * ratio_emp
            cos2_emp = math.cos(arg_emp) ** 2
            R_no_cp = max(1.0, 50.0 * (80.0 ** cos2_emp))
            X_no_cp = 1500.0 * math.sin(2.0 * arg_emp)
            # vswr_no_cp: antenna-side VSWR ref 50 Ω, no UnUn, empirical formula.
            # This represents the bare wire impedance before the UnUn transformer.
            vswr_no = _recompute_vswr(R_no_cp, X_no_cp, 1.0)  # ratio=1 → antenna side

            lambda_qtr = lhalf / 2.0 if lhalf else 0.0
            ratio_qtr = w / lambda_qtr if lambda_qtr else 0.0
            frac_qtr = ratio_qtr % 1.0
            avoid = min(min(frac_qtr, 1.0 - frac_qtr), 0.25)
            rating = _avoidance_rating(avoid)

            writer.writerow({
                "band":           cr.band,
                "freq_mhz":       freq,
                "active":         "YES" if cr.active else "NO",
                "lambda_half_m":  round(lhalf, 4),
                "lambda_qtr_m":   round(lambda_qtr, 4),
                "wire_len_m":     w,
                "L_over_lhalf":   round(w / lhalf if lhalf else 0.0, 4),
                "R_wire_ohm":     round(R, 2),
                "X_wire_ohm":     round(X, 2),
                "vswr_no_cp":     round(vswr_no, 3),
                "vswr_with_cp":   _recompute_vswr(R, X, unun_ratio)
                                  if cr.active else "",
                "Z_eff_ohm":      round(math.hypot(R, X), 2),
                "Zcp_ohm":        "",
                "unun_ratio":     unun_ratio,
                "avoidance_score":round(avoid, 4),
                "quality_rating": rating,
                "cp_len_m":       best.cp_len_m,
                "cp_height_m":    cr.cp_height_m if cr.cp_height_m is not None else 0.5,
                "num_radials":    cr.num_radials if cr.num_radials is not None else 1,
            })


# ═══════════════════════════════════════════════════════════════════════════
# BEST-ANTENNA NEC2 DECK WRITER
# ═══════════════════════════════════════════════════════════════════════════

def write_best_nec_deck(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    out_path: str,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,
    cp_height_m: float = 0.5,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
    n_elevation: int = 37,
    n_azimuth: int = 73,
) -> None:
    """
    Write a full NEC2 deck for the best antenna geometry with complete
    radiation pattern (RP) cards for every active band.
    """
    active = [r for r in calc_rows if r.active]
    freqs_active = [cr.freq_mhz for cr in active]
    freqs_all    = [cr.freq_mhz for cr in calc_rows]

    highest_f = max(freqs_all) if freqs_all else 30.0
    cp_type   = best.cp_type if best.cp_type != "both" else "horizontal"

    with open(out_path, "w") as fh:
        fh.write("CM ============================================================\n")
        fh.write("CM  NEC2 Best-Antenna Deck — generated by nec2_length_optimizer\n")
        fh.write(f"CM  Wire length : {best.wire_len_m:.3f} m\n")
        fh.write(f"CM  CP length   : {best.cp_len_m:.3f} m  ({cp_type})\n")
        fh.write(f"CM  CP score    : {best.score_combined:.4f}\n")
        for cr in active:
            b = cr.band
            v = best.band_vswr.get(b, 999.0)
            fh.write(f"CM  {b:>6}  {cr.freq_mhz:.4f} MHz  VSWR={v:.2f}\n")
        fh.write("CM ============================================================\n")
        fh.write("CE\n")

        segs_ant = _segs(best.wire_len_m, highest_f)
        segs_cp  = max(5, _segs(best.cp_len_m, highest_f))

        # ── Wire-1 coordinates (slope-aware) ────────────────────────────
        _slope_end = wire_slope_end_m if wire_slope_end_m is not None else best.wire_slope_end_m
        _z_near = wire_height_m
        # GE 1: ground plane present — required for GN Sommerfeld-Norton to take effect.
        if _slope_end is not None:
            _z_far = max(float(_slope_end), wire_radius_m)
            _rise  = _z_near - _z_far
            _x_far = math.sqrt(max(0.0, best.wire_len_m**2 - _rise**2))
        else:
            _z_far   = _z_near
            _x_far   = best.wire_len_m
        _ge_flag = 1

        fh.write(f"GW 1 {segs_ant} "
                 f"0.0 0.0 {_z_near:.3f} "
                 f"{_x_far:.3f} 0.0 {_z_far:.4f} "
                 f"{wire_radius_m:.5f}\n")

        if cp_type == "horizontal":
            drop_len = wire_height_m - cp_height_m
            if drop_len > 0.01:
                segs_drop = max(5, _segs(drop_len, highest_f))
                fh.write(f"GW 2 {segs_drop} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
                fh.write(f"GW 3 {segs_cp} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{-best.cp_len_m:.3f} 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
            else:
                fh.write(f"GW 2 {segs_cp} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"{-best.cp_len_m:.3f} 0.0 {wire_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
        else:
            cp_bottom_z = max(cp_height_m, wire_height_m - best.cp_len_m)
            vert_len    = max(0.0, wire_height_m - cp_bottom_z)
            horiz_rem   = max(0.0, best.cp_len_m - vert_len)
            if vert_len > 0.01:
                segs_cp_v   = max(5, _segs(vert_len, highest_f))
                if segs_cp_v % 2 == 0:
                    segs_cp_v += 1
                fh.write(f"GW 2 {segs_cp_v} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"0.0 0.0 {cp_bottom_z:.3f} "
                         f"{wire_radius_m:.5f}\n")
            if horiz_rem > 0.01:
                segs_cp_h = max(3, _segs(horiz_rem, highest_f))
                if segs_cp_h % 2 == 0:
                    segs_cp_h += 1
                fh.write(f"GW 3 {segs_cp_h} "
                         f"0.0 0.0 {cp_bottom_z:.3f} "
                         f"{-horiz_rem:.3f} 0.0 {cp_bottom_z:.3f} "
                         f"{wire_radius_m:.5f}\n")

        fh.write(f"GE {_ge_flag}\n")
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        d_theta = 90.0  / max(1, n_elevation - 1)
        d_phi   = 360.0 / max(1, n_azimuth)       # Bug 1 fix: n points span 0..360-d_phi

        # Simulate ALL bands so inactive-band impedance data is also available
        # in the output deck.  RP pattern cards are written only for active bands
        # (radiation diagrams are only meaningful for bands the antenna is used on).
        active_freq_set = set(cr.freq_mhz for cr in active)
        for cr in calc_rows:
            f = cr.freq_mhz
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            if f in active_freq_set:
                fh.write(
                    f"RP 0 {n_elevation} {n_azimuth} 1000 "
                    f"0.0 0.0 {d_theta:.4f} {d_phi:.4f} 0.0\n"
                )
            fh.write("XQ\n")

        fh.write("EN\n")

    print(f"  📡  Best-antenna NEC2 deck saved → {out_path}")


# ═══════════════════════════════════════════════════════════════════════════
# MATPLOTLIB PLOTS
# ═══════════════════════════════════════════════════════════════════════════

def plot_radiation_diagrams(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    nec2c_bin: str,
    out_png: str,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,
    cp_height_m: float = 0.5,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    n_elevation: int = 73,
    n_azimuth:   int = 73,
) -> None:
    """
    Run NEC2 with a full RP pattern for each active band, parse the
    radiation pattern output, and save elevation + azimuth diagrams
    for all active bands to a single PNG.
    """
    if not HAS_MPL:
        print("  matplotlib not available — skipping radiation diagrams.")
        return

    active = [r for r in calc_rows if r.active]
    if not active:
        print("  No active bands — skipping radiation diagrams.")
        return

    cp_type = best.cp_type if best.cp_type != "both" else "horizontal"
    freqs_all = [cr.freq_mhz for cr in calc_rows]

    d_theta = 90.0  / max(1, n_elevation - 1)
    d_phi   = 360.0 / max(1, n_azimuth)           # Bug 1 fix: n points span 0..360-d_phi
    elevations_deg = [i * d_theta for i in range(n_elevation)]
    azimuths_deg   = [i * d_phi   for i in range(n_azimuth)]   # last point = 360-d_phi

    band_patterns: Dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="nec2rad_") as tmpdir:
        nec_path = os.path.join(tmpdir, "best_radiation.nec")
        out_path_nec = os.path.join(tmpdir, "best_radiation.out")

        highest_f = max(freqs_all)
        segs_ant = _segs(best.wire_len_m, highest_f)
        segs_cp  = max(5, _segs(best.cp_len_m, highest_f))

        with open(nec_path, "w") as fh:
            fh.write("CM RP sweep deck\n")

            # ── Wire-1 coordinates (slope-aware) ────────────────────────
            _rad_slope = wire_slope_end_m if wire_slope_end_m is not None else best.wire_slope_end_m
            _rad_z_near = wire_height_m
            # GE 1: ground plane present — required for GN Sommerfeld-Norton to take effect.
            if _rad_slope is not None:
                _rad_z_far = max(float(_rad_slope), WIRE_RADIUS_M)
                _rad_rise  = _rad_z_near - _rad_z_far
                _rad_x_far = math.sqrt(max(0.0, best.wire_len_m**2 - _rad_rise**2))
            else:
                _rad_z_far = _rad_z_near
                _rad_x_far = best.wire_len_m
            _rad_ge    = 1

            fh.write("CE\n")
            fh.write(f"GW 1 {segs_ant} "
                     f"0.0 0.0 {_rad_z_near:.3f} "
                     f"{_rad_x_far:.3f} 0.0 {_rad_z_far:.4f} "
                     f"{WIRE_RADIUS_M:.5f}\n")
            if cp_type == "horizontal":
                drop_len = wire_height_m - cp_height_m
                if drop_len > 0.01:
                    segs_drop = max(5, _segs(drop_len, highest_f))
                    fh.write(f"GW 2 {segs_drop} "
                             f"0.0 0.0 {wire_height_m:.3f} "
                             f"0.0 0.0 {cp_height_m:.3f} "
                             f"{WIRE_RADIUS_M:.5f}\n")
                    fh.write(f"GW 3 {segs_cp} "
                             f"0.0 0.0 {cp_height_m:.3f} "
                             f"{-best.cp_len_m:.3f} 0.0 {cp_height_m:.3f} "
                             f"{WIRE_RADIUS_M:.5f}\n")
                else:
                    fh.write(f"GW 2 {segs_cp} "
                             f"0.0 0.0 {wire_height_m:.3f} "
                             f"{-best.cp_len_m:.3f} 0.0 {wire_height_m:.3f} "
                             f"{WIRE_RADIUS_M:.5f}\n")
            else:
                cp_bottom_z = max(cp_height_m, wire_height_m - best.cp_len_m)
                vert_len = max(0.0, wire_height_m - cp_bottom_z)
                horiz_rem = max(0.0, best.cp_len_m - vert_len)
                if vert_len > 0.01:
                    segs_cp_v = max(5, _segs(vert_len, highest_f))
                    if segs_cp_v % 2 == 0:
                        segs_cp_v += 1
                    fh.write(f"GW 2 {segs_cp_v} "
                             f"0.0 0.0 {wire_height_m:.3f} "
                             f"0.0 0.0 {cp_bottom_z:.3f} "
                             f"{WIRE_RADIUS_M:.5f}\n")
                if horiz_rem > 0.01:
                    segs_cp_h = max(3, _segs(horiz_rem, highest_f))
                    if segs_cp_h % 2 == 0:
                        segs_cp_h += 1
                    fh.write(f"GW 3 {segs_cp_h} "
                             f"0.0 0.0 {cp_bottom_z:.3f} "
                             f"{-horiz_rem:.3f} 0.0 {cp_bottom_z:.3f} "
                             f"{WIRE_RADIUS_M:.5f}\n")
            fh.write(f"GE {_rad_ge}\n")
            fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
            fh.write("EX 0 1 1 0 1.0 0.0\n")

            for cr in active:
                fh.write(f"FR 0 1 0 0 {cr.freq_mhz:.4f} 0\n")
                fh.write(
                    f"RP 0 {n_elevation} {n_azimuth} 1000 "
                    f"0.0 0.0 {d_theta:.4f} {d_phi:.4f} 0.0\n"
                )
                fh.write("XQ\n")
            fh.write("EN\n")

        ok = run_nec2c(nec2c_bin, nec_path, out_path_nec, timeout=120)
        if not ok:
            print(f"  ⚠  NEC2 radiation run failed — skipping radiation diagrams.")
            return

        try:
            with open(out_path_nec, "r", errors="replace") as fh:
                raw = fh.read()
        except Exception as e:
            print(f"  ⚠  Cannot read NEC2 output: {e}")
            return

        _has_rp_section = any(
            "RADIATION PATTERN" in _ln.upper()
            and "REQUESTED" not in _ln.upper()
            and not _ln.strip().startswith("CM")
            and not _ln.strip().startswith("*")
            for _ln in raw.splitlines()
        )
        if not _has_rp_section:
            print("  ⚠  NEC2 output contains no RADIATION PATTERN section.")
            return

        parsed_patterns: Dict[float, list] = {}

        _active_freqs = [cr.freq_mhz for cr in active]
        _rp_block_idx    = -1
        _cur_freq_ord: Optional[float] = None
        _cur_freq_ban: Optional[float] = None

        _freq_re = re.compile(r'FREQUENCY\s*=\s*([0-9.E+\-]+)\s*MHZ', re.IGNORECASE)
        # Each column is a proper signed floating-point number, optionally in
        # scientific notation.  The old pattern ([\d.E+\-]+) was a character
        # class that matched arbitrary sequences of digits, dots, E, +, and -
        # — it could not represent a signed number correctly and would also
        # match separator lines like "----" (caught only by the later
        # ValueError).  The pattern below uses a proper numeric grammar:
        #   [-+]?          optional sign
        #   (?:\d+\.?\d*   integer-part with optional decimal, OR
        #      |\.\d+)     leading-dot decimal
        #   (?:[Ee][+\-]?\d+)?  optional exponent
        _SFLOAT = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+\-]?\d+)?'
        _rp_row_re = re.compile(
            rf'^\s*({_SFLOAT})\s+({_SFLOAT})'
            rf'\s+({_SFLOAT})\s+({_SFLOAT})'
            rf'\s+({_SFLOAT})',
            re.MULTILINE,
        )

        in_rp = False

        for line in raw.splitlines():
            fm = _freq_re.search(line)
            if fm:
                try:
                    _cur_freq_ban = float(fm.group(1))
                except ValueError:
                    pass
                continue

            stripped = line.strip()
            if ("RADIATION PATTERN" in line.upper()
                    and "REQUESTED" not in line.upper()
                    and not stripped.startswith("CM")
                    and not stripped.startswith("*")):
                in_rp = False           # Bug 2 fix: stop collecting for previous block immediately
                _rp_block_idx += 1
                if _rp_block_idx < len(_active_freqs):
                    _cur_freq_ord = _active_freqs[_rp_block_idx]
                    if (_cur_freq_ban is not None
                            and abs(_cur_freq_ban - _cur_freq_ord) > 0.5):
                        print(
                            f"  ⚠  RP block {_rp_block_idx+1}: "
                            f"order freq {_cur_freq_ord:.4f} MHz differs from "
                            f"banner {_cur_freq_ban:.4f} MHz — using order."
                        )
                    existing = parsed_patterns.get(_cur_freq_ord, [])
                    if len(existing) == 0:
                        parsed_patterns[_cur_freq_ord] = []
                    in_rp = True
                else:
                    in_rp = False   # Bug 2 fix: also reset here for out-of-range blocks
                continue

            if in_rp and _cur_freq_ord is not None:
                m = _rp_row_re.match(line)
                if m:
                    try:
                        theta    = float(m.group(1))
                        phi      = float(m.group(2))
                        total_db = float(m.group(5))
                        bucket = parsed_patterns[_cur_freq_ord]
                        bucket.append((theta, phi, total_db))   # Bug 3 fix: removed broken dedupe guard
                    except ValueError:
                        pass

        if not parsed_patterns:
            print(T("warn_no_rp_data"))
            return

        for cr in active:
            freq = cr.freq_mhz
            best_key = min(parsed_patterns.keys(), key=lambda k: abs(k - freq))
            if abs(best_key - freq) > 0.5:
                print(T("warn_no_rp_freq").format(freq, cr.band))
                continue
            rows = parsed_patterns[best_key]
            if not rows:
                continue

            elev_data = sorted(
                [(90.0 - t, db) for (t, p, db) in rows if abs(p) < 1.0 or abs(p - 360) < 1.0],
                key=lambda x: x[0]
            )
            if rows:
                all_db  = [db for (_, _, db) in rows]
                max_db  = max(all_db)

                # ── Azimuth: max-gain envelope per phi ──────────────────────
                # For each azimuth angle φ keep the highest gain found at ANY
                # elevation θ.  This is the standard antenna-pattern convention
                # and correctly reveals directional patterns (e.g. the two
                # broadside lobes of a 1.76λ wire on 20 m).  The old approach
                # took a single horizontal slice at the θ of the global-max
                # point; when that maximum fell near zenith (θ_nec ≈ 0–1°)
                # the cut looked omnidirectional and hid real directionality.
                _az_env: dict = {}   # phi_deg (rounded 2 dp) → max dBi
                for (_t3, _p3, _db3) in rows:
                    _pk = round(_p3, 2)
                    if _pk not in _az_env or _db3 > _az_env[_pk]:
                        _az_env[_pk] = _db3
                az_data = sorted(_az_env.items(), key=lambda x: x[0])

                # TOA: θ of the global-max gain point (first occurrence in
                # parse order, i.e. lowest θ that matches within 0.1 dB)
                best_theta = None
                for (_t3, _p3, _db3) in rows:
                    if abs(_db3 - max_db) < 0.1:
                        best_theta = _t3
                        break
            else:
                max_db     = -999.0
                az_data    = []
                best_theta = None

            toa = 90.0 - (best_theta if best_theta is not None else 90.0)

            band_patterns[cr.band] = {
                "freq_mhz": freq,
                "elev": elev_data,
                "azim": az_data,
                "raw":  rows,       # full (theta_nec, phi, dBi) point cloud for 3-D plot
                "max_db": max_db,
                "toa_deg": toa,
                "vswr": best.band_vswr.get(cr.band, 999.0),
            }

    if not band_patterns:
        print(T("warn_no_rp_bands"))
        return

    band_list = [cr.band for cr in active if cr.band in band_patterns]
    n_bands = len(band_list)          # must match band_list length exactly
    if n_bands == 0:
        print(T("warn_no_rp_bands"))
        return

    # ── MMANA-GAL-style renderer (v2) ────────────────────────────────────
    # White background, correct elevation orientation (horizon at bottom,
    # zenith at top), true dBi rings, clean lobe rendering.
    import numpy as _np

    # ── Design tokens ────────────────────────────────────────────────────
    _BG        = "white"
    _FG        = "#111111"     # axis labels, titles, info text
    _RING_COL  = "#ccddee"     # concentric dB ring lines
    _RING_TXT  = "#336699"     # dB ring labels
    _SPOKE_COL = "#ccddee"     # radial spoke lines
    _ANG_TXT   = "#224466"     # compass / degree tick labels
    _LOBE_EL   = "#0077cc"     # elevation lobe stroke (blue)
    _FILL_EL   = "#0099ff"     # elevation lobe fill
    _LOBE_AZ   = "#cc6600"     # azimuth lobe stroke  (orange)
    _FILL_AZ   = "#ff8800"     # azimuth lobe fill
    _TOA_COL   = "#cc0000"     # TOA dashed marker
    _DB_STEPS  = 5             # dB per concentric ring
    _DB_RINGS  = 6             # rings → 30 dB total dynamic range

    # ── Helper: clamp raw point cloud to a sensible dB floor ─────────────
    def _clamp_raw(raw_pts, floor_db=None, dyn=_DB_STEPS * _DB_RINGS + 5):
        """Return raw_pts with gain values clamped to [max-dyn, max]."""
        if not raw_pts:
            return raw_pts
        g_max = max(db for (_, _, db) in raw_pts)
        if floor_db is None:
            floor_db = g_max - dyn
        return [(t, p, max(db, floor_db)) for (t, p, db) in raw_pts]

    # ── Core polar drawing helper ─────────────────────────────────────────
    def _draw_polar(ax, angles_rad, gains_raw,
                    stroke, fill_c,
                    title_str, info_str,
                    toa_rad=None,
                    theta_min=-90, theta_max=90,
                    tick_degs=None, tick_labels=None):
        """
        Draw one MMANA-GAL polar panel.

        Elevation:   theta_min=-90, theta_max=90, zero_loc='E'
                     angles_rad in [−π/2 … +π/2] (mirrored sweep)
        Azimuth:     theta_min=0,  theta_max=360, zero_loc='N'
                     angles_rad in [0 … 2π]
        """
        ax.set_facecolor(_BG)
        try:
            ax.spines["polar"].set_color(_RING_COL)
        except Exception:
            pass

        dyn_db  = _DB_STEPS * _DB_RINGS

        if gains_raw:
            g_max   = max(gains_raw)
            g_floor = g_max - dyn_db

            def _r(db):
                return max(0.0, db - g_floor)

            r_vals = [_r(g) for g in gains_raw]
        else:
            g_max = 0.0
            r_vals = []

        # ── Concentric dB rings ───────────────────────────────────────
        _ring_theta = _np.linspace(
            math.radians(theta_min), math.radians(theta_max), 361)
        for ring_i in range(1, _DB_RINGS + 1):
            r_ring = ring_i * _DB_STEPS
            ax.plot(_ring_theta, [r_ring] * len(_ring_theta),
                    color=_RING_COL, linewidth=0.8, zorder=1)
            # Label innermost 5 rings (skip the outermost boundary ring)
            if ring_i < _DB_RINGS:
                db_label = g_max - (_DB_RINGS - ring_i) * _DB_STEPS
                # Place label at a fixed angular position that stays inside the plot
                if theta_min == -90:   # elevation: place at +20°
                    lbl_angle = math.radians(20)
                else:                  # azimuth: place at 35°
                    lbl_angle = math.radians(35)
                ax.text(lbl_angle, r_ring - 0.6,
                        f"{db_label:.0f}",
                        color=_RING_TXT, fontsize=6.5,
                        ha="center", va="center", zorder=3)

        # ── Radial spokes ─────────────────────────────────────────────
        if tick_degs is not None:
            for sa in tick_degs:
                ax.plot([math.radians(sa), math.radians(sa)],
                        [0, dyn_db],
                        color=_SPOKE_COL, linewidth=0.6, zorder=1)

        # ── Lobe ──────────────────────────────────────────────────────
        if r_vals:
            ax.fill(angles_rad, r_vals, color=fill_c, alpha=0.20, zorder=2)
            ax.plot(angles_rad, r_vals, color=stroke,  linewidth=2.0, zorder=4)

        # ── TOA marker ────────────────────────────────────────────────
        if toa_rad is not None and r_vals:
            for _sign in (+1, -1):
                ax.plot([_sign * toa_rad, _sign * toa_rad], [0, dyn_db],
                        color=_TOA_COL, linewidth=1.3,
                        linestyle="--", zorder=5, alpha=0.9)

        # ── Axes ──────────────────────────────────────────────────────
        ax.set_rmax(dyn_db)
        ax.set_rmin(0)
        ax.set_rticks([])
        ax.yaxis.set_visible(False)
        ax.set_theta_direction(-1)
        ax.set_thetamin(theta_min)
        ax.set_thetamax(theta_max)

        if tick_degs is not None and tick_labels is not None:
            ax.set_xticks([math.radians(a) for a in tick_degs])
            ax.set_xticklabels(tick_labels, fontsize=7.0, color=_ANG_TXT)
        ax.tick_params(axis="x", pad=5, colors=_ANG_TXT)
        ax.grid(False)

        # ── Title & info ──────────────────────────────────────────────
        ax.set_title(title_str, color=_FG, fontsize=10.5,
                     pad=14, fontweight="bold")
        ax.text(0.5, -0.08, info_str,
                transform=ax.transAxes,
                ha="center", va="top",
                fontsize=7.5, color=_FG,
                fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor="#eef4ff", edgecolor="#aabbcc",
                          alpha=0.7))

    # ── Figure layout ────────────────────────────────────────────────────
    n_cols     = 3
    cell_h     = 5.4
    fig_height = max(5.4, cell_h * n_bands + 1.4)
    fig        = plt.figure(figsize=(18, fig_height), facecolor=_BG)
    fig.suptitle(
        T("plot_radiation_title").format(best.wire_len_m, best.cp_len_m, cp_type),
        fontsize=13, fontweight="bold", color=_FG, y=1.0
    )

    for row_idx, band in enumerate(band_list):
        pat      = band_patterns[band]
        freq_str = f"{pat['freq_mhz']:.3f} MHz"
        vswr_str = f"VSWR {pat['vswr']:.2f}"
        max_str  = f"Max {pat['max_db']:.1f} dBi"
        toa_str  = f"TOA {pat['toa_deg']:.1f}°"
        info     = f"{freq_str}  {vswr_str}  {max_str}  {toa_str}"

        # ── Column 0: Elevation ───────────────────────────────────────
        # elev_data: list of (elevation_deg, dBi)
        #   elevation_deg = 90 − theta_nec,  so  0° = horizon, 90° = zenith
        # We render as a symmetrical upper-hemisphere half-plane:
        #   theta_zero = East  →  0° maps to rightmost spoke
        #   The sweep goes  right (0°=horizon) → top (90°=zenith) → left (0°=horizon)
        #   Mapping:  angle_on_polar = (90° − elevation_deg)  in radians,
        #             then mirrored left/right.
        ax_el = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 1,
                                projection="polar")
        ax_el.set_theta_zero_location("N")   # 0 rad points up → zenith at top

        el_tick_degs   = list(range(-90, 91, 15))
        el_tick_labels = []
        for _a in el_tick_degs:
            _elev = abs(_a)   # elevation = distance from horizon
            el_tick_labels.append(f"{_elev}°" if _elev % 30 == 0 or _elev == 0 else "")

        if pat["elev"]:
            _elevs = [e for (e, _) in pat["elev"]]
            _gains = [g for (_, g) in pat["elev"]]
            # Map elevation angle → polar angle:
            # elevation=0 (horizon) → polar=±90°, elevation=90 (zenith) → polar=0°
            # i.e. polar_angle = 90° − elevation_deg,  then mirror
            _polar_pos = [math.radians(90.0 - e) for e in _elevs]  # 0…π/2
            # Full mirrored sweep: negative side (left) then positive (right)
            _angles_mir = (
                list(reversed([-a for a in _polar_pos])) + list(_polar_pos)
            )
            _gains_mir  = list(reversed(_gains)) + list(_gains)
            toa_r = math.radians(90.0 - pat["toa_deg"])   # convert elev→polar
            _draw_polar(ax_el,
                        _angles_mir, _gains_mir,
                        _LOBE_EL, _FILL_EL,
                        f"{band}  Elevation", info,
                        toa_rad=toa_r,
                        theta_min=-90, theta_max=90,
                        tick_degs=el_tick_degs,
                        tick_labels=el_tick_labels)
        else:
            _draw_polar(ax_el, [], [],
                        _LOBE_EL, _FILL_EL,
                        f"{band}  Elevation", info,
                        theta_min=-90, theta_max=90,
                        tick_degs=el_tick_degs,
                        tick_labels=el_tick_labels)

        # ── Column 1: Azimuth ─────────────────────────────────────────
        ax_az = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 2,
                                projection="polar")
        ax_az.set_theta_zero_location("N")

        az_tick_degs   = list(range(0, 360, 30))
        compass        = {0: "N", 90: "E", 180: "S", 270: "W"}
        az_tick_labels = [compass.get(a, f"{a}°") for a in az_tick_degs]

        if pat["azim"]:
            _azims = [a for (a, _) in pat["azim"]]
            _gains = [g for (_, g) in pat["azim"]]
            _a_rad = [math.radians(a) for a in _azims]
            # Close the loop
            _d_phi_r = math.radians(d_phi)
            if abs(_a_rad[-1] - (2 * math.pi - _d_phi_r)) < 0.02:
                _a_rad  = _a_rad  + [2 * math.pi]
                _gains  = _gains  + [_gains[0]]
            _draw_polar(ax_az,
                        _a_rad, _gains,
                        _LOBE_AZ, _FILL_AZ,
                        f"{band}  Azimuth", info,
                        theta_min=0, theta_max=360,
                        tick_degs=az_tick_degs,
                        tick_labels=az_tick_labels)
        else:
            _draw_polar(ax_az, [], [],
                        _LOBE_AZ, _FILL_AZ,
                        f"{band}  Azimuth", info,
                        theta_min=0, theta_max=360,
                        tick_degs=az_tick_degs,
                        tick_labels=az_tick_labels)

        # ── Column 2: 3-D surface ─────────────────────────────────────
        ax3d = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 3,
                               projection="3d")
        ax3d.set_facecolor(_BG)
        ax3d.set_title(f"{band}  3-D Pattern  {freq_str}",
                       fontsize=10.5, fontweight="bold", color=_FG, pad=8)

        # ── 3-D pattern: upper hemisphere only (theta 0°→90°) ────────────
        # NEC2 with GN 2 (Sommerfeld-Norton ground) produces RP data only
        # for theta 0°→90°.  The correct visualisation is a half-balloon
        # sitting on the Z=0 ground plane.
        #
        # ROOT CAUSE of fin/spike artifacts:
        # Antenna patterns like 40m (TOA=58°) or 20m (TOA=89°) produce
        # non-convex surfaces: R(theta) peaks at the TOA angle then drops
        # to the floor both toward zenith (theta→0) AND toward horizon
        # (theta→90).  This means Z = R·cos(theta) is non-monotonic —
        # it rises from the zenith, peaks near TOA, then falls to zero at
        # the horizon.  matplotlib's plot_surface painter algorithm assigns
        # each face a single Z-centroid depth and sorts on that alone; on a
        # non-monotonic surface multiple faces share similar Z values but
        # are at completely different screen positions, so they composite in
        # the wrong order producing the "spike/fin" artefacts.
        #
        # FIX: replace plot_surface with Poly3DCollection + manual depth sort.
        # We project every face centroid onto the camera view vector and sort
        # back-to-front (furthest face drawn first).  This is the correct
        # painter algorithm and handles non-convex surfaces correctly.
        _raw_pts = _clamp_raw(pat.get("raw", []),
                              dyn=_DB_STEPS * _DB_RINGS)   # 30 dB range
        if _raw_pts:
            _raw_max  = max(db for (_, _, db) in _raw_pts)
            _raw_min  = min(db for (_, _, db) in _raw_pts)

            _thetas_set = sorted({t for (t, _, _) in _raw_pts})
            _phis_set   = sorted({p for (_, p, _) in _raw_pts})
            _grid_lut: dict = {}
            for (t, p, db) in _raw_pts:
                _grid_lut[(round(t, 4), round(p, 4))] = db

            _T  = _np.array(_thetas_set)   # 0° … 90° only
            _P  = _np.array(_phis_set)

            # Pre-fill with NaN sentinel; real NEC2 values overwrite below.
            _DB = _np.full((len(_thetas_set), len(_phis_set)), _np.nan)
            for _i, _t in enumerate(_thetas_set):
                for _j, _p in enumerate(_phis_set):
                    _key = (round(_t, 4), round(_p, 4))
                    if _key in _grid_lut:
                        _DB[_i, _j] = _grid_lut[_key]

            # ── Fill missing (theta, phi) grid cells ─────────────────────
            # ROOT CAUSE of "spike fan + washed-out green" on 40m/20m:
            # the previous code filled every missing cell with _raw_min
            # (= g_max - 30 dB after clamping, i.e. the BOTTOM of the
            # colour range).  When the parsed point cloud doesn't form a
            # perfectly dense theta×phi grid (a few cells missing — e.g.
            # one RP block ending early or a duplicate-angle row), those
            # flat-floor cells:
            #   1. create deep "valleys" immediately next to full-height
            #      neighbours → thin radial spike/fin silhouettes, and
            #   2. drag a large fraction of the face-colour samples down
            #      to vmin, so the turbo colormap renders almost entirely
            #      blue/green with the true high-gain (red/yellow) lobe
            #      reduced to a few isolated faces.
            # Fix: fill missing cells by interpolating from neighbouring
            # theta rows at the same phi (linear, nearest-available),
            # falling back to the row mean, then to _raw_min only if an
            # entire row/column is empty.  This keeps the surface smooth
            # and keeps colours representative of the true gain pattern.
            for _j in range(_DB.shape[1]):
                _col = _DB[:, _j]
                _valid = ~_np.isnan(_col)
                if _valid.any() and not _valid.all():
                    _idx_valid = _np.where(_valid)[0]
                    _DB[:, _j] = _np.interp(
                        _np.arange(len(_col)),
                        _idx_valid, _col[_idx_valid])
            # Any rows/columns that were entirely NaN (no data anywhere
            # for that theta) — fill from the overall mean of valid data.
            if _np.isnan(_DB).any():
                _overall_mean = _np.nanmean(_DB) if not _np.all(_np.isnan(_DB)) else _raw_min
                _DB = _np.where(_np.isnan(_DB), _overall_mean, _DB)

            # ── Smooth pole rows (zenith side) ────────────────────────────
            # At theta=0, sin(θ)=0 so X=Y=0 for all φ regardless of DB.  If
            # DB varies across φ at theta=0 (or at very small theta, where
            # sin(θ)≈0 collapses nearly all points to the same XYZ location
            # but R still differs per-φ), the result is a fan of thin
            # "spike/fin" wedges radiating from the apex — the artefact
            # visible on the 40m/20m 3-D plots (high-TOA patterns whose
            # peak gain sits at or very near theta≈0).  10m (TOA=15°,
            # low-elevation pattern) has its peak far from the pole and is
            # unaffected.
            #
            # Fix: average DB across φ for EVERY theta row close enough to
            # the pole that sin(θ) is small (theta <= ~2×dθ), not just the
            # exact theta=0 row.  This collapses all near-apex points to a
            # consistent radius, eliminating the fin artefacts while leaving
            # the rest of the pattern (including any genuine high-TOA lobe
            # that is NOT exactly at the pole) intact.
            _pole_tol_deg = max(2.0 * (_thetas_set[1] - _thetas_set[0])
                                 if len(_thetas_set) > 1 else 0.0, 1e-6)
            for _i, _t in enumerate(_thetas_set):
                if _t <= _pole_tol_deg:
                    _DB[_i, :] = _DB[_i, :].mean()

            # ── Close the phi loop ───────────────────────────────────────
            # NEC2 outputs phi 0°…360°−dφ.  Append phi=360° = phi=0° column
            # so the last meridional strip stitches to the first.
            if len(_phis_set) > 1 and _phis_set[-1] < 359.9:
                _P  = _np.append(_P, 360.0)
                _DB = _np.concatenate([_DB, _DB[:, :1]], axis=1)

            # ── Trim horizon rows (theta near 90°) ───────────────────────
            # ROOT CAUSE of the green half-disk on 40m/20m:
            # At theta=90° (horizon), cos(90°)=0 so Z=0 for every phi.
            # The last strip of faces (between theta≈88.75° and theta=90°)
            # therefore lies nearly flat at Z=0, spanning the full 0→360°
            # phi range — forming a complete horizontal disc.  Its turbo
            # colour (mid-range green, ~-10 to -15 dB) is the green disk.
            # Fix: discard all theta rows within 2° of the horizon before
            # building the mesh.  The pattern is physically zero along the
            # exact horizon anyway (ground reflection kills it), so no
            # information is lost, and the surface closes cleanly above Z=0.
            _horizon_cutoff = 88.0   # degrees — trim theta >= this value
            _keep = _T < _horizon_cutoff
            if _keep.sum() < 2:
                _keep = _T <= _T[-2]   # always keep at least 2 rows
            _T  = _T[_keep]
            _DB = _DB[_keep, :]

            _TG, _PG = _np.meshgrid(_T, _P, indexing="ij")

            # ── Normalise R via dB-to-amplitude: R = 10^((dB - max)/20) ──
            _R3D_FLOOR = 0.01
            _R = _np.maximum(_R3D_FLOOR, 10.0 ** ((_DB - _raw_max) / 20.0))

            # ── Smooth R in the near-pole rows too ───────────────────────
            # The DB pole-smoothing above already makes _DB[0,:] uniform
            # (a single averaged value repeated across all φ), so _R[0,:]
            # is already uniform too — every point on the θ=0 row maps to
            # X=Y=0 (since sin(0)=0) regardless of R, so R itself doesn't
            # even matter at θ=0.  The remaining "needle" artefact comes
            # from a *radius discontinuity* between the θ=0 row and the
            # θ=dθ row: forcing R[0,:] to the θ=dθ row's mean (as before)
            # can introduce a jump if the pole-smoothed DB at θ=0 differs
            # substantially from the (non-averaged) θ=dθ values.  Instead,
            # blend the θ=0 radius toward the θ=dθ row's mean radius using
            # the pole-smoothed DB-derived value as a starting point, which
            # keeps the apex height continuous with its neighbours without
            # discarding the smoothed gain information.
            if _R.shape[0] > 1:
                _r0 = _R[0, :].mean()
                _r1 = _R[1, :].mean()
                _R[0, :] = 0.5 * (_r0 + _r1)

            # ── Spherical → Cartesian (upper hemisphere: Z >= 0) ─────────
            _theta_rad = _np.radians(_TG)   # 0…π/2
            _phi_rad   = _np.radians(_PG)
            _X = _R * _np.sin(_theta_rad) * _np.cos(_phi_rad)
            _Y = _R * _np.sin(_theta_rad) * _np.sin(_phi_rad)
            _Z = _R * _np.cos(_theta_rad)

            # ── Colormap and normalization ────────────────────────────────
            _get_cm  = (lambda n: _mpl_cm.colormaps[n]) \
                       if hasattr(_mpl_cm, "colormaps") else plt.get_cmap
            # "turbo" has better perceptual uniformity than "jet":
            # blue=low gain, green=mid, red=peak.
            try:
                _cmap = _get_cm("turbo")
            except KeyError:
                _cmap = _get_cm("jet")

            # Fixed 30 dB window so colours match the 2-D ring labels.
            _COLOUR_DYN = float(_DB_STEPS * _DB_RINGS)   # 30 dB
            _norm = _mpl_colors.Normalize(
                vmin=_raw_max - _COLOUR_DYN,
                vmax=_raw_max,
            )

            # ── Dynamic view elevation based on TOA ───────────────────────
            # Keep camera at a low-to-mid angle so the ground disc is never
            # seen face-on (which turns it into a solid half-disk).
            _toa_deg = pat.get("toa_deg", 30.0)
            if _toa_deg >= 70.0:
                _view_elev = 35   # near-zenith: moderate angle
            elif _toa_deg >= 45.0:
                _view_elev = 30   # mid-elevation
            else:
                _view_elev = 25   # near-horizon: show horizontal spread

            # ── Camera view vector for depth sorting ──────────────────────
            # matplotlib view_init(elev, azim): camera sits at
            #   (cos(elev)*cos(azim), cos(elev)*sin(azim), sin(elev)) * dist
            # The vector FROM camera TOWARD origin (into scene):
            _ve = math.radians(_view_elev)
            _va = math.radians(-55.0)          # azim fixed at -55°
            _cam_in = _np.array([
                -math.cos(_ve) * math.cos(_va),
                -math.cos(_ve) * math.sin(_va),
                -math.sin(_ve),
            ])

            # ── Build face list: quads + depth + colour ───────────────────
            # Lambertian shading is intentionally omitted: it crushes colors
            # on high-TOA (near-zenith) lobes where face normals point
            # upward and the lateral light vector yields near-zero dot
            # products, forcing all faces toward the ambient floor and
            # collapsing the full turbo colour range to a narrow dark band.
            # Pure colormap colours faithfully convey gain across all bands.

            _nt, _np2 = _X.shape
            _n_faces  = (_nt - 1) * (_np2 - 1)
            _verts3d  = []     # list of (4,3) vertex arrays
            _depths   = _np.empty(_n_faces)
            _fcolors  = []

            _idx = 0
            for _fi in range(_nt - 1):
                for _fj in range(_np2 - 1):
                    _v = _np.array([
                        [_X[_fi,   _fj],   _Y[_fi,   _fj],   _Z[_fi,   _fj]  ],
                        [_X[_fi+1, _fj],   _Y[_fi+1, _fj],   _Z[_fi+1, _fj]  ],
                        [_X[_fi+1, _fj+1], _Y[_fi+1, _fj+1], _Z[_fi+1, _fj+1]],
                        [_X[_fi,   _fj+1], _Y[_fi,   _fj+1], _Z[_fi,   _fj+1]],
                    ])
                    _verts3d.append(_v)

                    # Depth = projection of centroid onto the inward camera ray.
                    # Larger value → face is further from camera → draw first.
                    _c = _v.mean(axis=0)
                    _depths[_idx] = _np.dot(_c, _cam_in)

                    # Per-face dB (average of 4 vertices)
                    _db_f = (_DB[_fi,   _fj]   + _DB[_fi+1, _fj] +
                             _DB[_fi+1, _fj+1] + _DB[_fi,   _fj+1]) / 4.0

                    # Direct colormap lookup — no shading multiplier so the
                    # full turbo blue→green→red range is preserved on every
                    # antenna pattern regardless of lobe orientation.
                    _rgba = _cmap(_norm(_db_f))
                    _fcolors.append(_rgba)

                    _idx += 1

            # ── Ground-plane disc faces (Z=0) ──────────────────────────────
            # Built as quads in the SAME Poly3DCollection as the pattern
            # surface so a single back-to-front depth sort orders both
            # together.
            #
            # ROOT CAUSE of the flat green/grey "wedge slicing through the
            # lobe" on 40m/20m: the pattern's θ=90° row (horizon) also lies
            # at Z=0 with R up to 1.0 — i.e. it is COPLANAR with the disc
            # (radius 1.0, Z=0) over a wide overlapping area.  Coplanar
            # faces have centroids whose projection onto _cam_in differ by
            # only floating-point noise, so _np.argsort(-_depths) orders
            # them essentially at random/alternating.  Disc faces (pale
            # grey, alpha 0.25) interleaved in front of pattern faces of
            # similar gain (often turbo-green for the -10..-15 dB band at
            # the horizon) read visually as a flat colored wedge cutting
            # through the lobe.
            #
            # Fix: make the disc strictly smaller and strictly below the
            # pattern surface (radius < 1, Z < 0) so the two surfaces never
            # share a depth value and the painter's sort is unambiguous.
            _disc_n_phi   = 72
            _disc_n_r     = 4
            _disc_radius  = 0.65          # well inside the horizon ring
            _disc_z       = -0.02         # below the Z=0 pattern floor
            _disc_phi   = _np.linspace(0, 2 * _np.pi, _disc_n_phi + 1)
            _disc_r     = _np.linspace(0, _disc_radius, _disc_n_r + 1)
            _DPg, _DRg  = _np.meshgrid(_disc_phi, _disc_r)
            _DXg = _DRg * _np.cos(_DPg)
            _DYg = _DRg * _np.sin(_DPg)
            _DZg = _np.full_like(_DRg, _disc_z)

            _disc_color = (0.7, 0.7, 0.7, 0.10)    # very transparent ground plane
            for _fi in range(_disc_n_r):
                for _fj in range(_disc_n_phi):
                    _v = _np.array([
                        [_DXg[_fi,   _fj],   _DYg[_fi,   _fj],   _DZg[_fi,   _fj]  ],
                        [_DXg[_fi+1, _fj],   _DYg[_fi+1, _fj],   _DZg[_fi+1, _fj]  ],
                        [_DXg[_fi+1, _fj+1], _DYg[_fi+1, _fj+1], _DZg[_fi+1, _fj+1]],
                        [_DXg[_fi,   _fj+1], _DYg[_fi,   _fj+1], _DZg[_fi,   _fj+1]],
                    ])
                    _verts3d.append(_v)
                    _c = _v.mean(axis=0)
                    _depths = _np.append(_depths, _np.dot(_c, _cam_in))
                    _fcolors.append(_disc_color)

            # Sort back-to-front: largest depth (furthest from camera) first.
            _order = _np.argsort(-_depths)   # descending → furthest first

            from mpl_toolkits.mplot3d.art3d import Poly3DCollection as _P3C
            _poly = _P3C(
                [_verts3d[_k] for _k in _order],
                facecolors=[_fcolors[_k] for _k in _order],
                linewidths=0,
                edgecolors="none",
            )
            ax3d.add_collection3d(_poly)

            # ── Colorbar ──────────────────────────────────────────────────
            _sm = _mpl_cm.ScalarMappable(cmap=_cmap, norm=_norm)
            _sm.set_array([])
            _cb = fig.colorbar(_sm, ax=ax3d, shrink=0.52, pad=0.08, aspect=14)
            _cb.set_label("dBi", fontsize=7.5, color=_FG)
            _cb.ax.tick_params(labelsize=6.5, colors=_FG)

        # Fallback view angle if _raw_pts was empty (no data for this band)
        if not _raw_pts:
            _view_elev = 30

        # 3-D cosmetics (white background)
        ax3d.xaxis.pane.fill = False
        ax3d.yaxis.pane.fill = False
        ax3d.zaxis.pane.fill = False
        ax3d.xaxis.pane.set_edgecolor("#cccccc")
        ax3d.yaxis.pane.set_edgecolor("#cccccc")
        ax3d.zaxis.pane.set_edgecolor("#cccccc")
        ax3d.tick_params(labelsize=6, colors=_FG)
        ax3d.xaxis.label.set_color(_FG)
        ax3d.yaxis.label.set_color(_FG)
        ax3d.zaxis.label.set_color(_FG)
        ax3d.set_xlabel("X", fontsize=7, labelpad=2)
        ax3d.set_ylabel("Y", fontsize=7, labelpad=2)
        ax3d.set_zlabel("Z", fontsize=7, labelpad=2)
        ax3d.set_xlim(-1.0, 1.0)
        ax3d.set_ylim(-1.0, 1.0)
        ax3d.set_zlim(-0.02, 1.0)
        try:
            # X and Y span 2 units (-1…1), Z spans 1 unit (0…1).
            # box_aspect must reflect this 2:2:1 ratio so the half-balloon
            # is not vertically squashed into a flat pancake.
            ax3d.set_box_aspect([2.0, 2.0, 1.0])
        except AttributeError:
            pass
        ax3d.view_init(elev=_view_elev, azim=-55)
        ax3d.grid(True, color="#cccccc", linewidth=0.5)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(out_png, dpi=180, bbox_inches="tight",
                facecolor=_BG, edgecolor="none")
    plt.close()
    print(T("radiation_saved").format(out_png))


def plot_results(
    results: List[CandidateResult],
    pareto: List[CandidateResult],
    ranked: List[CandidateResult],
    calc_rows: List[CalcRow],
    unun_ratio: float,
    out_png: str,
) -> None:
    if not HAS_MPL:
        print(T("matplotlib_missing"))
        return

    active = [r for r in calc_rows if r.active]
    bands = [cr.band for cr in active]

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle(T("plot_title"), fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.55, wspace=0.4)

    ax1 = fig.add_subplot(gs[0, :2])
    ws = [r.wire_len_m for r in results]
    cs = [r.cp_len_m   for r in results]
    sc = [r.score_combined for r in results]
    sc_clipped = [min(s, 5.0) for s in sc]
    scatter = ax1.scatter(ws, cs, c=sc_clipped, cmap="RdYlGn_r",
                          s=20, alpha=0.6, vmin=min(sc_clipped), vmax=5.0)
    fig.colorbar(scatter, ax=ax1, label=T("plot_colorbar"))
    pw = [r.wire_len_m for r in pareto]
    pc = [r.cp_len_m   for r in pareto]
    ax1.scatter(pw, pc, marker="*", s=120, c="blue", zorder=5, label=T("plot_pareto_label"))
    if ranked:
        ax1.scatter(ranked[0].wire_len_m, ranked[0].cp_len_m,
                    marker="D", s=160, c="black", zorder=6, label=T("plot_best_label"))
        ax1.annotate(f"Best\n{ranked[0].wire_len_m:.2f}m / {ranked[0].cp_len_m:.2f}m",
                     xy=(ranked[0].wire_len_m, ranked[0].cp_len_m),
                     xytext=(10, 10), textcoords="offset points", fontsize=8)
    ax1.set_xlabel(T("plot_xlabel_wire"))
    ax1.set_ylabel(T("plot_ylabel_cp"))
    ax1.set_title(T("plot_heatmap_title"))
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[0, 2])
    ax2.scatter([r.score_vswr_raw for r in results],
                [r.score_avoidance_active for r in results],
                s=10, alpha=0.4, color="gray", label="All")
    ax2.scatter([r.score_vswr_raw for r in pareto],
                [r.score_avoidance_active for r in pareto],
                s=60, marker="*", color="blue", label="Pareto")
    if ranked:
        ax2.scatter(ranked[0].score_vswr_raw, ranked[0].score_avoidance_active,
                    s=100, marker="D", color="black", label="Best")
    ax2.set_xlabel(T("plot_vswr_xlabel"))
    ax2.set_ylabel(T("plot_avoidance_ylabel"))
    ax2.set_title(T("plot_pareto_title"))
    ax2.legend(fontsize=7)
    ax2.grid(True, alpha=0.3)

    top10 = ranked[:10]
    labels = [f"{r.wire_len_m:.1f}m\n{r.cp_len_m:.1f}m" for r in top10]

    for bi, cr in enumerate(active[:6]):
        row_idx = 1 + bi // 3
        col_idx = bi % 3
        ax = fig.add_subplot(gs[row_idx, col_idx])
        vswrs = [r.band_vswr.get(cr.band, 999) for r in top10]
        colors = ["green" if v <= 1.5 else "orange" if v <= 3.0 else "red"
                  for v in vswrs]
        ax.bar(range(len(top10)), vswrs, color=colors, width=0.7)
        ax.axhline(1.5, color="green", linestyle="--", linewidth=0.8)
        ax.axhline(3.0, color="orange", linestyle="--", linewidth=0.8)
        ax.axhline(6.0, color="red",    linestyle="--", linewidth=0.8)
        ax.set_xticks(range(len(top10)))
        ax.set_xticklabels(labels, fontsize=6, rotation=30, ha="right")
        ax.set_title(f"{cr.band}  {cr.freq_mhz:.3f} MHz", fontsize=9)
        ax.set_ylabel(T("plot_vswr_ylabel"))
        ax.set_ylim(0.9, min(20, max(vswrs) * 1.15 + 0.5))
        ax.grid(True, alpha=0.3, axis="y")

    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(T("plot_saved").format(out_png))


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nec2_length_optimizer.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=T("ap_description"),
    )
    p.add_argument("--csv", metavar="FILE", default=None,
                   help=T("ap_csv"))
    p.add_argument("--bands", metavar="NAMES", default=None,
                   help=T("ap_bands"))
    p.add_argument("--freqs", metavar="MHZ", default=None,
                   help=T("ap_freqs"))
    p.add_argument("--wire-len", metavar="M", type=float, default=None,
                   help=T("ap_wire_len"))
    p.add_argument("--cp-len", metavar="M", type=float, default=None,
                   help=T("ap_cp_len"))
    p.add_argument("--active-bands", metavar="BANDS", default=None,
                   help=T("ap_active_bands"))
    p.add_argument("--unun", metavar="RATIO", type=float, default=None,
                   help=T("ap_unun"))
    p.add_argument("--mode", choices=["empirical", "nec2", "auto"],
                   default="auto",
                   help=T("ap_mode"))
    p.add_argument("--nec2c", metavar="PATH", default=None,
                   help=T("ap_nec2c"))
    p.add_argument("--margin", metavar="M", type=float, default=2.0,
                   help=T("ap_margin"))
    p.add_argument("--wire-min", metavar="M", type=float, default=None,
                   help=T("ap_wire_min"))
    p.add_argument("--wire-max", metavar="M", type=float, default=None,
                   help=T("ap_wire_max"))
    p.add_argument("--wire-step", metavar="M", type=float, default=0.25,
                   help=T("ap_wire_step"))
    p.add_argument("--cp-min", metavar="M", type=float, default=None,
                   help=T("ap_cp_min"))
    p.add_argument("--cp-max", metavar="M", type=float, default=None,
                   help=T("ap_cp_max"))
    p.add_argument("--cp-step", metavar="M", type=float, default=0.25,
                   help=T("ap_cp_step"))
    p.add_argument("--wire-height", metavar="M", type=float, default=None,
                   help=T("ap_wire_height").format(DEFAULT_HEIGHT_M))
    p.add_argument("--wire-slope-end-height", metavar="M", type=float, default=None,
                   help=(
                       "Height of the far (non-feedpoint) wire end above ground in metres. "
                       "0.0 = wire end at ground level (sloping/diagonal wire). "
                       "Omit to keep the default horizontal flat wire. "
                       "When set, NEC2 mode is forced; empirical formulas do not apply."
                   ))
    p.add_argument("--cp-height", metavar="M", type=float, default=None,
                   help=T("ap_cp_height"))
    p.add_argument("--cp-type", choices=["horizontal", "vertical", "both"],
                   default="both",
                   help=T("ap_cp_type"))
    p.add_argument("--ground-cond", metavar="S/M", type=float,
                   default=DEFAULT_GROUND_COND,
                   help=T("ap_ground_cond").format(DEFAULT_GROUND_COND))
    p.add_argument("--ground-diel", metavar="EPS", type=float,
                   default=DEFAULT_GROUND_DIEL,
                   help=T("ap_ground_diel").format(DEFAULT_GROUND_DIEL))
    p.add_argument("--top-n", metavar="N", type=int, default=20,
                   help=T("ap_top_n"))
    p.add_argument("--out-txt", metavar="FILE", default="optimizer_report.txt",
                   help=T("ap_out_txt"))
    p.add_argument("--out-png", metavar="FILE", default="optimizer_plot.png",
                   help=T("ap_out_png"))
    p.add_argument("--out-csv", metavar="FILE", default="optimizer_best.csv",
                   help=T("ap_out_csv"))
    p.add_argument("--out-nec", metavar="FILE", default="best_antenna.nec",
                   help=T("ap_out_nec"))
    p.add_argument("--out-radiation", metavar="FILE", default="radiation_diagrams.png",
                   help=T("ap_out_radiation"))
    p.add_argument("--retry", metavar="N", type=int, default=0,
                   help=T("ap_retry"))
    p.add_argument("--no-interactive", action="store_true",
                   help=T("ap_no_interactive"))
    p.add_argument("--quiet", "-q", action="store_true",
                   help=T("ap_quiet"))
    p.add_argument("--lang", metavar="LANG", default="",
                   choices=["", "en", "es"],
                   help=T("ap_lang"))
    p.add_argument("--gui", action="store_true",
                   help="Open the graphical user interface (all other flags become optional).")
    return p


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print(f"{Fore.CYAN}{'═'*70}")

    # ── Detect language early so --help is already translated ────────────
    # Pre-parse only --lang / -q before building the full parser.
    _pre = argparse.ArgumentParser(add_help=False)
    _pre.add_argument("--lang", default="")
    _pre.add_argument("--gui", action="store_true")
    _pre_args, _ = _pre.parse_known_args()
    _init_lang(getattr(_pre_args, "lang", ""))

    # ── GUI mode: launch tkinter front-end and exit ───────────────────────
    if getattr(_pre_args, "gui", False):
        _launch_gui()
        return

    print("  " + T("banner_title"))
    print(f"{'═'*70}{Style.RESET_ALL}")
    print()


    parser = _build_parser()
    args, _unknown = parser.parse_known_args()
    # Language already initialised above; honour an explicit flag in the full parse too.
    _init_lang(getattr(args, "lang", ""))
    verbose = not args.quiet

    # ── Load bands — CSV or manual ───────────────────────────────────────
    calc_rows: List[CalcRow]

    if args.csv is not None:
        if not os.path.isfile(args.csv):
            print(f"{Fore.RED}" + T("csv_not_found").format(args.csv) + f"{Style.RESET_ALL}")
            sys.exit(1)

        _csv_to_load = args.csv
        try:
            with open(args.csv, "r", encoding="utf-8-sig") as _fh:
                _raw = _fh.read()
            _first_line = _raw.split("\n")[0]
            if ";" in _first_line and _first_line.count(";") >= _first_line.count(","):
                def _fix_decimal(m):
                    s = m.group(0)
                    return re.sub(r'(\d),(\d)', r'\1.\2', s)
                _norm = re.sub(r'[^;\n]+', _fix_decimal, _raw)
                _norm = _norm.replace(";", ",")
                _tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".csv", prefix="nec2opt_norm_")
                with os.fdopen(_tmp_fd, "w", encoding="utf-8") as _fh:
                    _fh.write(_norm)
                _csv_to_load = _tmp_path
                print(T("csv_format_european"))
            else:
                print(T("csv_format_standard"))
        except Exception as _e:
            print(f"{Fore.YELLOW}" + T("csv_locale_detection_failed").format(_e) + f"{Style.RESET_ALL}")

        print(T("csv_loading").format(args.csv))
        try:
            calc_rows = load_csv(_csv_to_load)
        except Exception as e:
            print(f"{Fore.RED}" + T("csv_load_failed").format(e) + f"{Style.RESET_ALL}")
            sys.exit(1)
        finally:
            if _csv_to_load != args.csv and os.path.isfile(_csv_to_load):
                try:
                    os.unlink(_csv_to_load)
                except OSError:
                    pass

    else:
        _missing = []
        if not args.bands:
            _missing.append("--bands  (e.g. --bands 40m,20m,15m)")
        if args.wire_len is None:
            _missing.append("--wire-len  (starting wire length in metres)")
        if args.cp_len is None:
            _missing.append("--cp-len  (starting counterpoise length in metres)")
        if _missing:
            print(f"{Fore.RED}" + T("err_no_csv") + f"{Style.RESET_ALL}")
            for m in _missing:
                print(f"{Fore.RED}    {m}{Style.RESET_ALL}")
            print(f"{Fore.RED}" + T("err_supply_csv_or_args") + f"{Style.RESET_ALL}")
            sys.exit(1)

        _band_names = [b.strip() for b in args.bands.split(",") if b.strip()]

        if args.freqs:
            try:
                _freqs_explicit = [float(f.strip()) for f in args.freqs.split(",") if f.strip()]
            except ValueError as _ve:
                print(f"{Fore.RED}" + T("err_freqs_nonnumeric").format(_ve) + f"{Style.RESET_ALL}")
                sys.exit(1)
            if len(_band_names) != len(_freqs_explicit):
                print(f"{Fore.RED}" + T("err_bands_freqs_mismatch").format(len(_band_names), len(_freqs_explicit)) + f"{Style.RESET_ALL}")
                sys.exit(1)
            _freqs_mhz = _freqs_explicit
            print(T("freqs_explicit"))
        else:
            _freqs_mhz = []
            _unknown_bands = []
            for _bn in _band_names:
                _f = _lookup_band_freq(_bn)
                if _f is None:
                    _unknown_bands.append(_bn)
                else:
                    _freqs_mhz.append(_f)
            if _unknown_bands:
                print(f"{Fore.RED}" + T("err_unknown_bands") + f"{Style.RESET_ALL}")
                for _ub in _unknown_bands:
                    print(f"{Fore.RED}    '{_ub}'{Style.RESET_ALL}")
                _known = sorted(BAND_CENTRE_FREQ_MHZ.keys())
                print(f"{Fore.RED}" + T("known_bands").format(', '.join(_known)) + f"{Style.RESET_ALL}")
                print(f"{Fore.RED}" + T("supply_freqs") + f"{Style.RESET_ALL}")
                sys.exit(1)
            print(T("freqs_auto"))
            for _bn, _f in zip(_band_names, _freqs_mhz):
                print(f"    {_bn:>8} → {_f} MHz")

        if args.active_bands:
            _active_set = {b.strip() for b in args.active_bands.split(",") if b.strip()}
            _unknown_active = _active_set - set(_band_names)
            if _unknown_active:
                print(f"{Fore.YELLOW}" + T("warn_active_bands_unknown").format(sorted(_unknown_active)) + f"{Style.RESET_ALL}")
        else:
            _active_set = set(_band_names)

        _nocsv_unun = args.unun if args.unun is not None else None

        _wire_len_init = args.wire_len
        _cp_len_init   = args.cp_len
        _cp_height_val = args.cp_height if args.cp_height is not None else 0.5
        _wire_h_val    = args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M

        calc_rows = []
        for _bn, _fmhz in zip(_band_names, _freqs_mhz):
            _row = CalcRow()
            _row.band       = _bn
            _row.freq_mhz   = _fmhz
            _row.active     = (_bn in _active_set)
            _row.wire_len_m = _wire_len_init
            _row.cp_len_m   = _cp_len_init
            _row.cp_height_m   = _cp_height_val
            _row.wire_height_m = _wire_h_val
            _row.num_radials   = 1
            _row.unun_ratio    = _nocsv_unun if _nocsv_unun is not None else 9.0
            calc_rows.append(_row)

        print(T("band_source_cli"))
        print(T("bands_defined").format(len(calc_rows), ', '.join(_band_names)))

    # ── Apply --active-bands override (CSV path) ──────────────────────────
    if args.csv is not None and args.active_bands is not None:
        _active_set = {b.strip() for b in args.active_bands.split(",") if b.strip()}
        _all_names  = {r.band for r in calc_rows}
        _unknown_ab = _active_set - _all_names
        if _unknown_ab:
            print(f"{Fore.YELLOW}" + T("warn_active_bands_not_in_csv").format(sorted(_unknown_ab)) + f"{Style.RESET_ALL}")
        for _row in calc_rows:
            _row.active = (_row.band in _active_set)
        print(T("active_bands_overridden").format(sorted(_active_set & _all_names)))

    active = [r for r in calc_rows if r.active]
    if not active:
        print(f"{Fore.RED}" + T("no_active_bands") + f"{Style.RESET_ALL}")
        sys.exit(1)

    print(T("active_bands").format(len(active), len(calc_rows), ', '.join(r.band for r in active)))
    print(T("frequencies").format([r.freq_mhz for r in active]))

    # ── UnUn ratio ────────────────────────────────────────────────────────
    if args.unun is not None:
        unun_ratio = args.unun
    elif args.csv is None:
        if args.no_interactive:
            print(f"{Fore.RED}" + T("err_no_unun_nocsv_inline") + f"{Style.RESET_ALL}")
            sys.exit(1)
        val = input(f"{Fore.CYAN}" + T("unun_prompt") + f"{Style.RESET_ALL}").strip()
        unun_ratio = float(val) if val else 9.0
    else:
        csv_ununs = {r.unun_ratio for r in calc_rows if r.unun_ratio > 0}
        if len(csv_ununs) == 1:
            unun_ratio = list(csv_ununs)[0]
            print(T("unun_from_csv").format(unun_ratio))
        elif len(csv_ununs) == 0:
            if args.no_interactive:
                print(f"{Fore.RED}" + T("err_no_unun_in_csv") + f"{Style.RESET_ALL}")
                sys.exit(1)
            val = input(f"{Fore.CYAN}" + T("unun_prompt") + f"{Style.RESET_ALL}").strip()
            unun_ratio = float(val) if val else 9.0
        else:
            if args.no_interactive:
                print(f"{Fore.RED}" + T("err_multiple_unun").format(sorted(csv_ununs)) + f"{Style.RESET_ALL}")
                sys.exit(1)
            val = input(f"{Fore.CYAN}" + T("unun_multi_prompt").format(sorted(csv_ununs), list(csv_ununs)[0]) + f"{Style.RESET_ALL}").strip()
            unun_ratio = float(val) if val else list(csv_ununs)[0]

    print(T("unun_ratio").format(unun_ratio))

    # ── Resolve range / height defaults ──────────────────────────────────
    _MARGIN = args.margin

    def _csv_mean(attr: str, rows, fallback: float) -> float:
        vals = [getattr(r, attr) for r in rows
                if hasattr(r, attr) and getattr(r, attr) is not None
                and getattr(r, attr) != 0.0]
        return (sum(vals) / len(vals)) if vals else fallback

    if args.wire_min is None or args.wire_max is None:
        if args.wire_len is not None:
            ref_wire = args.wire_len
            src_wire = "--wire-len"
        else:
            ref_wire = _csv_mean("wire_len_m", active,
                                 fallback=_csv_mean("wire_len_m", calc_rows, 10.0))
            src_wire = "CSV"
        print(T("search_margin").format(_MARGIN, src_wire, ref_wire))
        if args.wire_min is None:
            args.wire_min = max(1.0, round(ref_wire - _MARGIN, 3))
            print(T("wire_min").format(args.wire_min))
        if args.wire_max is None:
            args.wire_max = round(ref_wire + _MARGIN, 3)
            print(T("wire_max").format(args.wire_max))

    if args.cp_min is None or args.cp_max is None:
        if args.cp_len is not None:
            ref_cp = args.cp_len
            src_cp = "--cp-len"
        else:
            ref_cp = _csv_mean("cp_len_m", active,
                               fallback=_csv_mean("cp_len_m", calc_rows, 4.0))
            src_cp = "CSV"
        print(T("cp_margin").format(_MARGIN, src_cp, ref_cp))
        if args.cp_min is None:
            args.cp_min = max(1.0, round(ref_cp - _MARGIN, 3))
            print(T("cp_min").format(args.cp_min))
        if args.cp_max is None:
            args.cp_max = round(ref_cp + _MARGIN, 3)
            print(T("cp_max").format(args.cp_max))

    if args.wire_height is None:
        csv_wh = _csv_mean("wire_height_m", active,
                           fallback=_csv_mean("wire_height_m", calc_rows,
                                              DEFAULT_HEIGHT_M))
        args.wire_height = csv_wh if csv_wh else DEFAULT_HEIGHT_M
        src_note = (T("wire_height_from_csv") if args.csv is not None
                    else T("wire_height_default"))
        print(T("wire_height").format(args.wire_height, src_note))

    if args.cp_height is None:
        csv_cph = _csv_mean("cp_height_m", active,
                            fallback=_csv_mean("cp_height_m", calc_rows, 0.5))
        args.cp_height = csv_cph if csv_cph else 0.5
        src_note = T("cp_height_from_csv") if args.csv is not None else T("cp_height_default")
        print(T("cp_height").format(args.cp_height, src_note))

    # ── Build search grid ────────────────────────────────────────────────
    wire_range = (args.wire_min, args.wire_max, args.wire_step)
    cp_range   = (args.cp_min,  args.cp_max,  args.cp_step)
    grid = build_search_grid(*wire_range, *cp_range)
    print(T("grid_size").format(len(grid)))

    cp_types = (["horizontal", "vertical"] if args.cp_type == "both"
                else [args.cp_type])
    print(T("cp_types").format(cp_types))

    # ── Locate nec2c ─────────────────────────────────────────────────────
    nec2c_bin: Optional[str] = None
    mode = args.mode

    if mode in ("nec2", "auto"):
        nec2c_bin = find_nec2c(
            explicit=args.nec2c,
            interactive=(not args.no_interactive),
        )
        if nec2c_bin is None:
            if mode == "nec2":
                print(f"{Fore.RED}" + T("nec2c_required") + f"{Style.RESET_ALL}")
                sys.exit(1)
            print(f"  {Fore.YELLOW}" + T("nec2c_fallback_empirical") + f"{Style.RESET_ALL}")
            mode = "empirical"
        else:
            mode = "nec2"

    # ── Force NEC2 mode when a slope is requested ─────────────────────────
    _slope = getattr(args, "wire_slope_end_height", None)
    if _slope is not None and mode == "empirical":
        print(f"  {Fore.YELLOW}INFO: --wire-slope-end-height requires NEC2 mode; "
              f"switching to --mode nec2.{Style.RESET_ALL}")
        if nec2c_bin is None:
            print(f"{Fore.RED}" + T("nec2c_required") + f"{Style.RESET_ALL}")
            sys.exit(1)
        mode = "nec2"

    # ── Helper: run one sweep and return (results, ranked, pareto_ranked) ─
    def _run_sweep(w_min: float, w_max: float, cp_min: float, cp_max: float):
        _grid = build_search_grid(w_min, w_max, args.wire_step,
                                  cp_min, cp_max, args.cp_step)
        print()
        print(T("sweep_starting").format(mode.upper()))
        print()
        if mode == "nec2":
            _res = nec2_sweep(
                grid=_grid,
                calc_rows=calc_rows,
                unun_ratio=unun_ratio,
                nec2c_bin=nec2c_bin,
                wire_height_m=args.wire_height,
                cp_height_m=args.cp_height,
                ground_cond=args.ground_cond,
                ground_diel=args.ground_diel,
                cp_types=cp_types,
                wire_slope_end_m=_slope,
                verbose=verbose,
            )
        else:
            _emp_cp = args.cp_type if args.cp_type != "both" else "horizontal"
            if args.cp_type == "both":
                print(f"  {Fore.YELLOW}" + T("warn_empirical_cp_forced") + f"{Style.RESET_ALL}")
            _res = empirical_sweep(
                grid=_grid,
                calc_rows=calc_rows,
                unun_ratio=unun_ratio,
                cp_type=_emp_cp,
                wire_slope_end_m=_slope,
                verbose=verbose,
            )
        print("\n" + T("sweep_complete").format(len(_res)))
        _rnk  = rank_results(_res)
        _par  = pareto_front(_res)
        _prnk = sorted(_par, key=lambda r: r.score_combined)
        return _res, _rnk, _prnk

    # ── Helper: detect boundary hits, return flags and hit counts ────────
    _TOL = 1e-6

    def _check_boundaries(ranked_list, w_min, w_max, cp_min, cp_max):
        """Return (wire_at_max, wire_at_min, cp_at_max, cp_at_min,
                   hits_wire, hits_cp) for the top-5 of ranked_list."""
        if not ranked_list:
            return False, False, False, False, 0, 0
        _best = ranked_list[0]
        _hits_wire = sum(
            1 for r in ranked_list[:5]
            if abs(r.wire_len_m - w_min) < _TOL
            or abs(r.wire_len_m - w_max) < _TOL
        )
        _hits_cp = sum(
            1 for r in ranked_list[:5]
            if abs(r.cp_len_m - cp_min) < _TOL
            or abs(r.cp_len_m - cp_max) < _TOL
        )
        _w_at_max = abs(_best.wire_len_m - w_max) < _TOL
        _w_at_min = abs(_best.wire_len_m - w_min) < _TOL
        _c_at_max = abs(_best.cp_len_m  - cp_max) < _TOL
        _c_at_min = abs(_best.cp_len_m  - cp_min) < _TOL
        return _w_at_max, _w_at_min, _c_at_max, _c_at_min, _hits_wire, _hits_cp

    # ── Initial sweep ─────────────────────────────────────────────────────
    results, ranked, pareto_ranked = _run_sweep(
        args.wire_min, args.wire_max, args.cp_min, args.cp_max
    )
    pareto = pareto_front(results)

    print(T("pareto_count").format(len(pareto_ranked)))

    # ── --retry loop ──────────────────────────────────────────────────────
    _retry_max   = max(0, int(args.retry))
    _cur_w_min   = args.wire_min
    _cur_w_max   = args.wire_max
    _cur_cp_min  = args.cp_min
    _cur_cp_max  = args.cp_max

    for _retry_n in range(1, _retry_max + 1):
        (w_at_max, w_at_min,
         c_at_max, c_at_min,
         _hw, _hc) = _check_boundaries(ranked,
                                        _cur_w_min, _cur_w_max,
                                        _cur_cp_min, _cur_cp_max)

        _need_retry = w_at_max or w_at_min or c_at_max or c_at_min
        if not _need_retry:
            print(f"\n  {Fore.GREEN}" + T("retry_converged").format(_retry_n - 1)
                  + f"{Style.RESET_ALL}")
            break

        _prev_best = ranked[0]
        _new_w_min, _new_w_max     = _cur_w_min, _cur_w_max
        _new_cp_min, _new_cp_max   = _cur_cp_min, _cur_cp_max

        if w_at_max:
            _new_w_min = _prev_best.wire_len_m
            _new_w_max = round(_prev_best.wire_len_m + args.margin, 3)
            print(f"\n  {Fore.YELLOW}"
                  + T("retry_wire_expanding_max").format(_new_w_max, _retry_n, _retry_max)
                  + f"{Style.RESET_ALL}")
        elif w_at_min:
            _new_w_max = _prev_best.wire_len_m
            _new_w_min = max(1.0, round(_prev_best.wire_len_m - args.margin, 3))
            print(f"\n  {Fore.YELLOW}"
                  + T("retry_wire_expanding_min").format(_new_w_min, _retry_n, _retry_max)
                  + f"{Style.RESET_ALL}")

        if c_at_max:
            _new_cp_min = _prev_best.cp_len_m
            _new_cp_max = round(_prev_best.cp_len_m + args.margin, 3)
            print(f"\n  {Fore.YELLOW}"
                  + T("retry_cp_expanding_max").format(_new_cp_max, _retry_n, _retry_max)
                  + f"{Style.RESET_ALL}")
        elif c_at_min:
            _new_cp_max = _prev_best.cp_len_m
            _new_cp_min = max(1.0, round(_prev_best.cp_len_m - args.margin, 3))
            print(f"\n  {Fore.YELLOW}"
                  + T("retry_cp_expanding_min").format(_new_cp_min, _retry_n, _retry_max)
                  + f"{Style.RESET_ALL}")

        _new_results, _new_ranked, _new_pareto_ranked = _run_sweep(
            _new_w_min, _new_w_max, _new_cp_min, _new_cp_max
        )

        if (_new_ranked
                and _new_ranked[0].score_combined < ranked[0].score_combined):
            results        = _new_results
            ranked         = _new_ranked
            pareto_ranked  = _new_pareto_ranked
            pareto         = pareto_front(results)
            _cur_w_min, _cur_w_max   = _new_w_min, _new_w_max
            _cur_cp_min, _cur_cp_max = _new_cp_min, _new_cp_max
            print(f"  {Fore.GREEN}"
                  + T("retry_new_best").format(
                      ranked[0].wire_len_m, ranked[0].cp_len_m,
                      ranked[0].score_combined)
                  + f"{Style.RESET_ALL}")
        else:
            print(f"  {Fore.CYAN}"
                  + T("retry_no_improvement").format(
                      ranked[0].wire_len_m, ranked[0].cp_len_m)
                  + f"{Style.RESET_ALL}")
            break   # no point continuing if the new window is worse

    # Use the (possibly updated) bounds for the final boundary warnings
    args.wire_min = _cur_w_min
    args.wire_max = _cur_w_max
    args.cp_min   = _cur_cp_min
    args.cp_max   = _cur_cp_max

    # ── Display best candidate ─────────────────────────────────────────────
    if ranked:
        best = ranked[0]
        print(f"\n  {Fore.GREEN}" + T("best_candidate") + f"{Style.RESET_ALL}"
              f"  wire = {best.wire_len_m:.3f} m   cp = {best.cp_len_m:.3f} m"
              f"   ({best.cp_type})")
        print(T("combined_score").format(best.score_combined))
        print(T("vswr_penalty").format(best.score_vswr))
        print(T("avoidance_mean").format(best.score_avoidance))

        (w_at_max, w_at_min,
         c_at_max, c_at_min,
         _boundary_hits_wire,
         _boundary_hits_cp) = _check_boundaries(ranked,
                                                  args.wire_min, args.wire_max,
                                                  args.cp_min,   args.cp_max)

        if w_at_max:
            print(f"\n  {Fore.YELLOW}" + T("warn_wire_at_max").format(args.wire_max, _boundary_hits_wire) + f"{Style.RESET_ALL}")
        elif w_at_min:
            print(f"\n  {Fore.YELLOW}" + T("warn_wire_at_min").format(args.wire_min, _boundary_hits_wire) + f"{Style.RESET_ALL}")
        if c_at_max:
            print(f"\n  {Fore.YELLOW}" + T("warn_cp_at_max").format(args.cp_max, _boundary_hits_cp) + f"{Style.RESET_ALL}")
        elif c_at_min:
            print(f"\n  {Fore.YELLOW}" + T("warn_cp_at_min").format(args.cp_min, _boundary_hits_cp) + f"{Style.RESET_ALL}")
        print()

        active_rows = [cr for cr in calc_rows if cr.active]
        print(f"  {Fore.CYAN}" + T("impedance_header").format(unun_ratio) + f"{Style.RESET_ALL}")
        hdr = (f"    {'Band':>8}  {'MHz':>7}  "
               f"{'R_ant':>8}  {'X_ant':>8}  {'|Z_ant|':>8}  "
               f"{'R_tx':>7}  {'X_tx':>7}  {'|Z_tx|':>7}  "
               f"{'VSWR':>5}  {'Src':>8}")
        print(hdr)
        print("    " + "─" * (len(hdr) - 4))
        for cr in active_rows:
            b   = cr.band
            R_a = best.band_R_ant.get(b, 0.0)
            X_a = best.band_X_ant.get(b, 0.0)
            R_t = best.band_R_tx.get(b, 0.0)
            X_t = best.band_X_tx.get(b, 0.0)
            Z_a = math.hypot(R_a, X_a)
            Z_t = math.hypot(R_t, X_t)
            v   = best.band_vswr.get(b, 999.0)
            src = best.band_imp_src.get(b, "?")
            vswr_color = (Fore.GREEN if v <= 1.5 else
                          Fore.YELLOW if v <= 3.0 else
                          Fore.RED)
            print(f"    {b:>8}  {cr.freq_mhz:7.3f}  "
                  f"{R_a:8.1f}  {X_a:+8.1f}  {Z_a:8.1f}  "
                  f"{R_t:7.2f}  {X_t:+7.2f}  {Z_t:7.2f}  "
                  f"{vswr_color}{v:5.2f}{Style.RESET_ALL}  {src:>8}")
        print()

    # ── UnUn optimisation ────────────────────────────────────────────────
    unun_result: Optional[UnUnResult] = None
    best_run_h: Optional[NEC2Run] = None
    best_run_v: Optional[NEC2Run] = None

    if ranked:
        best = ranked[0]

        if mode == "nec2" and nec2c_bin:
            all_freqs = [cr.freq_mhz for cr in calc_rows]
            _wh  = args.wire_height  if args.wire_height  is not None else DEFAULT_HEIGHT_M
            _cph = args.cp_height    if args.cp_height    is not None else 0.5
            with tempfile.TemporaryDirectory(prefix="nec2opt_unun_") as _td:
                for cpt, _attr in [("horizontal", "best_run_h"),
                                    ("vertical",   "best_run_v")]:
                    _nec = os.path.join(_td, f"best_{cpt}.nec")
                    _out = os.path.join(_td, f"best_{cpt}.out")
                    write_nec_deck(
                        nec_path=_nec,
                        wire_len_m=best.wire_len_m,
                        cp_len_m=best.cp_len_m,
                        cp_type=cpt,
                        freqs_mhz=all_freqs,
                        wire_height_m=_wh,
                        wire_slope_end_m=_slope,
                        cp_height_m=_cph,
                        ground_cond=args.ground_cond,
                        ground_diel=args.ground_diel,
                    )
                    if run_nec2c(nec2c_bin, _nec, _out):
                        try:
                            _run = parse_nec2_output(_out, debug=False,
                                                     explicit_nec_path=_nec)
                            if _run is not None and not _run.freq_map():
                                _run = None
                            if cpt == "horizontal":
                                best_run_h = _run
                            else:
                                best_run_v = _run
                        except Exception:
                            pass

        print(T("optimising_unun"))
        unun_result = find_best_unun(
            best=best,
            calc_rows=calc_rows,
            current_unun=unun_ratio,
            run_h=best_run_h,
            run_v=best_run_v,
            nec2_strict=(mode == "nec2"),
        )

        std_n   = unun_result.best_standard_ratio
        cont_n  = unun_result.best_continuous_ratio
        cur_score = unun_result.ratio_score[unun_ratio]
        std_score = unun_result.best_standard_score

        print(f"\n  {Fore.CYAN}" + T("unun_analysis_header").format(best.wire_len_m, best.cp_len_m) + f"{Style.RESET_ALL}")
        print(T("unun_current").format(unun_ratio, cur_score))
        print(T("unun_best_std").format(std_n, std_score))
        print(T("unun_continuous").format(cont_n, unun_result.best_continuous_score))

        if abs(std_n - unun_ratio) > 0.5 and (cur_score - std_score) > 0.001:
            print(f"    {Fore.YELLOW}" + T("unun_switch_recommend").format(std_n) + f"{Style.RESET_ALL}")
        else:
            print(f"    {Fore.GREEN}" + T("unun_current_optimal").format(unun_ratio) + f"{Style.RESET_ALL}")

        active_bands = [cr.band for cr in calc_rows if cr.active]
        print(f"\n    {'Band':>8}  {'Current':>9}  {'Best ratio':>12}  {'VSWR@best':>10}")
        print(f"    {'':─<8}  {'':─<9}  {'':─<12}  {'':─<10}")
        for b in active_bands:
            cur_v = best.band_vswr.get(b, 999.0)
            opt_n = unun_result.per_band_best_ratio.get(b, None)
            opt_v = unun_result.per_band_best_vswr.get(b, None)
            opt_n_str = f"{opt_n:10.2f}:1" if opt_n is not None else f"{'N/A (no NEC2)':>11}"
            opt_v_str = f"{opt_v:10.3f}"   if opt_v is not None else f"{'---':>10}"
            print(f"    {b:>8}  {cur_v:9.2f}  {opt_n_str}  {opt_v_str}")
        print()

    # ── Write outputs ────────────────────────────────────────────────────
    print(T("writing_outputs"))

    export_unun = unun_ratio
    if unun_result is not None:
        std_n = unun_result.best_standard_ratio
        cur_score = unun_result.ratio_score[unun_ratio]
        if (unun_result.best_standard_score < cur_score - 0.001
                and abs(std_n - unun_ratio) > 0.5):
            export_unun = std_n
            print(T("csv_export_recommended_unun").format(export_unun, unun_ratio))
            print(T("warn_rankings_unun").format(unun_ratio))
            print(T("rerun_with_unun").format(export_unun))

    report = write_report(
        ranked=ranked[:args.top_n],
        pareto=pareto_ranked,
        calc_rows=calc_rows,
        unun_ratio=unun_ratio,
        wire_range=(args.wire_min, args.wire_max, args.wire_step),
        cp_range=(args.cp_min, args.cp_max, args.cp_step),
        mode=mode,
        out_path=args.out_txt,
        unun_result=unun_result,
        total_candidates=len(results),
        wire_height_m=args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M,
    )
    print(T("report_saved").format(args.out_txt))

    if ranked:
        export_best_csv(ranked[0], calc_rows, export_unun, args.out_csv)
        print(T("csv_best_saved").format(args.out_csv, export_unun))

    plot_results(results, pareto, ranked, calc_rows, unun_ratio, args.out_png)

    _wh_out  = args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M
    _cph_out = args.cp_height   if args.cp_height   is not None else 0.5

    if ranked:
        write_best_nec_deck(
            best=ranked[0],
            calc_rows=calc_rows,
            out_path=args.out_nec,
            wire_height_m=_wh_out,
            wire_slope_end_m=_slope,
            cp_height_m=_cph_out,
            ground_cond=args.ground_cond,
            ground_diel=args.ground_diel,
        )

    if ranked and mode == "nec2" and nec2c_bin:
        print(T("radiation_generating"))
        plot_radiation_diagrams(
            best=ranked[0],
            calc_rows=calc_rows,
            nec2c_bin=nec2c_bin,
            out_png=args.out_radiation,
            wire_height_m=_wh_out,
            wire_slope_end_m=_slope,
            cp_height_m=_cph_out,
            ground_cond=args.ground_cond,
            ground_diel=args.ground_diel,
        )
    elif ranked and mode != "nec2":
        print(T("radiation_nec2_only_inline").format(mode))

    print()
    if verbose:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', report)
        print(clean)

    print(f"\n{Fore.CYAN}" + T("done") + f"{Style.RESET_ALL}\n")


# ═══════════════════════════════════════════════════════════════════════════
# EMBEDDED GUI  (only active when --gui is passed)
# ═══════════════════════════════════════════════════════════════════════════

def _launch_gui() -> None:
    """Import and start the tkinter GUI.  Called only when --gui is present."""
    try:
        import tkinter as _tk  # noqa: F401 — probe availability first
    except ImportError:
        print("ERROR: tkinter is not available in this Python installation.")
        print("Install it (e.g. 'sudo apt install python3-tk') and retry.")
        sys.exit(1)

    # ── All GUI code is inlined below so the file is self-contained ──────

    import locale as _gui_locale
    import threading as _threading
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    from pathlib import Path

    # ── Band / UnUn reference data ────────────────────────────────────────
    _BAND_CENTRE_FREQ_MHZ = {
        "2200m": 0.1365,  "630m": 0.475,   "160m": 1.850,   "80m": 3.650,
        "60m":   5.350,   "40m": 7.100,    "30m": 10.125,   "20m": 14.175,
        "17m":   18.118,  "15m": 21.225,   "12m": 24.940,   "10m": 28.500,
        "6m":    50.200,  "4m":  70.200,   "2m":  144.200,  "70cm": 432.100,
        "23cm":  1296.200,
    }
    _KNOWN_BANDS = _BAND_CENTRE_FREQ_MHZ.keys()
    _UNUN_RATIOS = [1, 1.5, 2, 3, 4, 6, 9, 12, 16, 25, 27, 36, 49, 64]

    def _gui_detect_lang() -> str:
        try:
            lang = _gui_locale.getlocale()[0] or ""
        except Exception:
            lang = ""
        return "es" if lang.lower().startswith("es") else "en"

    def _gui_find_nec2c() -> str:
        for name in ("nec2c", "nec2c-mpich"):
            p = shutil.which(name)
            if p:
                return p
        for p in ("/usr/bin/nec2c", "/usr/local/bin/nec2c",
                  "/opt/nec2c/bin/nec2c", "/opt/homebrew/bin/nec2c"):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return ""

    # ── i18n strings ──────────────────────────────────────────────────────
    _GUI_STRINGS = {
        "en": {
            "title":              "NEC2 Antenna Length Optimizer GUI",
            "header_title":       "NEC2 Antenna Length Optimizer",
            "header_subtitle":    "  •  Interactive GUI",
            "optimizer_script":   "Optimizer script:",
            "browse":             "Browse…",
            "font_label":         "Font:",
            "tab_input":          "  Band / Source  ",
            "tab_search":         "  Search Range  ",
            "tab_physics":        "  Physics  ",
            "tab_output":         "  Output Files  ",
            "tab_run":            "  Run  ",
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
            "wire_slope_end_lbl": "slope-end-height:",
            "wire_height_hint":   "Antenna wire height above ground  (default 8 m)",
            "cp_height_hint":     "Counterpoise height above ground  (default 0.5 m)",
            "wire_slope_end_hint": "Far-end height for sloped wire  (0 = ground; leave blank for horizontal)",
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
            "workdir_lf":         "Working / Output Directory",
            "outdir_label":       "Output directory:",
            "workdir_hint":       "The optimizer will be launched with this as the working directory.",
            "outfiles_lf":        "Output File Names",
            "txt_tip":            "Ranked text report",
            "png_tip":            "Score heat map + VSWR bar charts",
            "csv_tip":            "Best candidate in band-analysis CSV format",
            "nec_tip":            "NEC2 input deck for best geometry",
            "rad_tip":            "Radiation pattern PNG (NEC2 mode only)",
            "cmd_preview_lf":     "Command Preview",
            "refresh_preview":    "Refresh preview",
            "run_btn":            "▶  Run Optimizer",
            "stop_btn":           "■  Stop",
            "show_report_btn":    "📄  Show Report",
            "show_radiation_btn": "📡  Show Radiation Pattern",
            "idle":               "Idle",
            "console_lf":         "Console Output",
            "clear_btn":          "Clear",
            "running":            "Running…",
            "stopped":            "Stopped by user",
            "finished_ok":        "Finished successfully ✓",
            "exit_code":          "Process exited with code {rc}",
            "thread_error":       "Error: {e}",
            "script_nf_title":    "Script not found",
            "script_nf_msg":      ("Optimizer script not found:\n{script}\n\n"
                                   "Please set the correct path on the 'Band / Source' tab."),
            "cfg_err_title":      "Configuration error",
            "dir_err_title":      "Directory error",
            "dir_err_msg":        "Cannot create output directory:\n{e}",
            "done_title":         "Done",
            "done_msg":           "Optimization complete!\n\nOpen report file?\n{report}",
            "hint_wire_len":      "total radiating element length",
            "hint_cp_len":        "counterpoise / ground radial length",
            "hint_margin":        "±search window around starting length",
            "hint_wire_min":      "minimum wire length to test",
            "hint_wire_max":      "maximum wire length to test",
            "hint_wire_step":     "grid step between wire lengths",
            "hint_cp_min":        "minimum CP length to test",
            "hint_cp_max":        "maximum CP length to test",
            "hint_cp_step":       "grid step between CP lengths",
            "hint_max_retries":   "retry count when best hits boundary",
            "hint_top_n":         "candidates listed in text report",
            "hint_wire_height":   "antenna wire height above ground",
            "hint_cp_height":     "counterpoise height above ground",
            "hint_conductivity":  "soil conductivity in S/m",
            "hint_permittivity":  "relative permittivity (dielectric constant)",
            "hint_unun":          "impedance transformation ratio n:1",
            "hint_out_txt":       "ranked results text report",
            "hint_out_png":       "score heat-map + VSWR bar charts",
            "hint_out_csv":       "best candidate in CSV format",
            "hint_out_nec":       "NEC2 input deck for best geometry",
            "hint_out_rad":       "radiation pattern PNG (NEC2 only)",
            "lang_switch":        "ES",
        },
        "es": {
            "title":              "Optimizador de Longitud de Antenas NEC2 - GUI",
            "header_title":       "Optimizador de Longitud de Antenas NEC2",
            "header_subtitle":    "  •  GUI Interactiva",
            "optimizer_script":   "Script optimizador:",
            "browse":             "Examinar…",
            "font_label":         "Fuente:",
            "tab_input":          "  Banda / Fuente  ",
            "tab_search":         "  Rango de Búsqueda  ",
            "tab_physics":        "  Física  ",
            "tab_output":         "  Archivos de Salida  ",
            "tab_run":            "  Ejecutar  ",
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
            "wire_slope_end_lbl": "slope-end-height:",
            "wire_height_hint":   "Altura del hilo de antena sobre el suelo  (por defecto 8 m)",
            "cp_height_hint":     "Altura del contrapeso sobre el suelo  (por defecto 0,5 m)",
            "wire_slope_end_hint": "Altura del extremo lejano para hilo inclinado  (0 = suelo; dejar vacío para hilo horizontal)",
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
            "workdir_lf":         "Directorio de Trabajo / Salida",
            "outdir_label":       "Directorio de salida:",
            "workdir_hint":       "El optimizador se ejecutará con este como directorio de trabajo.",
            "outfiles_lf":        "Nombres de Archivos de Salida",
            "txt_tip":            "Informe de texto ordenado",
            "png_tip":            "Mapa de calor + gráficos VSWR",
            "csv_tip":            "Mejor candidato en formato CSV de análisis de banda",
            "nec_tip":            "Archivo de entrada NEC2 para la mejor geometría",
            "rad_tip":            "PNG de patrón de radiación (sólo modo NEC2)",
            "cmd_preview_lf":     "Vista Previa del Comando",
            "refresh_preview":    "Actualizar vista previa",
            "run_btn":            "▶  Ejecutar Optimizador",
            "stop_btn":           "■  Detener",
            "show_report_btn":    "📄  Ver Informe",
            "show_radiation_btn": "📡  Ver Patrón de Radiación",
            "idle":               "Inactivo",
            "console_lf":         "Salida de Consola",
            "clear_btn":          "Limpiar",
            "running":            "Ejecutando…",
            "stopped":            "Detenido por el usuario",
            "finished_ok":        "Finalizado con éxito ✓",
            "exit_code":          "El proceso terminó con código {rc}",
            "thread_error":       "Error: {e}",
            "script_nf_title":    "Script no encontrado",
            "script_nf_msg":      ("Script optimizador no encontrado:\n{script}\n\n"
                                   "Establezca la ruta correcta en la pestaña 'Banda / Fuente'."),
            "cfg_err_title":      "Error de configuración",
            "dir_err_title":      "Error de directorio",
            "dir_err_msg":        "No se puede crear el directorio de salida:\n{e}",
            "done_title":         "Completado",
            "done_msg":           "¡Optimización completada!\n\n¿Abrir archivo de informe?\n{report}",
            "hint_wire_len":      "longitud total del elemento radiante",
            "hint_cp_len":        "longitud del contrapeso / radial de tierra",
            "hint_margin":        "±ventana de búsqueda alrededor de la longitud inicial",
            "hint_wire_min":      "longitud mínima de hilo a probar",
            "hint_wire_max":      "longitud máxima de hilo a probar",
            "hint_wire_step":     "paso de grilla entre longitudes de hilo",
            "hint_cp_min":        "longitud mínima de CP a probar",
            "hint_cp_max":        "longitud máxima de CP a probar",
            "hint_cp_step":       "paso de grilla entre longitudes de CP",
            "hint_max_retries":   "reintentos cuando el mejor alcanza el límite",
            "hint_top_n":         "candidatos listados en el informe de texto",
            "hint_wire_height":   "altura del hilo de antena sobre el suelo",
            "hint_cp_height":     "altura del contrapeso sobre el suelo",
            "hint_conductivity":  "conductividad del suelo en S/m",
            "hint_permittivity":  "permitividad relativa (constante dieléctrica)",
            "hint_unun":          "relación de transformación de impedancia n:1",
            "hint_out_txt":       "informe de texto con resultados ordenados",
            "hint_out_png":       "mapa de calor de puntuación + gráficos VSWR",
            "hint_out_csv":       "mejor candidato en formato CSV",
            "hint_out_nec":       "archivo de entrada NEC2 para mejor geometría",
            "hint_out_rad":       "PNG de patrón de radiación (solo NEC2)",
            "lang_switch":        "EN",
        },
    }

    # ── Colour constants ──────────────────────────────────────────────────
    _BG        = "#DBD1BD"
    _BG2       = "#D0C6B2"
    _BG3       = "#C8BEA8"
    _ENTRY_BG  = "#EDE8DF"
    _BORDER    = "#C0C0C0"
    _FG        = "#000000"
    _FG2       = "#555555"
    _ACCENT    = "#1A4A8A"
    _ACCENT2   = "#1A5E1A"
    _WARN      = "#7A5500"
    _ERR       = "#8A1515"
    _BTN_BG    = "#C4BAA8"
    _BTN_HOV   = "#B0A898"
    _TAG_WARN  = "#7A5500"
    _TAG_ERR   = "#8A1515"
    _TAG_OK    = "#1A5E1A"
    _TAG_HEAD  = "#1A4A8A"

    _FF   = "Segoe UI"  if sys.platform == "win32" else "DejaVu Sans"
    _FFM  = "Consolas"  if sys.platform == "win32" else "DejaVu Sans Mono"
    _BASE = 10

    # ── App class ─────────────────────────────────────────────────────────

    class _App(tk.Tk):

        def __init__(self):
            super().__init__()
            self.resizable(True, True)
            self.minsize(920, 640)

            self._font_obj      = tkfont.Font(family=_FF,  size=_BASE)
            self._font_obj_mono = tkfont.Font(family=_FFM, size=_BASE)

            self._process = None
            self._thread  = None
            self._running = False
            self._stopped = False

            # Point GUI at this very script
            self._script_path = os.path.abspath(__file__)

            self._ui_lang = _gui_detect_lang()
            self._font_sz = _BASE
            self._tw: list = []

            self._build_style()
            self._build_ui()
            self._apply_language()
            self._auto_detect_nec2c()

            self.update_idletasks()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = 980, 760
            self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        # ── i18n ──────────────────────────────────────────────────────────

        def t(self, key: str, **kw) -> str:
            s = _GUI_STRINGS[self._ui_lang].get(key, key)
            return s.format(**kw) if kw else s

        def _reg(self, widget, key: str):
            self._tw.append(lambda w=widget, k=key: w.config(text=self.t(k)))
            return widget

        def _reg_fn(self, fn):
            self._tw.append(fn)
            return fn

        def _apply_language(self):
            self.title(self.t("title"))
            for fn in self._tw:
                try:
                    fn()
                except Exception:
                    pass
            for idx, key in self._tab_keys:
                try:
                    self._nb.tab(idx, text=self.t(key))
                except Exception:
                    pass

        def _toggle_lang(self):
            self._ui_lang = "es" if self._ui_lang == "en" else "en"
            self._apply_language()

        # ── Fonts ─────────────────────────────────────────────────────────

        def _font(self, variant="main"):
            sz = self._font_sz
            if variant == "mono":
                return self._font_obj_mono
            if variant == "h1":
                return (_FF, sz + 2, "bold")
            if variant == "bold":
                return (_FF, sz, "bold")
            if variant == "label":
                return (_FF, sz)
            return self._font_obj

        def _apply_fonts(self):
            self._font_obj.configure(family=_FF,  size=self._font_sz)
            self._font_obj_mono.configure(family=_FFM, size=self._font_sz)
            sz = self._font_sz
            st = ttk.Style(self)
            st.configure(".",                 font=(_FF, sz))
            st.configure("TLabel",            font=(_FF, sz))
            st.configure("Bold.TLabel",       font=(_FF, sz + 2, "bold"))
            st.configure("Muted.TLabel",      font=(_FF, sz))
            st.configure("TLabelframe.Label", font=(_FF, sz))
            st.configure("TNotebook.Tab",     font=(_FF, sz))
            st.configure("Accent.TButton",    font=(_FF, sz, "bold"))
            st.configure("Stop.TButton",      font=(_FF, sz, "bold"))
            st.configure("Browse.TButton",    font=(_FF, sz))
            st.configure("InfoBtn.TButton",   font=(_FF, sz))
            st.configure("Lang.TButton",      font=(_FF, sz, "bold"))
            st.configure("FontCtrl.TButton",  font=(_FF, sz, "bold"))
            st.configure("TEntry",            font=(_FF, sz))
            st.configure("TSpinbox",          font=(_FF, sz))
            st.configure("TCombobox",         font=(_FF, sz))
            st.configure("TCheckbutton",      font=(_FF, sz))
            st.configure("TRadiobutton",      font=(_FF, sz))
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

        # ── Style ─────────────────────────────────────────────────────────

        def _build_style(self):
            st = ttk.Style(self)
            st.theme_use("clam")
            st.configure(".", background=_BG, foreground=_FG,
                         fieldbackground=_ENTRY_BG, font=self._font(),
                         relief="flat", bordercolor=_BORDER)
            st.configure("TFrame",   background=_BG)
            st.configure("TLabel",   background=_BG, foreground=_FG,  font=self._font("label"))
            st.configure("Bold.TLabel",  background=_BG, foreground=_ACCENT, font=self._font("h1"))
            st.configure("Muted.TLabel", background=_BG, foreground=_FG2,    font=self._font("label"))
            st.configure("TEntry",  fieldbackground=_ENTRY_BG, foreground=_FG,
                         insertcolor=_FG, relief="solid", borderwidth=1, bordercolor=_BORDER)
            st.configure("TSpinbox", fieldbackground=_ENTRY_BG, foreground=_FG,
                         insertcolor=_FG, relief="solid", borderwidth=1, bordercolor=_BORDER)
            st.configure("TCombobox", fieldbackground=_ENTRY_BG, foreground=_FG,
                         selectbackground=_ACCENT, selectforeground=_BG,
                         relief="solid", borderwidth=1, bordercolor=_BORDER)
            st.map("TCombobox",
                   fieldbackground=[("readonly", _ENTRY_BG)],
                   foreground=[("readonly", _FG)])
            st.configure("TCheckbutton", background=_BG, foreground=_FG,
                         indicatorcolor=_ENTRY_BG, bordercolor=_BORDER)
            st.map("TCheckbutton", background=[("active", _BG)])
            st.configure("TRadiobutton", background=_BG, foreground=_FG,
                         indicatorcolor=_ENTRY_BG, bordercolor=_BORDER)
            st.map("TRadiobutton", background=[("active", _BG)])
            st.configure("TLabelframe", background=_BG, foreground=_FG,
                         bordercolor=_BORDER, relief="solid", borderwidth=1)
            st.configure("TLabelframe.Label", background=_BG, foreground=_FG, font=self._font())
            st.configure("TNotebook",     background=_BG2, borderwidth=1, bordercolor=_BORDER)
            st.configure("TNotebook.Tab", background=_BG3, foreground=_FG2,
                         padding=(12, 5), font=self._font(), bordercolor=_BORDER)
            st.map("TNotebook.Tab",
                   background=[("selected", _BG),    ("active", _BG2)],
                   foreground=[("selected", _ACCENT), ("active", _FG)])
            st.configure("TScrollbar", background=_BG2, troughcolor=_BG,
                         arrowcolor=_FG2, bordercolor=_BORDER)
            st.configure("TProgressbar", background=_ACCENT, troughcolor=_BG3, bordercolor=_BORDER)
            st.configure("TSeparator", background=_BORDER)
            st.configure("Accent.TButton", background=_ACCENT, foreground=_BG,
                         relief="solid", padding=(14, 8), font=self._font("bold"), bordercolor=_BORDER)
            st.map("Accent.TButton",
                   background=[("active", "#2560AA"), ("disabled", _BG3)],
                   foreground=[("disabled", _FG2)])
            st.configure("Stop.TButton", background=_ERR, foreground=_BG,
                         relief="solid", padding=(14, 8), font=self._font("bold"), bordercolor=_BORDER)
            st.map("Stop.TButton", background=[("active", "#AA2020")])
            st.configure("Browse.TButton", background=_BTN_BG, foreground=_FG,
                         relief="solid", padding=(6, 4), bordercolor=_BORDER)
            st.map("Browse.TButton", background=[("active", _BTN_HOV)])
            st.configure("InfoBtn.TButton", background=_BTN_BG, foreground=_FG,
                         relief="solid", padding=(14, 6), bordercolor=_BORDER,
                         anchor="center", justify="center")
            st.map("InfoBtn.TButton",
                   background=[("active", _BTN_HOV), ("disabled", _BG3)],
                   foreground=[("disabled", _FG2)])
            st.configure("Lang.TButton", background=_BTN_BG, foreground=_ACCENT,
                         relief="solid", padding=(6, 4), font=self._font("bold"), bordercolor=_BORDER)
            st.map("Lang.TButton", background=[("active", _BTN_HOV)])
            st.configure("FontCtrl.TButton", background=_BTN_BG, foreground=_FG,
                         relief="solid", padding=(4, 2), font=self._font("bold"), bordercolor=_BORDER)
            st.map("FontCtrl.TButton", background=[("active", _BTN_HOV)])

        # ── UI structure ──────────────────────────────────────────────────

        def _build_ui(self):
            hdr = ttk.Frame(self)
            hdr.pack(fill="x", padx=16, pady=(10, 4))

            self._hdr_title_lbl = ttk.Label(hdr, style="Bold.TLabel")
            self._hdr_title_lbl.pack(side="left")
            self._reg(self._hdr_title_lbl, "header_title")

            self._hdr_sub_lbl = ttk.Label(hdr, style="Muted.TLabel")
            self._hdr_sub_lbl.pack(side="left", pady=(3, 0))
            self._reg(self._hdr_sub_lbl, "header_subtitle")

            self._lang_btn = ttk.Button(hdr, style="Lang.TButton", command=self._toggle_lang)
            self._lang_btn.pack(side="right", padx=(6, 0))
            self._reg(self._lang_btn, "lang_switch")

            ttk.Button(hdr, text="+", style="FontCtrl.TButton",
                       command=self._font_up).pack(side="right", padx=(2, 0))
            self._font_sz_lbl = ttk.Label(hdr, text=str(self._font_sz),
                                          foreground=_FG2, width=3, anchor="center")
            self._font_sz_lbl.pack(side="right")
            ttk.Button(hdr, text="−", style="FontCtrl.TButton",
                       command=self._font_down).pack(side="right", padx=(6, 2))
            self._font_prefix_lbl = ttk.Label(hdr, style="Muted.TLabel")
            self._font_prefix_lbl.pack(side="right", padx=(16, 0))
            self._reg(self._font_prefix_lbl, "font_label")

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

            self._nb = ttk.Notebook(self)
            self._nb.pack(fill="both", expand=True, padx=10, pady=(0, 4))

            self._tab_input   = ttk.Frame(self._nb, padding=10)
            self._tab_search  = ttk.Frame(self._nb, padding=10)
            self._tab_physics = ttk.Frame(self._nb, padding=10)
            self._tab_output  = ttk.Frame(self._nb, padding=10)
            self._tab_run     = ttk.Frame(self._nb, padding=10)

            for tab in (self._tab_input, self._tab_search,
                        self._tab_physics, self._tab_output, self._tab_run):
                self._nb.add(tab, text="")

            self._tab_keys = [
                (0, "tab_input"), (1, "tab_search"), (2, "tab_physics"),
                (3, "tab_output"), (4, "tab_run"),
            ]

            self._build_tab_input()
            self._build_tab_search()
            self._build_tab_physics()
            self._build_tab_output()
            self._build_tab_run()

        # ── Tab: Band / Source ────────────────────────────────────────────

        def _build_tab_input(self):
            t = self._tab_input
            src_lf = ttk.LabelFrame(t, padding=8)
            src_lf.pack(fill="x", pady=(0, 8))
            self._reg(src_lf, "band_source_lf")
            src_lf.columnconfigure(2, weight=1)

            self._src_mode = tk.StringVar(value="manual")
            self._rb_csv = ttk.Radiobutton(src_lf, variable=self._src_mode,
                                            value="csv", command=self._toggle_src)
            self._rb_csv.grid(row=0, column=0, sticky="w", padx=(0, 20))
            self._reg(self._rb_csv, "load_csv")
            self._rb_man = ttk.Radiobutton(src_lf, variable=self._src_mode,
                                            value="manual", command=self._toggle_src)
            self._rb_man.grid(row=0, column=1, sticky="w")
            self._reg(self._rb_man, "enter_manual")

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

            self._manual_frame = ttk.Frame(src_lf)
            self._manual_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))

            self._bands_lbl = ttk.Label(self._manual_frame)
            self._bands_lbl.grid(row=0, column=0, sticky="w")
            self._reg(self._bands_lbl, "bands_label")
            self._bands_var = tk.StringVar(value="40m,20m,15m")
            ttk.Entry(self._manual_frame, textvariable=self._bands_var, width=40).grid(
                row=0, column=1, padx=6, sticky="ew")
            self._known_bands_lbl = ttk.Label(self._manual_frame, style="Muted.TLabel", wraplength=480)
            self._known_bands_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
            self._reg_fn(lambda: self._known_bands_lbl.config(
                text=self.t("known_prefix") + ", ".join(_KNOWN_BANDS)))

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
            _wl = ttk.Label(self._manual_frame, foreground=_ACCENT)
            _wl.grid(row=4, column=2, sticky="w", padx=(4, 0), pady=(6, 0))
            self._reg(_wl, "hint_wire_len")

            self._cp_len_lbl = ttk.Label(self._manual_frame)
            self._cp_len_lbl.grid(row=5, column=0, sticky="w", pady=(4, 0))
            self._reg(self._cp_len_lbl, "cp_len")
            self._cp_len_var = tk.StringVar(value="5.0")
            ttk.Entry(self._manual_frame, textvariable=self._cp_len_var, width=12).grid(
                row=5, column=1, padx=6, pady=(4, 0), sticky="w")
            _cl = ttk.Label(self._manual_frame, foreground=_ACCENT)
            _cl.grid(row=5, column=2, sticky="w", padx=(4, 0), pady=(4, 0))
            self._reg(_cl, "hint_cp_len")

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
                         values=[str(r) for r in _UNUN_RATIOS]).pack(side="left", padx=6)
            self._unun_hint_lbl = ttk.Label(uf, style="Muted.TLabel")
            self._unun_hint_lbl.pack(side="left")
            self._reg(self._unun_hint_lbl, "unun_hint")

            optlang_lf = ttk.LabelFrame(t, padding=8)
            optlang_lf.pack(fill="x", pady=(0, 8))
            self._reg(optlang_lf, "optlang_lf")
            olf = ttk.Frame(optlang_lf)
            olf.pack(anchor="w")
            self._optlang_lbl = ttk.Label(olf)
            self._optlang_lbl.pack(side="left")
            self._reg(self._optlang_lbl, "optlang_label")
            self._optlang_var = tk.StringVar(value="auto")
            ttk.Combobox(olf, textvariable=self._optlang_var, width=10,
                         values=["auto", "en", "es"], state="readonly").pack(side="left", padx=6)
            self._optlang_hint_lbl = ttk.Label(olf, style="Muted.TLabel")
            self._optlang_hint_lbl.pack(side="left")
            self._reg(self._optlang_hint_lbl, "optlang_hint")

            self._toggle_src()

        def _toggle_src(self):
            if self._src_mode.get() == "csv":
                self._csv_frame.grid()
                self._manual_frame.grid_remove()
            else:
                self._csv_frame.grid_remove()
                self._manual_frame.grid()

        # ── Tab: Search Range ─────────────────────────────────────────────

        def _build_tab_search(self):
            t = self._tab_search
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
            _mg = ttk.Label(mf, foreground=_ACCENT)
            _mg.pack(side="left", padx=(8, 0))
            self._reg(_mg, "hint_margin")

            wr_lf = ttk.LabelFrame(t, padding=8)
            wr_lf.pack(fill="x", pady=(0, 8))
            self._reg(wr_lf, "wire_range_lf")
            self._wire_min_var  = tk.StringVar()
            self._wire_max_var  = tk.StringVar()
            self._wire_step_var = tk.StringVar(value="0.25")
            for row_i, (flag, var, hk) in enumerate([
                ("wire-min:",  self._wire_min_var,  "hint_wire_min"),
                ("wire-max:",  self._wire_max_var,  "hint_wire_max"),
                ("wire-step:", self._wire_step_var, "hint_wire_step"),
            ]):
                ttk.Label(wr_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
                ttk.Entry(wr_lf, textvariable=var, width=10).grid(row=row_i, column=1, padx=6, pady=3, sticky="w")
                ttk.Label(wr_lf, text="m", style="Muted.TLabel").grid(row=row_i, column=2, sticky="w")
                _h = ttk.Label(wr_lf, foreground=_ACCENT)
                _h.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
                self._reg(_h, hk)
            self._wire_empty_lbl = ttk.Label(wr_lf, style="Muted.TLabel")
            self._wire_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(self._wire_empty_lbl, "leave_empty_wire")

            cp_lf = ttk.LabelFrame(t, padding=8)
            cp_lf.pack(fill="x", pady=(0, 8))
            self._reg(cp_lf, "cp_range_lf")
            self._cp_min_var  = tk.StringVar()
            self._cp_max_var  = tk.StringVar()
            self._cp_step_var = tk.StringVar(value="0.25")
            for row_i, (flag, var, hk) in enumerate([
                ("cp-min:",  self._cp_min_var,  "hint_cp_min"),
                ("cp-max:",  self._cp_max_var,  "hint_cp_max"),
                ("cp-step:", self._cp_step_var, "hint_cp_step"),
            ]):
                ttk.Label(cp_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
                ttk.Entry(cp_lf, textvariable=var, width=10).grid(row=row_i, column=1, padx=6, pady=3, sticky="w")
                ttk.Label(cp_lf, text="m", style="Muted.TLabel").grid(row=row_i, column=2, sticky="w")
                _h = ttk.Label(cp_lf, foreground=_ACCENT)
                _h.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
                self._reg(_h, hk)
            self._cp_empty_lbl = ttk.Label(cp_lf, style="Muted.TLabel")
            self._cp_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(self._cp_empty_lbl, "leave_empty_cp")

            rt_lf = ttk.LabelFrame(t, padding=8)
            rt_lf.pack(fill="x", pady=(0, 8))
            self._reg(rt_lf, "retry_lf")
            rtf = ttk.Frame(rt_lf)
            rtf.pack(anchor="w")
            self._retry_lbl = ttk.Label(rtf)
            self._retry_lbl.pack(side="left")
            self._reg(self._retry_lbl, "max_retries")
            self._retry_var = tk.StringVar(value="0")
            ttk.Spinbox(rtf, from_=0, to=10, textvariable=self._retry_var, width=5).pack(side="left", padx=6)
            self._retry_hint_lbl = ttk.Label(rtf, style="Muted.TLabel")
            self._retry_hint_lbl.pack(side="left")
            self._reg(self._retry_hint_lbl, "retry_hint")
            _rt = ttk.Label(rtf, foreground=_ACCENT)
            _rt.pack(side="left", padx=(8, 0))
            self._reg(_rt, "hint_max_retries")

            tn_lf = ttk.LabelFrame(t, padding=8)
            tn_lf.pack(fill="x", pady=(0, 8))
            self._reg(tn_lf, "report_opts_lf")
            tnf = ttk.Frame(tn_lf)
            tnf.pack(anchor="w")
            self._topn_lbl = ttk.Label(tnf)
            self._topn_lbl.pack(side="left")
            self._reg(self._topn_lbl, "top_n")
            self._topn_var = tk.StringVar(value="20")
            ttk.Spinbox(tnf, from_=5, to=200, textvariable=self._topn_var, width=6).pack(side="left", padx=6)
            _tn = ttk.Label(tnf, foreground=_ACCENT)
            _tn.pack(side="left", padx=(8, 0))
            self._reg(_tn, "hint_top_n")

        # ── Tab: Physics ──────────────────────────────────────────────────

        def _build_tab_physics(self):
            t = self._tab_physics
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
            self._browse_nec_btn = ttk.Button(nf, style="Browse.TButton", command=self._browse_nec2c)
            self._browse_nec_btn.pack(side="left")
            self._reg(self._browse_nec_btn, "browse")
            self._auto_detect_btn = ttk.Button(nf, style="Browse.TButton", command=self._auto_detect_nec2c)
            self._auto_detect_btn.pack(side="left", padx=(6, 0))
            self._reg(self._auto_detect_btn, "auto_detect_btn")
            self._nec2c_hint_lbl = ttk.Label(nec_lf, style="Muted.TLabel")
            self._nec2c_hint_lbl.pack(anchor="w", pady=(2, 0))
            self._reg(self._nec2c_hint_lbl, "nec2c_hint")

            hgt_lf = ttk.LabelFrame(t, padding=8)
            hgt_lf.pack(fill="x", pady=(0, 8))
            self._reg(hgt_lf, "antenna_geom_lf")
            self._wire_height_var      = tk.StringVar(value="8.0")
            self._cp_height_var        = tk.StringVar(value="0.5")
            self._wire_slope_end_var   = tk.StringVar(value="")   # empty = horizontal
            for row_i, (key_lbl, var, key_hint) in enumerate([
                ("wire_height_lbl",    self._wire_height_var,    "wire_height_hint"),
                ("cp_height_lbl",      self._cp_height_var,      "cp_height_hint"),
                ("wire_slope_end_lbl", self._wire_slope_end_var, "wire_slope_end_hint"),
            ]):
                lbl = ttk.Label(hgt_lf)
                lbl.grid(row=row_i, column=0, sticky="w", pady=3)
                self._reg(lbl, key_lbl)
                ttk.Entry(hgt_lf, textvariable=var, width=10).grid(row=row_i, column=1, padx=6, pady=3, sticky="w")
                ttk.Label(hgt_lf, text="m", style="Muted.TLabel").grid(row=row_i, column=2, sticky="w")
                hl = ttk.Label(hgt_lf, foreground=_ACCENT)
                hl.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
                self._reg(hl, key_hint)

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

            gnd_lf = ttk.LabelFrame(t, padding=8)
            gnd_lf.pack(fill="x", pady=(0, 8))
            self._reg(gnd_lf, "ground_lf")
            gf = ttk.Frame(gnd_lf)
            gf.pack(anchor="w")
            self._cond_lbl = ttk.Label(gf)
            self._cond_lbl.grid(row=0, column=0, sticky="w", pady=3)
            self._reg(self._cond_lbl, "conductivity")
            self._ground_cond_var = tk.StringVar(value="0.005")
            ttk.Entry(gf, textvariable=self._ground_cond_var, width=10).grid(row=0, column=1, padx=6, pady=3)
            self._cond_unit_lbl = ttk.Label(gf, style="Muted.TLabel")
            self._cond_unit_lbl.grid(row=0, column=2, sticky="w")
            self._reg(self._cond_unit_lbl, "cond_unit")
            self._perm_lbl = ttk.Label(gf)
            self._perm_lbl.grid(row=1, column=0, sticky="w", pady=3)
            self._reg(self._perm_lbl, "permittivity")
            self._ground_diel_var = tk.StringVar(value="13.0")
            ttk.Entry(gf, textvariable=self._ground_diel_var, width=10).grid(row=1, column=1, padx=6, pady=3)
            self._perm_hint_lbl = ttk.Label(gf, style="Muted.TLabel")
            self._perm_hint_lbl.grid(row=1, column=2, sticky="w")
            self._reg(self._perm_hint_lbl, "perm_hint")

            presets_frame = ttk.Frame(gnd_lf)
            presets_frame.pack(anchor="w", pady=(4, 0))
            self._presets_prefix_lbl = ttk.Label(presets_frame, style="Muted.TLabel")
            self._presets_prefix_lbl.pack(side="left")
            self._reg(self._presets_prefix_lbl, "quick_presets")
            for key, cond, diel in [
                ("preset_poor",  "0.001", "5"),
                ("preset_avg",   "0.005", "13"),
                ("preset_good",  "0.010", "20"),
                ("preset_excel", "0.030", "25"),
                ("preset_salt",  "5.000", "80"),
            ]:
                btn = ttk.Button(presets_frame, style="Browse.TButton",
                                 command=lambda c=cond, d=diel: (
                                     self._ground_cond_var.set(c),
                                     self._ground_diel_var.set(d)))
                btn.pack(side="left", padx=(6, 0))
                self._reg(btn, key)

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

        # ── Tab: Output Files ─────────────────────────────────────────────

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
            for row_i, (flag, var, hk) in enumerate([
                ("out-txt:",       self._out_txt_var, "hint_out_txt"),
                ("out-png:",       self._out_png_var, "hint_out_png"),
                ("out-csv:",       self._out_csv_var, "hint_out_csv"),
                ("out-nec:",       self._out_nec_var, "hint_out_nec"),
                ("out-radiation:", self._out_rad_var, "hint_out_rad"),
            ]):
                ttk.Label(of_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
                ttk.Entry(of_lf, textvariable=var, width=30).grid(
                    row=row_i, column=1, padx=6, pady=3, sticky="ew")
                hl = ttk.Label(of_lf, foreground=_ACCENT)
                hl.grid(row=row_i, column=2, sticky="w", padx=(8, 0))
                self._reg(hl, hk)
            of_lf.columnconfigure(1, weight=1)

        # ── Tab: Run ──────────────────────────────────────────────────────

        def _build_tab_run(self):
            t = self._tab_run
            cmd_lf = ttk.LabelFrame(t, padding=8)
            cmd_lf.pack(fill="x", expand=False, pady=(0, 8))
            self._reg(cmd_lf, "cmd_preview_lf")
            self._cmd_text = tk.Text(cmd_lf, height=4, wrap="word", state="disabled",
                                     bg=_ENTRY_BG, fg=_FG, font=self._font("mono"),
                                     relief="solid", insertbackground=_FG,
                                     highlightbackground=_BORDER, highlightthickness=1)
            self._cmd_text.pack(fill="x", expand=False)
            self._refresh_btn = ttk.Button(cmd_lf, style="Browse.TButton", command=self._refresh_cmd)
            self._refresh_btn.pack(anchor="e", pady=(4, 0))
            self._reg(self._refresh_btn, "refresh_preview")

            btn_frame = ttk.Frame(t)
            btn_frame.pack(fill="x", pady=(0, 8))
            self._run_btn = ttk.Button(btn_frame, style="Accent.TButton", command=self._run)
            self._run_btn.pack(side="left", padx=(0, 10))
            self._reg(self._run_btn, "run_btn")
            self._stop_btn = ttk.Button(btn_frame, style="Stop.TButton",
                                         command=self._stop, state="disabled")
            self._stop_btn.pack(side="left")
            self._reg(self._stop_btn, "stop_btn")
            self._show_report_btn = ttk.Button(btn_frame, style="InfoBtn.TButton",
                                                command=self._show_report, state="disabled")
            self._show_report_btn.pack(side="left", padx=(10, 0))
            self._reg(self._show_report_btn, "show_report_btn")
            self._show_radiation_btn = ttk.Button(btn_frame, style="InfoBtn.TButton",
                                                   command=self._show_radiation, state="disabled")
            self._show_radiation_btn.pack(side="left", padx=(6, 0))
            self._reg(self._show_radiation_btn, "show_radiation_btn")
            self._status_lbl = ttk.Label(btn_frame, foreground=_FG2)
            self._status_lbl.pack(side="left", padx=16)
            self._status_key: str = "idle"
            self._reg_fn(lambda: self._status_lbl.config(text=self.t(self._status_key))
                         if self._status_key else None)

            self._progress = ttk.Progressbar(t, mode="indeterminate", length=400)
            self._progress.pack(fill="x", pady=(0, 8))

            con_lf = ttk.LabelFrame(t, padding=4)
            con_lf.pack(fill="both", expand=True)
            self._reg(con_lf, "console_lf")
            self._console = scrolledtext.ScrolledText(
                con_lf, wrap="none", state="disabled",
                bg=_ENTRY_BG, fg=_FG, font=self._font("mono"), relief="solid",
                insertbackground=_FG, highlightbackground=_BORDER, highlightthickness=1)
            self._console.pack(fill="both", expand=True)
            self._console.tag_config("warn",  foreground=_TAG_WARN)
            self._console.tag_config("error", foreground=_TAG_ERR)
            self._console.tag_config("ok",    foreground=_TAG_OK)
            self._console.tag_config("head",  foreground=_TAG_HEAD)
            self._clear_btn = ttk.Button(con_lf, style="Browse.TButton", command=self._clear_console)
            self._clear_btn.pack(anchor="e", pady=(2, 0))
            self._reg(self._clear_btn, "clear_btn")

            self._set_status_key("idle")
            self._refresh_cmd()

        # ── Browse helpers ────────────────────────────────────────────────

        def _browse_script(self):
            p = filedialog.askopenfilename(
                title="Select nec2_length_optimizer.py",
                filetypes=[("Python script", "*.py"), ("All files", "*")])
            if p:
                self._script_var.set(p)

        def _browse_csv(self):
            p = filedialog.askopenfilename(
                title="Select band CSV file",
                filetypes=[("CSV files", "*.csv"), ("All files", "*")])
            if p:
                self._csv_var.set(p)

        def _browse_nec2c(self):
            p = filedialog.askopenfilename(
                title="Select nec2c binary",
                filetypes=[("Executable", "*"), ("All files", "*")])
            if p:
                self._nec2c_var.set(p)

        def _auto_detect_nec2c(self):
            found = _gui_find_nec2c()
            if found:
                self._nec2c_var.set(found)

        def _browse_outdir(self):
            p = filedialog.askdirectory(title="Select output directory")
            if p:
                self._outdir_var.set(p)

        # ── Command builder ───────────────────────────────────────────────

        def _build_cmd(self) -> list:
            script = self._script_var.get().strip()
            if not script:
                raise ValueError("Optimizer script path is not set.")
            cmd = [sys.executable, script]
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
            slope = self._wire_slope_end_var.get().strip()
            if slope:
                cmd += ["--wire-slope-end-height", slope]
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
            opt_lang = self._optlang_var.get().strip()
            if opt_lang and opt_lang != "auto":
                cmd += ["--lang", opt_lang]
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

        # ── Console helpers ───────────────────────────────────────────────

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

        def _set_status_key(self, key: str, color: str = _FG2, **kw):
            self._status_key = key
            self._status_lbl.config(text=self.t(key, **kw), foreground=color)

        def _set_status_text(self, text: str, color: str = _FG2):
            self._status_key = ""
            self._status_lbl.config(text=text, foreground=color)

        # ── Run / Stop ────────────────────────────────────────────────────

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
                    self.t("script_nf_msg", script=script))
                return
            self._refresh_cmd()
            self._clear_console()
            self._log(f"Command: {' '.join(cmd)}\n\n", "head")
            outdir = self._outdir_var.get().strip() or None
            if outdir and not os.path.isdir(outdir):
                try:
                    os.makedirs(outdir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror(self.t("dir_err_title"), self.t("dir_err_msg", e=e))
                    return
            self._running = True
            self._stopped = False
            self._run_btn.config(state="disabled")
            self._stop_btn.config(state="normal")
            self._show_report_btn.config(state="disabled")
            self._show_radiation_btn.config(state="disabled")
            self._progress.start(15)
            self._set_status_key("running", _ACCENT)
            self._thread = _threading.Thread(
                target=self._run_in_thread, args=(cmd, outdir), daemon=True)
            self._thread.start()

        def _run_in_thread(self, cmd: list, cwd):
            try:
                self._process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", cwd=cwd, bufsize=1)
                for line in self._process.stdout:
                    clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line)
                    self.after(0, self._log, clean)
                self._process.wait()
                rc = self._process.returncode
                if rc == 0:
                    self.after(0, self._run_finished, True, self.t("finished_ok"))
                else:
                    self.after(0, self._run_finished, False, self.t("exit_code", rc=rc))
            except Exception as e:
                self.after(0, self._run_finished, False, self.t("thread_error", e=e))
            finally:
                self._process = None

        def _run_finished(self, success: bool, msg: str):
            if self._stopped:
                return
            self._running = False
            self._run_btn.config(state="normal")
            self._stop_btn.config(state="disabled")
            self._progress.stop()
            color = _ACCENT2 if success else _ERR
            self._set_status_text(msg, color)
            self._log(f"\n{'─' * 60}\n{msg}\n", "ok" if success else "error")
            if success:
                outdir = self._outdir_var.get().strip() or os.getcwd()
                txt_name = self._out_txt_var.get().strip()
                rad_name = self._out_rad_var.get().strip()
                report  = os.path.join(outdir, txt_name) if txt_name else None
                radfile = os.path.join(outdir, rad_name) if rad_name else None
                if report and os.path.isfile(report):
                    self._show_report_btn.config(state="normal")
                if radfile and os.path.isfile(radfile):
                    self._show_radiation_btn.config(state="normal")

        def _stop(self):
            self._stopped = True
            if self._process is not None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._set_status_key("stopped", _WARN)
            self._running = False
            self._run_btn.config(state="normal")
            self._stop_btn.config(state="disabled")
            self._progress.stop()

        def _show_report(self):
            outdir   = self._outdir_var.get().strip() or os.getcwd()
            txt_name = self._out_txt_var.get().strip()
            report   = os.path.join(outdir, txt_name) if txt_name else None
            if report and os.path.isfile(report):
                self._open_file(report)

        def _show_radiation(self):
            outdir   = self._outdir_var.get().strip() or os.getcwd()
            rad_name = self._out_rad_var.get().strip()
            radfile  = os.path.join(outdir, rad_name) if rad_name else None
            if radfile and os.path.isfile(radfile):
                self._open_file(radfile)

        @staticmethod
        def _open_file(path: str):
            import platform as _plat
            if _plat.system() == "Windows":
                os.startfile(path)
            elif _plat.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])

    # ── Launch ────────────────────────────────────────────────────────────
    app = _App()
    app.mainloop()


if __name__ == "__main__":
    main()
