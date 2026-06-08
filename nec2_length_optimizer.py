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
        "en": "  Active bands  : {0}  ({1})",
        "es": "  Bandas activas: {0}  ({1})",
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
    r'^\s*((?:90(?:\.0+)?|[0-8]?\d(?:\.\d+)?))  \s+(\d{1,3}(?:\.\d+)?)\s+'
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
    try:
        with open(nec_path, 'r', errors='replace') as fh:
            for line in fh:
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
    for pat in _ALL_FREQ_RES:
        freq_matches.extend(pat.finditer(text))
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
    import re as _re
    if _re.fullmatch(r'-?[\d,\.]+', s):
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

    all_csv_scores = [r.avoidance_score for r in rows if r.avoidance_score > 0]
    use_computed = (len(set(all_csv_scores)) <= 1)

    for r in rows:
        if use_computed:
            pass
        else:
            if r.avoidance_score > 0:
                r._computed_avoidance = r.avoidance_score

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
    cp_height_m: float = 0.5,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
) -> None:
    """
    Write a minimal NEC2 input deck for a horizontal end-fed long wire
    with one counterpoise wire.

    Wire geometry:
      Wire 1  (antenna)  : horizontal, z = wire_height_m, x = 0..wire_len_m
      Wire 2  (CP, horiz): horizontal, z = cp_height_m,   x = 0..-cp_len_m
      Wire 2  (CP, vert) : vertical,   x = 0, z = wire_height_m..cp_height_m

    Source (EX): first segment of Wire 1 (x=0, the near end — the feedpoint
    junction where Wire 1 meets the counterpoise).
    """
    highest_f = max(freqs_mhz)
    segs_ant = _segs(wire_len_m, highest_f)
    segs_cp  = max(5, _segs(cp_len_m, highest_f))

    with open(nec_path, "w") as fh:
        fh.write(f"CM NEC2 Long Wire Optimizer Deck\n")
        fh.write(f"CM Wire length: {wire_len_m:.3f} m\n")
        fh.write(f"CM Counterpoise ({cp_type}): {cp_len_m:.3f} m  height: {cp_height_m:.2f} m\n")
        fh.write("CE\n")

        fh.write(f"GW 1 {segs_ant} "
                 f"0.0 0.0 {wire_height_m:.3f} "
                 f"{wire_len_m:.3f} 0.0 {wire_height_m:.3f} "
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
            vert_len    = wire_height_m - cp_bottom_z
            horiz_rem   = cp_len_m - vert_len
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

        fh.write("GE 0\n")
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        for f in freqs_mhz:
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            fh.write("XQ\n")
            fh.write("RP 0 1 1 0 90.0 0.0 0.0 0.0\n")
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


def _vswr_score_single(vswr: float) -> float:
    """
    Map a VSWR value to a penalty score:
      ≤1.5 → 0, ≤3.0 → linear 0-1, ≤6.0 → linear 1-3, >6 → 3 + log
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

        res.band_R_ant[cr.band]   = round(best_R, 2)
        res.band_X_ant[cr.band]   = round(best_X, 2)
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
        avoidance = min(frac, 1.0 - frac)           # 0 = at node; max = 0.5 mid-way, capped to 0.25 by threshold
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
    verbose: bool = False,
) -> List[CandidateResult]:
    results = []
    total = len(grid)
    for i, (w, c) in enumerate(grid):
        if verbose and i % max(1, total // 20) == 0:
            pct = i * 100 // total
            print(T("sweep_empirical_pct").format(pct, i, total, w, c), end="\r")
        r = score_candidate(w, c, calc_rows, unun_ratio, cp_type_hint=cp_type)
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
                    candidates_this.append(c_cand)

                if not candidates_this:
                    cand = CandidateResult(
                        wire_len_m=w, cp_len_m=c, cp_type="both",
                        score_combined=999.0, score_vswr_raw=999.0,
                        score_vswr=999.0, score_avoidance=0.0,
                        nec2_ok=False, note="NEC2 failed (both orientations)",
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
    """
    dominated = set()
    for i, a in enumerate(results):
        for j, b in enumerate(results):
            if i == j:
                continue
            if (b.score_vswr_raw          <= a.score_vswr_raw and
                    b.score_avoidance_active >= a.score_avoidance_active and
                    (b.score_vswr_raw         < a.score_vswr_raw or
                     b.score_avoidance_active > a.score_avoidance_active)):
                dominated.add(i)
                break
    return [r for i, r in enumerate(results) if i not in dominated]


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
) -> str:
    active = [r for r in calc_rows if r.active]
    bands  = [cr.band for cr in active]

    SEP  = "═" * 80
    SEP2 = "─" * 80
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
    all_bands_list  = [cr.band for cr in calc_rows]
    active_band_set = set(cr.band for cr in active)
    band_labels = [f"{b}(*)" if b in active_band_set else b for b in all_bands_list]
    ln(f"Active bands    : {len(active)} of {len(calc_rows)}"
       f"  ({', '.join(band_labels)})  (* = scored for VSWR)")

    display_total = total_candidates if total_candidates > 0 else len(ranked)
    ln(T("report_total_candidates").format(display_total))
    lines.append("")

    # ── TOP 20 RANKING ───────────────────────────────────────────────────
    top_n = len(ranked)
    h1(T("report_top_n_header").format(top_n))
    header = (f"  {'#':>3}  {'Wire(m)':>8}  {'CP(m)':>7}  {'CP type':>10}  "
              f"{'Score':>7}  {'meanVpen':>9}  {'1.5xWrst':>9}  {'-0.5xAv(a)':>10}  {'-0.1xCPbon':>11}  "
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
        _cp_bonus_deduction = (r.score_vswr_raw
                               - 0.5 * r.score_avoidance_active
                               - r.score_combined)
        lines.append(
            f"  {rank:3d}  {r.wire_len_m:8.3f}  {r.cp_len_m:7.3f}  {r.cp_type:>10}  "
            f"{r.score_combined:7.3f}  {_mean_vswr_pen:9.3f}  {_worst_pen_weighted:9.3f}  "
            f"{0.5*r.score_avoidance_active:10.4f}  {_cp_bonus_deduction:11.4f}  "
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
            ln(f"⚠  WIRE at search maximum ({_wmax:.3f} m) — {_hits_wire}/5 top candidates"
               f" hit this boundary.  True optimum may be longer."
               f"  Re-run with larger --wire-max or increase --margin.")
        elif abs(best.wire_len_m - _wmin) < _tol_r:
            ln(f"⚠  WIRE at search minimum ({_wmin:.3f} m) — {_hits_wire}/5 top candidates"
               f" hit this boundary.  True optimum may be shorter."
               f"  Re-run with smaller --wire-min or increase --margin.")
        if abs(best.cp_len_m - _cmax) < _tol_r:
            ln(f"⚠  CP at search maximum ({_cmax:.3f} m) — {_hits_cp}/5 top candidates"
               f" hit this boundary.  True optimum may be longer."
               f"  Re-run with larger --cp-max or increase --margin.")
        elif abs(best.cp_len_m - _cmin) < _tol_r:
            ln(f"⚠  CP at search minimum ({_cmin:.3f} m) — {_hits_cp}/5 top candidates"
               f" hit this boundary.  True optimum may be shorter."
               f"  Re-run with smaller --cp-min or increase --margin.")
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

    import re as _re
    clean = _re.sub(r'\x1b\[[0-9;]*m', '', report_text)
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
                "vswr_no_cp":     round(vswr_no, 3) if cr.active else "",
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

        fh.write(f"GW 1 {segs_ant} "
                 f"0.0 0.0 {wire_height_m:.3f} "
                 f"{best.wire_len_m:.3f} 0.0 {wire_height_m:.3f} "
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
            vert_len    = wire_height_m - cp_bottom_z
            horiz_rem   = best.cp_len_m - vert_len
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

        fh.write("GE 0\n")
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        d_theta = 90.0  / max(1, n_elevation - 1)
        d_phi   = 360.0 / max(1, n_azimuth   - 1)

        # Simulate ALL bands so inactive-band impedance data is also available
        # in the output deck.  RP pattern cards are written only for active bands
        # (radiation diagrams are only meaningful for bands the antenna is used on).
        active_freq_set = set(cr.freq_mhz for cr in active)
        for cr in calc_rows:
            f = cr.freq_mhz
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            fh.write("XQ\n")
            if f in active_freq_set:
                fh.write(
                    f"RP 0 {n_elevation} {n_azimuth} 1000 "
                    f"0.0 0.0 {d_theta:.4f} {d_phi:.4f} 0.0\n"
                )

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
    d_phi   = 360.0 / max(1, n_azimuth   - 1)
    elevations_deg = [i * d_theta for i in range(n_elevation)]
    azimuths_deg   = [i * d_phi   for i in range(n_azimuth)]

    band_patterns: Dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="nec2rad_") as tmpdir:
        nec_path = os.path.join(tmpdir, "best_radiation.nec")
        out_path_nec = os.path.join(tmpdir, "best_radiation.out")

        highest_f = max(freqs_all)
        segs_ant = _segs(best.wire_len_m, highest_f)
        segs_cp  = max(5, _segs(best.cp_len_m, highest_f))

        with open(nec_path, "w") as fh:
            fh.write("CM RP sweep deck\n")
            fh.write("CE\n")
            fh.write(f"GW 1 {segs_ant} "
                     f"0.0 0.0 {wire_height_m:.3f} "
                     f"{best.wire_len_m:.3f} 0.0 {wire_height_m:.3f} "
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
                vert_len = wire_height_m - cp_bottom_z
                horiz_rem = best.cp_len_m - vert_len
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
            fh.write("GE 0\n")
            fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")
            fh.write("EX 0 1 1 0 1.0 0.0\n")

            for cr in active:
                fh.write(f"FR 0 1 0 0 {cr.freq_mhz:.4f} 0\n")
                fh.write("XQ\n")
                fh.write(
                    f"RP 0 {n_elevation} {n_azimuth} 1000 "
                    f"0.0 0.0 {d_theta:.4f} {d_phi:.4f} 0.0\n"
                )
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
        _rp_row_re = re.compile(
            r'^\s*([\d.E+\-]+)\s+([\d.E+\-]+)'
            r'\s+([-+]?[\d.E+\-]+)\s+([-+]?[\d.E+\-]+)'
            r'\s+([-+]?[\d.E+\-]+)',
            re.MULTILINE,
        )

        in_rp = False
        _rows_at_rp_start: int = 0

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
                        _rows_at_rp_start = 0
                    else:
                        _rows_at_rp_start = len(existing)
                    in_rp = True
                else:
                    in_rp = False
                continue

            if in_rp and _cur_freq_ord is not None:
                m = _rp_row_re.match(line)
                if m:
                    try:
                        theta    = float(m.group(1))
                        phi      = float(m.group(2))
                        total_db = float(m.group(5))
                        bucket = parsed_patterns[_cur_freq_ord]
                        if _rows_at_rp_start == 0 or len(bucket) < _rows_at_rp_start:
                            bucket.append((theta, phi, total_db))
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
                best_theta = None
                for (t, p, db) in rows:
                    if abs(db - max_db) < 0.1:
                        best_theta = t
                        break
                if best_theta is not None:
                    az_data = sorted(
                        [(p, db) for (t, p, db) in rows if abs(t - best_theta) < d_theta * 1.5],
                        key=lambda x: x[0]
                    )
                else:
                    az_data = []
            else:
                max_db = -999.0
                az_data = []

            toa = 90.0 - (best_theta if best_theta is not None else 90.0)

            band_patterns[cr.band] = {
                "freq_mhz": freq,
                "elev": elev_data,
                "azim": az_data,
                "max_db": max_db,
                "toa_deg": toa,
                "vswr": best.band_vswr.get(cr.band, 999.0),
            }

    if not band_patterns:
        print(T("warn_no_rp_bands"))
        return

    n_bands = len(band_patterns)
    fig_height = max(5, 5 * n_bands)
    fig = plt.figure(figsize=(12, fig_height))
    fig.suptitle(
        T("plot_radiation_title").format(best.wire_len_m, best.cp_len_m, cp_type),
        fontsize=13, fontweight="bold", y=1.0
    )

    band_list = [cr.band for cr in active if cr.band in band_patterns]
    n_cols = 2

    for row_idx, band in enumerate(band_list):
        pat = band_patterns[band]
        freq_str = f"{pat['freq_mhz']:.3f} MHz"
        vswr_str = f"VSWR {pat['vswr']:.2f}"
        max_str  = f"Max {pat['max_db']:.1f} dBi"
        toa_str  = f"TOA {pat['toa_deg']:.1f}°"

        ax_el = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 1,
                                projection="polar")
        ax_el.set_title(f"{band}  {freq_str}\n{vswr_str}  {max_str}  {toa_str}",
                        fontsize=9, pad=12)

        if pat["elev"]:
            angles_el = [math.radians(e) for (e, _) in pat["elev"]]
            gains_el  = [g for (_, g) in pat["elev"]]
            g_floor = min(gains_el) if gains_el else 0.0
            g_max   = max(gains_el) if gains_el else 0.0
            gains_norm = [g - g_floor for g in gains_el]
            angles_mir = [-a for a in angles_el] + list(reversed(angles_el))
            gains_mir  = list(reversed(gains_norm)) + gains_norm
            ax_el.plot(angles_mir, gains_mir, color="steelblue", linewidth=1.5)
            ax_el.fill(angles_mir, gains_mir, color="steelblue", alpha=0.15)
            ax_el.set_rmax(g_max - g_floor)
            toa_rad = math.radians(pat["toa_deg"])
            ax_el.axvline(toa_rad,  color="red",   linestyle="--", linewidth=0.8, alpha=0.7)
            ax_el.axvline(-toa_rad, color="red",   linestyle="--", linewidth=0.8, alpha=0.7)

        ax_el.set_theta_zero_location("N")
        ax_el.set_theta_direction(-1)
        ax_el.set_thetamin(-90)
        ax_el.set_thetamax(90)
        ax_el.set_xticks([math.radians(a) for a in range(-90, 91, 15)])
        ax_el.set_xticklabels([f"{abs(a)}°" for a in range(-90, 91, 15)], fontsize=6)
        ax_el.set_ylabel(T("plot_dB_norm"), fontsize=7, labelpad=30)
        ax_el.grid(True, alpha=0.3)

        ax_az = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 2,
                                projection="polar")
        ax_az.set_title(T("plot_azimuth").format(band, freq_str), fontsize=9, pad=12)

        if pat["azim"]:
            angles_az = [math.radians(a) for (a, _) in pat["azim"]]
            gains_az  = [g for (_, g) in pat["azim"]]
            g_floor_az = min(gains_az) if gains_az else 0.0
            gains_az_norm = [g - g_floor_az for g in gains_az]
            if angles_az and abs(angles_az[-1] - 2 * math.pi) > 0.01:
                angles_az     = angles_az     + [2 * math.pi]
                gains_az_norm = gains_az_norm + [gains_az_norm[0]]
            ax_az.plot(angles_az, gains_az_norm, color="darkorange", linewidth=1.5)
            ax_az.fill(angles_az, gains_az_norm, color="darkorange", alpha=0.15)

        ax_az.set_theta_zero_location("N")
        ax_az.set_theta_direction(-1)
        ax_az.set_xticks([math.radians(a) for a in range(0, 360, 30)])
        ax_az.set_xticklabels([f"{a}°" for a in range(0, 360, 30)], fontsize=6)
        ax_az.set_ylabel(T("plot_dB_norm"), fontsize=7, labelpad=30)
        ax_az.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
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
                s=10, alpha=0.4, color="gray", label=T("plot_best_label")[1:])
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
        description=textwrap.dedent("""\
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
    )
    p.add_argument("--csv", metavar="FILE", default=None,
                   help="Band CSV (optional). "
                        "If omitted, supply --bands, --freqs, --wire-len, and --cp-len.")
    p.add_argument("--bands", metavar="NAMES", default=None,
                   help="Comma-separated band names, e.g. '40m,20m,15m'. "
                        "Required when --csv is not supplied.")
    p.add_argument("--freqs", metavar="MHZ", default=None,
                   help="Comma-separated centre frequencies in MHz, one per band. "
                        "Optional when all --bands names are recognised amateur-radio bands. "
                        "Required only for unrecognised band names.")
    p.add_argument("--wire-len", metavar="M", type=float, default=None,
                   help="Starting wire length in metres for the search window centre. "
                        "Required when --csv is not supplied.")
    p.add_argument("--cp-len", metavar="M", type=float, default=None,
                   help="Starting counterpoise length in metres for the search window centre. "
                        "Required when --csv is not supplied.")
    p.add_argument("--active-bands", metavar="BANDS", default=None,
                   help="Comma-separated list of band names to mark as active for VSWR scoring. "
                        "Overrides the 'active' column in the CSV.")
    p.add_argument("--unun", metavar="RATIO", type=float, default=None,
                   help="UnUn ratio (e.g. 9 for 9:1).  Default: read from CSV.")
    p.add_argument("--mode", choices=["empirical", "nec2", "auto"],
                   default="auto",
                   help="Evaluation mode (default: auto = nec2 if binary found, else empirical).")
    p.add_argument("--nec2c", metavar="PATH", default=None,
                   help="Explicit path to nec2c binary.  Overrides auto-discovery.")
    p.add_argument("--margin", metavar="M", type=float, default=2.0,
                   help="Search radius in metres around the CSV wire and CP lengths "
                        "(default 2.0 m).  Overridden by explicit --wire-min/max or "
                        "--cp-min/max.")
    p.add_argument("--wire-min", metavar="M", type=float, default=None,
                   help="Minimum wire length to search (metres).")
    p.add_argument("--wire-max", metavar="M", type=float, default=None,
                   help="Maximum wire length to search (metres).")
    p.add_argument("--wire-step", metavar="M", type=float, default=0.25,
                   help="Wire length step size (metres, default 0.25).")
    p.add_argument("--cp-min", metavar="M", type=float, default=None,
                   help="Minimum counterpoise length (metres).")
    p.add_argument("--cp-max", metavar="M", type=float, default=None,
                   help="Maximum counterpoise length (metres).")
    p.add_argument("--cp-step", metavar="M", type=float, default=0.25,
                   help="Counterpoise length step size (metres, default 0.25).")
    p.add_argument("--wire-height", metavar="M", type=float, default=None,
                   help="Antenna wire height above ground (metres). "
                        f"Default: height from CSV, or {DEFAULT_HEIGHT_M} m if not in CSV.")
    p.add_argument("--cp-height", metavar="M", type=float, default=None,
                   help="Counterpoise height above ground (metres). "
                        "Default: CP height from CSV, or 0.5 m if not in CSV.")
    p.add_argument("--cp-type", choices=["horizontal", "vertical", "both"],
                   default="both",
                   help="Counterpoise orientation(s) to simulate (default: both).")
    p.add_argument("--ground-cond", metavar="S/M", type=float,
                   default=DEFAULT_GROUND_COND,
                   help=f"Ground conductivity S/m (default {DEFAULT_GROUND_COND}).")
    p.add_argument("--ground-diel", metavar="EPS", type=float,
                   default=DEFAULT_GROUND_DIEL,
                   help=f"Ground relative permittivity (default {DEFAULT_GROUND_DIEL}).")
    p.add_argument("--top-n", metavar="N", type=int, default=20,
                   help="Number of top candidates to show in report (default 20).")
    p.add_argument("--out-txt", metavar="FILE", default="optimizer_report.txt",
                   help="Output report filename (default: optimizer_report.txt).")
    p.add_argument("--out-png", metavar="FILE", default="optimizer_plot.png",
                   help="Output plot filename (default: optimizer_plot.png).")
    p.add_argument("--out-csv", metavar="FILE", default="optimizer_best.csv",
                   help="Best-candidate CSV output (default: optimizer_best.csv).")
    p.add_argument("--out-nec", metavar="FILE", default="best_antenna.nec",
                   help="NEC2 deck for the best antenna geometry (default: best_antenna.nec). "
                        "Includes full RP radiation-pattern cards per active band.")
    p.add_argument("--out-radiation", metavar="FILE", default="radiation_diagrams.png",
                   help="Radiation diagram PNG for all active bands (default: radiation_diagrams.png).")
    p.add_argument("--retry", metavar="N", type=int, default=0,
                   help="If the best candidate hits a search boundary (wire or CP at min/max), "
                        "automatically re-run the sweep up to N times, shifting the window "
                        "in the direction suggested by the warning (best+margin for 'may be "
                        "longer', best-margin for 'may be shorter').  Default: 0 (disabled).")
    p.add_argument("--no-interactive", action="store_true",
                   help="Do not prompt interactively for missing inputs; exit with error instead.")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress progress output.")
    p.add_argument("--lang", metavar="LANG", default="",
                   choices=["", "en", "es"],
                   help="Interface language: en (English) or es (Español). "
                        "Default: auto-detect from system locale.")
    return p


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print(f"{Fore.CYAN}{'═'*70}")
    print("  " + T("banner_title"))
    print(f"{'═'*70}{Style.RESET_ALL}")
    print()

    parser = _build_parser()
    args, _unknown = parser.parse_known_args()
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
            if ";" in _first_line and "," not in _first_line.split(";", 1)[1]:
                import re as _re
                def _fix_decimal(m):
                    s = m.group(0)
                    return _re.sub(r'(\d),(\d)', r'\1.\2', s)
                _norm = _re.sub(r'[^;\n]+', _fix_decimal, _raw)
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

    print(T("active_bands").format(len(active), ', '.join(r.band for r in active)))
    print(T("frequencies").format([r.freq_mhz for r in active]))

    # ── UnUn ratio ────────────────────────────────────────────────────────
    if args.unun is not None:
        unun_ratio = args.unun
    elif args.csv is None:
        if args.no_interactive:
            print(f"{Fore.RED}  No --unun supplied and no CSV to read it from."
                  f"  Use --unun RATIO (e.g. --unun 9).{Style.RESET_ALL}")
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
                        wire_height_m=args.wire_height,
                        cp_height_m=args.cp_height,
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
    )
    print(T("report_saved").format(args.out_txt))

    if ranked:
        export_best_csv(ranked[0], calc_rows, export_unun, args.out_csv)
        print(T("csv_best_saved").format(args.out_csv, export_unun))

    plot_results(results, pareto, ranked, calc_rows, unun_ratio, args.out_png)

    if ranked:
        write_best_nec_deck(
            best=ranked[0],
            calc_rows=calc_rows,
            out_path=args.out_nec,
            wire_height_m=args.wire_height,
            cp_height_m=args.cp_height,
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
            wire_height_m=args.wire_height,
            cp_height_m=args.cp_height,
            ground_cond=args.ground_cond,
            ground_diel=args.ground_diel,
        )
    elif ranked and mode != "nec2":
        print(f"  ℹ  Radiation diagrams require NEC2 mode"
              f" (current mode: {mode}) — skipped.")

    print()
    if verbose:
        import re as _re
        clean = _re.sub(r'\x1b\[[0-9;]*m', '', report)
        print(clean)

    print(f"\n{Fore.CYAN}" + T("done") + f"{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
