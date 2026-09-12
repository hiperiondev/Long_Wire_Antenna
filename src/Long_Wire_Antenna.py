#!/usr/bin/env python3
"""
=============================================================================
  NEC2 Antenna Length Optimizer
  Author: LU3VEA (CC0 v1.0)

  Searches for the optimal antenna wire length AND counterpoise length
  that minimise aggregate VSWR across all active bands given on the
  command line.

  For each candidate (wire_len, cp_len) pair the script:
    1. Writes a NEC2 .nec input deck  (sloping radiator + sloping counterpoise)
    2. Runs nec2c to produce a .out file
    3. Parses the .out file internally
    4. Computes the aggregate score  (penalised VSWR, avoidance, CP delta)
    5. Tracks the Pareto-optimal candidates

  At the end it writes:
    • A ranked text report     (optimizer_report.txt)
    • A scatter plot PNG       (optimizer_plot.png)
    • A ready-to-use CSV       (optimizer_best.csv)

  Usage:
    # Known bands — --freqs is optional (centre frequency auto-resolved):
    python nec2_length_optimizer.py --bands 40m,20m,15m \\
        --wire-len 21.0 --cp-len 5.0 [options]

    # Custom/unknown bands — --freqs required:
    python nec2_length_optimizer.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \\
        --wire-len 21.0 --cp-len 5.0 [options]

  Active band selection:
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
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
#   1. --lang {en|es|it}  CLI flag  (highest priority)
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
    """Return 'es'/'it' if the system locale looks Spanish/Italian, else 'en'."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var, "")
        if val:
            code = val.lower().split(".")[0].split("@")[0]
            if code.startswith("es"):
                return "es"
            if code.startswith("it"):
                return "it"
            if code[:2] in ("en", "fr", "de", "pt", "nl", "pl", "ru",
                            "zh", "ja", "ko", "ar", "tr"):
                return "en"   # any other explicit non-Spanish/Italian → English
    try:
        loc = _locale.getlocale()[0] or ""
        if loc.lower().startswith("es"):
            return "es"
        if loc.lower().startswith("it"):
            return "it"
    except Exception:
        pass
    return "en"

def _init_lang(lang_arg: str = "") -> None:
    """Set the active language.  Call once from main() after arg-parse."""
    global _LANG
    if lang_arg in ("en", "es", "it"):
        _LANG = lang_arg
    else:
        _LANG = _detect_locale_lang()

# ── Translation catalogue ─────────────────────────────────────────────────

_STRINGS: Dict[str, Dict[str, str]] = {
    # ── startup banner ───────────────────────────────────────────────────
    "banner_title": {
        "en": "NEC2 Antenna Length Optimizer",
        "es": "Optimizador de Longitud de Antena NEC2",
        "it": 'Ottimizzatore di Lunghezza Antenna NEC2',
    },
    # ── segmentation / convergence ───────────────────────────────────────
    # NOTE: the segmentation constants are defined further down, so these
    # strings carry {0}/{1} placeholders and are formatted at the call site.
    # Literal percent signs are doubled because argparse %-formats help text.
    "help_segs_per_half_wave": {
        "en": ("NEC2 segments per half wavelength: overrides both the sweep "
               "(default {0}) and the final runs (default {1}).  21 is "
               "pattern-grade only: it leaves R ~14%% low and gets the sign "
               "of X wrong."),
        "es": ("Segmentos NEC2 por media onda: anula tanto el barrido (por "
               "defecto {0}) como las corridas finales (por defecto {1}).  21 "
               "sirve sólo para diagramas: deja R un 14%% baja y equivoca el "
               "signo de X."),
        "it": 'Segmenti NEC2 per mezza onda: sostituisce sia la scansione (predefinito {0}) sia le esecuzioni finali (predefinito {1}).  21 serve solo per i diagrammi: lascia R circa il 14%% basso e sbaglia il segno di X.',
    },
    "help_fast": {
        "en": ("Sweep with coarse segmentation ({0} seg/half wave).  The ranking "
               "tolerates it; the winning geometry is recomputed at the fine "
               "density regardless."),
        "es": ("Barrido con segmentación gruesa ({0} seg/media onda).  El ranking "
               "lo tolera; la geometría ganadora se recalcula igualmente con la "
               "segmentación fina."),
        "it": 'Scansione con segmentazione grossolana ({0} seg/mezza onda).  La classifica lo tollera; la geometria vincente viene ricalcolata comunque con la segmentazione fine.',
    },
    "help_converge": {
        "en": ("Re-run the winning geometry at 2x and 4x segmentation and report "
               "how far R and X still move."),
        "es": ("Reejecuta la geometria ganadora a 2x y 4x la segmentacion e "
               "informa cuanto se siguen moviendo R y X."),
        "it": 'Riesegue la geometria vincente a 2x e 4x la segmentazione e riporta quanto R e X si spostano ancora.',
    },
    "segs_msg": {
        "en": "Segmentation: sweep {0} seg/half wave, published results {1} seg/half wave (R uncertainty ~{2:.0f}%)",
        "es": "Segmentación: barrido {0} seg/media onda, resultados publicados {1} seg/media onda (incertidumbre de R ~{2:.0f}%)",
        "it": 'Segmentazione: scansione {0} seg/mezza onda, risultati pubblicati {1} seg/mezza onda (incertezza di R ~{2:.0f}%)',
    },
    "segs_fast_warn": {
        "en": ("FAST sweep: {0} seg/half wave carries ~{1:.0f}% error on R — used "
               "for ranking only, never for the published impedances."),
        "es": ("Barrido RÁPIDO: {0} seg/media onda arrastra ~{1:.0f}% de error en R "
               "— sólo para ordenar candidatos, nunca para las impedancias publicadas."),
        "it": 'Scansione RAPIDA: {0} seg/mezza onda comporta ~{1:.0f}% di errore su R — usato solo per la classifica, mai per le impedenze pubblicate.',
    },
    "refining_best": {
        "en": "  Recomputing the best geometry at {0} segments per half wave …",
        "es": "  Recalculando la mejor geometría con {0} segmentos por media onda …",
        "it": '  Ricalcolo della migliore geometria con {0} segmenti per mezza onda …',
    },
    "refining_best_failed": {
        "en": "Refinement run failed — the impedances are still the coarse sweep values.",
        "es": "Falló el recálculo — las impedancias siguen siendo las del barrido grueso.",
        "it": 'Il ricalcolo è fallito — le impedenze sono ancora quelle della scansione grossolana.',
    },
    "converge_header": {
        "en": "  Segmentation convergence check (base {0} seg/half wave, plus {1}) …",
        "es": "  Comprobación de convergencia de segmentación (base {0} seg/media onda, más {1}) …",
        "it": '  Verifica di convergenza della segmentazione (base {0} seg/mezza onda, più {1}) …',
    },
    "converge_running": {
        "en": "    running {0} seg/half wave  (wire {1} seg / cp {2} seg) …",
        "es": "    ejecutando {0} seg/media onda  (hilo {1} seg / cp {2} seg) …",
        "it": '    esecuzione {0} seg/mezza onda  (filo {1} seg / cp {2} seg) …',
    },
    "converge_drift": {
        "en": "R drift from {0} to {1} seg/half wave: {2:.1f}%  |  largest X change: {3:.1f} ohm",
        "es": "Deriva de R entre {0} y {1} seg/media onda: {2:.1f}%  |  mayor cambio de X: {3:.1f} ohm",
        "it": 'Deriva di R tra {0} e {1} seg/mezza onda: {2:.1f}%  |  maggior variazione di X: {3:.1f} ohm',
    },
    "converge_sign_flip": {
        "en": "! The reactance CHANGES SIGN between segmentation densities on: {0}",
        "es": "! La reactancia CAMBIA DE SIGNO entre segmentaciones en: {0}",
        "it": '! La reattanza CAMBIA SEGNO tra le densità di segmentazione su: {0}',
    },
    "converge_r_ok": {
        "en": "R converged: the R drift is within the {0:.0f}% tolerance.",
        "es": "R convergida: la deriva de R está dentro de la tolerancia del {0:.0f}%.",
        "it": 'R convergente: la deriva di R è entro la tolleranza del {0:.0f}%.',
    },
    "converge_warn": {
        "en": ("! R NOT converged: the R drift exceeds {0:.0f}%.  The resistance is "
               "still moving at {1} seg/half wave — treat R as indicative."),
        "es": ("! R SIN convergir: la deriva de R supera el {0:.0f}%.  La resistencia "
               "sigue moviéndose con {1} seg/media onda — tomar R como orientativa."),
        "it": '! R NON convergente: la deriva di R supera il {0:.0f}%.  La resistenza si muove ancora a {1} seg/mezza onda — considerare R come indicativa.',
    },
    "converge_x_ok": {
        "en": "X converged: largest X drift {0:.1f} ohm, tolerance {1:.1f} ohm.",
        "es": "X convergida: mayor deriva de X {0:.1f} ohm, tolerancia {1:.1f} ohm.",
        "it": 'X convergente: massima deriva di X {0:.1f} ohm, tolleranza {1:.1f} ohm.',
    },
    "converge_x_warn": {
        "en": ("! X NOT converged: largest X drift {0:.1f} ohm against a {1:.1f} ohm "
               "tolerance on {2}.  The reactance is still moving at {3} seg/half "
               "wave — do NOT size a matching network from it."),
        "es": ("! X SIN convergir: mayor deriva de X {0:.1f} ohm frente a una tolerancia "
               "de {1:.1f} ohm en {2}.  La reactancia sigue moviéndose con {3} "
               "seg/media onda — NO dimensionar un acoplador con ella."),
        "it": '! X NON convergente: massima deriva di X {0:.1f} ohm contro una tolleranza di {1:.1f} ohm su {2}.  La reattanza si muove ancora a {3} seg/mezza onda — NON dimensionare un accoppiatore da essa.',
    },
    "converge_unc_pair": {
        "en": "Published uncertainty: R ±{0:.1f}% of R, X ±{1:.1f} ohm (both measured).",
        "es": "Incertidumbre publicada: R ±{0:.1f}% de R, X ±{1:.1f} ohm (ambas medidas).",
        "it": 'Incertezza pubblicata: R ±{0:.1f}% di R, X ±{1:.1f} ohm (entrambe misurate).',
    },
    "impedance_uncertainty_note": {
        "en": "({0} seg/half wave; R uncertainty ~{1:.0f}% of R, {2})",
        "es": "({0} seg/media onda; incertidumbre de R ~{1:.0f}% de R, {2})",
        "it": '({0} seg/mezza onda; incertezza di R ~{1:.0f}% di R, {2})',
    },
    "imp_unc_measured": {
        "en": "measured with --converge",
        "es": "medida con --converge",
        "it": 'misurata con --converge',
    },
    "imp_unc_estimated": {
        "en": "estimated — run --converge to measure it",
        "es": "estimada — usar --converge para medirla",
        "it": 'stimata — eseguire --converge per misurarla',
    },
    "imp_unc_x_measured": {
        "en": "     X uncertainty ±{0:.1f} ohm (measured with --converge).",
        "es": "     Incertidumbre de X ±{0:.1f} ohm (medida con --converge).",
        "it": '     Incertezza di X ±{0:.1f} ohm (misurata con --converge).',
    },
    "imp_unc_x_estimated": {
        "en": ("     X is printed WITHOUT an uncertainty: the % above applies to R only. "
               "X drifts with segmentation on a different scale — run --converge to "
               "measure it."),
        "es": ("     X se imprime SIN incertidumbre: el % anterior se aplica sólo a R. "
               "X deriva con la segmentación en otra escala — usar --converge para "
               "medirla."),
        "it": '     X è stampata SENZA incertezza: la % sopra si applica solo a R. X deriva con la segmentazione su una scala diversa — eseguire --converge per misurarla.',
    },
    "report_segmentation": {
        "en": "Segmentation      : sweep {0} seg/half wave, published results {1} seg/half wave",
        "es": "Segmentación      : barrido {0} seg/media onda, resultados publicados {1} seg/media onda",
        "it": 'Segmentazione      : scansione {0} seg/mezza onda, risultati pubblicati {1} seg/mezza onda',
    },
    "report_imp_uncertainty": {
        "en": "Impedance error   : R ~{0:.0f}% of R from segmentation ({1})",
        "es": "Error de impedancia: R ~{0:.0f}% de R por segmentación ({1})",
        "it": 'Errore di impedenza: R ~{0:.0f}% di R per segmentazione ({1})',
    },
    "report_imp_uncertainty_x": {
        "en": "                    X ±{0:.1f} ohm from segmentation (measured with --converge)",
        "es": "                    X ±{0:.1f} ohm por segmentación (medida con --converge)",
        "it": '                    X ±{0:.1f} ohm per segmentazione (misurata con --converge)',
    },
    "report_imp_uncertainty_x_none": {
        "en": ("                    X has no measured uncertainty — the figure above "
               "applies to R only; run --converge to measure the X drift"),
        "es": ("                    X no tiene incertidumbre medida — la cifra anterior "
               "se aplica sólo a R; usar --converge para medir la deriva de X"),
        "it": '                    X non ha incertezza misurata — la cifra sopra si applica solo a R; eseguire --converge per misurare la deriva di X',
    },
    "report_imp_precision_note": {
        "en": ("  R_ant is printed with its segmentation uncertainty "
               "({0} seg/half wave, ~{1:.0f}% of R)."),
        "es": ("  R_ant se imprime con su incertidumbre de segmentación "
               "({0} seg/media onda, ~{1:.0f}% de R)."),
        "it": '  R_ant è stampata con la sua incertezza di segmentazione ({0} seg/mezza onda, ~{1:.0f}% di R).',
    },
    "report_imp_precision_note_x": {
        "en": "  X_ant is printed with its measured segmentation uncertainty (±{0:.1f} ohm).",
        "es": "  X_ant se imprime con su incertidumbre de segmentación medida (±{0:.1f} ohm).",
        "it": '  X_ant è stampata con la sua incertezza di segmentazione misurata (±{0:.1f} ohm).',
    },
    "report_imp_precision_note_x_none": {
        "en": ("  X_ant is printed WITHOUT an uncertainty: the percentage above is an R "
               "model and does not describe the X drift.  Run --converge to measure it."),
        "es": ("  X_ant se imprime SIN incertidumbre: el porcentaje anterior es un modelo "
               "de R y no describe la deriva de X.  Usar --converge para medirla."),
        "it": '  X_ant è stampata SENZA incertezza: la percentuale sopra è un modello di R e non descrive la deriva di X.  Eseguire --converge per misurarla.',
    },
    "report_converge_section": {
        "en": "SEGMENTATION CONVERGENCE CHECK",
        "es": "COMPROBACIÓN DE CONVERGENCIA DE SEGMENTACIÓN",
        "it": 'VERIFICA DI CONVERGENZA DELLA SEGMENTAZIONE',
    },
    "unun_refined_change": {
        "en": ("The refined impedances change the best UnUn ratio: {0}:1 -> {1}:1 "
               "(the coarse sweep values pointed at the previous one)."),
        "es": ("Las impedancias refinadas cambian la mejor relación de UnUn: {0}:1 → {1}:1 "
               "(los valores del barrido grueso apuntaban a la anterior)."),
        "it": 'Le impedenze raffinate cambiano il miglior rapporto UnUn: {0}:1 -> {1}:1 (i valori della scansione grossolana indicavano il precedente).',
    },
    # ── nec2c discovery ──────────────────────────────────────────────────
    "nec2c_not_found_path": {
        "en": "  --nec2c path not found or not executable: {0}",
        "es": "  La ruta --nec2c no existe o no es ejecutable: {0}",
        "it": '  Percorso --nec2c non trovato o non eseguibile: {0}',
    },
    "nec2c_found_env": {
        "en": "  nec2c found via $NEC2C → {0}",
        "es": "  nec2c encontrado vía $NEC2C → {0}",
        "it": '  nec2c trovato via $NEC2C → {0}',
    },
    "nec2c_found_path": {
        "en": "  nec2c found on PATH → {0}",
        "es": "  nec2c encontrado en PATH → {0}",
        "it": '  nec2c trovato nel PATH → {0}',
    },
    "nec2c_found": {
        "en": "  nec2c found → {0}",
        "es": "  nec2c encontrado → {0}",
        "it": '  nec2c trovato → {0}',
    },
    "nec2c_not_found_auto": {
        "en": "  nec2c/onec binary not found automatically.",
        "es": "  El binario nec2c/onec no se encontró automáticamente.",
        "it": '  Binario nec2c/onec non trovato automaticamente.',
    },
    "nec2c_options": {
        "en": "  Options:",
        "es": "  Opciones:",
        "it": '  Opzioni:',
    },
    "nec2c_install_apt": {
        "en": "    • Install:  sudo apt install nec2c   (Debian/Ubuntu)",
        "es": "    • Instalar: sudo apt install nec2c   (Debian/Ubuntu)",
        "it": '    • Installare: sudo apt install nec2c   (Debian/Ubuntu)',
    },
    "nec2c_install_brew": {
        "en": "    •           brew install nec2c        (macOS / Homebrew)",
        "es": "    •           brew install nec2c        (macOS / Homebrew)",
        "it": '    •             brew install nec2c        (macOS / Homebrew)',
    },
    "nec2c_install_onec_header": {
        "en": "    • Install OpenNEC (onec):",
        "es": "    • Instalar OpenNEC (onec):",
        "it": '    • Installare OpenNEC (onec):',
    },
    "nec2c_install_onec_brew": {
        "en": ("        brew tap maurymarkowitz/tap https://github.com/maurymarkowitz/homebrew-tap\n"
               "        brew install maurymarkowitz/tap/onec   (macOS / Linux)"),
        "es": ("        brew tap maurymarkowitz/tap https://github.com/maurymarkowitz/homebrew-tap\n"
               "        brew install maurymarkowitz/tap/onec   (macOS / Linux)"),
        "it": '        brew tap maurymarkowitz/tap https://github.com/maurymarkowitz/homebrew-tap\n        brew install maurymarkowitz/tap/onec   (macOS / Linux)',
    },
    "nec2c_install_onec_scoop": {
        "en": ("        scoop bucket add maurymarkowitz https://github.com/maurymarkowitz/scoop-bucket\n"
               "        scoop install onec                     (Windows)"),
        "es": ("        scoop bucket add maurymarkowitz https://github.com/maurymarkowitz/scoop-bucket\n"
               "        scoop install onec                     (Windows)"),
        "it": '        scoop bucket add maurymarkowitz https://github.com/maurymarkowitz/scoop-bucket\n        scoop install onec                     (Windows)',
    },
    "nec2c_build_source_header": {
        "en": "    • Build nec2c from source (small, compiles in seconds, no package needed):",
        "es": "    • Compilar nec2c desde el código fuente (pequeño, compila en segundos, sin paquete):",
        "it": '    • Compilare nec2c dal codice sorgente (piccolo, compila in pochi secondi, nessun pacchetto necessario):',
    },
    "nec2c_build_source_steps": {
        "en": ("        git clone https://github.com/KJ7LNW/nec2c.git && cd nec2c\n"
               "        gcc -O2 -DPACKAGE_STRING='\\\"nec2c\\\"' -o nec2c $(ls *.c | grep -v '^nec2c.c$') -lm\n"
               "        (then point here with --nec2c ./nec2c  or  export NEC2C=$PWD/nec2c)"),
        "es": ("        git clone https://github.com/KJ7LNW/nec2c.git && cd nec2c\n"
               "        gcc -O2 -DPACKAGE_STRING='\\\"nec2c\\\"' -o nec2c $(ls *.c | grep -v '^nec2c.c$') -lm\n"
               "        (luego indique la ruta con --nec2c ./nec2c  o  export NEC2C=$PWD/nec2c)"),
        "it": '        git clone https://github.com/KJ7LNW/nec2c.git && cd nec2c\n        gcc -O2 -DPACKAGE_STRING=\'\\"nec2c\\"\' -o nec2c $(ls *.c | grep -v \'^nec2c.c$\') -lm\n        (poi indicare il percorso con --nec2c ./nec2c  o  export NEC2C=$PWD/nec2c)',
    },
    "nec2c_rerun": {
        "en": "    • Re-run with:  --nec2c /full/path/to/nec2c  or  --nec2c C:\\path\\to\\onec.exe",
        "es": "    • Ejecutar con: --nec2c /ruta/completa/a/nec2c  o  --nec2c C:\\ruta\\a\\onec.exe",
        "it": '    • Rieseguire con:  --nec2c /percorso/completo/a/nec2c  o  --nec2c C:\\percorso\\a\\onec.exe',
    },
    "nec2c_env": {
        "en": "    • Set env var:  export NEC2C=/full/path/to/nec2c  (or set NEC2C=...  on Windows)",
        "es": "    • Variable env: export NEC2C=/ruta/completa/a/nec2c  (o set NEC2C=...  en Windows)",
        "it": '    • Variabile env:  export NEC2C=/percorso/completo/a/nec2c  (o set NEC2C=...  su Windows)',
    },
    "nec2c_prompt": {
        "en": "  Enter path to nec2c binary (or press Enter to skip NEC2 runs): ",
        "es": "  Ingrese la ruta al binario nec2c (o Enter para omitir NEC2): ",
        "it": '  Inserire il percorso del binario nec2c (o Invio per saltare le esecuzioni NEC2): ',
    },
    "nec2c_bad_path": {
        "en": "  Path not found or not executable: {0}",
        "es": "  Ruta no encontrada o no ejecutable: {0}",
        "it": '  Percorso non trovato o non eseguibile: {0}',
    },
    "nec2c_fallback_empirical": {
        "en": ("  nec2c not found — falling back to empirical mode (screening only; "
               "reactance values are not modelled and must not be used for matching-"
               "network design). Install nec2c for accurate impedances — see build "
               "instructions above."),
        "es": ("  nec2c no encontrado — cambiando a modo empírico (sólo para cribar; "
               "los valores de reactancia no están modelados y no deben usarse para "
               "diseñar una red de adaptación). Instale nec2c para impedancias "
               "confiables — vea las instrucciones de compilación arriba."),
        "it": '  nec2c non trovato — passaggio alla modalità empirica (solo per selezione; i valori di reattanza non sono modellati e non devono essere usati per progettare una rete di adattamento). Installare nec2c per impedenze affidabili — vedere le istruzioni di compilazione sopra.',
    },
    "nec2c_required": {
        "en": "  --mode nec2 requires nec2c binary.  Use --nec2c PATH or install nec2c.",
        "es": "  --mode nec2 requiere el binario nec2c.  Use --nec2c RUTA o instale nec2c.",
        "it": '  --mode nec2 richiede il binario nec2c.  Usare --nec2c PERCORSO o installare nec2c.',
    },
    # ── band setup ───────────────────────────────────────────────────────
    # ── CLI errors ───────────────────────────────────────────────────────
    "err_missing_args": {
        "en": "  ERROR: the following arguments are required:",
        "es": "  ERROR: faltan los siguientes argumentos requeridos:",
        "it": '  ERRORE: i seguenti argomenti sono obbligatori:',
    },
    "err_supply_args": {
        "en": "  Supply all of the arguments above.",
        "es": "  Proporcione todos los argumentos anteriores.",
        "it": '  Fornire tutti gli argomenti sopra indicati.',
    },
    "err_freqs_nonnumeric": {
        "en": "  ERROR: --freqs contains a non-numeric value: {0}",
        "es": "  ERROR: --freqs contiene un valor no numérico: {0}",
        "it": '  ERRORE: --freqs contiene un valore non numerico: {0}',
    },
    "err_bands_freqs_mismatch": {
        "en": "  ERROR: --bands has {0} entries but --freqs has {1} entries.  They must match one-to-one.",
        "es": "  ERROR: --bands tiene {0} entradas pero --freqs tiene {1}.  Deben coincidir uno a uno.",
        "it": '  ERRORE: --bands ha {0} voci ma --freqs ne ha {1}.  Devono corrispondere una a una.',
    },
    "freqs_explicit": {
        "en": "  Frequencies   : explicit via --freqs",
        "es": "  Frecuencias   : explícitas vía --freqs",
        "it": '  Frequenze     : esplicite via --freqs',
    },
    "err_unknown_bands": {
        "en": "  ERROR: --freqs was not supplied and the following band name(s) are not in the built-in frequency table:",
        "es": "  ERROR: no se suministró --freqs y los siguientes nombres de banda no están en la tabla integrada:",
        "it": '  ERRORE: --freqs non è stato fornito e i seguenti nomi di banda non sono nella tabella integrata:',
    },
    "known_bands": {
        "en": "  Known bands: {0}",
        "es": "  Bandas conocidas: {0}",
        "it": '  Bande note: {0}',
    },
    "supply_freqs": {
        "en": "  Supply --freqs with one frequency per band to use custom names.",
        "es": "  Proporcione --freqs con una frecuencia por banda para usar nombres personalizados.",
        "it": '  Fornire --freqs con una frequenza per banda per usare nomi personalizzati.',
    },
    "freqs_auto": {
        "en": "  Frequencies   : auto-resolved from band names (use --freqs to override)",
        "es": "  Frecuencias   : resueltas automáticamente de los nombres de banda (use --freqs para anular)",
        "it": '  Frequenze     : risolte automaticamente dai nomi di banda (usare --freqs per sostituire)',
    },
    "warn_active_bands_unknown": {
        "en": "  ⚠  --active-bands contains names not in --bands: {0}.  They will be ignored.",
        "es": "  ⚠  --active-bands contiene nombres que no están en --bands: {0}.  Se ignorarán.",
        "it": '  ⚠  --active-bands contiene nomi non presenti in --bands: {0}.  Saranno ignorati.',
    },
    "band_source_cli": {
        "en": "  Band source   : command-line",
        "es": "  Fuente de bandas: línea de comandos",
        "it": '  Origine bande : riga di comando',
    },
    "bands_defined": {
        "en": "  Bands defined : {0}  ({1})",
        "es": "  Bandas definidas: {0}  ({1})",
        "it": '  Bande definite: {0}  ({1})',
    },
    "no_active_bands": {
        "en": "  No active bands found.  Use --active-bands to pick some, or omit it to activate every band in --bands.",
        "es": "  No se encontraron bandas activas.  Use --active-bands para elegir algunas, u omítalo para activar todas las bandas de --bands.",
        "it": '  Nessuna banda attiva trovata.  Usare --active-bands per sceglierne alcune, oppure ometterlo per attivare tutte le bande di --bands.',
    },
    "active_bands": {
        "en": "  Active bands  : {0} of {1}  ({2})",
        "es": "  Bandas activas: {0} de {1}  ({2})",
        "it": '  Bande attive  : {0} di {1}  ({2})',
    },
    "frequencies": {
        "en": "  Frequencies   : {0}",
        "es": "  Frecuencias   : {0}",
        "it": '  Frequenze     : {0}',
    },
    # ── UnUn (automatic) ─────────────────────────────────────────────────
    "unun_auto_mode": {
        "en": "  UnUn ratio    : automatic (the optimizer selects the best ratio)",
        "es": "  Relación UnUn : automática (el optimizador elige la mejor relación)",
        "it": "  Rapporto UnUn : automatico (l'ottimizzatore sceglie il rapporto migliore)",
    },
    # ── search range / grid ──────────────────────────────────────────────
    "search_margin": {
        "en": "  Search margin : ±{0} m around {1} wire {2:.3f} m  (use --margin to change)",
        "es": "  Margen búsqueda: ±{0} m alrededor del hilo {1} de {2:.3f} m  (use --margin para cambiar)",
        "it": '  Margine ricerca: ±{0} m attorno al filo {1} di {2:.3f} m  (usare --margin per cambiare)',
    },
    "wire_min": {
        "en": "  --wire-min    : {0} m",
        "es": "  --wire-min    : {0} m",
        "it": '  --wire-min    : {0} m',
    },
    "wire_max": {
        "en": "  --wire-max    : {0} m",
        "es": "  --wire-max    : {0} m",
        "it": '  --wire-max    : {0} m',
    },
    "cp_margin": {
        "en": "  CP margin     : ±{0} m around {1} CP {2:.3f} m  (use --margin to change)",
        "es": "  Margen CP     : ±{0} m alrededor del CP {1} de {2:.3f} m  (use --margin para cambiar)",
        "it": '  Margine CP    : ±{0} m attorno al CP {1} di {2:.3f} m  (usare --margin per cambiare)',
    },
    "cp_min": {
        "en": "  --cp-min      : {0} m",
        "es": "  --cp-min      : {0} m",
        "it": '  --cp-min      : {0} m',
    },
    "cp_max": {
        "en": "  --cp-max      : {0} m",
        "es": "  --cp-max      : {0} m",
        "it": '  --cp-max      : {0} m',
    },
    "ant_height": {
        "en": "  Antenna height: {0} m  {1}",
        "es": "  Altura antena : {0} m  {1}",
        "it": '  Altezza antenna: {0} m  {1}',
    },
    "ant_height_arg": {
        "en": "(--height)",
        "es": "(--height)",
        "it": '(--height)',
    },
    "ant_height_default": {
        "en": "(default; use --height to override)",
        "es": "(valor por defecto; use --height para anular)",
        "it": '(valore predefinito; usare --height per sostituire)',
    },
    "grid_size": {
        "en": "  Grid size     : {0} (wire) × {1} (cp) = {2} pairs",
        "es": "  Tamaño grilla : {0} (hilo) × {1} (CP) = {2} pares",
        "it": '  Dimensione griglia: {0} (filo) × {1} (CP) = {2} coppie',
    },
    "cp_end_height_msg": {
        "en": "  CP far end    : {0:.4f} m above ground  (counterpoise runs from the feedpoint down to this height)",
        "es": "  Extremo CP    : {0:.4f} m sobre el suelo  (el contrapeso va del punto de alimentación hasta esa altura)",
        "it": "  Estremo CP    : {0:.4f} m sopra il suolo  (il contrappeso va dal punto di alimentazione fino a quell'altezza)",
    },
    "cp_end_height_src_arg": {
        "en": "(--cp-end-height)",
        "es": "(--cp-end-height)",
        "it": '(--cp-end-height)',
    },
    "cp_end_height_warn_all": {
        "en": ("  WARNING: no counterpoise length in the range {0:.2f}–{1:.2f} m can reach a far end "
               "at {2:.4f} m from a feedpoint at {3:.3f} m (it needs at least {4:.3f} m). "
               "Every candidate will hang vertically and --cp-end-height will have no effect on the "
               "sweep. Raise --cp-end-height, lower --height, or extend --cp-max."),
        "es": ("  AVISO: ninguna longitud de contrapeso en el rango {0:.2f}–{1:.2f} m puede llegar a un "
               "extremo a {2:.4f} m desde una alimentación a {3:.3f} m (necesita al menos {4:.3f} m). "
               "Todos los candidatos colgarán vertical y --cp-end-height no afectará al barrido. "
               "Suba --cp-end-height, baje --height o amplíe --cp-max."),
        "it": "  AVVISO: nessuna lunghezza di contrappeso nell'intervallo {0:.2f}–{1:.2f} m può raggiungere un estremo a {2:.4f} m da un'alimentazione a {3:.3f} m (servono almeno {4:.3f} m). Tutti i candidati penderanno verticalmente e --cp-end-height non avrà effetto sulla scansione. Aumentare --cp-end-height, abbassare --height o estendere --cp-max.",
    },
    "cp_end_height_warn_some": {
        "en": ("  Note: counterpoise lengths below {0:.3f} m cannot reach the {1:.4f} m far end from a "
               "feedpoint at {2:.3f} m; those candidates hang vertically instead."),
        "es": ("  Nota: los contrapesos de menos de {0:.3f} m no pueden llegar al extremo de {1:.4f} m "
               "desde una alimentación a {2:.3f} m; esos candidatos cuelgan vertical."),
        "it": "  Nota: le lunghezze di contrappeso inferiori a {0:.3f} m non possono raggiungere l'estremo di {1:.4f} m da un'alimentazione a {2:.3f} m; quei candidati pendono verticalmente.",
    },
    "cp_end_height_src_cph": {
        "en": "(default; = antenna height, use --cp-end-height to override)",
        "es": "(por defecto; = altura de la antena, use --cp-end-height para anular)",
        "it": "(predefinito; = altezza dell'antenna, usare --cp-end-height per sostituire)",
    },
    # ── sweep progress ───────────────────────────────────────────────────
    "sweep_starting": {
        "en": "  Starting {0} sweep …",
        "es": "  Iniciando barrido {0} …",
        "it": '  Avvio scansione {0} …',
    },
    "sweep_empirical_pct": {
        "en": "  Empirical sweep {0:3d}% ({1}/{2})  w={3:.2f} m  cp={4:.2f} m",
        "es": "  Barrido empírico {0:3d}% ({1}/{2})  h={3:.2f} m  cp={4:.2f} m",
        "it": '  Scansione empirica {0:3d}% ({1}/{2})  h={3:.2f} m  cp={4:.2f} m',
    },
    "sweep_empirical_done": {
        "en": "  Empirical sweep 100% ({0}/{0}) — done.         ",
        "es": "  Barrido empírico 100% ({0}/{0}) — completado.  ",
        "it": '  Scansione empirica 100% ({0}/{0}) — completata.  ',
    },
    "sweep_nec2_progress": {
        "en": "  NEC2 {0:4d}/{1}  wire={2:.2f} m  cp={3:.2f} m  ({4})",
        "es": "  NEC2 {0:4d}/{1}  hilo={2:.2f} m  cp={3:.2f} m  ({4})",
        "it": '  NEC2 {0:4d}/{1}  filo={2:.2f} m  cp={3:.2f} m  ({4})',
    },
    "sweep_nec2_done": {
        "en": "  NEC2 sweep complete. {0} runs processed.           ",
        "es": "  Barrido NEC2 completado. {0} ejecuciones procesadas.",
        "it": '  Scansione NEC2 completata. {0} esecuzioni elaborate.',
    },
    "warn_empirical_cp_geometry": {
        "en": "  Note: empirical VSWR model ignores CP geometry (far-end height); cp-avoidance scoring still active for all bands.",
        "es": "  Nota: el modelo VSWR empírico ignora la geometría del CP (altura del extremo); evaluación de evitación de CP activa para todas las bandas.",
        "it": "  Nota: il modello VSWR empirico ignora la geometria del CP (altezza dell'estremo); la valutazione di evitamento del CP resta attiva per tutte le bande.",
    },
    "sweep_complete": {
        "en": "  Sweep complete.  {0} candidates evaluated.",
        "es": "  Barrido completado.  {0} candidatos evaluados.",
        "it": '  Scansione completata.  {0} candidati valutati.',
    },
    "pareto_count": {
        "en": "  Pareto-optimal candidates: {0}",
        "es": "  Candidatos Pareto-óptimos: {0}",
        "it": '  Candidati Pareto-ottimali: {0}',
    },
    # ── best candidate display ───────────────────────────────────────────
    "best_candidate": {
        "en": "★ BEST CANDIDATE:",
        "es": "★ MEJOR CANDIDATO:",
        "it": '★ MIGLIOR CANDIDATO:',
    },
    "combined_score": {
        "en": "    Combined score  = {0:.4f}",
        "es": "    Puntuación comb.= {0:.4f}",
        "it": '    Punteggio combinato = {0:.4f}',
    },
    "vswr_penalty": {
        "en": "    VSWR penalty    = {0:.4f}",
        "es": "    Penalización ROS= {0:.4f}",
        "it": '    Penalità ROS     = {0:.4f}',
    },
    "avoidance_mean": {
        "en": "    Avoidance mean  = {0:.4f}",
        "es": "    Evitación media = {0:.4f}",
        "it": '    Evitamento medio = {0:.4f}',
    },
    # ── boundary warnings ────────────────────────────────────────────────
    "warn_wire_at_max": {
        "en": "⚠  WIRE LENGTH at search maximum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be longer. Re-run with a larger --wire-max or increase --margin.",
        "es": "⚠  LONGITUD DE HILO en el máximo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser mayor. Re-ejecute con --wire-max mayor o aumente --margin.",
        "it": "⚠  LUNGHEZZA FILO al massimo di ricerca ({0:.3f} m).  {1}/5 migliori candidati hanno toccato questo limite.\n     L'ottimo reale potrebbe essere maggiore. Rieseguire con --wire-max maggiore o aumentare --margin.",
    },
    "warn_wire_at_min": {
        "en": "⚠  WIRE LENGTH at search minimum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be shorter. Re-run with a smaller --wire-min or increase --margin.",
        "es": "⚠  LONGITUD DE HILO en el mínimo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser menor. Re-ejecute con --wire-min menor o aumente --margin.",
        "it": "⚠  LUNGHEZZA FILO al minimo di ricerca ({0:.3f} m).  {1}/5 migliori candidati hanno toccato questo limite.\n     L'ottimo reale potrebbe essere minore. Rieseguire con --wire-min minore o aumentare --margin.",
    },
    "warn_cp_at_max": {
        "en": "⚠  CP LENGTH at search maximum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be longer. Re-run with a larger --cp-max or increase --margin.",
        "es": "⚠  LONGITUD CP en el máximo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser mayor. Re-ejecute con --cp-max mayor o aumente --margin.",
        "it": "⚠  LUNGHEZZA CP al massimo di ricerca ({0:.3f} m).  {1}/5 migliori candidati hanno toccato questo limite.\n     L'ottimo reale potrebbe essere maggiore. Rieseguire con --cp-max maggiore o aumentare --margin.",
    },
    "warn_cp_at_min": {
        "en": "⚠  CP LENGTH at search minimum ({0:.3f} m).  {1}/5 top candidates hit this boundary.\n     The true optimum may be shorter. Re-run with a smaller --cp-min or increase --margin.",
        "es": "⚠  LONGITUD CP en el mínimo de búsqueda ({0:.3f} m).  {1}/5 mejores candidatos tocaron este límite.\n     El óptimo real puede ser menor. Re-ejecute con --cp-min menor o aumente --margin.",
        "it": "⚠  LUNGHEZZA CP al minimo di ricerca ({0:.3f} m).  {1}/5 migliori candidati hanno toccato questo limite.\n     L'ottimo reale potrebbe essere minore. Rieseguire con --cp-min minore o aumentare --margin.",
    },
    # ── retry messages ──────────────────────────────────────────────────
    "retry_wire_expanding_max": {
        "en": "  🔁  --retry: wire boundary at maximum — expanding upper bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite de hilo en máximo — expandiendo límite superior a {0:.3f} m (reintento {1}/{2})",
        "it": '  🔁  --retry: limite del filo al massimo — estensione del limite superiore a {0:.3f} m (tentativo {1}/{2})',
    },
    "retry_wire_expanding_min": {
        "en": "  🔁  --retry: wire boundary at minimum — expanding lower bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite de hilo en mínimo — expandiendo límite inferior a {0:.3f} m (reintento {1}/{2})",
        "it": '  🔁  --retry: limite del filo al minimo — estensione del limite inferiore a {0:.3f} m (tentativo {1}/{2})',
    },
    "retry_cp_expanding_max": {
        "en": "  🔁  --retry: CP boundary at maximum — expanding upper bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite CP en máximo — expandiendo límite superior a {0:.3f} m (reintento {1}/{2})",
        "it": '  🔁  --retry: limite CP al massimo — estensione del limite superiore a {0:.3f} m (tentativo {1}/{2})',
    },
    "retry_cp_expanding_min": {
        "en": "  🔁  --retry: CP boundary at minimum — expanding lower bound to {0:.3f} m (retry {1}/{2})",
        "es": "  🔁  --retry: límite CP en mínimo — expandiendo límite inferior a {0:.3f} m (reintento {1}/{2})",
        "it": '  🔁  --retry: limite CP al minimo — estensione del limite inferiore a {0:.3f} m (tentativo {1}/{2})',
    },
    "retry_new_best": {
        "en": "  ✔  --retry: new best after retry — wire = {0:.3f} m   cp = {1:.3f} m   score = {2:.4f}",
        "es": "  ✔  --retry: nuevo mejor tras reintento — hilo = {0:.3f} m   cp = {1:.3f} m   puntuación = {2:.4f}",
        "it": '  ✔  --retry: nuovo migliore dopo il tentativo — filo = {0:.3f} m   cp = {1:.3f} m   punteggio = {2:.4f}',
    },
    "retry_no_improvement": {
        "en": "  ℹ  --retry: no improvement found — keeping previous best (wire = {0:.3f} m, cp = {1:.3f} m).",
        "es": "  ℹ  --retry: sin mejora encontrada — manteniendo mejor previo (hilo = {0:.3f} m, cp = {1:.3f} m).",
        "it": '  ℹ  --retry: nessun miglioramento trovato — mantenuto il migliore precedente (filo = {0:.3f} m, cp = {1:.3f} m).',
    },
    "retry_converged": {
        "en": "  ✔  --retry: boundary no longer hit — converged after {0} retry(s).",
        "es": "  ✔  --retry: límite ya no alcanzado — convergido tras {0} reintento(s).",
        "it": '  ✔  --retry: limite non più raggiunto — convergenza dopo {0} tentativo/i.',
    },
    "retry_post_unun": {
        "en": "  🔁  The window was explored under the seed ratio; the best geometry\n"
              "      still sits on a boundary under the final UnUn ({0:.0f}:1) — expanding again.",
        "es": "  🔁  La ventana se exploró con la relación semilla; la mejor geometría\n"
              "      sigue en un borde con el UnUn final ({0:.0f}:1) — expandiendo de nuevo.",
        "it": "  🔁  La finestra è stata esplorata con il rapporto seme; la miglior geometria\n      è ancora su un bordo con l'UnUn finale ({0:.0f}:1) — nuova estensione.",
    },
    "retry_post_unun_ok": {
        "en": "  ✔  Best geometry is inside the window under the final UnUn ratio.",
        "es": "  ✔  La mejor geometría queda dentro de la ventana con el UnUn final.",
        "it": '  ✔  La miglior geometria è dentro la finestra con il rapporto UnUn finale.',
    },
    "retry_budget_spent": {
        "en": "  ℹ  Boundary still hit under the final UnUn ratio, but the --retry budget\n"
              "      is spent — re-run with a larger --retry or a wider window.",
        "es": "  ℹ  Límite aún alcanzado con el UnUn final, pero el presupuesto de --retry\n"
              "      está agotado — reejecute con --retry mayor o una ventana más amplia.",
        "it": "  ℹ  Limite ancora raggiunto con l'UnUn finale, ma il budget di --retry\n      è esaurito — rieseguire con --retry maggiore o una finestra più ampia.",
    },
    # ── conductor losses ────────────────────────────────────────────────
    "ap_wire_diameter": {
        "en": "Wire diameter in mm (default {0:.1f} mm). Affects radiation "
              "resistance and especially Q; also shown on the construction plan.",
        "es": "Diámetro del hilo en mm (por defecto {0:.1f} mm). Afecta la "
              "resistencia de radiación y sobre todo la Q; se muestra también "
              "en el plano de construcción.",
        "it": 'Diametro del filo in mm (predefinito {0:.1f} mm). Influisce sulla resistenza di radiazione e soprattutto sul Q; è mostrato anche nel disegno costruttivo.',
    },
    "ap_wire_material": {
        "en": "Conductor material for the wires ({0}); 'perfect' writes no LD card (lossless).",
        "es": "Material del conductor de los hilos ({0}); 'perfect' no escribe tarjeta LD (sin pérdidas).",
        "it": "Materiale del conduttore dei fili ({0}); 'perfect' non scrive la scheda LD (senza perdite).",
    },
    "ap_wire_conductivity": {
        "en": "Wire conductivity in S/m; overrides --wire-material (default copper, {0:.2E}).",
        "es": "Conductividad del hilo en S/m; sustituye a --wire-material (por defecto cobre, {0:.2E}).",
        "it": 'Conducibilità del filo in S/m; sostituisce --wire-material (predefinito rame, {0:.2E}).',
    },
    "wire_diam_msg": {
        "en": "  Wire diameter: {0:.2f} mm ({1:.3f} mm radius).",
        "es": "  Diámetro del hilo: {0:.2f} mm ({1:.3f} mm de radio).",
        "it": '  Diametro del filo: {0:.2f} mm ({1:.3f} mm di raggio).',
    },
    "wire_loss_msg": {
        "en": "  Conductor: {0} — σ = {1:.3E} S/m (LD 5 card written on every deck).",
        "es": "  Conductor: {0} — σ = {1:.3E} S/m (tarjeta LD 5 escrita en todos los decks).",
        "it": '  Conduttore: {0} — σ = {1:.3E} S/m (scheda LD 5 scritta su ogni deck).',
    },
    "wire_loss_perfect": {
        "en": "  ⚠  Conductor losses disabled: every wire is a perfect conductor and the\n"
              "     gains below are idealised (no I²R loss in the wire or the transformer).",
        "es": "  ⚠  Pérdidas de conductor desactivadas: todos los hilos son conductores perfectos\n"
              "     y las ganancias siguientes son idealizadas (sin pérdida I²R en hilo ni transformador).",
        "it": '  ⚠  Perdite di conduttore disattivate: ogni filo è un conduttore perfetto e\n     i guadagni seguenti sono idealizzati (nessuna perdita I²R nel filo o nel trasformatore).',
    },
    # NEC-2's POWER BUDGET gives RADIATED = INPUT − STRUCTURE LOSS − NETWORK
    # LOSS.  That is the I²R loss of the conductors and loads ONLY: ground
    # absorption never appears in it, because it is not power the structure
    # took.  So this figure is a CONDUCTOR efficiency, and calling it
    # "radiation efficiency" tells the user a horizontal wire at 0.19 λ over
    # average ground radiates 98 % of its power, which is wildly untrue.
    # (The gain figures elsewhere in the report DO include ground loss —
    # only this label was wrong.)
    "conductor_efficiency": {
        "en": ("    Conductor (I²R) efficiency (NEC2 power budget): {0:.1f} % mean over the active bands\n"
               "    — copper/load loss only; EXCLUDES ground absorption, so it is not radiation efficiency."),
        "es": ("    Rendimiento del conductor (I²R) (balance de potencia NEC2): {0:.1f} % medio en las bandas activas\n"
               "    — sólo pérdida en cobre/cargas; EXCLUYE la absorción del suelo, no es el rendimiento de radiación."),
        "it": "    Efficienza del conduttore (I²R) (bilancio di potenza NEC2): {0:.1f} % media sulle bande attive\n    — solo perdita in rame/carichi; ESCLUDE l'assorbimento del suolo, non è l'efficienza di radiazione.",
    },
    # ── impedance table header ───────────────────────────────────────────
    "impedance_header": {
        "en": "  Impedance — antenna side & transmitter side (UnUn {0:.0f}:1):",
        "es": "  Impedancia — lado antena y lado transmisor (UnUn {0:.0f}:1):",
        "it": '  Impedenza — lato antenna e lato trasmettitore (UnUn {0:.0f}:1):',
    },
    # ── UnUn analysis display ────────────────────────────────────────────
    "optimising_unun": {
        "en": "  Optimising the UnUn ratio automatically …",
        "es": "  Optimizando la relación UnUn automáticamente …",
        "it": '  Ottimizzazione automatica del rapporto UnUn …',
    },
    "unun_auto_pass": {
        "en": "    pass {0}: {1:.0f}:1 → {2:.0f}:1 — re-ranking every candidate …",
        "es": "    pasada {0}: {1:.0f}:1 → {2:.0f}:1 — reclasificando todos los candidatos …",
        "it": '    passata {0}: {1:.0f}:1 → {2:.0f}:1 — riclassificazione di tutti i candidati …',
    },
    "unun_auto_selected": {
        "en": "UnUn selected automatically: {0:.0f}:1",
        "es": "UnUn seleccionado automáticamente: {0:.0f}:1",
        "it": 'UnUn selezionato automaticamente: {0:.0f}:1',
    },
    "unun_auto_geometry": {
        "en": "    (best geometry under this ratio: {0:.3f} m wire / {1:.3f} m counterpoise)",
        "es": "    (mejor geometría con esta relación: {0:.3f} m de hilo / {1:.3f} m de contrapeso)",
        "it": '    (miglior geometria con questo rapporto: {0:.3f} m di filo / {1:.3f} m di contrappeso)',
    },
    "unun_analysis_header": {
        "en": "  UnUn Analysis (best geometry: {0:.3f} m / {1:.3f} m):",
        "es": "  Análisis UnUn (mejor geometría: {0:.3f} m / {1:.3f} m):",
        "it": '  Analisi UnUn (miglior geometria: {0:.3f} m / {1:.3f} m):',
    },
    "unun_current": {
        "en": "    Ratio in use     : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Relación usada   : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
        "it": '    Rapporto in uso   : {0:.0f}:1  (penalità ROS aggregata {1:.4f})',
    },
    "unun_best_std": {
        "en": "    Best standard    : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Mejor estándar   : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
        "it": '    Miglior standard  : {0:.0f}:1  (penalità ROS aggregata {1:.4f})',
    },
    "unun_continuous": {
        "en": "    Continuous opt.  : {0:.2f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "    Óptimo continuo  : {0:.2f}:1  (penalización ROS agregada {1:.4f})",
        "it": '    Ottimo continuo   : {0:.2f}:1  (penalità ROS aggregata {1:.4f})',
    },
    # ── output files ─────────────────────────────────────────────────────
    "writing_outputs": {
        "en": "  Writing outputs …",
        "es": "  Escribiendo resultados …",
        "it": '  Scrittura dei risultati …',
    },
    "report_saved": {
        "en": "  📄  Report saved → {0}",
        "es": "  📄  Informe guardado → {0}",
        "it": '  📄  Report salvato → {0}',
    },
    "csv_best_saved": {
        "en": "  📋  Best-candidate CSV → {0}  (UnUn {1:.0f}:1)",
        "es": "  📋  CSV mejor candidato → {0}  (UnUn {1:.0f}:1)",
        "it": '  📋  CSV miglior candidato → {0}  (UnUn {1:.0f}:1)',
    },
    "radiation_generating": {
        "en": "  Generating radiation diagrams (full RP sweep) …",
        "es": "  Generando diagramas de radiación (barrido RP completo) …",
        "it": '  Generazione dei diagrammi di radiazione (scansione RP completa) …',
    },
    "radiation_saved": {
        "en": "  📻  Radiation diagrams saved → {0}",
        "es": "  📻  Diagramas de radiación guardados → {0}",
        "it": '  📻  Diagrammi di radiazione salvati → {0}',
    },
    "plot_skipped_no_results": {
        "en": "  ⚠️  Optimizer plot skipped: the sweep produced no candidates.",
        "es": "  ⚠️  Gráfico del optimizador omitido: el barrido no produjo candidatos.",
        "it": "  ⚠️  Grafico dell'ottimizzatore omesso: la scansione non ha prodotto candidati.",
    },
    "plot_saved": {
        "en": "  📊  Optimizer plot saved → {0}",
        "es": "  📊  Gráfico del optimizador guardado → {0}",
        "it": "  📊  Grafico dell'ottimizzatore salvato → {0}",
    },
    "construction_saved": {
        "en": "  🛠️  Construction diagram saved → {0}",
        "es": "  🛠️  Diagrama de construcción guardado → {0}",
        "it": '  🛠️  Disegno costruttivo salvato → {0}',
    },
    "nec2_deck_saved": {
        "en": "  📡  Best-antenna NEC2 deck saved → {0}",
        "es": "  📡  Archivo NEC2 de la mejor antena guardado → {0}",
        "it": '  📡  Deck NEC2 della miglior antenna salvato → {0}',
    },
    "construction_ground_label": {
        "en": "ground",
        "es": "tierra",
        "it": 'terra',
    },
    "construction_feedpoint": {
        "en": "Feedpoint",
        "es": "Punto de alimentación",
        "it": 'Punto di alimentazione',
    },
    "construction_radiator_label": {
        "en": "Radiator (long wire)",
        "es": "Radiador (hilo largo)",
        "it": 'Radiatore (filo lungo)',
    },
    "construction_cp_label": {
        "en": "Counterpoise / ground",
        "es": "Contrapeso / tierra",
        "it": 'Contrappeso / terra',
    },
    "construction_dim_radiator": {
        "en": "Radiator length",
        "es": "Longitud del radiador",
        "it": 'Lunghezza del radiatore',
    },
    "construction_dim_cp": {
        "en": "Counterpoise length",
        "es": "Longitud del contrapeso",
        "it": 'Lunghezza del contrappeso',
    },
    "construction_dim_cp_reach": {
        "en": "CP reach from mast",
        "es": "Alcance CP desde mástil",
        "it": 'Portata CP dal palo',
    },
    "construction_dim_height": {
        "en": "Support height",
        "es": "Altura de soporte",
        "it": 'Altezza di supporto',
    },
    "construction_dim_far_height": {
        "en": "Far-end height",
        "es": "Altura extremo lejano",
        "it": 'Altezza estremo lontano',
    },
    "construction_dim_far_support": {
        "en": "Far-end support distance",
        "es": "Distancia soporte extremo lejano",
        "it": 'Distanza supporto estremo lontano',
    },
    "construction_xlabel": {
        "en": "Horizontal distance (m)",
        "es": "Distancia horizontal (m)",
        "it": 'Distanza orizzontale (m)',
    },
    "construction_ylabel": {
        "en": "Height above ground (m)",
        "es": "Altura sobre el suelo (m)",
        "it": 'Altezza sul suolo (m)',
    },
    "construction_spec_wire_diam": {
        "en": "Wire diameter",
        "es": "Diámetro del hilo",
        "it": 'Diametro del filo',
    },
    "construction_dim_cp_end": {
        "en": "CP far-end height",
        "es": "Altura extremo CP",
        "it": 'Altezza estremo CP',
    },
    "construction_col_band": {
        "en": "Band",
        "es": "Banda",
        "it": 'Banda',
    },
    "construction_col_freq": {
        "en": "MHz",
        "es": "MHz",
        "it": 'MHz',
    },
    "construction_col_vswr": {
        "en": "VSWR",
        "es": "ROE",
        "it": 'ROS',
    },
    "construction_col_quality": {
        "en": "Quality",
        "es": "Calidad",
        "it": 'Qualità',
    },
    "matplotlib_missing": {
        "en": "  matplotlib not available — skipping plot.",
        "es": "  matplotlib no disponible — omitiendo gráfico.",
        "it": '  matplotlib non disponibile — grafico omesso.',
    },
    "construction_plot_skipped": {
        "en": "  ⚠  Construction diagram skipped: {0}",
        "es": "  ⚠  Diagrama constructivo omitido: {0}",
        "it": '  ⚠  Disegno costruttivo omesso: {0}',
    },
    "done": {
        "en": "  Done.",
        "es": "  Listo.",
        "it": '  Fatto.',
    },
    # ── radiation pattern warnings ───────────────────────────────────────
    "warn_no_rp_data": {
        "en": "  ⚠  No radiation pattern data parsed — check NEC2 output format.",
        "es": "  ⚠  No se parsearon datos de patrón de radiación — verifique el formato de salida de NEC2.",
        "it": '  ⚠  Nessun dato di diagramma di radiazione analizzato — verificare il formato di uscita di NEC2.',
    },
    "warn_no_rp_freq": {
        "en": "  ⚠  No parsed RP freq within 0.5 MHz of {0:.4f} MHz — skipping {1}.",
        "es": "  ⚠  Sin frecuencia RP parseada a 0.5 MHz de {0:.4f} MHz — omitiendo {1}.",
        "it": '  ⚠  Nessuna frequenza RP analizzata entro 0.5 MHz da {0:.4f} MHz — {1} omesso.',
    },
    "warn_no_rp_bands": {
        "en": "  ⚠  No bands produced usable radiation pattern data — skipping plot.",
        "es": "  ⚠  Ninguna banda produjo datos de patrón utilizables — omitiendo gráfico.",
        "it": '  ⚠  Nessuna banda ha prodotto dati di diagramma di radiazione utilizzabili — grafico omesso.',
    },
    # ── plot labels ──────────────────────────────────────────────────────
    "plot_title": {
        "en": "NEC2 Antenna Length Optimizer Results",
        "es": "Resultados del Optimizador de Antena NEC2",
        "it": "Risultati dell'Ottimizzatore di Antenna NEC2",
    },
    "plot_colorbar": {
        "en": "Combined score (lower=better)",
        "es": "Puntuación combinada (menor=mejor)",
        "it": 'Punteggio combinato (minore=migliore)',
    },
    "plot_pareto_label": {
        "en": "Pareto front",
        "es": "Frente de Pareto",
        "it": 'Fronte di Pareto',
    },
    "plot_best_label": {
        "en": "Best",
        "es": "Mejor",
        "it": 'Migliore',
    },
    "plot_xlabel_wire": {
        "en": "Wire length (m)",
        "es": "Longitud de hilo (m)",
        "it": 'Lunghezza del filo (m)',
    },
    "plot_ylabel_cp": {
        "en": "Counterpoise length (m)",
        "es": "Longitud de contrapeso (m)",
        "it": 'Lunghezza del contrappeso (m)',
    },
    "plot_heatmap_title": {
        "en": "Combined Score Heat Map",
        "es": "Mapa de calor de puntuación combinada",
        "it": 'Mappa di calore del punteggio combinato',
    },
    "plot_vswr_xlabel": {
        "en": "VSWR penalty mean+1.5×worst (lower=better)",
        "es": "Penalización ROS media+1.5×peor (menor=mejor)",
        "it": 'Penalità ROS media+1.5×peggiore (minore=migliore)',
    },
    "plot_avoidance_ylabel": {
        "en": "Active-band avoidance (higher=better)",
        "es": "Evitación banda activa (mayor=mejor)",
        "it": 'Evitamento banda attiva (maggiore=migliore)',
    },
    "plot_pareto_title": {
        "en": "Pareto Space (active bands)",
        "es": "Espacio de Pareto (bandas activas)",
        "it": 'Spazio di Pareto (bande attive)',
    },
    "plot_vswr_ylabel": {
        "en": "VSWR (Tx side)",
        "es": "ROS (lado Tx)",
        "it": 'ROS (lato Tx)',
    },
    "plot_radiation_title": {
        "en": "Radiation Diagrams — Wire {0:.2f} m / CP {1:.2f} m ({2})",
        "es": "Diagramas de Radiación — Hilo {0:.2f} m / CP {1:.2f} m ({2})",
        "it": 'Diagrammi di Radiazione — Filo {0:.2f} m / CP {1:.2f} m ({2})',
    },
    # ── report strings ───────────────────────────────────────────────────
    "report_title": {
        "en": "NEC2 ANTENNA LENGTH OPTIMIZER REPORT",
        "es": "INFORME DEL OPTIMIZADOR DE LONGITUD DE ANTENA NEC2",
        "it": "REPORT DELL'OTTIMIZZATORE DI LUNGHEZZA ANTENNA NEC2",
    },
    "report_mode": {
        "en": "Evaluation mode : {0}",
        "es": "Modo de evaluación: {0}",
        "it": 'Modalità di valutazione: {0}',
    },
    "report_unun": {
        "en": "UnUn ratio      : {0:.1f}:1",
        "es": "Relación UnUn   : {0:.1f}:1",
        "it": 'Rapporto UnUn   : {0:.1f}:1',
    },
    "report_wire_range": {
        "en": "Wire range      : {0:.2f} m … {1:.2f} m  step {2:.3f} m",
        "es": "Rango de hilo   : {0:.2f} m … {1:.2f} m  paso {2:.3f} m",
        "it": 'Intervallo filo : {0:.2f} m … {1:.2f} m  passo {2:.3f} m',
    },
    "report_cp_range": {
        "en": "CP range        : {0:.2f} m … {1:.2f} m  step {2:.3f} m",
        "es": "Rango de CP     : {0:.2f} m … {1:.2f} m  paso {2:.3f} m",
        "it": 'Intervallo CP   : {0:.2f} m … {1:.2f} m  passo {2:.3f} m',
    },
    "report_wire_geom_sloped_summary": {
        "en": "Wire geometry   : SLOPED  (far-end height = {0:.4f} m)",
        "es": "Geometría hilo  : INCLINADO  (altura extremo lejano = {0:.4f} m)",
        "it": 'Geometria filo  : INCLINATA  (altezza estremo lontano = {0:.4f} m)',
    },
    "report_wire_geom_horizontal": {
        "en": "Wire geometry   : horizontal (flat)",
        "es": "Geometría hilo  : horizontal (plano)",
        "it": 'Geometria filo  : orizzontale (piatta)',
    },
    "report_wire_geom_sloped_detail": {
        "en": "Wire geometry   : SLOPED  (feedpoint z={0:.3f} m → far end z={1:.4f} m)",
        "es": "Geometría hilo  : INCLINADO  (punto alimentación z={0:.3f} m → extremo lejano z={1:.4f} m)",
        "it": 'Geometria filo  : INCLINATA  (alimentazione z={0:.3f} m → estremo lontano z={1:.4f} m)',
    },
    "report_wire_geom_horizontal_const": {
        "en": "Wire geometry   : horizontal (flat, z = constant)",
        "es": "Geometría hilo  : horizontal (plano, z = constante)",
        "it": 'Geometria filo  : orizzontale (piatta, z = costante)',
    },
    "report_cp_geom_summary": {
        "en": "CP geometry     : feedpoint z={0:.3f} m → far-end target z={1:.4f} m",
        "es": "Geometría CP    : alimentación z={0:.3f} m → extremo objetivo z={1:.4f} m",
        "it": 'Geometria CP    : alimentazione z={0:.3f} m → estremo obiettivo z={1:.4f} m',
    },
    "report_cp_geom_detail": {
        "en": "CP geometry     : feedpoint z={0:.3f} m → far end z={1:.4f} m  ({2:.1f}° from vertical, reach {3:.3f} m)",
        "es": "Geometría CP    : alimentación z={0:.3f} m → extremo z={1:.4f} m  ({2:.1f}° desde la vertical, alcance {3:.3f} m)",
        "it": 'Geometria CP    : alimentazione z={0:.3f} m → estremo z={1:.4f} m  ({2:.1f}° dalla verticale, portata {3:.3f} m)',
    },
    "report_cp_geom_short": {
        "en": "                  {0} of the {1} listed candidates are too short to reach it and hang vertically",
        "es": "                  {0} de los {1} candidatos listados son demasiado cortos y cuelgan vertical",
        "it": '                  {0} dei {1} candidati elencati sono troppo corti per raggiungerlo e pendono verticalmente',
    },
    "report_cp_geom_vertical": {
        "en": "CP geometry     : hangs vertically (too short to reach the target far-end height)",
        "es": "Geometría CP    : cuelga vertical (demasiado corto para llegar a la altura objetivo)",
        "it": "Geometria CP    : pende verticalmente (troppo corto per raggiungere l'altezza obiettivo)",
    },
    "report_active_bands": {
        "en": "Active bands    : {0} of {1}  ({2})  (* = scored for VSWR)",
        "es": "Bandas activas  : {0} de {1}  ({2})  (* = evaluadas para ROS)",
        "it": 'Bande attive    : {0} di {1}  ({2})  (* = valutate per ROS)',
    },
    "report_total_candidates": {
        "en": "Total candidates: {0}",
        "es": "Total candidatos: {0}",
        "it": 'Candidati totali: {0}',
    },
    "report_top_n_header": {
        "en": "TOP {0} CANDIDATES  (lower combined score = better)",
        "es": "TOP {0} CANDIDATOS  (menor puntuación combinada = mejor)",
        "it": 'TOP {0} CANDIDATI  (punteggio combinato più basso = migliore)',
    },
    "report_pareto_header": {
        "en": "PARETO-OPTIMAL FRONT  ({0} candidates)",
        "es": "FRENTE PARETO-ÓPTIMO  ({0} candidatos)",
        "it": 'FRONTE PARETO-OTTIMALE  ({0} candidati)',
    },
    "report_pareto_note": {
        "en": "Candidates not dominated on both VSWR-penalty and avoidance score.",
        "es": "Candidatos no dominados en penalización ROS y puntuación de evitación.",
        "it": 'Candidati non dominati sia nella penalità ROS sia nel punteggio di evitamento.',
    },
    "report_best_header": {
        "en": "BEST CANDIDATE — DETAILED BREAKDOWN",
        "es": "MEJOR CANDIDATO — DESGLOSE DETALLADO",
        "it": 'MIGLIOR CANDIDATO — DETTAGLIO',
    },
    "report_wire_len": {
        "en": "Wire length   : {0:.3f} m",
        "es": "Longitud hilo : {0:.3f} m",
        "it": 'Lunghezza filo: {0:.3f} m',
    },
    "report_cp_len": {
        "en": "CP length     : {0:.3f} m   (far end z={1:.4f} m, {2:.1f}° from vertical)",
        "es": "Longitud CP   : {0:.3f} m   (extremo z={1:.4f} m, {2:.1f}° desde la vertical)",
        "it": 'Lunghezza CP  : {0:.3f} m   (estremo z={1:.4f} m, {2:.1f}° dalla verticale)',
    },
    "report_cp_disabled": {
        "en": "Counterpoise  : NOT USED  (--no-counterpoise)",
        "es": "Contrapeso    : NO UTILIZADO  (--no-counterpoise)",
        "it": 'Contrappeso   : NON USATO  (--no-counterpoise)',
    },
    "report_cp_range_disabled": {
        "en": "  CP range      : not searched (antenna without counterpoise)",
        "es": "  Rango CP      : no explorado (antena sin contrapeso)",
        "it": '  Intervallo CP : non esplorato (antenna senza contrappeso)',
    },
    "no_cp_banner": {
        "en": ("Counterpoise DISABLED (--no-counterpoise): the radiator is fed at its near end "
               "against the return conductor selected with --no-cp-return (ground rod or "
               "coax-braid stub) — NEC-2 has no implicit return path, so some return conductor "
               "must exist in the deck.  The CP length range, the CP far-end height and the "
               "CP λ/4 bonus are all ignored."),
        "es": ("Contrapeso DESHABILITADO (--no-counterpoise): el radiador se alimenta en su "
               "extremo cercano contra el conductor de retorno elegido con --no-cp-return (pica "
               "de tierra o muñón de coaxial) — NEC-2 no tiene camino de retorno implícito, así "
               "que el deck debe contener algún conductor de retorno.  Se ignoran el rango de "
               "longitud del CP, la altura del extremo del CP y el bonus λ/4 del CP."),
        "it": "Contrappeso DISATTIVATO (--no-counterpoise): il radiatore è alimentato al suo estremo vicino contro il conduttore di ritorno scelto con --no-cp-return (picchetto di terra o stub di calza coassiale) — NEC-2 non ha un percorso di ritorno implicito, quindi un qualche conduttore di ritorno deve esistere nel deck.  L'intervallo di lunghezza del CP, l'altezza dell'estremo del CP e il bonus λ/4 del CP sono tutti ignorati.",
    },
    "pdf_spec_cp_none_rod": {
        "en": "None — return via ground rod to z=0",
        "es": "Ninguno — retorno por pica de tierra a z=0",
        "it": 'Nessuno — ritorno tramite picchetto di terra a z=0',
    },
    "pdf_spec_cp_none_stub": {
        "en": "None — return via {0:.2f} m coax-braid stub",
        "es": "Ninguno — retorno por muñón de coaxial de {0:.2f} m",
        "it": 'Nessuno — ritorno tramite stub di calza coassiale di {0:.2f} m',
    },
    "construction_return_label": {
        "en": "Return conductor",
        "es": "Conductor de retorno",
        "it": 'Conduttore di ritorno',
    },
    "construction_return_rod": {
        "en": "No counterpoise\nGround rod to z=0",
        "es": "Sin contrapeso\nPica de tierra a z=0",
        "it": 'Nessun contrappeso\nPicchetto di terra a z=0',
    },
    "construction_return_stub": {
        "en": "No counterpoise\nCoax-braid stub {0:.2f} m",
        "es": "Sin contrapeso\nMuñón de coaxial {0:.2f} m",
        "it": 'Nessun contrappeso\nStub di calza coassiale {0:.2f} m',
    },
    "ap_no_cp_return": {
        "en": ("How the return conductor is modelled when --no-counterpoise is used. "
               "NEC-2 has no implicit return path, so a wire fed at its end against nothing "
               "is an open circuit, not an end-fed antenna.  "
               "ground-rod = vertical conductor from the feedpoint down to z=0 over a "
               "perfectly conducting ground (GN 1); "
               "coax-stub = short vertical stub representing the coax braid / common-mode path; "
               "reject = refuse the combination in NEC2 mode.  Default: ground-rod."),
        "es": ("Cómo se modela el conductor de retorno cuando se usa --no-counterpoise. "
               "NEC-2 no tiene camino de retorno implícito, así que un hilo alimentado en su "
               "extremo contra nada es un circuito abierto, no una antena end-fed.  "
               "ground-rod = conductor vertical desde el punto de alimentación hasta z=0 sobre "
               "tierra perfectamente conductora (GN 1); "
               "coax-stub = muñón vertical corto que representa la malla del coaxial y el camino "
               "de modo común; "
               "reject = rechazar la combinación en modo NEC2.  Por defecto: ground-rod."),
        "it": "Come viene modellato il conduttore di ritorno quando si usa --no-counterpoise. NEC-2 non ha un percorso di ritorno implicito, quindi un filo alimentato al suo estremo contro il nulla è un circuito aperto, non un'antenna alimentata all'estremità.  ground-rod = conduttore verticale dal punto di alimentazione fino a z=0 su terra perfettamente conduttiva (GN 1); coax-stub = breve stub verticale che rappresenta la calza del coassiale e il percorso di modo comune; reject = rifiuta la combinazione in modalità NEC2.  Predefinito: ground-rod.",
    },
    "ap_cp_stub_len": {
        "en": ("Length in metres of the coax-braid stub used by --no-cp-return coax-stub. "
               "Default: {0} m."),
        "es": ("Longitud en metros del muñón de coaxial usado por --no-cp-return coax-stub. "
               "Por defecto: {0} m."),
        "it": 'Lunghezza in metri dello stub di calza coassiale usato da --no-cp-return coax-stub. Predefinito: {0} m.',
    },
    "ap_ground_model": {
        "en": ("NEC-2 ground model.  sommerfeld = GN 2 real ground (default): no wire end may "
               "come closer than 0.05·lambda to the ground, because NEC-2's Sommerfeld-Norton "
               "ground is singular there and returns garbage without any error.  "
               "perfect = GN 1 perfectly conducting ground: wire ends requested at or below that "
               "floor are placed at exactly z=0, which is the correct NEC-2 idiom for a galvanic "
               "ground connection (a real ground connection over real ground is a NEC-4 feature)."),
        "es": ("Modelo de tierra NEC-2.  sommerfeld = GN 2 tierra real (por defecto): ningún "
               "extremo de hilo puede acercarse a menos de 0,05·lambda del suelo, porque la tierra "
               "Sommerfeld-Norton de NEC-2 es singular ahí y devuelve basura sin emitir error.  "
               "perfect = GN 1 tierra perfecta: los extremos pedidos en o por debajo de ese suelo "
               "se colocan exactamente en z=0, que es el modismo correcto en NEC-2 para una conexión "
               "galvánica a tierra (una conexión real a tierra real es una prestación de NEC-4)."),
        "it": "Modello di terra NEC-2.  sommerfeld = GN 2 terra reale (predefinito): nessun estremo di filo può avvicinarsi a meno di 0,05·lambda dal suolo, perché la terra Sommerfeld-Norton di NEC-2 è singolare lì e restituisce valori insensati senza alcun errore.  perfect = GN 1 terra perfettamente conduttiva: gli estremi richiesti a o sotto quel suolo vengono posizionati esattamente a z=0, che è l'idioma corretto in NEC-2 per una connessione galvanica a terra (una connessione reale a terra reale è una funzione di NEC-4).",
    },
    "no_cp_return_msg": {
        "en": "Return path (no counterpoise): {0}",
        "es": "Camino de retorno (sin contrapeso): {0}",
        "it": 'Percorso di ritorno (senza contrappeso): {0}',
    },
    "ground_model_msg": {
        "en": "Ground model  : {0}   (wire-end floor {1:.2f} m = {2:.2f}·lambda at the lowest band)",
        "es": "Modelo tierra : {0}   (suelo de extremos {1:.2f} m = {2:.2f}·lambda en la banda más baja)",
        "it": 'Modello terra : {0}   (soglia estremo filo {1:.2f} m = {2:.2f}·lambda alla banda più bassa)',
    },
    "err_feedpoint_below_ground": {
        "en": ("ERROR: the antenna height ({0:.3f} m) is below ground.  The feedpoint — where "
               "both wires start and where the source sits — must be at or above z=0."),
        "es": ("ERROR: la altura de la antena ({0:.3f} m) está bajo tierra.  El punto de "
               "alimentación —donde arrancan ambos hilos y donde está el generador— debe estar "
               "en z=0 o por encima."),
        "it": "ERRORE: l'altezza dell'antenna ({0:.3f} m) è sottoterra.  Il punto di alimentazione — dove iniziano entrambi i fili e dove si trova il generatore — deve trovarsi a z=0 o al di sopra.",
    },
    "err_feedpoint_too_low": {
        "en": ("ERROR: the antenna height ({0:.3f} m) is below {2:.2f}·λ ({1:.2f} m at the lowest "
               "band).  NEC-2's Sommerfeld-Norton ground is singular there: nec2c reports no "
               "error and returns impedances that are simply wrong.  Raise the antenna, or use "
               "--ground-model perfect if a galvanic ground connection is intended."),
        "es": ("ERROR: la altura de la antena ({0:.3f} m) está por debajo de {2:.2f}·λ ({1:.2f} m "
               "en la banda más baja).  La tierra Sommerfeld-Norton de NEC-2 es singular ahí: "
               "nec2c no informa ningún error y devuelve impedancias sencillamente falsas.  Suba "
               "la antena, o use --ground-model perfect si se pretende una conexión galvánica a "
               "tierra."),
        "it": "ERRORE: l'altezza dell'antenna ({0:.3f} m) è inferiore a {2:.2f}·λ ({1:.2f} m alla banda più bassa).  La terra Sommerfeld-Norton di NEC-2 è singolare lì: nec2c non segnala alcun errore e restituisce impedenze semplicemente sbagliate.  Alzare l'antenna, oppure usare --ground-model perfect se si intende una connessione galvanica a terra.",
    },
    "err_no_return_path": {
        "en": ("ERROR: --no-counterpoise in NEC2 mode needs a return conductor.  NEC-2 has no "
               "implicit return path: the deck would be a single wire with the source on its end "
               "segment, i.e. an open circuit (kilo-ohms of R, huge negative X), not an end-fed "
               "antenna.  Choose --no-cp-return ground-rod or --no-cp-return coax-stub, or run "
               "the counterpoise-less antenna with --mode empirical."),
        "es": ("ERROR: --no-counterpoise en modo NEC2 necesita un conductor de retorno.  NEC-2 no "
               "tiene camino de retorno implícito: el deck sería un solo hilo con el generador en "
               "su segmento extremo, es decir un circuito abierto (kilohmios de R, X negativa "
               "enorme), no una antena end-fed.  Elija --no-cp-return ground-rod o --no-cp-return "
               "coax-stub, o ejecute la antena sin contrapeso con --mode empirical."),
        "it": "ERRORE: --no-counterpoise in modalità NEC2 richiede un conduttore di ritorno.  NEC-2 non ha un percorso di ritorno implicito: il deck sarebbe un unico filo con il generatore sul suo segmento estremo, cioè un circuito aperto (kilo-ohm di R, X negativa enorme), non un'antenna alimentata all'estremità.  Scegliere --no-cp-return ground-rod o --no-cp-return coax-stub, oppure eseguire l'antenna senza contrappeso con --mode empirical.",
    },
    "warn_slope_below_floor": {
        "en": ("WARNING: --wire-slope-end-height {0:.3f} m is below the NEC-2 floor {1:.2f} m "
               "({2:.2f}·lambda at the lowest band).  It will be raised to that floor.  NEC-2's "
               "Sommerfeld-Norton ground is singular closer than this and nec2c reports no error, "
               "so the impedance would be meaningless.  Use --ground-model perfect with "
               "--wire-slope-end-height 0 for a genuine ground connection."),
        "es": ("AVISO: --wire-slope-end-height {0:.3f} m está por debajo del suelo NEC-2 de {1:.2f} m "
               "({2:.2f}·lambda en la banda más baja).  Se elevará a ese suelo.  La tierra "
               "Sommerfeld-Norton de NEC-2 es singular más cerca que eso y nec2c no informa ningún "
               "error, así que la impedancia no significaría nada.  Use --ground-model perfect con "
               "--wire-slope-end-height 0 para una conexión real a tierra."),
        "it": "AVVISO: --wire-slope-end-height {0:.3f} m è sotto la soglia NEC-2 di {1:.2f} m ({2:.2f}·lambda alla banda più bassa).  Sarà elevato a quella soglia.  La terra Sommerfeld-Norton di NEC-2 è singolare più vicino di così e nec2c non segnala alcun errore, quindi l'impedenza sarebbe priva di significato.  Usare --ground-model perfect con --wire-slope-end-height 0 per una connessione a terra reale.",
    },
    "warn_radiator_far_end_unreliable": {
        "en": ("WARNING: Radiator far end: requested {0:.3f} m is below 0.02·\u03bb ({1:.2f} m); "
               "NEC-2's Sommerfeld-Norton ground is singular there and nec2c reports no error.  "
               "Raised to {2:.2f} m and the result is marked UNRELIABLE.  Use --ground-model "
               "perfect with the end at z=0 if a real ground connection is intended."),
        "es": ("AVISO: Extremo del radiador: {0:.3f} m está por debajo de 0.02·\u03bb ({1:.2f} m); "
               "la tierra Sommerfeld-Norton de NEC-2 es singular ahí y nec2c no informa ningún "
               "error.  Se elevó a {2:.2f} m y el resultado se marca como NO FIABLE.  Use "
               "--ground-model perfect con el extremo en z=0 si se pretende una conexión real a "
               "tierra."),
        "it": ("AVVISO: Estremo del radiatore: {0:.3f} m è sotto 0.02·\u03bb ({1:.2f} m); la terra "
               "Sommerfeld-Norton di NEC-2 è singolare lì e nec2c non segnala alcun errore.  "
               "Elevato a {2:.2f} m e il risultato è marcato come NON AFFIDABILE.  Usare "
               "--ground-model perfect con l'estremo a z=0 se si intende una connessione a terra "
               "reale."),
    },
    "warn_cp_far_end_unreliable": {
        "en": ("WARNING: Counterpoise far end: requested {0:.3f} m is below 0.02·\u03bb ({1:.2f} m); "
               "NEC-2's Sommerfeld-Norton ground is singular there and nec2c reports no error.  "
               "The result is marked UNRELIABLE.  Use --ground-model perfect with the end at "
               "z=0 if a real ground connection is intended."),
        "es": ("AVISO: Extremo del contrapeso: {0:.3f} m está por debajo de 0.02·\u03bb ({1:.2f} m); "
               "la tierra Sommerfeld-Norton de NEC-2 es singular ahí y nec2c no informa ningún "
               "error.  El resultado se marca como NO FIABLE.  Use --ground-model perfect con el "
               "extremo en z=0 si se pretende una conexión real a tierra."),
        "it": ("AVVISO: Estremo del contrappeso: {0:.3f} m è sotto 0.02·\u03bb ({1:.2f} m); la terra "
               "Sommerfeld-Norton di NEC-2 è singolare lì e nec2c non segnala alcun errore.  Il "
               "risultato è marcato come NON AFFIDABILE.  Usare --ground-model perfect con "
               "l'estremo a z=0 se si intende una connessione a terra reale."),
    },
    "report_return_path": {
        "en": "Return path   : {0}",
        "es": "Retorno       : {0}",
        "it": 'Percorso ritorno: {0}',
    },
    "report_ground_model": {
        "en": "Ground model  : {0}",
        "es": "Modelo tierra : {0}",
        "it": 'Modello terra : {0}',
    },
    "ap_no_counterpoise": {
        "en": ("Model the antenna WITHOUT a counterpoise: only the radiator is built, "
               "and --cp-len / --cp-min / --cp-max / --cp-step / --cp-end-height are ignored."),
        "es": ("Modelar la antena SIN contrapeso: sólo se construye el radiador y se "
               "ignoran --cp-len / --cp-min / --cp-max / --cp-step / --cp-end-height."),
        "it": "Modella l'antenna SENZA contrappeso: viene costruito solo il radiatore, e --cp-len / --cp-min / --cp-max / --cp-step / --cp-end-height vengono ignorati.",
    },
    "report_combined_score": {
        "en": "Combined score: {0:.4f}",
        "es": "Puntuación comb: {0:.4f}",
        "it": 'Punteggio comb.: {0:.4f}',
    },
    "report_vswr_penalty": {
        "en": "VSWR penalty  : {0:.4f}  (mean VSWR penalty across active bands; score_combined = mean + 1.5×worst − bonuses)",
        "es": "Penaliz. ROS  : {0:.4f}  (media de penalización ROS en bandas activas; score_combined = media + 1.5×peor − bonos)",
        "it": 'Penalità ROS  : {0:.4f}  (media penalità ROS sulle bande attive; score_combined = media + 1.5×peggiore − bonus)',
    },
    "report_avoidance_act": {
        "en": "Avoidance(act): {0:.4f}  (mean across ACTIVE bands — used in score_combined)",
        "es": "Evitación(act): {0:.4f}  (media en bandas ACTIVAS — usada en score_combined)",
        "it": 'Evitamento(att): {0:.4f}  (media sulle bande ATTIVE — usata in score_combined)',
    },
    "report_avoidance_all": {
        "en": "Avoidance(all): {0:.4f}  (mean across ALL defined bands — shown for reference)",
        "es": "Evitación(all): {0:.4f}  (media en TODAS las bandas definidas — referencia)",
        "it": 'Evitamento(tot): {0:.4f}  (media su TUTTE le bande definite — mostrata per riferimento)',
    },
    "report_nec2_used": {
        "en": "NEC2 data used: {0}",
        "es": "Datos NEC2 usados: {0}",
        "it": 'Dati NEC2 usati: {0}',
    },
    "report_nec2_yes": {
        "en": "YES",
        "es": "SÍ",
        "it": 'SÌ',
    },
    "report_nec2_no": {
        "en": "NO — empirical model only",
        "es": "NO — solo modelo empírico",
        "it": 'NO — solo modello empirico',
    },
    "report_nec2_untrusted": {
        "en": "  WARNING: NEC2 data was produced but is flagged UNRELIABLE — see note below.",
        "es": "  ADVERTENCIA: se obtuvieron datos NEC2 pero están marcados como NO FIABLES — ver nota.",
        "it": '  ATTENZIONE: sono stati prodotti dati NEC2 ma sono segnalati come NON AFFIDABILI — vedere la nota sotto.',
    },
    "report_nec2_note": {
        "en": "  Note: {0}",
        "es": "  Nota: {0}",
        "it": '  Nota: {0}',
    },
    "report_warn_wire_max": {
        "en": "⚠  WIRE at search maximum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be longer.  Re-run with larger --wire-max or increase --margin.",
        "es": "⚠  HILO en el máximo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser mayor.  Re-ejecute con --wire-max mayor o aumente --margin.",
        "it": "⚠  FILO al massimo di ricerca ({0:.3f} m) — {1}/5 migliori candidati hanno toccato questo limite.  L'ottimo reale potrebbe essere maggiore.  Rieseguire con --wire-max maggiore o aumentare --margin.",
    },
    "report_warn_wire_min": {
        "en": "⚠  WIRE at search minimum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be shorter.  Re-run with smaller --wire-min or increase --margin.",
        "es": "⚠  HILO en el mínimo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser menor.  Re-ejecute con --wire-min menor o aumente --margin.",
        "it": "⚠  FILO al minimo di ricerca ({0:.3f} m) — {1}/5 migliori candidati hanno toccato questo limite.  L'ottimo reale potrebbe essere minore.  Rieseguire con --wire-min minore o aumentare --margin.",
    },
    "report_warn_cp_max": {
        "en": "⚠  CP at search maximum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be longer.  Re-run with larger --cp-max or increase --margin.",
        "es": "⚠  CP en el máximo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser mayor.  Re-ejecute con --cp-max mayor o aumente --margin.",
        "it": "⚠  CP al massimo di ricerca ({0:.3f} m) — {1}/5 migliori candidati hanno toccato questo limite.  L'ottimo reale potrebbe essere maggiore.  Rieseguire con --cp-max maggiore o aumentare --margin.",
    },
    "report_warn_cp_min": {
        "en": "⚠  CP at search minimum ({0:.3f} m) — {1}/5 top candidates hit this boundary.  True optimum may be shorter.  Re-run with smaller --cp-min or increase --margin.",
        "es": "⚠  CP en el mínimo de búsqueda ({0:.3f} m) — {1}/5 mejores candidatos tocaron este límite.  El óptimo real puede ser menor.  Re-ejecute con --cp-min menor o aumente --margin.",
        "it": "⚠  CP al minimo di ricerca ({0:.3f} m) — {1}/5 migliori candidati hanno toccato questo limite.  L'ottimo reale potrebbe essere minore.  Rieseguire con --cp-min minore o aumentare --margin.",
    },
    "report_per_band": {
        "en": "Per-band results:",
        "es": "Resultados por banda:",
        "it": 'Risultati per banda:',
    },
    "report_per_band_imp": {
        "en": "Per-band impedance (antenna side and transmitter side):",
        "es": "Impedancia por banda (lado antena y lado transmisor):",
        "it": 'Impedenza per banda (lato antenna e lato trasmettitore):',
    },
    "report_unun_note": {
        "en": "  (UnUn {0:.0f}:1 — antenna-side Z divided by {0:.0f} to give Tx-side Z)",
        "es": "  (UnUn {0:.0f}:1 — Z lado antena dividida por {0:.0f} para obtener Z lado Tx)",
        "it": '  (UnUn {0:.0f}:1 — Z lato antenna divisa per {0:.0f} per ottenere Z lato Tx)',
    },
    "report_unun_section": {
        "en": "UnUn RATIO ANALYSIS  (for best antenna geometry)",
        "es": "ANÁLISIS DE RELACIÓN UnUn  (para la mejor geometría de antena)",
        "it": "ANALISI DEL RAPPORTO UnUn  (per la miglior geometria d'antenna)",
    },
    "report_unun_used": {
        "en": "UnUn ratio selected automatically : {0:.1f}:1",
        "es": "Relación UnUn elegida automáticamente: {0:.1f}:1",
        "it": 'Rapporto UnUn scelto automaticamente : {0:.1f}:1',
    },
    "report_unun_cont_hit_upper": {
        "en": "  ⚠ HIT UPPER BOUND — true optimum may be >100:1",
        "es": "  ⚠ LÍMITE SUPERIOR ALCANZADO — el óptimo real puede ser >100:1",
        "it": "  ⚠ LIMITE SUPERIORE RAGGIUNTO — l'ottimo reale potrebbe essere >100:1",
    },
    "report_unun_cont_hit_lower": {
        "en": "  ⚠ HIT LOWER BOUND — try no transformer",
        "es": "  ⚠ LÍMITE INFERIOR ALCANZADO — pruebe sin transformador",
        "it": '  ⚠ LIMITE INFERIORE RAGGIUNTO — provare senza trasformatore',
    },
    "report_unun_continuous": {
        "en": "Continuous optimum         : {0:.2f}:1  (aggregate VSWR penalty {1:.4f}){2}",
        "es": "Óptimo continuo            : {0:.2f}:1  (penalización ROS agregada {1:.4f}){2}",
        "it": 'Ottimo continuo            : {0:.2f}:1  (penalità ROS aggregata {1:.4f}){2}',
    },
    "report_unun_best_std": {
        "en": "Best standard ratio        : {0:.0f}:1  (aggregate VSWR penalty {1:.4f})",
        "es": "Mejor relación estándar    : {0:.0f}:1  (penalización ROS agregada {1:.4f})",
        "it": 'Miglior rapporto standard  : {0:.0f}:1  (penalità ROS aggregata {1:.4f})',
    },
    "report_unun_improve": {
        "en": "  → Switching to {0:.0f}:1 improves aggregate VSWR penalty by {1:.4f}  ({2:.1f} %)",
        "es": "  → Cambiar a {0:.0f}:1 mejora la penalización ROS agregada en {1:.4f}  ({2:.1f} %)",
        "it": '  → Passare a {0:.0f}:1 migliora la penalità ROS aggregata di {1:.4f}  ({2:.1f} %)',
    },
    "report_unun_already_optimal": {
        "en": "  → {0:.0f}:1 is the optimum among the standard ratios; rankings and outputs all use it.",
        "es": "  → {0:.0f}:1 es el óptimo entre las relaciones estándar; las clasificaciones y salidas la usan.",
        "it": "  → {0:.0f}:1 è l'ottimo tra i rapporti standard; classifiche e output lo usano tutti.",
    },
    "report_std_sweep": {
        "en": "Standard ratio sweep:",
        "es": "Barrido de relaciones estándar:",
        "it": 'Scansione dei rapporti standard:',
    },
    "report_ant_impedance": {
        "en": "Antenna-side impedance (independent of UnUn ratio):",
        "es": "Impedancia lado antena (independiente de la relación UnUn):",
        "it": 'Impedenza lato antenna (indipendente dal rapporto UnUn):',
    },
    "report_perband_optimal": {
        "en": "Per-band optimal ratio (independent, continuous):",
        "es": "Relación óptima por banda (independiente, continua):",
        "it": 'Rapporto ottimale per banda (indipendente, continuo):',
    },
    "report_perband_conflict_note": {
        "en": "Note: per-band ratios optimise each band independently and may",
        "es": "Nota: las relaciones por banda optimizan cada banda de forma independiente y pueden",
        "it": 'Nota: i rapporti per banda ottimizzano ogni banda in modo indipendente e possono',
    },
    "report_perband_conflict_note2": {
        "en": "      conflict with each other.  The aggregate score above is the",
        "es": "      entrar en conflicto entre sí.  La puntuación agregada anterior es la",
        "it": '      entrare in conflitto tra loro.  Il punteggio aggregato sopra è la',
    },
    "report_perband_conflict_note3": {
        "en": "      correct metric for a single multi-band UnUn.",
        "es": "      métrica correcta para un UnUn multibanda único.",
        "it": '      metrica corretta per un singolo UnUn multibanda.',
    },
    "report_physical_header": {
        "en": "PHYSICAL INTERPRETATION",
        "es": "INTERPRETACIÓN FÍSICA",
        "it": 'INTERPRETAZIONE FISICA',
    },
    "report_end": {
        "en": "END OF OPTIMIZER REPORT",
        "es": "FIN DEL INFORME DEL OPTIMIZADOR",
        "it": "FINE DEL REPORT DELL'OTTIMIZZATORE",
    },
    # ── physical interpretation notes ────────────────────────────────────
    "note1_title": {
        "en": "Wire length selection",
        "es": "Selección de longitud del hilo",
        "it": 'Selezione della lunghezza del filo',
    },
    "note1_body": {
        "en": ("The feedpoint alternates every λ/4: odd multiples (λ/4, 3λ/4 …) are current"
               " maxima with a low R of tens of ohms, while even multiples (λ/2, λ, 3λ/2 …)"
               " are voltage maxima of several kΩ.  Only ONE of those two classes is bad,"
               " and which one depends on the UnUn: fed directly or through a low ratio the"
               " kΩ points are the ones to avoid, while a 49:1/64:1 transformer exists"
               " precisely to match them (end-fed half-wave) and it is then the low-R points"
               " that load it badly.  The avoidance score is 1.0 on the resonance class the"
               " selected ratio wants, 0.0 on the other and 0.5 midway, averaged over ALL"
               " defined bands — including those marked inactive for VSWR scoring."
               " 1.0 = ★★★ EXCELLENT; values below 0.24 flag RESONANCE RISK, meaning the"
               " wire sits on the wrong resonance class for the transformer in use."),
        "es": ("El punto de alimentación alterna cada λ/4: los múltiplos impares (λ/4, 3λ/4 …)"
               " son máximos de corriente con R baja, de decenas de ohmios, mientras que los"
               " pares (λ/2, λ, 3λ/2 …) son máximos de tensión de varios kΩ.  Sólo UNA de las"
               " dos clases es mala, y cuál depende del UnUn: con alimentación directa o de"
               " relación baja hay que evitar los puntos de kΩ, mientras que un transformador"
               " 49:1/64:1 existe justamente para adaptarlos (end-fed de media onda) y entonces"
               " son los puntos de R baja los que lo cargan mal.  La puntuación de evitación"
               " vale 1.0 sobre la clase de resonancia que quiere la relación seleccionada, 0.0"
               " sobre la otra y 0.5 en el punto medio, promediada sobre TODAS las bandas"
               " definidas — incluidas las marcadas como inactivas para ROS.  1.0 = ★★★"
               " EXCELENTE; valores inferiores a 0.24 indican RIESGO DE RESONANCIA: el hilo"
               " está en la clase de resonancia equivocada para el transformador en uso."),
        "it": "Il punto di alimentazione alterna ogni λ/4: i multipli dispari (λ/4, 3λ/4 …) sono massimi di corrente con R bassa, di decine di ohm, mentre i multipli pari (λ/2, λ, 3λ/2 …) sono massimi di tensione di diversi kΩ.  Solo UNA di queste due classi è negativa, e quale dipende dall'UnUn: alimentando direttamente o con rapporto basso i punti a kΩ sono quelli da evitare, mentre un trasformatore 49:1/64:1 esiste proprio per adattarli (end-fed a mezza onda) e allora sono i punti a R bassa che lo caricano male.  Il punteggio di evitamento vale 1.0 sulla classe di risonanza che il rapporto selezionato desidera, 0.0 sull'altra e 0.5 a metà strada, mediato su TUTTE le bande definite — incluse quelle segnate come inattive per il ROS. 1.0 = ★★★ ECCELLENTE; valori sotto 0.24 segnalano RISCHIO DI RISONANZA, cioè il filo si trova nella classe di risonanza sbagliata per il trasformatore in uso.",
    },
    "note2_title": {
        "en": "Counterpoise length selection",
        "es": "Selección de longitud del contrapeso",
        "it": 'Selezione della lunghezza del contrappeso',
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
        "it": "Il contrappeso funge da metà mancante del sistema d'antenna.  Una lunghezza vicina a λ/4 alla frequenza operativa (o un suo multiplo dispari: 3λ/4, 5λ/4 …) fornisce un percorso di ritorno a bassa impedenza ed è attivamente premiata dall'ottimizzatore. Lunghezze vicine a un multiplo pari di λ/4 (cioè λ/2, λ, 3λ/2 …) producono un percorso di ritorno ad alta impedenza e non ricevono alcun premio.  Questo bonus è intenzionalmente piccolo rispetto al termine ROS, così che la risonanza del CP possa influenzare una coppia ravvicinata di candidati ma non possa prevalere su un cattivo adattamento ROS.",
    },
    "note3_title": {
        "en": "VSWR after UnUn",
        "es": "ROS después del UnUn",
        "it": "ROS dopo l'UnUn",
    },
    "note3_body": {
        "en": ("All VSWR values shown are referred to the TRANSMITTER side (50 Ω coaxial)"
               " AFTER the {0:.0f}:1 UnUn.  The antenna-side impedance is divided"
               " by {0:.0f} before computing VSWR.  The ratio is not a user setting:"
               " the optimizer sweeps every standard ratio and keeps the one with the"
               " lowest aggregate VSWR penalty for this geometry, which is {0:.0f}:1."),
        "es": ("Todos los valores de ROS mostrados corresponden al lado del TRANSMISOR (coaxial 50 Ω)"
               " DESPUÉS del UnUn {0:.0f}:1.  La impedancia del lado antena se divide"
               " por {0:.0f} antes de calcular el ROS.  La relación no la elige el usuario:"
               " el optimizador barre todas las relaciones estándar y conserva la de menor"
               " penalización ROS agregada para esta geometría, que resulta {0:.0f}:1."),
        "it": "Tutti i valori di ROS mostrati sono riferiti al lato TRASMETTITORE (coassiale 50 Ω) DOPO l'UnUn {0:.0f}:1.  L'impedenza lato antenna viene divisa per {0:.0f} prima di calcolare il ROS.  Il rapporto non è un'impostazione dell'utente: l'ottimizzatore scansiona tutti i rapporti standard e mantiene quello con la penalità ROS aggregata più bassa per questa geometria, che è {0:.0f}:1.",
    },
    "note4_title": {
        "en": "NEC2 vs empirical",
        "es": "NEC2 vs. empírico",
        "it": 'NEC2 vs empirico',
    },
    "note4_body": {
        "en": ("When nec2c is available, the optimizer runs a full Sommerfeld-Norton ground"
               " simulation for each candidate.  Without NEC2, the empirical formulas"
               " R = 50·80^cos²(π·L/λ½) and X = 1500·sin(2π·L/λ½) are used as a free-space,"
               " no-ground, no-counterpoise approximation for SCREENING GEOMETRIES ONLY."
               " Against NEC2 with a real ground and counterpoise, R can be off by 60x or more"
               " near L = λ/4-type points, and X is unreliable in both magnitude and sign —"
               " the formula predicts zero reactance at every half-wave multiple, while NEC2"
               " typically shows large negative reactance there because ground and counterpoise"
               " losses dominate X, and free-space wire formulas do not model them at all."
               " Never use the empirical X value to design a matching network.  NEC2 results"
               " are always preferred; install nec2c (see below) whenever accuracy matters,"
               " and cross-validate the final geometry with a VNA on the bench."),
        "es": ("Cuando nec2c está disponible, el optimizador ejecuta una simulación completa de"
               " tierra Sommerfeld-Norton para cada candidato.  Sin NEC2 se usan las fórmulas"
               " empíricas R = 50·80^cos²(π·L/λ½) y X = 1500·sin(2π·L/λ½) como una aproximación"
               " de hilo en espacio libre, sin tierra ni contrapeso, SÓLO PARA CRIBAR GEOMETRÍAS."
               " Frente a NEC2 con tierra real y contrapeso, R puede errar por 60x o más cerca de"
               " puntos tipo L = λ/4, y X no es confiable ni en magnitud ni en signo: la fórmula"
               " predice reactancia nula en cada múltiplo de media onda, mientras que NEC2 suele"
               " dar una reactancia negativa grande allí, porque las pérdidas de tierra y"
               " contrapeso dominan X y las fórmulas de hilo en espacio libre no las modelan en"
               " absoluto.  Nunca use el valor de X empírico para diseñar una red de adaptación."
               " Los resultados NEC2 siempre son preferidos; instale nec2c (ver más abajo) cuando"
               " la precisión importe, y valide la geometría final con un VNA en el banco."),
        "it": "Quando nec2c è disponibile, l'ottimizzatore esegue una simulazione completa di terra Sommerfeld-Norton per ogni candidato.  Senza NEC2 si usano le formule empiriche R = 50·80^cos²(π·L/λ½) e X = 1500·sin(2π·L/λ½) come approssimazione di filo in spazio libero, senza terra né contrappeso, SOLO PER LA SELEZIONE DELLE GEOMETRIE. Rispetto a NEC2 con terra reale e contrappeso, R può sbagliare di 60x o più vicino a punti tipo L = λ/4, e X non è affidabile né in modulo né in segno — la formula prevede reattanza nulla a ogni multiplo di mezza onda, mentre NEC2 mostra tipicamente una grande reattanza negativa lì, perché le perdite di terra e contrappeso dominano X e le formule di filo in spazio libero non le modellano affatto. Non usare mai il valore X empirico per progettare una rete di adattamento.  I risultati NEC2 sono sempre preferiti; installare nec2c (vedi sotto) ogni volta che la precisione conta, e validare la geometria finale con un VNA in laboratorio.",
    },
    "note5_title": {
        "en": "Next steps",
        "es": "Próximos pasos",
        "it": 'Prossimi passi',
    },
    "note5_body": {
        "en": ("1. Validate with a VNA before cutting the final wire."
               "  2. If VSWR > 3 on any priority band, add a second CP radial cut to λ/4"
               "   for that specific band, or drop that band from --active-bands so the"
               "   automatic UnUn search is not pulled towards it."
               "  3. Re-run with a finer --wire-step / --cp-step around the best candidate"
               "   to refine the optimum within a narrower window."),
        "es": ("1. Valide con un VNA antes de cortar el hilo final."
               "  2. Si ROS > 3 en alguna banda prioritaria, agregue un segundo radial de CP"
               "   cortado a λ/4 para esa banda, o quítela de --active-bands para que la"
               "   búsqueda automática del UnUn no se desvíe hacia ella."
               "  3. Re-ejecute con --wire-step / --cp-step más finos alrededor del mejor candidato"
               "   para refinar el óptimo en una ventana más estrecha."),
        "it": "1. Validare con un VNA prima di tagliare il filo definitivo.  2. Se il ROS > 3 su una banda prioritaria, aggiungere un secondo radiale di CP   tagliato a λ/4 per quella banda specifica, oppure rimuoverla da --active-bands così che   la ricerca automatica dell'UnUn non venga attratta verso di essa.  3. Rieseguire con --wire-step / --cp-step più fini attorno al miglior candidato   per raffinare l'ottimo in una finestra più stretta.",
    },
    # ── avoidance ratings ────────────────────────────────────────────────
    "rating_excellent": {
        "en": "★★★ EXCELLENT",
        "es": "★★★ EXCELENTE",
        "it": '★★★ ECCELLENTE',
    },
    "rating_good": {
        "en": "★★  GOOD",
        "es": "★★  BUENO",
        "it": '★★  BUONO',
    },
    "rating_marginal": {
        "en": "★   MARGINAL",
        "es": "★   MARGINAL",
        "it": '★   MARGINALE',
    },
    "rating_risk": {
        "en": "✗   RESONANCE RISK",
        "es": "✗   RIESGO DE RESONANCIA",
        "it": '✗   RISCHIO DI RISONANZA',
    },
    # ── VSWR quality labels ──────────────────────────────────────────────
    "vswr_excellent": {
        "en": "EXCELLENT",
        "es": "EXCELENTE",
        "it": 'ECCELLENTE',
    },
    "vswr_good": {
        "en": "GOOD",
        "es": "BUENO",
        "it": 'BUONO',
    },
    "vswr_marginal": {
        "en": "MARGINAL",
        "es": "MARGINAL",
        "it": 'MARGINALE',
    },
    "vswr_poor": {
        "en": "POOR",
        "es": "POBRE",
        "it": 'SCARSO',
    },
    # ── argparse description ─────────────────────────────────────────────
    "ap_description": {
        "en": textwrap.dedent("""\
            NEC2 Antenna Length Optimizer
            ─────────────────────────────
            Searches (wire_len, cp_len) combinations and ranks them by aggregate
            VSWR across all active bands.

            BAND SOURCE:
              --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
                  (--freqs optional for known amateur bands; auto centre freq used)
              --bands custom1,custom2 --freqs 7.1,14.2 --wire-len 21.0 --cp-len 5.0
                  (--freqs required for unrecognised band names)

            ACTIVE BANDS:
              --active-bands 40m,20m   Restrict which bands are scored for VSWR.
                                       Omit it to score every band in --bands.

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
              optimizer_best.csv    — best candidate exported as CSV
        """),
        "es": textwrap.dedent("""\
            Optimizador de Longitud de Antena NEC2
            ──────────────────────────────────────
            Busca combinaciones (longitud_hilo, longitud_CP) y las clasifica por
            ROS agregado en todas las bandas activas.

            FUENTE DE BANDAS:
              --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
                  (--freqs opcional para bandas amateur conocidas; usa freq. central auto)
              --bands custom1,custom2 --freqs 7.1,14.2 --wire-len 21.0 --cp-len 5.0
                  (--freqs requerido para nombres de banda no reconocidos)

            BANDAS ACTIVAS:
              --active-bands 40m,20m   Restringe qué bandas se evalúan para ROS.
                                       Omítalo para evaluar todas las de --bands.

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
        "it": "Ottimizzatore di Lunghezza Antenna NEC2\n────────────────────────────────────────\nCerca combinazioni (lunghezza_filo, lunghezza_CP) e le classifica in base al\nROS aggregato su tutte le bande attive.\n\nORIGINE DELLE BANDE:\n  --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0\n      (--freqs opzionale per bande amatoriali note; usa freq. centrale automatica)\n  --bands custom1,custom2 --freqs 7.1,14.2 --wire-len 21.0 --cp-len 5.0\n      (--freqs richiesto per nomi di banda non riconosciuti)\n\nBANDE ATTIVE:\n  --active-bands 40m,20m   Limita quali bande sono valutate per il ROS.\n                           Ometterlo per valutare tutte le bande di --bands.\n\nPer impostazione predefinita la finestra di ricerca è ±2 m attorno alle lunghezze\ndi filo e CP.  Usare --margin per ampliarla, oppure --wire-min/max e\n--cp-min/max per limiti espliciti.\n\nDue modalità di valutazione:\n  empirical  — veloce, usa le stesse formule R/X del foglio di calcolo\n  nec2       — precisa, esegue nec2c per ogni geometria candidata\n\nRICERCA DEL BINARIO NEC2C (automatica, in ordine):\n  1. --nec2c /percorso/a/nec2c\n  2. Variabile d'ambiente $NEC2C\n  3. PATH  (nec2c, nec2c-mpich)\n  4. Percorsi fissi (/usr/bin, /usr/local/bin, /opt/nec2c/bin …)\n  5. Richiesta interattiva\n\nFILE DI OUTPUT:\n  optimizer_report.txt  — tabella classificata + fronte di Pareto + interpretazione\n  optimizer_plot.png    — mappa di calore + grafici a barre del ROS per banda\n  optimizer_best.csv    — miglior candidato esportato come CSV\n",
    },
    # ── argparse argument help strings ───────────────────────────────────
    "ap_bands": {
        "en": "Comma-separated band names, e.g. '40m,20m,15m'. Required.",
        "es": "Nombres de banda separados por coma, ej. '40m,20m,15m'. Requerido.",
        "it": "Nomi di banda separati da virgola, es. '40m,20m,15m'. Obbligatorio.",
    },
    "ap_freqs": {
        "en": ("Comma-separated centre frequencies in MHz, one per band. "
               "Optional when all --bands names are recognised amateur-radio bands. "
               "Required only for unrecognised band names."),
        "es": ("Frecuencias centrales en MHz separadas por coma, una por banda. "
               "Opcional cuando todos los nombres en --bands son bandas amateur reconocidas. "
               "Requerido sólo para nombres de banda no reconocidos."),
        "it": 'Frequenze centrali in MHz separate da virgola, una per banda. Opzionale quando tutti i nomi in --bands sono bande amatoriali riconosciute. Richiesto solo per nomi di banda non riconosciuti.',
    },
    "ap_wire_len": {
        "en": "Starting wire length in metres for the search window centre. Required.",
        "es": "Longitud inicial del hilo en metros para el centro de la ventana de búsqueda. Requerido.",
        "it": 'Lunghezza iniziale del filo in metri per il centro della finestra di ricerca. Obbligatorio.',
    },
    "ap_cp_len": {
        "en": "Starting counterpoise length in metres for the search window centre. Required.",
        "es": "Longitud inicial del contrapeso en metros para el centro de la ventana de búsqueda. Requerido.",
        "it": 'Lunghezza iniziale del contrappeso in metri per il centro della finestra di ricerca. Obbligatorio.',
    },
    "ap_active_bands": {
        "en": ("Comma-separated list of band names to mark as active for VSWR scoring. "
               "Omit it to score every band in --bands."),
        "es": ("Lista de nombres de banda separados por coma para marcar como activas en la evaluación de ROS. "
               "Omítalo para puntuar todas las bandas de --bands."),
        "it": 'Elenco separato da virgole di nomi di banda da segnare come attive per la valutazione ROS. Ometterlo per valutare tutte le bande di --bands.',
    },
    "ap_mode": {
        "en": "Evaluation mode (default: auto = nec2 if binary found, else empirical).",
        "es": "Modo de evaluación (por defecto: auto = nec2 si se encuentra el binario, si no empírico).",
        "it": 'Modalità di valutazione (predefinito: auto = nec2 se il binario è trovato, altrimenti empirical).',
    },
    "ap_nec2c": {
        "en": "Explicit path to nec2c binary.  Overrides auto-discovery.",
        "es": "Ruta explícita al binario nec2c.  Reemplaza el descubrimiento automático.",
        "it": 'Percorso esplicito al binario nec2c.  Sostituisce la ricerca automatica.',
    },
    "ap_margin": {
        "en": ("Search radius in metres around the --wire-len and --cp-len values "
               "(default 2.0 m).  Overridden by explicit --wire-min/max or --cp-min/max."),
        "es": ("Radio de búsqueda en metros alrededor de los valores de --wire-len y --cp-len "
               "(por defecto 2.0 m).  Es reemplazado por --wire-min/max o --cp-min/max explícitos."),
        "it": 'Raggio di ricerca in metri attorno ai valori di --wire-len e --cp-len (predefinito 2.0 m).  Sostituito da --wire-min/max o --cp-min/max espliciti.',
    },
    "ap_wire_min": {
        "en": "Minimum wire length to search (metres).",
        "es": "Longitud mínima de hilo a buscar (metros).",
        "it": 'Lunghezza minima del filo da esplorare (metri).',
    },
    "ap_wire_max": {
        "en": "Maximum wire length to search (metres).",
        "es": "Longitud máxima de hilo a buscar (metros).",
        "it": 'Lunghezza massima del filo da esplorare (metri).',
    },
    "ap_wire_step": {
        "en": "Wire length step size (metres, default 0.25).",
        "es": "Tamaño de paso de longitud de hilo (metros, por defecto 0.25).",
        "it": 'Passo della lunghezza del filo (metri, predefinito 0.25).',
    },
    "ap_cp_min": {
        "en": "Minimum counterpoise length (metres).",
        "es": "Longitud mínima del contrapeso (metros).",
        "it": 'Lunghezza minima del contrappeso (metri).',
    },
    "ap_cp_max": {
        "en": "Maximum counterpoise length (metres).",
        "es": "Longitud máxima del contrapeso (metros).",
        "it": 'Lunghezza massima del contrappeso (metri).',
    },
    "ap_cp_step": {
        "en": "Counterpoise length step size (metres, default 0.25).",
        "es": "Tamaño de paso de longitud del contrapeso (metros, por defecto 0.25).",
        "it": 'Passo della lunghezza del contrappeso (metri, predefinito 0.25).',
    },
    "ap_height": {
        "en": ("Antenna height above ground (metres) — feedpoint height, shared by the radiator "
               "and the counterpoise. Default: {0} m."),
        "es": ("Altura de la antena sobre el suelo (metros) — altura del punto de alimentación, "
               "común al radiador y al contrapeso. Por defecto: {0} m."),
        "it": "Altezza dell'antenna sopra il suolo (metri) — altezza del punto di alimentazione, comune al radiatore e al contrappeso. Predefinito: {0} m.",
    },
    "ap_cp_end_height": {
        "en": ("Height of the far (non-feedpoint) counterpoise end above ground in metres. "
               "The counterpoise runs straight from the feedpoint down to this height; its slope "
               "follows from the CP length. Omit to keep it level with the antenna height."),
        "es": ("Altura del extremo lejano (no alimentado) del contrapeso sobre el suelo en metros. "
               "El contrapeso va recto desde el punto de alimentación hasta esa altura; su inclinación "
               "resulta de la longitud del CP. Omitir para dejarlo a la altura de la antena."),
        "it": "Altezza dell'estremo lontano (non alimentato) del contrappeso sopra il suolo, in metri. Il contrappeso va dritto dal punto di alimentazione fino a questa altezza; la sua inclinazione deriva dalla lunghezza del CP. Omettere per mantenerlo a livello dell'altezza dell'antenna.",
    },
    "ap_ground_cond": {
        "en": "Ground conductivity S/m (default {0}).",
        "es": "Conductividad del suelo en S/m (por defecto {0}).",
        "it": 'Conducibilità del suolo in S/m (predefinito {0}).',
    },
    "ap_ground_diel": {
        "en": "Ground relative permittivity (default {0}).",
        "es": "Permitividad relativa del suelo (por defecto {0}).",
        "it": 'Permittività relativa del suolo (predefinito {0}).',
    },
    "ap_top_n": {
        "en": "Number of top candidates to show in report (default 20).",
        "es": "Número de mejores candidatos a mostrar en el informe (por defecto 20).",
        "it": 'Numero di migliori candidati da mostrare nel report (predefinito 20).',
    },
    "ap_out_txt": {
        "en": "Output report filename (default: optimizer_report.txt).",
        "es": "Nombre del archivo de informe de salida (por defecto: optimizer_report.txt).",
        "it": 'Nome del file di report in uscita (predefinito: optimizer_report.txt).',
    },
    "ap_out_png": {
        "en": "Output plot filename (default: optimizer_plot.png).",
        "es": "Nombre del archivo de gráfico de salida (por defecto: optimizer_plot.png).",
        "it": 'Nome del file del grafico in uscita (predefinito: optimizer_plot.png).',
    },
    "ap_out_csv": {
        "en": "Best-candidate CSV output (default: optimizer_best.csv).",
        "es": "Salida CSV del mejor candidato (por defecto: optimizer_best.csv).",
        "it": 'CSV del miglior candidato in uscita (predefinito: optimizer_best.csv).',
    },
    "ap_out_nec": {
        "en": ("NEC2 deck for the best antenna geometry (default: best_antenna.nec). "
               "Includes full RP radiation-pattern cards per active band."),
        "es": ("Deck NEC2 para la mejor geometría de antena (por defecto: best_antenna.nec). "
               "Incluye tarjetas RP de patrón de radiación completo por banda activa."),
        "it": "Deck NEC2 per la miglior geometria d'antenna (predefinito: best_antenna.nec). Include schede RP di diagramma di radiazione completo per ogni banda attiva.",
    },
    "ap_out_radiation": {
        "en": "Radiation diagram PNG for all active bands (default: radiation_diagrams.png).",
        "es": "PNG de diagramas de radiación para todas las bandas activas (por defecto: radiation_diagrams.png).",
        "it": 'PNG dei diagrammi di radiazione per tutte le bande attive (predefinito: radiation_diagrams.png).',
    },
    "ap_out_construction": {
        "en": "Construction diagram PNG with build dimensions (default: antenna_construction.png).",
        "es": "PNG del diagrama de construcción con dimensiones (por defecto: antenna_construction.png).",
        "it": 'PNG del disegno costruttivo con le dimensioni (predefinito: antenna_construction.png).',
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
        "it": "Se il miglior candidato tocca un limite di ricerca (filo o CP al minimo/massimo), riesegue automaticamente la scansione fino a N volte, spostando la finestra nella direzione suggerita dall'avviso (migliore+margine per 'potrebbe essere maggiore', migliore-margine per 'potrebbe essere minore').  Predefinito: 0 (disattivato).",
    },
    "ap_no_interactive": {
        "en": "Do not prompt interactively for missing inputs; exit with error instead.",
        "es": "No solicitar entradas faltantes de forma interactiva; salir con error en su lugar.",
        "it": 'Non chiedere interattivamente gli input mancanti; uscire con errore invece.',
    },
    "ap_quiet": {
        "en": "Suppress progress output.",
        "es": "Suprimir la salida de progreso.",
        "it": "Sopprime l'output di avanzamento.",
    },
    "ap_lang": {
        "en": "Interface language: en (English) or es (Español). Default: auto-detect from system locale.",
        "es": "Idioma de la interfaz: en (English) o es (Español). Por defecto: detección automática del locale del sistema.",
        "it": "Lingua dell'interfaccia: en (English), es (Español) oppure it (Italiano). Predefinito: rilevamento automatico dal locale di sistema.",
    },
    "err_unknown_args": {
        "en": "  ERROR: unrecognized arguments: {0}",
        "es": "  ERROR: argumentos no reconocidos: {0}",
        "it": '  ERRORE: argomenti non riconosciuti: {0}',
    },
    "ap_gui": {
        "en": "Open the graphical user interface (all other flags become optional).",
        "es": "Abre la interfaz gráfica de usuario (todos los demás parámetros se vuelven opcionales).",
        "it": "Apre l'interfaccia grafica utente (tutti gli altri parametri diventano opzionali).",
    },
    # ── hardcoded strings in main() ──────────────────────────────────────
    "radiation_nec2_only_inline": {
        "en": "  ℹ  Radiation diagrams require NEC2 mode (current mode: {0}) — skipped.",
        "es": "  ℹ  Los diagramas de radiación requieren modo NEC2 (modo actual: {0}) — omitido.",
        "it": '  ℹ  I diagrammi di radiazione richiedono la modalità NEC2 (modalità attuale: {0}) — saltato.',
    },
    # ── PDF brochure ──────────────────────────────────────────────────────
    "ap_out_pdf": {
        "en": "Output PDF brochure (default: %(default)s)",
        "es": "Folleto PDF de salida (por defecto: %(default)s)",
        "it": 'Brochure PDF in uscita (predefinito: %(default)s)',
    },
    "pdf_generating": {
        "en": "Generating PDF brochure...",
        "es": "Generando folleto PDF...",
        "it": 'Generazione della brochure PDF...',
    },
    "pdf_saved": {
        "en": "  ✓ PDF brochure saved -> {0}",
        "es": "  ✓ Folleto PDF guardado -> {0}",
        "it": '  ✓ Brochure PDF salvata -> {0}',
    },
    "pdf_skip_no_reportlab": {
        "en": "  ⚠ reportlab not installed — skipping PDF brochure (pip install reportlab)",
        "es": "  ⚠ reportlab no está instalado — se omite el folleto PDF (pip install reportlab)",
        "it": '  ⚠ reportlab non installato — brochure PDF saltata (pip install reportlab)',
    },
    "pdf_brand_title": {
        "en": "Multiband Wire Antenna",
        "es": "Antena de Hilo Multibanda",
        "it": 'Antenna Filare Multibanda',
    },
    "pdf_brand_subtitle": {
        "en": "NEC2-Optimized Configuration Datasheet",
        "es": "Hoja de Datos de Configuración Optimizada con NEC2",
        "it": 'Scheda Tecnica di Configurazione Ottimizzata con NEC2',
    },
    "pdf_section_overview": {
        "en": "Configuration Overview",
        "es": "Resumen de la Configuración",
        "it": 'Panoramica della Configurazione',
    },
    "pdf_section_performance": {
        "en": "Performance Report",
        "es": "Informe de Rendimiento",
        "it": 'Report delle Prestazioni',
    },
    "pdf_section_radiation": {
        "en": "Radiation Patterns",
        "es": "Diagramas de Radiación",
        "it": 'Diagrammi di Radiazione',
    },
    "pdf_section_perband": {
        "en": "Per-Band Performance",
        "es": "Rendimiento por Banda",
        "it": 'Prestazioni per Banda',
    },
    "pdf_col_band": {"en": "Band", "es": "Banda", "it": 'Banda'},
    "pdf_col_freq": {"en": "Freq (MHz)", "es": "Frec (MHz)", "it": 'Freq (MHz)'},
    "pdf_col_vswr": {"en": "VSWR", "es": "ROE", "it": 'ROS'},
    "pdf_col_rating": {"en": "Rating", "es": "Calificación", "it": 'Valutazione'},
    "pdf_col_r_ant": {"en": "R_ant (Ω)", "es": "R_ant (Ω)", "it": 'R_ant (Ω)'},
    "pdf_col_x_ant": {"en": "X_ant (Ω)", "es": "X_ant (Ω)", "it": 'X_ant (Ω)'},
    "pdf_col_z_ant": {"en": "|Z_ant| (Ω)", "es": "|Z_ant| (Ω)", "it": '|Z_ant| (Ω)'},
    "pdf_col_r_tx":  {"en": "R_tx (Ω)",  "es": "R_tx (Ω)", "it": 'R_tx (Ω)'},
    "pdf_col_x_tx":  {"en": "X_tx (Ω)",  "es": "X_tx (Ω)", "it": 'X_tx (Ω)'},
    "pdf_col_source": {"en": "Source", "es": "Fuente", "it": 'Fonte'},
    "pdf_imp_precision_note": {
        "en": ("R_ant, X_ant rounded to segmentation uncertainty "
               "({0} seg/half wave, ~{1:.0f}% of R{2}). R_tx, X_tx are the "
               "transformed values and carry the same relative uncertainty."),
        "es": ("R_ant, X_ant redondeados a la incertidumbre de segmentación "
               "({0} seg/media onda, ~{1:.0f}% de R{2}). R_tx, X_tx son los "
               "valores transformados y llevan la misma incertidumbre relativa."),
        "it": ('R_ant, X_ant arrotondati all\u2019incertezza di segmentazione '
               '({0} seg/mezza onda, ~{1:.0f}% di R{2}). R_tx, X_tx sono i '
               'valori trasformati e presentano la stessa incertezza relativa.'),
    },
    "pdf_imp_precision_x_measured": {
        "en": "; X_ant \u00b1{0:.1f} \u03a9 measured",
        "es": "; X_ant \u00b1{0:.1f} \u03a9 medido",
        "it": '; X_ant \u00b1{0:.1f} \u03a9 misurato',
    },
    "pdf_col_theta":  {"en": "θ (°)", "es": "θ (°)", "it": 'θ (°)'},
    "pdf_col_ratio":  {"en": "Ratio", "es": "Relación", "it": 'Rapporto'},
    "pdf_col_score":  {"en": "Score", "es": "Puntuación", "it": 'Punteggio'},
    "pdf_col_best_ratio": {"en": "Best ratio", "es": "Mejor relación", "it": 'Miglior rapporto'},
    "pdf_col_avoidance":  {"en": "Avoidance", "es": "Evitación", "it": 'Evitamento'},
    "pdf_na": {"en": "N/A", "es": "N/D", "it": 'N/D'},
    "pdf_unun_used_label":      {"en": "UnUn ratio (automatic)",     "es": "Relación UnUn (automática)", "it": 'Rapporto UnUn (automatico)'},
    "pdf_unun_continuous_label":{"en": "Continuous optimum",         "es": "Óptimo continuo", "it": 'Ottimo continuo'},
    "pdf_unun_best_std_label":  {"en": "Best standard ratio",        "es": "Mejor relación estándar", "it": 'Miglior rapporto standard'},
    "pdf_unun_recommendation":  {"en": "Recommendation",             "es": "Recomendación", "it": 'Raccomandazione'},
    "pdf_unun_penalty_label":   {"en": "agg. VSWR penalty",         "es": "penaliz. ROS agr.", "it": 'penalità ROS agg.'},
    "pdf_detail_wire_len":      {"en": "Wire length",                "es": "Longitud del hilo", "it": 'Lunghezza del filo'},
    "pdf_detail_cp_len":        {"en": "CP length",                  "es": "Longitud del CP", "it": 'Lunghezza del CP'},
    "pdf_detail_geometry":      {"en": "Wire geometry",              "es": "Geometría del hilo", "it": 'Geometria del filo'},
    "pdf_detail_score":         {"en": "Combined score",             "es": "Puntuación combinada", "it": 'Punteggio combinato'},
    "pdf_detail_vswr_penalty":  {"en": "VSWR penalty",               "es": "Penalización ROS", "it": 'Penalità ROS'},
    "pdf_detail_avoid_act":     {"en": "Avoidance (active bands)",   "es": "Evitación (bandas activas)", "it": 'Evitamento (bande attive)'},
    "pdf_detail_avoid_all":     {"en": "Avoidance (all bands)",      "es": "Evitación (todas las bandas)", "it": 'Evitamento (tutte le bande)'},
    "pdf_detail_nec2":          {"en": "NEC2 data used",             "es": "Datos NEC2 usados", "it": 'Dati NEC2 usati'},
    "pdf_detail_nec2_trust":    {"en": "NEC2 data reliability",      "es": "Fiabilidad de datos NEC2", "it": 'Affidabilità dei dati NEC2'},
    "pdf_geom_horizontal":      {"en": "horizontal (flat, z = constant)", "es": "horizontal (plano, z = constante)", "it": 'orizzontale (piatta, z = costante)'},
    "pdf_spec_wire_len": {"en": "Radiator length", "es": "Longitud del radiador", "it": 'Lunghezza del radiatore'},
    "pdf_spec_cp_len": {"en": "Counterpoise length", "es": "Longitud del contrapeso", "it": 'Lunghezza del contrappeso'},
    "pdf_spec_cp_type": {"en": "Counterpoise geometry", "es": "Geometría del contrapeso", "it": 'Geometria del contrappeso'},
    "pdf_spec_unun": {"en": "Recommended UnUn ratio", "es": "Relación de UnUn recomendada", "it": 'Rapporto UnUn raccomandato'},
    "pdf_spec_height": {"en": "Antenna height", "es": "Altura de la antena", "it": "Altezza dell'antenna"},
    "pdf_spec_wire_diam": {"en": "Wire diameter", "es": "Diámetro del hilo", "it": 'Diametro del filo'},
    "pdf_spec_score": {"en": "Combined score (lower = better)", "es": "Puntaje combinado (menor = mejor)", "it": 'Punteggio combinato (minore = migliore)'},
    "pdf_spec_mode": {"en": "Optimization mode", "es": "Modo de optimización", "it": 'Modalità di ottimizzazione'},
    "pdf_spec_bands": {"en": "Active bands", "es": "Bandas activas", "it": 'Bande attive'},
    "pdf_footer": {
        "en": "Generated automatically by the NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0). "
              "All values are simulation estimates over average ground; on-site results may vary.",
        "es": "Generado automáticamente por el Optimizador de Longitud de Antena NEC2 (LU3VEA, CC0 v1.0). "
              "Todos los valores son estimaciones de simulación sobre tierra promedio; los resultados "
              "en el sitio pueden variar.",
        "it": "Generato automaticamente dall'Ottimizzatore di Lunghezza Antenna NEC2 (LU3VEA, CC0 v1.0). Tutti i valori sono stime di simulazione su terreno medio; i risultati sul campo possono variare.",
    },
    "pdf_spec_toa": {"en": "Take-off angle (main band)", "es": "Ángulo de despegue (banda principal)", "it": 'Angolo di decollo (banda principale)'},
    "pdf_detail_gain": {"en": "Peak gain / TOA per band", "es": "Ganancia máx. / TOA por banda", "it": 'Guadagno di picco / TOA per banda'},

    # ── Radiation-performance scoring (gain / take-off angle) ────────────
    "ap_gain_weight": {
        "en": ("Weight of the radiation term in the final score: "
               "score_final = score_combined − w × mean(gain at target TOA, dBi). "
               "0 disables the radiation re-ranking."),
        "es": ("Peso del término de radiación en la puntuación final: "
               "score_final = score_combined − w × media(ganancia al TOA objetivo, dBi). "
               "0 desactiva la reordenación por radiación."),
        "it": 'Peso del termine di radiazione nel punteggio finale: score_final = score_combined − w × media(guadagno al TOA obiettivo, dBi). 0 disattiva la riclassificazione per radiazione.',
    },
    "ap_target_toa": {
        "en": ("Target take-off angle in degrees above the horizon at which the "
               "gain term is evaluated (typical DX value: 20–30°)."),
        "es": ("Ángulo de despegue objetivo, en grados sobre el horizonte, al que "
               "se evalúa el término de ganancia (valor típico para DX: 20–30°)."),
        "it": "Angolo di decollo obiettivo in gradi sopra l'orizzonte a cui viene valutato il termine di guadagno (valore tipico per DX: 20–30°).",
    },
    "ap_rerank_top": {
        "en": ("How many of the best VSWR candidates are re-simulated with a full "
               "radiation pattern before the winner is declared."),
        "es": ("Cuántos de los mejores candidatos por ROE se vuelven a simular con "
               "diagrama de radiación completo antes de declarar el ganador."),
        "it": 'Quanti dei migliori candidati per ROS vengono nuovamente simulati con un diagramma di radiazione completo prima di dichiarare il vincitore.',
    },
    "gain_rerank_header": {
        "en": "Re-evaluating the {0} best candidates with a full radiation pattern (target TOA {1:.0f}°)…",
        "es": "Reevaluando los {0} mejores candidatos con diagrama de radiación completo (TOA objetivo {1:.0f}°)…",
        "it": 'Rivalutazione dei {0} migliori candidati con diagramma di radiazione completo (TOA obiettivo {1:.0f}°)…',
    },
    "gain_rerank_progress": {
        "en": "  pattern {0}/{1}: wire {2:.3f} m  cp {3:.3f} m",
        "es": "  patrón {0}/{1}: hilo {2:.3f} m  cp {3:.3f} m",
        "it": '  diagramma {0}/{1}: filo {2:.3f} m  cp {3:.3f} m',
    },
    "gain_rerank_failed": {
        "en": "  Radiation re-ranking could not run (no usable NEC2 pattern data) — ranking by VSWR only.",
        "es": "  No se pudo ejecutar la reordenación por radiación (sin datos de patrón NEC2 utilizables) — se ordena sólo por ROE.",
        "it": '  Impossibile eseguire la riclassificazione per radiazione (nessun dato di diagramma NEC2 utilizzabile) — classifica solo per ROS.',
    },
    "gain_rerank_table_hdr": {
        "en": "    {0:>6}  {1:>9}  {2:>9}  {3:>10}  {4:>8}  {5:>10}",
        "es": "    {0:>6}  {1:>9}  {2:>9}  {3:>10}  {4:>8}  {5:>10}",
        "it": '    {0:>6}  {1:>9}  {2:>9}  {3:>10}  {4:>8}  {5:>10}',
    },
    "gain_rerank_changed": {
        "en": "  Radiation re-ranking changed the winner: wire {0:.3f} m / cp {1:.3f} m "
              "({2:+.2f} dB at {3:.0f}° over the VSWR-only winner).",
        "es": "  La reordenación por radiación cambió el ganador: hilo {0:.3f} m / cp {1:.3f} m "
              "({2:+.2f} dB a {3:.0f}° sobre el ganador por ROE sola).",
        "it": '  La riclassificazione per radiazione ha cambiato il vincitore: filo {0:.3f} m / cp {1:.3f} m ({2:+.2f} dB a {3:.0f}° rispetto al vincitore per solo ROS).',
    },
    "gain_rerank_kept": {
        "en": "  Radiation re-ranking confirmed the VSWR winner.",
        "es": "  La reordenación por radiación confirmó al ganador por ROE.",
        "it": '  La riclassificazione per radiazione ha confermato il vincitore per ROS.',
    },
    "radiation_summary_hdr": {
        "en": "RADIATION PERFORMANCE OF THE WINNER (target TOA {0:.0f}°)",
        "es": "RENDIMIENTO RADIANTE DEL GANADOR (TOA objetivo {0:.0f}°)",
        "it": 'PRESTAZIONI DI RADIAZIONE DEL VINCITORE (TOA obiettivo {0:.0f}°)',
    },
    "radiation_row_hdr": {
        "en": "    {0:>8}  {1:>7}  {2:>10}  {3:>7}  {4:>12}",
        "es": "    {0:>8}  {1:>7}  {2:>10}  {3:>7}  {4:>12}",
        "it": '    {0:>8}  {1:>7}  {2:>10}  {3:>7}  {4:>12}',
    },
    "radiation_col_band":  {"en": "Band",       "es": "Banda", "it": 'Banda'},
    "radiation_col_mhz":   {"en": "MHz",        "es": "MHz", "it": 'MHz'},
    "radiation_col_gain":  {"en": "Max dBi",    "es": "Máx dBi", "it": 'Max dBi'},
    "radiation_col_toa":   {"en": "TOA",        "es": "TOA", "it": 'TOA'},
    "radiation_col_gtoa":  {"en": "dBi @ TOAobj", "es": "dBi @ TOAobj", "it": 'dBi @ TOAobj'},
    "warn_high_toa": {
        "en": ("WARNING: on {0} the main lobe peaks at {1:.0f}° above the horizon — "
               "this antenna radiates mostly upward (NVIS/cloud-warmer) on that band, "
               "not toward the horizon."),
        "es": ("ADVERTENCIA: en {0} el lóbulo principal apunta a {1:.0f}° sobre el horizonte — "
               "en esa banda la antena radia sobre todo hacia arriba (NVIS/calienta-nubes), "
               "no hacia el horizonte."),
        "it": "ATTENZIONE: su {0} il lobo principale punta a {1:.0f}° sopra l'orizzonte — su quella banda l'antenna irradia soprattutto verso l'alto (NVIS/scalda-nuvole), non verso l'orizzonte.",
    },
    "warn_no_radiation_data": {
        "en": "  No radiation-pattern data available for the winner — gain and TOA are unknown.",
        "es": "  Sin datos de diagrama de radiación para el ganador — ganancia y TOA desconocidos.",
        "it": '  Nessun dato di diagramma di radiazione disponibile per il vincitore — guadagno e TOA sconosciuti.',
    },
    "plot_elev_cut_label": {
        "en": "{0}  Elevation @ φ={1:.0f}° / {2:.0f}°",
        "es": "{0}  Elevación @ φ={1:.0f}° / {2:.0f}°",
        "it": '{0}  Elevazione @ φ={1:.0f}° / {2:.0f}°',
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
    # Conductor (I²R) efficiency (0–1), parsed from the NEC2 power budget when
    # the
    # deck carries conductor losses (LD card) and a pattern request.  It stays
    # None when the run did not report one — a default of 1.0 would have the
    # data structure claim a lossless antenna that was never measured.
    efficiency: Optional[float] = None
    vswr50:     float = 99.0       # VSWR ref 50 Ω
    # Full radiation-pattern table for this frequency, as parsed from the RP
    # section: list of (theta_nec_deg, phi_deg, total_gain_dbi).  Empty when
    # the deck carried no RP card (impedance-only sweep runs).  Kept so the
    # optimiser can score gain at a chosen take-off angle instead of only
    # reading the global maximum.
    rp_rows: List[Tuple[float, float, float]] = field(default_factory=list)

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
    cp_angle_deg: float = -1.0     # degrees from vertical; -1 = unknown
    freqs:      List[FreqPoint] = field(default_factory=list)
    # Diagnostic set by the parser when it detects its own failure (e.g.
    # block-splitting mismatch, duplicate-impedance heuristic) so callers
    # can surface *why* a run's impedances came back as NaN/NEC2-MISS
    # instead of just seeing VSWR 999 with no explanation.
    note:       str = ""

    def freq_map(self, decimals: int = 4) -> Dict[float, FreqPoint]:
        return {round(fp.freq_mhz, decimals): fp for fp in self.freqs}


@dataclass
class CalcRow:
    """One band definition (built from --bands / --freqs)."""
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

# The ANTENNA INPUT PARAMETERS table is printed as TAG, SEG, then a run of
# column *groups* (VOLTAGE, CURRENT, IMPEDANCE, sometimes ADMITTANCE, POWER,
# ...), each contributing REAL/IMAGINARY numeric fields except the trailing
# scalar POWER column. classic nec2c happens to print VOLTAGE, CURRENT,
# IMPEDANCE in that order with no ADMITTANCE column, which is why "4 numeric
# fields then R, X" used to be hardcoded below. But the module explicitly
# supports other engines (onec/OpenNEC, 4nec2/xnec2c/EZNEC export per the
# parse_nec2_output docstring), and at least one of those is known to insert
# an extra ADMITTANCE (MHOS) group into this table. If that group is ever
# emitted *before* IMPEDANCE instead of after it, a fixed "skip 4 fields"
# regex binds R/X to the wrong columns without failing to match -- a wrong-
# but-confident number instead of a clean no-match. So the offset is now
# read from the column-group header actually present in each file (see
# _antinput_impedance_offset), and the old fixed layout is kept only as a
# last-resort fallback for the (rare) case where no header line is found at
# all.
_RE_ANTINPUT_GROUP = re.compile(r'([A-Z]+)\s*\(', re.IGNORECASE)

_RE_ANTINPUT_FALLBACK = re.compile(
    r'^\s*\d+\s+\d+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+'
    r'([\-\d.E+]+)\s+([\-\d.E+]+)',
    re.IGNORECASE | re.MULTILINE)


def _antinput_impedance_offset(header_text: str) -> Optional[int]:
    """Return how many numeric fields (after TAG and SEG) precede the
    IMPEDANCE REAL/IMAGINARY pair in this file's ANTENNA INPUT PARAMETERS
    table, based on the column-group header actually printed -- instead of
    assuming the classic nec2c order (VOLTAGE, CURRENT, IMPEDANCE) always
    holds.

    Returns None if no "IMPEDANCE (...)" group is found in the header, so
    the caller knows the offset could not be determined and should not
    trust a positional guess.
    """
    groups = [g.upper() for g in _RE_ANTINPUT_GROUP.findall(header_text)]
    if 'IMPEDANCE' not in groups:
        return None
    offset = 0
    for g in groups:
        if g == 'IMPEDANCE':
            return offset
        # Every group group in this table is a REAL/IMAGINARY pair (2
        # numeric fields) except the trailing scalar POWER column.
        offset += 1 if g == 'POWER' else 2
    return None  # pragma: no cover - unreachable, IMPEDANCE checked above


def _build_antinput_regex(offset: int) -> 're.Pattern[str]':
    """Build the ANTENNA INPUT PARAMETERS data-row regex for a header-
    derived number of numeric fields preceding the impedance REAL/
    IMAGINARY pair."""
    skip = r'[\-\d.E+]+\s+' * offset
    return re.compile(
        r'^\s*\d+\s+\d+\s+' + skip + r'([\-\d.E+]+)\s+([\-\d.E+]+)',
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
# nec2c prints the efficiency inside the POWER BUDGET block that accompanies a
# pattern request once the structure has losses (LD card).  Both the explicit
# EFFICIENCY line and the raw input/radiated powers are read, so the figure
# survives formatting differences between nec2c builds.
_RE_PWR_IN = re.compile(
    r'INPUT\s+POWER\s*=\s*([\d.E+\-]+)', re.IGNORECASE)
_RE_PWR_RAD = re.compile(
    r'RADIATED\s+POWER\s*=\s*([\d.E+\-]+)', re.IGNORECASE)
_RE_WIRE_CM = re.compile(r'Wire\s+length:\s*([\d.]+)\s*m',             re.IGNORECASE)
# Current format, written by build_deck_geometry():
#   CM Counterpoise: 3.000 m  feed z=8.000 m -> end z=8.0000 m  (reach 3.000 m, 90.0 deg from vertical)
_RE_CP_CM_LEN = re.compile(
    r'Counterpoise:\s*([\d.]+)\s*m',                                   re.IGNORECASE)
_RE_CP_CM_ANGLE = re.compile(
    r'([\d.]+)\s*deg\s+from\s+vertical',                               re.IGNORECASE)
# Legacy format kept for backward compatibility with older/third-party .out
# files; not produced by this codebase's current writer.
_RE_CP_CM_LEN_LEGACY = re.compile(
    r'Counterpoise\s*\(angle=[\d.]+\s*deg\):\s*([\d.]+)\s*m',          re.IGNORECASE)
_RE_CP_VERT = re.compile(r'counterpoise\s*\(vertical\)',                re.IGNORECASE)

_RE_RP_SECTION = re.compile(r'[-]{4,}\s*RADIATION PATTERNS\s*[-]{4,}', re.IGNORECASE)

# The RADIATION PATTERNS table's gain columns are NOT a fixed layout: the
# RP card's XNDA "X" digit selects between "major axis, minor axis, total
# gain" (X=0) and "vertical, horizontal, total gain" (X=1) -- a user choice
# on the RP card, not a nec2c constant. A regex that hardcodes "3rd numeric
# field is skipped, 4th is TOTAL" happens to match nec2c's classic X=1
# layout, but gives a wrong-but-confident number instead of a clean
# no-match if a differing engine/export ever reorders or extends that
# column set. So, mirroring _antinput_impedance_offset /
# _build_antinput_regex above, the TOTAL-gain column position is read from
# the column header actually printed under the "RADIATION PATTERNS" banner
# in this file (nec2c prints "...VERT.  HOR.  TOTAL..." or "...MAJOR
# MINOR  TOTAL..."), and the old fixed-offset regex is kept only as a
# last-resort fallback for the rare case no such header line is found.
_RE_RP_HEADER = re.compile(
    r'^.*(?:MAJOR|VERT\.?).*(?:MINOR|HOR\.?).*TOTAL.*$', re.IGNORECASE | re.MULTILINE)
_RE_RP_HEADER_COL = re.compile(r'MAJOR|MINOR|VERT\.?|HOR\.?|TOTAL', re.IGNORECASE)

_RE_RP_ROW_FALLBACK = re.compile(
    r'^\s*((?:90(?:\.0+)?|[0-8]?\d(?:\.\d+)?))\s+(\d{1,3}(?:\.\d+)?)\s+'
    r'([\-\d.]+)\s+[\-\d.]+\s+([\-\d.]+)',
    re.MULTILINE)


def _rp_total_gain_offset(rp_text: str) -> Optional[int]:
    """Return how many numeric gain fields (after THETA and PHI) precede
    the TOTAL gain field in this file's RADIATION PATTERNS table, based on
    the column header actually printed -- instead of assuming the classic
    nec2c "3rd gain field is TOTAL" layout always holds.

    Returns None if no header line with a recognizable "TOTAL" column is
    found, so the caller knows the offset could not be determined and
    should fall back to the fixed-layout regex.
    """
    hm = _RE_RP_HEADER.search(rp_text)
    if not hm:
        return None
    nl = rp_text.find('\n', hm.start())
    header_line = rp_text[hm.start(): nl if nl >= 0 else len(rp_text)]
    cols = [c.upper() for c in _RE_RP_HEADER_COL.findall(header_line)]
    if 'TOTAL' not in cols:
        return None
    return cols.index('TOTAL')


def _build_rp_row_regex(offset: int) -> 're.Pattern[str]':
    """Build the RADIATION PATTERNS data-row regex for a header-derived
    number of gain fields preceding TOTAL gain, analogous to
    _build_antinput_regex."""
    skip = r'[\-\d.]+\s+' * offset
    return re.compile(
        r'^\s*((?:90(?:\.0+)?|[0-8]?\d(?:\.\d+)?))\s+(\d{1,3}(?:\.\d+)?)\s+'
        + skip + r'([\-\d.]+)',
        re.MULTILINE)


def _detect_freq_pattern(text: str):
    """Deterministically pick which frequency-marker regex applies to this
    .out file, instead of picking whichever pattern happens to return the
    most matches.

    The old "most matches wins" approach let the very permissive
    ``_RE_FREQ5`` (bare ``NNN.N MHZ`` at the start of a line) beat the
    engine-specific patterns whenever it happened to snag stray numeric text
    in comments or in another engine's differently-shaped output — even
    though real nec2c output only ever matches ``_RE_FREQ6``
    (``FREQUENCY :  ... MHz``).

    Instead, try the strict, engine-specific patterns first, in order of
    specificity, and return the first one that appears anywhere in the file.
    Only fall back to the loose ``_RE_FREQ5`` catch-all, and only once the
    file has independently been confirmed to look like genuine NEC2 output
    (via the ANTENNA INPUT PARAMETERS or RADIATION PATTERNS section
    headers), so an unrelated "NN.N MHZ" fragment elsewhere can't win.
    """
    strict_patterns = [_RE_FREQ6, _RE_FREQ3, _RE_FREQ, _RE_FREQ4, _RE_FREQ2]
    for pat in strict_patterns:
        if pat.search(text):
            return pat
    if _RE_ANTINPUT_SECTION.search(text) or _RE_RP_SECTION.search(text):
        if _RE_FREQ5.search(text):
            return _RE_FREQ5
    return None


def _filter_freq_markers(
        text: str,
        raw_positions: List[Tuple[int, float]]
) -> List[Tuple[int, float]]:
    """Discard frequency markers that do not actually lead a per-frequency
    data block.

    ``parse_nec2_output`` slices the file into one block per frequency
    marker, which is only correct if nec2c emits *exactly one* recognised
    marker per ``FR`` card execution. That assumption can silently fail in
    at least two ways:

      * A marker-shaped string appears somewhere that is not a genuine
        per-frequency block start (e.g. an echoed ``.nec`` input deck, a
        comment card, or a stray numeric line matched by the loose
        ``_RE_FREQ5`` fallback pattern).
      * A single genuine ``FR`` execution has the marker printed more than
        once before its data (e.g. once in a structure/echo section and
        again just before "ANTENNA INPUT PARAMETERS").

    Either way, treating every raw match as its own block boundary
    over-splits the file. Instead, keep a marker only if a recognised
    per-frequency data section (``ANTENNA INPUT PARAMETERS`` or
    ``RADIATION PATTERNS``) begins somewhere between it and the *next*
    raw marker (or EOF). A marker with no such section ahead of it never
    introduces a genuine new block, so it is dropped — collapsing
    duplicate markers within one FR execution down to the single marker
    that actually precedes that execution's data, and dropping markers
    that don't precede any recognisable data at all.

    If the file has no recognisable data sections at all, filtering can't
    be judged one way or the other, so the raw positions are returned
    unchanged and the decision is left to the structural block-count
    check and, ultimately, the fallback parser.
    """
    if not raw_positions:
        return raw_positions

    section_starts = sorted(
        m.start() for m in itertools.chain(
            _RE_ANTINPUT_SECTION.finditer(text),
            _RE_RP_SECTION.finditer(text)))
    if not section_starts:
        return raw_positions

    n = len(raw_positions)
    filtered = []
    for i, (pos, freq_mhz) in enumerate(raw_positions):
        next_pos = raw_positions[i + 1][0] if i + 1 < n else len(text)
        if any(pos < s < next_pos for s in section_starts):
            filtered.append((pos, freq_mhz))
    return filtered


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
            fp.freq_mhz = round(_safe_float(candidates[-1].group(1)), 4)
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

    # Normalize line endings: some NEC2 engines (e.g. OpenNEC/onec on
    # Windows) emit CRLF, others (nec2c on Linux) emit LF.  Stripping the
    # carriage return keeps every regex below behaving identically
    # regardless of which engine/platform produced the .out file.
    text = text.replace('\r\n', '\n').replace('\r', '\n')

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
    m = _RE_CP_CM_LEN.search(text) or _RE_CP_CM_LEN_LEGACY.search(text)
    if m:
        run.cp_len_m = float(m.group(1))
    if _RE_CP_VERT.search(text):
        run.cp_type = "vertical"
    elif run.cp_len_m > 0:
        # cp_angle_deg convention (see _cp_angle_from_geometry): 0 deg = hanging
        # straight down (vertical), 90 deg = horizontal.
        m_angle = _RE_CP_CM_ANGLE.search(text)
        if m_angle and float(m_angle.group(1)) < 45.0:
            run.cp_type = "vertical"
        else:
            run.cp_type = "horizontal"
    else:
        run.cp_type = "none"

    _parse_cp_from_nec_deck(filepath, run, explicit_nec_path=explicit_nec_path)

    freq_positions: List[Tuple[int, float]] = []
    freq_pattern = _detect_freq_pattern(text)
    if freq_pattern is not None:
        raw_positions = [(m.start(), _safe_float(m.group(1)))
                          for m in freq_pattern.finditer(text)]
        freq_positions = _filter_freq_markers(text, raw_positions)

    if debug and not freq_positions:
        print("  DEBUG: No frequency markers found with any pattern.")
        print("  DEBUG: Check the file format against the patterns in _ALL_FREQ_RES.")

    if not freq_positions:
        _parse_nec2_fallback(text, run)
        return run

    # ── Structural pre-check: verify the split is trustworthy BEFORE
    #    using it to build any FreqPoints ────────────────────────────────
    #
    # freq_positions is about to become the block boundaries for the
    # per-frequency parsing loop below. That is only valid if it has
    # exactly one entry per "ANTENNA INPUT PARAMETERS" block nec2c
    # actually emitted (one per FR card). _filter_freq_markers() already
    # removed markers that don't lead to a data section at all, but it
    # cannot fix the file if nec2c's own output is structurally
    # inconsistent (e.g. missing/extra blocks). Check that here, BEFORE
    # parsing, so a bad split is prevented rather than parsed into
    # plausible-looking FreqPoints that then have to be found and wiped
    # out afterwards.
    #
    # The check only applies when ANTENNA INPUT PARAMETERS is actually
    # the section format present: some engines/exports report impedance
    # via a different format entirely (Method 1 "IMPEDANCE = (R, X)",
    # Method 3 ZIN rows, Method 4 "Z = R +j X" tables) and never print
    # "ANTENNA INPUT PARAMETERS" at all. Comparing against a block count
    # of 0 in that case would falsely fail every genuinely valid run.
    n_antinput_blocks = len(_RE_ANTINPUT_SECTION.findall(text))
    if n_antinput_blocks > 0 and n_antinput_blocks != len(freq_positions):
        reason = (f"NEC2 output has {n_antinput_blocks} ANTENNA INPUT "
                  f"PARAMETERS block(s) but {len(freq_positions)} frequency "
                  f"marker(s) survived filtering — block-splitting cannot "
                  f"be trusted, falling back to impedance-anchored parsing "
                  f"(NEC2-MISS).")
        run.note = (run.note + " " + reason).strip()
        if debug:
            print(f"  DEBUG: {reason}")
        _parse_nec2_fallback(text, run)
        return run

    freq_positions.append((len(text), 0.0))

    for idx, (pos, freq_mhz) in enumerate(freq_positions[:-1]):
        block = text[pos: freq_positions[idx + 1][0]]
        fp = FreqPoint(freq_mhz=round(freq_mhz, 4))

        # Method 1: IMPEDANCE = (R, X)
        found = False
        m = _RE_IMPEDANCE.search(block)
        if m:
            fp.R_ohm = _safe_float(m.group(1))
            fp.X_ohm = _safe_float(m.group(2))
            found = True

        # Method 2: ANTENNA INPUT PARAMETERS table
        if not found:
            sec_m = _RE_ANTINPUT_SECTION.search(block)
            antinput_text = block[sec_m.start():] if sec_m else ""
            curr_pos = antinput_text.find('CURRENTS AND LOCATION')
            if curr_pos < 0:
                curr_pos = antinput_text.upper().find('CURRENTS AND LOCATION')
            search_text = antinput_text[:curr_pos] if curr_pos >= 0 else antinput_text

            # Work out the R/X column offset from this file's own column-
            # group header rather than assuming the classic nec2c layout,
            # so an engine that reorders or adds columns (e.g. an extra
            # ADMITTANCE group) can't silently bind R/X to the wrong
            # fields. Only fall back to the fixed nec2c layout if no
            # header line is found at all.
            offset = _antinput_impedance_offset(search_text)
            if offset is not None:
                m = _build_antinput_regex(offset).search(search_text)
            else:
                m = _RE_ANTINPUT_FALLBACK.search(search_text)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                fp.X_ohm = _safe_float(m.group(2))
                found = True

        # Method 3: ZIN label
        if not found:
            m = _RE_ZIN_ROW.search(block)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                fp.X_ohm = _safe_float(m.group(2))
                found = True

        # Method 4: Z = R +j X table
        if not found:
            m = _RE_Z_TABLE.search(block)
            if m:
                fp.R_ohm = _safe_float(m.group(1))
                sign     = 1.0 if m.group(2) == '+' else -1.0
                fp.X_ohm = sign * _safe_float(m.group(3))
                found = True

        # --- gain ---
        m = _RE_GAIN_MAX.search(block)
        if m:
            fp.gain_dbi = _safe_float(m.group(1))
        else:
            m = _RE_GAIN_DB.search(block)
            if m:
                fp.gain_dbi = _safe_float(m.group(1))

        # --- radiation efficiency (only when the run reports one) ---
        m = _RE_EFF.search(block)
        if m:
            _eff = _safe_float(m.group(1))
            if _eff > 1.5:              # printed as a percentage
                _eff /= 100.0
            if 0.0 < _eff <= 1.0:
                fp.efficiency = _eff
        if fp.efficiency is None:
            _mi = _RE_PWR_IN.search(block)
            _mr = _RE_PWR_RAD.search(block)
            if _mi and _mr:
                _pin = _safe_float(_mi.group(1))
                _prad = _safe_float(_mr.group(1))
                if _pin > 0.0 and 0.0 < _prad <= _pin * 1.001:
                    fp.efficiency = min(1.0, _prad / _pin)

        # --- RP table ---
        rp_gains: List[Tuple[float, float, float]] = []
        rp_sec_m = _RE_RP_SECTION.search(block)
        rp_search_text = block[rp_sec_m.start():] if rp_sec_m else ""
        # Derive the TOTAL-gain column offset from this file's own RP
        # column header (see _rp_total_gain_offset) instead of assuming
        # nec2c's classic "vertical, horizontal, total" layout always
        # holds -- an RP card with XNDA X=0 prints "major, minor, total"
        # in the same slot count, and a fixed offset can't tell the two
        # apart. Only fall back to the old fixed-offset regex (group 4)
        # when no recognizable header line is present at all.
        rp_offset = _rp_total_gain_offset(rp_search_text)
        if rp_offset is not None:
            rp_row_re = _build_rp_row_regex(rp_offset)
            total_group = 3
        else:
            rp_row_re = _RE_RP_ROW_FALLBACK
            total_group = 4
        for rm in rp_row_re.finditer(rp_search_text):
            theta = _safe_float(rm.group(1))
            phi   = _safe_float(rm.group(2))
            gain  = _safe_float(rm.group(total_group))
            if gain <= -200.0:
                continue
            rp_gains.append((theta, phi, gain))

        if rp_gains:
            best_rp = max(rp_gains, key=lambda t: t[2])
            fp.gain_dbi = best_rp[2]
            fp.toa_deg = 90.0 - best_rp[0]
            # Keep the whole table: the global maximum alone cannot tell the
            # optimiser what the antenna does at a low take-off angle.
            fp.rp_rows = rp_gains

        fp.vswr50 = fp.compute_vswr50()
        run.freqs.append(fp)

    # ── Sanity check: same (R, X) reused across multiple distinct
    #    frequencies almost certainly means the per-frequency blocks were
    #    not correctly split (the parser extracted the same impedance line
    #    for every FR/RP block).  Different antenna lengths/frequencies
    #    practically never produce identical impedance to 2 decimals, so
    #    treat any such duplicates as a parse failure rather than letting
    #    them silently masquerade as valid NEC2 results.
    #
    #    The block-count-vs-marker-count structural check now runs BEFORE
    #    this loop (see above) and returns early via the fallback parser
    #    on mismatch, so it never reaches here with a known-bad split.
    #    This remaining check is defense-in-depth for the rarer case where
    #    the block count matches but the same impedance line still leaked
    #    into more than one block; it requires full-precision identity (no
    #    rounding) *and* more than two frequencies involved, so two
    #    genuinely close bands landing on the same 2-decimal (R, X) can't
    #    trip it and silently wipe out an otherwise valid candidate.
    if len(run.freqs) > 1:
        seen: Dict[Tuple[float, float], List[int]] = {}
        for i, fp in enumerate(run.freqs):
            seen.setdefault((fp.R_ohm, fp.X_ohm), []).append(i)
        for (r_val, x_val), idxs in seen.items():
            if len(idxs) > 1 and not (r_val == 0.0 and x_val == 0.0):
                freqs_involved = {run.freqs[i].freq_mhz for i in idxs}
                if len(freqs_involved) > 2:
                    for i in idxs:
                        run.freqs[i].R_ohm = float('nan')
                        run.freqs[i].X_ohm = float('nan')
                        run.freqs[i].vswr50 = 999.0
                    reason = (f"duplicate impedance ({r_val}, {x_val}) found "
                              f"across frequencies {sorted(freqs_involved)} — "
                              f"marking as parse failure (NEC2-MISS).")
                    run.note = (run.note + " " + reason).strip()
                    if debug:
                        print(f"  DEBUG: {reason}")

    return run


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS & DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════

C_MHZ = 299.792458          # speed of light / 1e6
WIRE_RADIUS_M = 0.001       # RADIUS in metres (not diameter): 1 mm radius = 2 mm
                             # (~AWG 12) diameter copper wire. Overridable via
                             # --wire-diameter (see main()).

# ── Conductor losses (NEC-2 LD card) ───────────────────────────────────────
# Without an LD card every wire in the deck is a PERFECT conductor and the
# published gains are idealised — exactly in the geometries this tool tends
# to prefer (short counterpoises, high feed impedances), where the I²R loss
# in a 1 mm wire is not negligible.  All decks therefore carry a wire
# conductivity, copper by default.
WIRE_MATERIALS: Dict[str, float] = {
    "copper":    5.80e7,
    "aluminium": 3.54e7,
    "aluminum":  3.54e7,
    "brass":     1.56e7,
    "silver":    6.30e7,
    "steel":     6.99e6,     # galvanised steel wire
    "perfect":   0.0,        # no LD card — lossless, for comparison runs
}
DEFAULT_WIRE_MATERIAL = "copper"
WIRE_CONDUCTIVITY = WIRE_MATERIALS[DEFAULT_WIRE_MATERIAL]   # S/m; set from CLI

# ── Display-name translations for WIRE_MATERIALS ───────────────────────────
# The dict keys above ("copper", "aluminium", …) are the canonical values:
# they are argparse --wire-material choices and are passed verbatim on the
# command line built by the GUI, so they must NEVER be translated or the
# CLI call breaks (argparse's `choices` only accepts the English keys).
# This table only supplies a localized *label* for the GUI combobox; the
# underlying StringVar still stores/returns the English key.
WIRE_MATERIAL_LABELS: Dict[str, Dict[str, str]] = {
    "copper":    {"en": "copper",    "es": "cobre",   "it": "rame"},
    "aluminium": {"en": "aluminium", "es": "aluminio", "it": "alluminio"},
    "aluminum":  {"en": "aluminum",  "es": "aluminio (US)", "it": "alluminio (US)"},
    "brass":     {"en": "brass",     "es": "latón",   "it": "ottone"},
    "silver":    {"en": "silver",    "es": "plata",   "it": "argento"},
    "steel":     {"en": "steel",     "es": "acero (galvanizado)", "it": "acciaio (zincato)"},
    "perfect":   {"en": "perfect",   "es": "perfecto (sin pérdidas)", "it": "perfetto (senza perdite)"},
}

def wire_material_label(key: str, lang: Optional[str] = None) -> str:
    """Localized display label for a WIRE_MATERIALS key.
    `lang` defaults to the module-level CLI language (_LANG); the GUI passes
    its own live self._ui_lang so the combobox can be relabeled independently
    of the CLI's language setting."""
    entry = WIRE_MATERIAL_LABELS.get(key)
    if not entry:
        return key
    use_lang = lang if lang is not None else _LANG
    return entry.get(use_lang, entry["en"])

def wire_material_key_from_label(label: str, lang: Optional[str] = None) -> str:
    """Reverse lookup: localized label -> canonical WIRE_MATERIALS key.
    Falls back to treating `label` as already a key (covers English/CLI use)."""
    for key, entry in WIRE_MATERIAL_LABELS.items():
        if label in entry.values():
            return key
    return label
# NOTE: decorative under nec2c. LD 5's second value (F2, relative
# permeability) is a NEC-4 field; nec2c's calculations.c load(), case 6,
# reads only F1 (conductivity) for type-5 cards and ignores F2 entirely.
# Changing this will NOT model magnetic wire on the stock nec2c binary this
# script targets — it is written to the card for forwards compatibility only.
WIRE_REL_PERMEABILITY = 1.0

# ── Transmatch tap quantisation ────────────────────────────────────────────
TRANSMATCH_TAP_TOL = 0.02   # max relative error of a realised tap resistance
TRANSMATCH_MIN_TREF = 10    # floor for the Z0 reference winding (was 5)
TRANSMATCH_MAX_TREF = 200   # never propose a reference longer than this

# ── Transmatch self-resonance ──────────────────────────────────────────────
# A tapped autotransformer is only an autotransformer BELOW the self-resonant
# frequency of its own winding.  Above the SRF the solenoid is a capacitively
# dominated network, the coupling between the Z0 portion and the tap collapses,
# and the model r_p = R/n^2 is void.  This bit the design silently: fed with a
# real 3617/1195/640 ohm antenna on 40/20/15 m, the auto reference produced an
# 85-turn, 77.8 uH coil on a 50 mm former whose SRF is around 10 MHz — the 20 m
# and 15 m taps sat ABOVE it and were still reported as SWR 1.9 / 3.5 with no
# warning.  The winding is therefore checked for SRF, and the auto reference is
# shortened until the SRF clears the highest band by this margin.
TRANSMATCH_SRF_MARGIN = 1.5   # SRF must exceed 1.5 x f_max
# The winding also SHUNTS the antenna port with its own reactance.  When
# X_winding is not much larger than |Z_antenna| the tap is loaded by the coil
# rather than transforming through it; below this ratio the row is flagged.
TRANSMATCH_SHUNT_RATIO_MIN = 10.0

DEFAULT_HEIGHT_M = 8.0      # antenna height above ground (radiator + counterpoise)
AUTO_UNUN_SEED = 9.0        # seed ratio for the first sweep; the optimiser
                            # then selects the best UnUn automatically
AUTO_UNUN_PASSES = 4        # max geometry ↔ UnUn refinement iterations
DEFAULT_GROUND_COND = 0.005 # S/m  (average ground)
DEFAULT_GROUND_DIEL = 13.0  # relative permittivity
# ── Segmentation (NEC-2 segments per half wavelength) ──────────────────────
# 21 segments per half wave (~42 per lambda) is enough for RADIATION PATTERNS
# but far too coarse for IMPEDANCE, especially with the source sitting on a
# wire junction.  Measured with nec2c at 14.175 MHz, 19 m radiator + 2 m
# counterpoise, feedpoint 8 m, Sommerfeld-Norton ground:
#
#     seg/half-wave   segs (wire/cp)     R (Ohm)     X (Ohm)
#            10            17 /  7        229.4      +19.70
#            21            37 /  7        278.0      +10.06
#            31            55 /  7        293.7       +5.48
#            45            81 /  9        305.4       +1.96
#            63           113 / 11        312.2       -0.44
#            90           161 / 17        319.2       -2.33
#           120           215 / 23        323.2       -3.55
#
# R keeps climbing all the way to 215 segments, and — the part that actually
# misleads the user — the SIGN of the reactance is still wrong at 45 seg/half
# wave: it only flips to the converged sign somewhere above 60.  Near
# resonance the sign of X is exactly what the operator is asking about, so the
# density used for the PUBLISHED impedances is set above that crossover.
#
# Cost is not the obstacle: one full-band 8-band deck of this antenna takes
# 0.20 s at 21 seg/half wave, 0.37 s at 45, 0.57 s at 63 and 1.09 s at 90.
# The expensive part is the SWEEP (thousands of decks), not the handful of
# final runs, so the two densities are decoupled:
#
#   FAST  : coarse, explicit --fast sweeps and RP pattern decks
#   SWEEP : default density of the search — the RANKING is robust to it
#   FINE  : every number that gets published (best-candidate run, exported
#           deck, report, CSV) is recomputed at this density
SEGS_PER_HALF_WAVE_FAST  = 21   # pattern-grade only
SEGS_PER_HALF_WAVE_SWEEP = 45   # default search density
SEGS_PER_HALF_WAVE_FINE  = 90   # default for published impedances
SEGS_PER_HALF_WAVE = SEGS_PER_HALF_WAVE_FINE   # module default for all decks
SEGS_PER_HALF_WAVE_MAX = 400    # sanity cap (deck size / runtime)

# Convergence self-check (--converge): the winning geometry is re-run at these
# multiples of the working segmentation and the drift of R/X is reported.
CONVERGENCE_FACTORS = (2.0, 4.0)
CONVERGENCE_R_TOL_PCT = 3.0     # R drift above this is flagged in the report

# R and X do NOT converge together.  Measured on a 19 m radiator + 2 m
# counterpoise at 90 / 180 / 360 seg per half wave: R moved 0.4 % while X moved
# 304 ohm and had not settled its sign at the finest density.  A verdict built
# on R alone therefore certifies a reactance that is still moving, and X is
# exactly the quantity the builder uses to size the matching network.  X is
# consequently given its OWN tolerance and its OWN published uncertainty:
#
#     tol_X = max(CONVERGENCE_X_TOL_OHM_MIN, CONVERGENCE_X_TOL_Z_PCT % of |Z|)
#
# The absolute floor keeps the criterion meaningful near resonance (|Z| small,
# a few ohm of drift matters); the |Z| fraction keeps it from being absurdly
# strict on a 3.7 kOhm feedpoint.
CONVERGENCE_X_TOL_OHM_MIN = 5.0   # absolute floor of the X tolerance, ohm
CONVERGENCE_X_TOL_Z_PCT   = 2.0   # ...or this % of |Z|, whichever is larger
SEGS_X_UNCERTAINTY_FLOOR_OHM = 1.0  # never publish X as better than +/-1 ohm

# ── Radiation re-ranking (gain / take-off angle) ───────────────────────────
# The sweep scores impedance only: its decks carry no RP card, which is what
# makes it fast.  A candidate that is a perfect match but fires straight up is
# therefore indistinguishable, on VSWR alone, from one that puts the same
# power at 20° elevation.  To close that gap without paying for a pattern on
# every grid point, the best RERANK_TOP_N candidates are re-simulated WITH an
# RP card and re-ordered by
#     score_final = score_combined − gain_weight × mean(gain at target TOA)
# before a winner is declared.
DEFAULT_TARGET_TOA_DEG = 25.0   # elevation at which the gain term is read
DEFAULT_GAIN_WEIGHT    = 0.20   # dB⁻¹ — 5 dB of gain ≈ 1.0 of score
DEFAULT_RERANK_TOP_N   = 6      # candidates re-simulated with a full pattern
RP_RERANK_N_THETA      = 19     # θ = 0…90° in 5° steps
RP_RERANK_N_PHI        = 24     # φ = 0…345° in 15° steps
HIGH_TOA_WARN_DEG      = 60.0   # above this the antenna is a cloud-warmer

# Segmentation-induced impedance uncertainty, as a percentage of R.
# Fitted to the measured table above, taking the 120 seg/half-wave run as the
# reference: the error is ~14 % at 21, ~5.5 % at 45 and ~1.2 % at 90.  K=250
# tracks the coarse end and stays deliberately conservative at the fine end.
# It exists so R/X can be printed with the precision they actually have when
# no explicit --converge measurement is available.
SEGS_UNCERTAINTY_K = 294.0
SEGS_UNCERTAINTY_FLOOR_PCT = 1.0

# ── Ground-proximity limits (NEC-2 Sommerfeld-Norton ground) ───────────────
# NEC-2's SN ground is singular as a wire approaches z=0: the impedance does
# not converge towards the grounded case, it jumps to an unrelated value (and
# nec2c prints no warning whatsoever).  Wire ends are therefore never allowed
# closer to ground than GROUND_CLEAR_FRAC_SAFE·λ at the LOWEST frequency in
# the deck; anything requested below GROUND_CLEAR_FRAC_HARD·λ is additionally
# reported as unreliable so the candidate is not silently scored.
GROUND_CLEAR_FRAC_SAFE = 0.05   # hard floor applied to every wire end
GROUND_CLEAR_FRAC_HARD = 0.02   # below this the run is flagged nec2_ok=False

# Ground models.  "sommerfeld" = GN 2 (real ground, no wire may touch it);
# "perfect"    = GN 1 (perfectly conducting ground, wire ends MAY sit at
# exactly z=0 and are then galvanically connected to it).  A true buried or
# ground-connected conductor over REAL ground is a NEC-4 feature and is not
# available here.
GROUND_MODEL_CHOICES = ("sommerfeld", "perfect")
DEFAULT_GROUND_MODEL = "sommerfeld"

# How the return path is modelled when the antenna is built WITHOUT a
# counterpoise.  NEC-2 has no implicit return path: a single wire fed at its
# absolute end is an open circuit, not an end-fed antenna.
#   ground-rod : vertical conductor from the feedpoint down to z=0 over a
#                perfectly conducting ground (GN 1) — a ground rod / earth stake.
#   coax-stub  : short vertical stub representing the coax braid and the
#                common-mode path, kept clear of ground, real ground retained.
#   reject     : refuse the combination in NEC2 mode (empirical mode still OK).
NO_CP_RETURN_CHOICES = ("ground-rod", "coax-stub", "reject")
DEFAULT_NO_CP_RETURN = "ground-rod"
DEFAULT_CP_STUB_LEN_M = 2.0     # default coax-braid stub length (metres)

# NEC2 engine search paths (searched in order after PATH)
# Two families are supported, auto-detected from the binary's filename:
#   • nec2c  (classic, Linux/macOS)   → invoked as:  nec2c -i IN -o OUT
#   • onec   (OpenNEC, Linux/macOS/Windows) → invoked as: onec -o OUT IN
NEC2C_SEARCH_PATHS = [
    "/usr/bin/nec2c",
    "/usr/local/bin/nec2c",
    "/opt/nec2c/bin/nec2c",
    "/opt/homebrew/bin/nec2c",
    "/usr/bin/nec2c-mpich",
    "/usr/local/bin/nec2c-mpich",
    "/usr/bin/onec",
    "/usr/local/bin/onec",
    "/opt/onec/bin/onec",
    "/opt/homebrew/bin/onec",
    # Common Windows install locations (OpenNEC / scoop)
    r"C:\Program Files\OpenNEC\onec.exe",
    r"C:\Program Files (x86)\OpenNEC\onec.exe",
    os.path.expanduser(r"~\scoop\apps\onec\current\onec.exe"),
    os.path.expanduser(r"~\scoop\shims\onec.exe"),
]

# Names tried on PATH, in priority order. On Windows shutil.which() will
# also match the ".exe" variants automatically via PATHEXT.
NEC2C_NAMES = ["nec2c", "nec2c-mpich", "onec"]


def _nec2_engine_kind(binary_path: str) -> str:
    """
    Identify which NEC2 engine 'binary_path' refers to, based on its
    filename. Used to select the correct command-line syntax.

    Returns "onec" for OpenNEC (onec / onec.exe), otherwise "nec2c"
    (covers nec2c, nec2c-mpich, xnec2c and similar classic builds).
    """
    name = os.path.basename(binary_path).lower()
    if name.startswith("onec"):
        return "onec"
    return "nec2c"

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


def freq_match_tol_mhz(freq_mhz: float) -> float:
    """
    Return the frequency-matching tolerance (MHz) used to bind a requested
    band frequency to the nearest frequency actually present in a parsed
    NEC2 run (run.freq_map()).

    Scales at 4% of the target frequency, clamped to [floor, 0.75] MHz.
    The floor is *relative* (0.2% of freq) rather than a fixed 0.15 MHz,
    because a fixed floor is larger than the frequency itself for 2200m
    (0.1365 MHz) and comparable to it for 630m (0.475 MHz) — unphysical
    for sub-MHz work and a thin margin against cross-band misbinding.

    This is the single source of truth for that tolerance; every call
    site that matches a requested freq_mhz against fmap.keys() must use
    this helper instead of a local literal, so the rule can't drift out
    of sync across call sites again.
    """
    return max(0.002 * freq_mhz, min(0.75, 0.04 * freq_mhz))


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


# Typical feedpoint resistance at the two resonance classes of a wire fed
# against a counterpoise.  Used only to decide WHICH class the transformer in
# use is aiming at — the numbers need to be the right order of magnitude, not
# exact.
R_CURRENT_MAX = 50.0      # Ω at an odd  λ/4 multiple (λ/4, 3λ/4 …)
R_VOLTAGE_MAX = 4000.0    # Ω at an even λ/4 multiple (λ/2, λ …)


def resonance_preference(unun_ratio: float) -> Tuple[float, float]:
    """
    (w_odd, w_even): how much each resonance class is WANTED, given the
    transformer ratio actually in use.  Weights sum to 1.

    Which resonance is "good" is not an absolute property of the wire — it
    depends on what the feed transforms.  Fed directly or through a low ratio,
    the odd multiples (current maxima, tens of ohms) are the good ones and the
    even multiples (voltage maxima, kΩ) are the ones to avoid.  Through a
    49:1/64:1 transformer — an end-fed half-wave — the polarity inverts: the
    kΩ voltage maximum is precisely the point being matched, and it is now the
    low-R current maximum that presents a bad load.

    Each class is scored by how close its resistance lands to 50 Ω after the
    transformer, in log-resistance terms, and the two are softmax-blended.  At
    an intermediate ratio (e.g. 9:1, aimed at ~450 Ω, which is neither
    resonance) the weights come out near 0.5/0.5 and the metric correctly
    expresses "no parity preference".
    """
    r = max(float(unun_ratio), 1e-9)
    e_odd = abs(math.log((R_CURRENT_MAX / r) / 50.0))
    e_even = abs(math.log((R_VOLTAGE_MAX / r) / 50.0))
    w_odd, w_even = math.exp(-e_odd), math.exp(-e_even)
    tot = w_odd + w_even
    return (w_odd / tot, w_even / tot) if tot > 0 else (0.5, 0.5)


def band_avoidance_score(wire_len_m: float,
                         freq_mhz: float,
                         unun_ratio: float,
                         weights: Optional[Tuple[float, float]] = None) -> float:
    """
    Normalised resonance-avoidance score (0…1) for ONE band.

    SINGLE SOURCE OF TRUTH.  Every consumer — score_candidate(), the
    re-score pass that runs when the UnUn ratio changes, and the CSV
    exporter — must call this and nothing else.  Three independent copies
    of this arithmetic used to exist and they disagreed with each other
    (the report and the CSV of the same run printed opposite verdicts for
    the same band), so any new consumer goes through here too.

    Not every λ/4 multiple is something to avoid — only every OTHER one:
      odd  multiples (λ/4, 3λ/4, 5λ/4 …) → current maximum, R of tens of ohms;
      even multiples (λ/2, λ, 3λ/2 …)    → voltage maximum, R of a few kΩ.
    WHICH of the two is the good one depends on the transformer in use, so
    the score is ratio-dependent, NOT geometry-only: see
    resonance_preference().  1.0 means sitting on the resonance class the
    transformer actually wants, 0.0 the other one, 0.5 midway between two
    resonances — the scale _avoidance_rating() is calibrated for.

    `weights` lets a caller hoist resonance_preference(unun_ratio) out of a
    per-band loop; when given it must be that exact pair.
    """
    w_odd, w_even = (weights if weights is not None
                     else resonance_preference(unun_ratio))
    lambda_qtr = C_MHZ / (4.0 * freq_mhz) if freq_mhz else 0.0
    if lambda_qtr <= 0.0:
        return 0.0
    ratio = wire_len_m / lambda_qtr        # how many λ/4 units is the wire?
    mod2 = ratio % 2.0                     # odd multiples near 1, even near 0 or 2
    dist_from_odd = abs(mod2 - 1.0)        # 0 = odd λ/4, 1 = even λ/4
    near_odd = math.cos(math.pi * dist_from_odd / 2.0) ** 2  # 1 at odd, 0 at even
    return w_odd * near_odd + w_even * (1.0 - near_odd)


def _avoidance_rating(score: float) -> str:
    """
    Map a resonance-avoidance score to a human-readable label.

    Thresholds calibrated for the normalised avoidance metric, where 1 means
    sitting on the resonance class the transformer in use actually wants
    (see resonance_preference()), 0 means sitting on the other one, and 0.5
    means midway between two resonances:
      ≥ 0.80  → ★★★ EXCELLENT
      ≥ 0.48  → ★★  GOOD
      ≥ 0.24  → ★   MARGINAL
      < 0.24  → ✗   RESONANCE RISK
    """
    if score >= 0.80:
        return T("rating_excellent")
    elif score >= 0.48:
        return T("rating_good")
    elif score >= 0.24:
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
        print(f"\n{Fore.YELLOW}" + T("nec2c_not_found_auto") + f"{Style.RESET_ALL}")
        print(T("nec2c_options"))
        print(T("nec2c_install_apt"))
        print(T("nec2c_install_brew"))
        print(T("nec2c_install_onec_header"))
        print(T("nec2c_install_onec_brew"))
        print(T("nec2c_install_onec_scoop"))
        print(T("nec2c_build_source_header"))
        print(T("nec2c_build_source_steps"))
        print(T("nec2c_rerun"))
        print(T("nec2c_env"))
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

def _segs(length_m: float, highest_freq_mhz: float,
          segs_per_half_wave: Optional[int] = None) -> int:
    """Return an odd number of segments appropriate for the wire length.

    Odd segment count is preferred for NEC2 numerical stability and to give
    a well-defined physical centre segment.  The source (EX card) is placed
    at segment 1 (the near end / feedpoint junction), not the centre segment.

    `segs_per_half_wave` overrides the module default (SEGS_PER_HALF_WAVE);
    it is what the sweep, the final best-candidate run and the convergence
    self-check use to work at different segmentation densities.
    """
    spw = int(segs_per_half_wave or SEGS_PER_HALF_WAVE)
    spw = max(5, min(spw, SEGS_PER_HALF_WAVE_MAX))
    lambda_half = C_MHZ / (2.0 * highest_freq_mhz) if highest_freq_mhz else 10.0
    n = max(7, int(length_m / lambda_half * spw))
    return n if n % 2 == 1 else n + 1


def _segs_at_length(length_m: float, seg_len_m: float, min_segs: int = 1) -> int:
    """Segment a wire to a GIVEN target segment length, rounded to odd.

    Used for every conductor that shares the feedpoint junction with the
    radiator.  `_segs` sizes each wire independently with a hard floor of 7
    segments, so a short second conductor ends up with segments far shorter
    than the radiator's — and the mismatch lands exactly on the segment the
    EX card feeds, which is the worst place for it in NEC-2 (the guideline is
    <=2:1 between adjacent segments).  Deriving both counts from one target
    length keeps the junction matched.
    """
    if seg_len_m <= 0.0:
        return max(1, min_segs)
    n = max(int(min_segs), int(round(length_m / seg_len_m)))
    return n if n % 2 == 1 else n + 1


def junction_seg_len_m(wire_len_m: float, highest_freq_mhz: float,
                       segs_per_half_wave: Optional[int] = None) -> float:
    """Segment length of the radiator — the reference for every other wire."""
    n = _segs(wire_len_m, highest_freq_mhz, segs_per_half_wave)
    return (wire_len_m / n) if n else 0.0


def estimated_imp_uncertainty_pct(segs_per_half_wave: Optional[int] = None) -> float:
    """Estimated segmentation error on R, in percent, for a given density.

    Derived from the measured convergence table above (≈14 % at 21 segments per
    half wave).  This is a rough scale, not a bound: it exists so the report
    can state the precision it actually has instead of printing 0.1 Ω.
    """
    spw = int(segs_per_half_wave or SEGS_PER_HALF_WAVE)
    spw = max(5, min(spw, SEGS_PER_HALF_WAVE_MAX))
    return max(SEGS_UNCERTAINTY_FLOOR_PCT, SEGS_UNCERTAINTY_K / float(spw))


def convergence_x_tol_ohm(z_mag_ohm: float) -> float:
    """Tolerance on the segmentation drift of X, in ohm, for a given |Z|.

    Absolute floor OR a fraction of |Z|, whichever is larger — see the comment
    on CONVERGENCE_X_TOL_OHM_MIN.  X is checked in ohm, not in percent of R:
    a reactance drifting 300 ohm is a broken matching network whether R is
    50 ohm or 3700 ohm.
    """
    z = abs(float(z_mag_ohm or 0.0))
    return max(CONVERGENCE_X_TOL_OHM_MIN, CONVERGENCE_X_TOL_Z_PCT * z / 100.0)


def imp_uncertainties(conv_report: Optional["ConvergenceReport"],
                      segs_per_half_wave: Optional[int],
                      R_ohm: float) -> Tuple[float, Optional[float]]:
    """Absolute uncertainties to publish alongside one NEC2 impedance.

    Returns ``(u_R_ohm, u_X_ohm)``.  ``u_X_ohm`` is None when no --converge
    measurement exists: the estimated percentage is a model of the R drift
    only, and reusing it for X understates the real X drift by roughly an
    order of magnitude (measured: 304 ohm of drift published as +/-37 ohm).
    In that case X is printed bare, with a note saying so.
    """
    if conv_report is not None:
        u_r_pct = conv_report.r_uncertainty_pct()
        u_x = conv_report.x_uncertainty_ohm()
    else:
        u_r_pct = estimated_imp_uncertainty_pct(segs_per_half_wave)
        u_x = None
    return abs(float(R_ohm)) * u_r_pct / 100.0, u_x


def fmt_imp_with_unc(value: float, unc_abs: Optional[float],
                     signed: bool = False) -> str:
    """Format an impedance value rounded to the scale of its uncertainty.

    302.68 Ω ± 24 Ω → "303 ±24".  Printing 302.7 when the segmentation error
    is ±24 Ω is false precision; this keeps the digits that mean something.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    u = abs(float(unc_abs)) if unc_abs is not None else 0.0
    if u <= 0.0:
        return f"{value:+.1f}" if (signed or value < 0) else f"{value:.1f}"
    if u >= 10.0:
        return f"{value:+.0f} ±{u:.0f}" if signed else f"{value:.0f} ±{u:.0f}"
    if u >= 1.0:
        return f"{value:+.1f} ±{u:.1f}" if signed else f"{value:.1f} ±{u:.1f}"
    return f"{value:+.2f} ±{u:.2f}" if signed else f"{value:.2f} ±{u:.2f}"



def _cp_end_z(
    wire_height_m: float,
    cp_end_height_m: Optional[float],
    cp_height_m: Optional[float] = None,
    wire_radius_m: float = WIRE_RADIUS_M,
) -> float:
    """
    Resolve the requested far-end height of the counterpoise.

    Priority:  explicit cp_end_height_m  →  cp_height_m  →  wire_height_m.

    The radiator and the counterpoise hang from the same feedpoint, so they
    always share one antenna height; cp_height_m is kept only for callers that
    still pass a stored value, and when it is absent (or zero) the far end
    simply sits level with the antenna, giving a horizontal counterpoise.

    The result is clamped to [wire_radius_m, wire_height_m]:
      • NEC2 needs every wire end at z ≥ the wire radius (never exactly 0).
      • A far end above the feedpoint is not supported by this single-mast model,
        so it is levelled to the feedpoint height (→ horizontal counterpoise).
    """
    if cp_end_height_m is not None:
        z = cp_end_height_m
    elif cp_height_m:
        z = cp_height_m
    else:
        z = wire_height_m
    z = float(z)
    z = max(z, wire_radius_m)
    z = min(z, wire_height_m)
    return z


def _cp_geometry(
    cp_len_m: float,
    wire_height_m: float,
    cp_end_z_m: float,
) -> tuple:
    """
    Counterpoise geometry, defined exactly like the sloping radiator: the wire
    is a single straight run from the feedpoint (0, 0, wire_height_m) to a far
    end at z = cp_end_z_m, laid out along -x.

        drop  = wire_height_m - cp_end_z_m          (vertical fall)
        x_end = sqrt(cp_len_m² - drop²)              (horizontal reach)

    If the counterpoise is too short to reach the requested far-end height
    (cp_len_m <= drop) it simply hangs vertically from the feedpoint and its
    far end stops at z = wire_height_m - cp_len_m.  This keeps every point of
    the search grid valid instead of discarding short candidates.

    Returns (vert_len, horiz_rem, cp_bottom_z, x_end, z_end) for backwards
    compatibility with the callers.  The wire is always a single segment, so
    vert_len and horiz_rem are always 0.0 and cp_bottom_z == z_end.
    """
    drop = wire_height_m - cp_end_z_m

    if drop <= 1e-9:
        # Far end at (or above) the feedpoint → horizontal counterpoise
        return 0.0, 0.0, wire_height_m, cp_len_m, wire_height_m

    if cp_len_m <= drop:
        # Too short to reach the target height — hangs straight down
        z_end = wire_height_m - cp_len_m
        return 0.0, 0.0, z_end, 0.0, z_end

    x_end = math.sqrt(max(0.0, cp_len_m ** 2 - drop ** 2))
    return 0.0, 0.0, cp_end_z_m, x_end, cp_end_z_m


def _cp_angle_from_geometry(
    x_end: float,
    wire_height_m: float,
    z_end: float,
) -> float:
    """
    Angle of the counterpoise measured from the vertical, in degrees
    (0° = hanging straight down, 90° = horizontal).  Derived from the
    geometry — it is reported, never entered by the user.
    """
    drop = wire_height_m - z_end
    return math.degrees(math.atan2(abs(x_end), drop)) if (abs(x_end) or drop) else 0.0

# ═══════════════════════════════════════════════════════════════════════════
# GROUND CLEARANCE + DECK GEOMETRY (single source of truth for all decks)
# ═══════════════════════════════════════════════════════════════════════════

class NoReturnPathError(ValueError):
    """Raised when a counterpoise-less deck is requested with no return path."""


def lambda_max_m(freqs_mhz: List[float]) -> float:
    """Free-space wavelength at the LOWEST frequency of the deck, in metres."""
    f_lo = min([f for f in freqs_mhz if f > 0.0], default=0.0)
    return (C_MHZ / f_lo) if f_lo > 0.0 else 0.0


def ground_clearance_floor_m(freqs_mhz: List[float]) -> float:
    """Minimum height above ground allowed for any wire end (0.05·λ_max)."""
    return GROUND_CLEAR_FRAC_SAFE * lambda_max_m(freqs_mhz)


def ground_clearance_hard_min_m(freqs_mhz: List[float]) -> float:
    """Height below which NEC-2 results are considered invalid (0.02·λ_max)."""
    return GROUND_CLEAR_FRAC_HARD * lambda_max_m(freqs_mhz)


class FeedpointHeightError(ValueError):
    """Raised when the requested feedpoint height cannot be simulated."""


def validate_feedpoint_height(
    wire_height_m: float,
    freqs_mhz: List[float],
    ground_model: str = DEFAULT_GROUND_MODEL,
) -> float:
    """
    Validate the feedpoint height — the one wire end that must never be moved.

    Both wires start at the feedpoint and the EX source sits on the first
    segment of wire 1, so silently raising it would simulate a different
    antenna than the one the user asked about.  Therefore:

      • a height below ground (z < 0) is always rejected;
      • over a Sommerfeld-Norton ground (GN 2) a height inside the 0.02·λ
        singularity is rejected as well — nec2c reports no error there, it
        just returns impedances that look plausible and are not;
      • over a perfect ground (GN 1) z=0 is a legal galvanic connection, so
        only the negative case is rejected.

    Returns the validated height.
    """
    z = float(wire_height_m)
    if not math.isfinite(z):
        raise FeedpointHeightError("Feedpoint height must be a finite number.")
    if z < 0.0:
        raise FeedpointHeightError(
            f"Feedpoint height {z:.3f} m is below ground: the antenna must be "
            f"at or above z=0."
        )
    if ground_model == "perfect":
        return z
    hard_m = ground_clearance_hard_min_m(freqs_mhz)
    if z < hard_m:
        raise FeedpointHeightError(
            f"Feedpoint height {z:.3f} m is below {GROUND_CLEAR_FRAC_HARD:.2f}·λ "
            f"({hard_m:.2f} m at the lowest band): NEC-2's Sommerfeld-Norton "
            f"ground is singular there and nec2c returns no error, only invalid "
            f"impedances.  Raise the antenna, or use --ground-model perfect if a "
            f"galvanic ground connection is intended."
        )
    return z


@dataclass
class DeckGeometry:
    """Resolved geometry + NEC cards shared by every deck writer."""
    gw_lines:    List[str] = field(default_factory=list)
    comments:    List[str] = field(default_factory=list)
    warnings:    List[str] = field(default_factory=list)
    ge_flag:     int   = 1
    gn_line:     str   = ""
    ex_line:     str   = "EX 0 1 1 0 1.0 0.0\n"
    ok:          bool  = True          # False → NEC2 result must not be trusted
    # Radiator
    z_near:      float = DEFAULT_HEIGHT_M
    z_far:       float = DEFAULT_HEIGHT_M
    x_far:       float = 0.0
    # Counterpoise / return conductor
    return_kind: str   = "counterpoise"   # counterpoise | ground-rod | coax-stub
    cp_x_end:    Optional[float] = None
    cp_z_end:    Optional[float] = None
    cp_angle_deg: float = 0.0
    segs_cp:     int = 0   # segments actually written on the GW 2 card
    cp_len_deck_m: float = 0.0   # straight-line length of the GW 2 card as written
    # Bookkeeping
    segs_per_half_wave: int = SEGS_PER_HALF_WAVE
    ground_model: str  = DEFAULT_GROUND_MODEL
    clearance_floor_m: float = 0.0
    seg_len_ref_m: float = 0.0        # radiator segment length at the junction


def build_deck_geometry(
    wire_len_m: float,
    cp_len_m: float,
    freqs_mhz: List[float],
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,
    cp_height_m: Optional[float] = None,
    cp_end_height_m: Optional[float] = None,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,
) -> DeckGeometry:
    """
    Resolve the complete NEC-2 geometry (GW/GE/GN/EX cards) for one candidate.

    This is the ONLY place where geometry is turned into NEC cards; the sweep
    deck, the best-antenna deck and the radiation-pattern deck all call it, so
    they can never drift apart.

    Two physical rules are enforced here:

    1. A counterpoise-less antenna still needs a RETURN CONDUCTOR.  NEC-2 has
       no implicit ground/feedline return: a wire fed at its absolute end with
       nothing else in the model is an open circuit (kilo-ohms of R and huge
       −jX), not an end-fed antenna.  `no_cp_return` selects the model:
         • ground-rod : vertical conductor feedpoint → z=0 over GN 1 ground
         • coax-stub  : short vertical stub (coax braid / common-mode path)
         • reject     : raise NoReturnPathError
    2. No wire end may approach the Sommerfeld-Norton ground.  Every end is
       clamped to 0.05·λ at the lowest frequency; a request below 0.02·λ also
       clears `ok`, so the candidate is not scored as valid NEC-2 data.
       Under `ground_model="perfect"` (GN 1) the restriction does not apply:
       ends at or below the floor are snapped to exactly z=0, which is the
       correct NEC-2 idiom for a galvanic ground connection.
    """
    g = DeckGeometry()
    g.ground_model = ground_model if ground_model in GROUND_MODEL_CHOICES else DEFAULT_GROUND_MODEL
    spw = int(segs_per_half_wave or SEGS_PER_HALF_WAVE)
    spw = max(5, min(spw, SEGS_PER_HALF_WAVE_MAX))
    g.segs_per_half_wave = spw
    highest_f = max(freqs_mhz)
    floor_m   = ground_clearance_floor_m(freqs_mhz)
    hard_m    = ground_clearance_hard_min_m(freqs_mhz)
    g.clearance_floor_m = floor_m

    use_cp = bool(use_counterpoise) and cp_len_m > 1e-9
    if not use_cp:
        cp_len_m = 0.0
        if no_cp_return not in NO_CP_RETURN_CHOICES:
            no_cp_return = DEFAULT_NO_CP_RETURN
        if no_cp_return == "reject":
            raise NoReturnPathError(
                "NEC-2 cannot model a wire fed against nothing: a single wire "
                "with the source on its end segment is an open circuit, not an "
                "end-fed antenna.  Choose a return-path model (ground rod or "
                "coax-braid stub) or run the counterpoise-less antenna in "
                "empirical mode."
            )
        # A ground rod is a galvanic connection to ground: only legal in NEC-2
        # over a perfectly conducting ground.
        if no_cp_return == "ground-rod" and g.ground_model != "perfect":
            g.ground_model = "perfect"
            g.warnings.append(
                "Ground-rod return requires a perfectly conducting ground "
                "(GN 1) — NEC-2 cannot connect a wire to a Sommerfeld-Norton "
                "ground; the ground model was switched to perfect for this deck."
            )
        g.return_kind = no_cp_return
    else:
        g.return_kind = "counterpoise"

    perfect = (g.ground_model == "perfect")

    def _clamp_end(z_req: float, what: str, *, result_is_final: bool = True) -> float:
        """Apply the ground-proximity rule to one wire end.

        `result_is_final` tells the warning text whether the value this
        function returns is actually what ends up on the GW card.  For most
        callers it is: the feedpoint, the radiator far end and the coax-stub
        end all take the return value verbatim.  The counterpoise far end is
        the exception — its target is re-resolved by `_cp_geometry`, which in
        the too-short-to-reach branch ignores the clamped target completely
        and hangs the wire from the feedpoint instead.  Claiming "raised to
        X m" there would describe a value that never reaches the deck, so
        that caller passes result_is_final=False and reports the outcome
        itself once the real resolved end is known.
        """
        z_req = float(z_req)
        if perfect:
            # GN 1: touching ground is exact and legal; snap tiny gaps to 0.
            if z_req <= floor_m:
                if z_req > 1e-9 and result_is_final:
                    g.warnings.append(
                        f"{what}: requested {z_req:.3f} m over a perfectly "
                        f"conducting ground — snapped to z=0.000 m "
                        f"(galvanic ground connection)."
                    )
                return 0.0
            return z_req
        if z_req < hard_m:
            g.ok = False
            if result_is_final:
                g.warnings.append(
                    f"{what}: requested {z_req:.3f} m is below {GROUND_CLEAR_FRAC_HARD:.2f}·λ "
                    f"({hard_m:.2f} m); NEC-2's Sommerfeld-Norton ground is singular there "
                    f"and nec2c reports no error.  Raised to {floor_m:.2f} m and the "
                    f"result is marked UNRELIABLE.  Use --ground-model perfect with the "
                    f"end at z=0 if a real ground connection is intended."
                )
            else:
                g.warnings.append(
                    f"{what}: requested {z_req:.3f} m is below {GROUND_CLEAR_FRAC_HARD:.2f}·λ "
                    f"({hard_m:.2f} m); NEC-2's Sommerfeld-Norton ground is singular there "
                    f"and nec2c reports no error.  The result is marked UNRELIABLE.  Use "
                    f"--ground-model perfect with the end at z=0 if a real ground "
                    f"connection is intended."
                )
            return floor_m
        if z_req < floor_m:
            if result_is_final:
                g.warnings.append(
                    f"{what}: requested {z_req:.3f} m raised to the NEC-2 floor "
                    f"{floor_m:.2f} m ({GROUND_CLEAR_FRAC_SAFE:.2f}·λ at the lowest band)."
                )
            return floor_m
        return z_req

    # ── Radiator (Wire 1) ────────────────────────────────────────────────
    # The feedpoint is a wire end too — in fact the one where BOTH wires start
    # and where the source sits.  It is validated, not silently clamped: a
    # height inside the ground singularity (or below ground) is rejected
    # outright, because raising the feed point would answer a question about a
    # different antenna.  Between the hard floor and the safe floor it follows
    # the same rule as every other end: raised to the floor WITH a warning.
    z_near = validate_feedpoint_height(wire_height_m, freqs_mhz, g.ground_model)
    if not perfect and z_near < floor_m:
        z_near = _clamp_end(z_near, "Feedpoint")
    if wire_slope_end_m is not None:
        z_far = _clamp_end(wire_slope_end_m, "Radiator far end")
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

    g.z_near, g.z_far, g.x_far = z_near, z_far, x_far
    segs_ant = _segs(wire_len_m, highest_f, spw)
    # Reference segment length at the feedpoint junction: every other wire that
    # meets wire 1 there is segmented to match it (see _segs_at_length).
    seg_len_ref = (wire_len_m / segs_ant) if segs_ant else 0.0
    g.seg_len_ref_m = seg_len_ref
    g.gw_lines.append(
        f"GW 1 {segs_ant} 0.0 0.0 {z_near:.3f} "
        f"{x_far:.3f} 0.0 {z_far:.4f} {wire_radius_m:.5f}\n"
    )
    g.comments.append(f"CM Wire length: {wire_len_m:.3f} m")
    g.comments.append(
        f"CM Segmentation: {spw} segments per half wave "
        f"(estimated impedance uncertainty ~{estimated_imp_uncertainty_pct(spw):.0f}% of R)"
    )
    if wire_slope_end_m is not None:
        g.comments.append(f"CM Wire slope end z: {z_far:.4f} m")

    # ── Second conductor: counterpoise or return path ────────────────────
    if use_cp:
        # BOTH wires start at the feedpoint, so the counterpoise must be built
        # from the RESOLVED feedpoint height `z_near`, never from the requested
        # `wire_height_m`.  When the soft ground-clearance clamp above raises
        # the feedpoint, using the requested height here writes the GW 2 card
        # at a different z than the GW 1 card: the two wires then share no node,
        # the EX source sits on a free end, and nec2c happily returns the
        # impedance of an open circuit (huge −jX) without reporting an error.
        cp_z_target = _cp_end_z(z_near, cp_end_height_m, cp_height_m, wire_radius_m)
        cp_z_target = _clamp_end(cp_z_target, "Counterpoise far end", result_is_final=False)
        _cvl, _chr, _cbot, cp_x_end, cp_z_end = _cp_geometry(
            cp_len_m, z_near, cp_z_target)
        # The far end is clamped ONCE, on the TARGET, before the geometry is
        # resolved.  Clamping the resolved end a second time moved it without
        # touching cp_x_end, silently changing the modelled wire length: over a
        # perfect ground the clamp snaps to z=0, which turned a 6.5 m hanging
        # counterpoise into an 8.0 m grounded vertical.
        #
        # The second clamp is also unnecessary.  _cp_geometry only lowers the
        # end below the target in the vertical-hang branch, and that branch
        # requires cp_len <= drop = wire_height - target, so the resolved end
        # is >= target, which is already at or above the floor.  The check
        # below is a safety net, not a correction: it flags the candidate
        # instead of reshaping it.
        if not perfect and cp_z_end < hard_m:
            g.ok = False
            g.warnings.append(
                f"Counterpoise far end resolved to {cp_z_end:.3f} m, below "
                f"{GROUND_CLEAR_FRAC_HARD:.2f}·lambda ({hard_m:.2f} m); NEC-2's "
                f"Sommerfeld-Norton ground is singular there and the result is "
                f"marked UNRELIABLE.  The geometry is left untouched so the "
                f"modelled wire keeps the length being optimised."
            )
        g.cp_angle_deg = _cp_angle_from_geometry(cp_x_end, z_near, cp_z_end)
        g.cp_x_end, g.cp_z_end = cp_x_end, cp_z_end
        cp_x_neg = -cp_x_end if cp_x_end > 1e-9 else 0.0
        # Segment the counterpoise to the radiator's segment length: it shares
        # the fed junction with wire 1 (see _segs_at_length).  The length used
        # is the one actually written on the GW card, not the requested one.
        _cp_len_deck = math.hypot(cp_x_end, z_near - cp_z_end)
        segs_cp = _segs_at_length(_cp_len_deck, seg_len_ref)
        g.segs_cp = segs_cp
        g.cp_len_deck_m = _cp_len_deck
        g.gw_lines.append(
            f"GW 2 {segs_cp} 0.0 0.0 {z_near:.3f} "
            f"{cp_x_neg:.3f} 0.0 {cp_z_end:.4f} {wire_radius_m:.5f}\n"
        )
        g.comments.append(
            f"CM Counterpoise: {cp_len_m:.3f} m  feed z={z_near:.3f} m -> "
            f"end z={cp_z_end:.4f} m  (reach {cp_x_end:.3f} m, "
            f"{g.cp_angle_deg:.1f} deg from vertical)"
        )
        if cp_z_target >= z_near - 1e-9:
            g.comments.append("CM WARNING: CP end height >= wire height; CP placed at wire height (horizontal).")
        if cp_len_m <= z_near - cp_z_target:
            g.comments.append("CM WARNING: CP too short to reach the requested end height; it hangs vertically.")

    elif g.return_kind == "ground-rod":
        # Vertical conductor from the feedpoint down to the earth stake at z=0.
        rod_len = max(0.0, z_near)
        if rod_len < wire_radius_m:
            raise FeedpointHeightError(
                f"Ground-rod return requires the feedpoint to be strictly "
                f"above z=0: at z={z_near:.4f} m the rod length ({rod_len:.4f} m) "
                f"collapses to less than the wire radius ({wire_radius_m:.5f} m), "
                f"which NEC-2 cannot model as a wire (a GW card with coincident "
                f"endpoints is a zero-length-segment geometry error).  Raise the "
                f"feedpoint above ground, or choose a different return-path "
                f"model (coax-stub) for a feedpoint at z=0."
            )
        segs_rod = _segs_at_length(rod_len, seg_len_ref)
        g.cp_x_end, g.cp_z_end, g.cp_angle_deg = 0.0, 0.0, 0.0
        g.gw_lines.append(
            f"GW 2 {segs_rod} 0.0 0.0 {z_near:.3f} "
            f"0.0 0.0 0.0 {wire_radius_m:.5f}\n"
        )
        g.comments.append(
            f"CM Return path: GROUND ROD — vertical conductor {rod_len:.3f} m "
            f"from the feedpoint to z=0 (perfect ground, GN 1)"
        )

    elif g.return_kind == "coax-stub":
        # Short vertical stub standing in for the coax braid / common-mode path.
        stub_len = max(0.0, float(cp_stub_len_m))
        z_stub   = z_near - stub_len
        if z_stub < (0.0 if perfect else floor_m):
            z_stub = _clamp_end(z_stub, "Coax-braid stub end")
            stub_len = z_near - z_stub
            g.warnings.append(
                f"Coax-braid stub shortened to {stub_len:.3f} m to keep its end "
                f"clear of ground."
            )
        segs_stub = _segs_at_length(max(stub_len, 1e-3), seg_len_ref)
        g.cp_x_end, g.cp_z_end, g.cp_angle_deg = 0.0, z_stub, 0.0
        g.gw_lines.append(
            f"GW 2 {segs_stub} 0.0 0.0 {z_near:.3f} "
            f"0.0 0.0 {z_stub:.4f} {wire_radius_m:.5f}\n"
        )
        g.comments.append(
            f"CM Return path: COAX-BRAID STUB — vertical {stub_len:.3f} m from the "
            f"feedpoint down to z={z_stub:.4f} m (common-mode path)"
        )
    else:
        g.comments.append("CM Counterpoise: NONE (antenna without counterpoise)")

    # ── Structural invariant: every conductor starts at the feed node ─────
    # The EX card excites segment 1 of wire 1, i.e. the feedpoint.  If wire 2
    # does not start at EXACTLY the same coordinates, NEC-2 builds two disjoint
    # structures, the source sits on a free end and nec2c returns the impedance
    # of an open circuit (hundreds of ohms of R, tens of kilo-ohms of −jX)
    # without printing a single error.  Nothing downstream can detect that, so
    # the deck is rejected here instead of being simulated.
    if len(g.gw_lines) > 1:
        _feed_node = g.gw_lines[0].split()[3:6]
        for _card in g.gw_lines[1:]:
            if _card.split()[3:6] != _feed_node:
                raise ValueError(
                    "internal geometry error: conductor "
                    f"'{_card.strip()}' does not start at the feedpoint "
                    f"({' '.join(_feed_node)}); the deck would be an open "
                    "circuit at the source."
                )

    # ── Ground / excitation cards ────────────────────────────────────────
    g.ge_flag = 1   # ground plane present; required for the GN card to apply
    if perfect:
        g.gn_line = "GN 1\n"
        g.comments.append("CM Ground model: PERFECT (GN 1)")
    else:
        g.gn_line = f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n"
        g.comments.append(
            f"CM Ground model: Sommerfeld-Norton (GN 2), eps={ground_diel:.1f} "
            f"sigma={ground_cond:.4f} S/m; wire-end floor {floor_m:.2f} m"
        )
    g.ex_line = "EX 0 1 1 0 1.0 0.0\n"
    return g


def cm_cards(text: str, tag: str = "CM", width: int = 70) -> List[str]:
    """Split one comment into legal NEC-2 CM cards.

    NEC-2 reads cards from a fixed-size buffer: a long comment spills onto a
    second line that no longer starts with CM, and nec2c then aborts the whole
    deck with "INCORRECT LABEL FOR A COMMENT CARD".  Non-ASCII characters are
    transliterated for the same reason — the card reader is byte-oriented.
    """
    body = (text or "")
    for _src, _dst in (("\u2014", "-"), ("\u2013", "-"), ("\u2192", "->"),
                       ("\u03bb", "lambda"), ("\u2265", ">="), ("\u2264", "<="),
                       ("\u00b7", "."), ("\u00b0", " deg"), ("\u00b1", "+/-"),
                       ("\u03c3", "sigma"), ("\u03b5", "eps"), ("\u00bd", "1/2")):
        body = body.replace(_src, _dst)
    body = body.encode("ascii", "replace").decode("ascii")
    if body.startswith(tag + " "):
        body = body[len(tag) + 1:]
    body = body.strip()
    if not body:
        return [tag]
    out: List[str] = []
    line = ""
    for word in body.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(f"{tag} {line}")
            line = word
        else:
            line = f"{line} {word}".strip()
        while len(line) > width:            # single word longer than the card
            # Reserve one column for a trailing hyphen so the split is visibly
            # a continuation rather than a silent mid-word truncation.
            out.append(f"{tag} {line[:width - 1]}-")
            line = line[width - 1:]
    if line:
        out.append(f"{tag} {line}")
    return out


def ld_card(conductivity: Optional[float] = None) -> str:
    """
    LD card giving every segment of the structure a finite wire conductivity.

    `LD 5 0 0 0 σ µr` — type 5 is "wire conductivity, mhos/metre"; ITAG 0 with
    both segment numbers 0 applies it to the whole structure, so it covers the
    radiator, the counterpoise and whatever return conductor the geometry
    builder emitted.  Returns "" for a non-positive conductivity, which is the
    lossless (perfect-conductor) case and simply writes no card.

    The trailing µr field is written for card-format completeness only: nec2c
    (calculations.c, load(), case 6) reads just F1/conductivity for type-5
    cards and discards F2/permeability, so WIRE_REL_PERMEABILITY has no effect
    on the simulated result under nec2c. Relative permeability on wire loads
    is a NEC-4 feature.
    """
    s = WIRE_CONDUCTIVITY if conductivity is None else float(conductivity)
    if not (s and s > 0.0 and math.isfinite(s)):
        return ""
    return f"LD 5 0 0 0 {s:.4E} {WIRE_REL_PERMEABILITY:.1f}\n"


def write_nec_deck(
    nec_path: str,
    wire_len_m: float,
    cp_len_m: float,
    freqs_mhz: List[float],
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,  # None → horizontal (z_far = wire_height_m)
    cp_height_m: Optional[float] = None,   # None → = wire_height_m
    cp_end_height_m: Optional[float] = None,   # None → level with wire_height_m
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,
    rp_freqs_mhz: Optional[List[float]] = None,
    rp_n_theta: int = RP_RERANK_N_THETA,
    rp_n_phi:   int = RP_RERANK_N_PHI,
    wire_conductivity: Optional[float] = None,  # None → WIRE_CONDUCTIVITY
) -> DeckGeometry:
    """
    Write a minimal NEC2 input deck for an end-fed long wire with one
    counterpoise wire, and return the resolved DeckGeometry.

    `rp_freqs_mhz` selects the frequencies that additionally get an RP
    pattern card.  It is None for the impedance-only sweep (RP costs time
    and the sweep does not need it) and is set by the radiation re-ranking
    pass, which DOES need gain and take-off angle to score a candidate.

    Geometry, ground model and return path are all resolved by
    build_deck_geometry(); this function only serialises the cards.  The
    returned object carries `ok` (False when the geometry sits too close to
    the NEC-2 ground to be trusted) and `warnings`, which the caller must
    propagate to the candidate result instead of scoring the run blindly.

    Wire geometry (antenna, Wire 1):
      Horizontal (wire_slope_end_m is None):
        z = wire_height_m throughout; x = 0 .. wire_len_m
      Sloping (wire_slope_end_m is not None):
        Near end (feedpoint): x=0, z=wire_height_m
        Far end             : x=h_proj, z=wire_slope_end_m (clamped, see below)

    Counterpoise (Wire 2): the same construction mirrored along −x.  When the
    counterpoise is disabled, Wire 2 becomes the RETURN CONDUCTOR selected by
    `no_cp_return` (ground rod or coax-braid stub) — a fed wire with no return
    conductor is an open circuit in NEC-2, not an antenna.

    Source (EX): first segment of Wire 1 (the near/feedpoint end).
    """
    geo = build_deck_geometry(
        wire_len_m=wire_len_m,
        cp_len_m=cp_len_m,
        freqs_mhz=freqs_mhz,
        wire_height_m=wire_height_m,
        wire_slope_end_m=wire_slope_end_m,
        cp_height_m=cp_height_m,
        cp_end_height_m=cp_end_height_m,
        ground_cond=ground_cond,
        ground_diel=ground_diel,
        wire_radius_m=wire_radius_m,
        use_counterpoise=use_counterpoise,
        no_cp_return=no_cp_return,
        cp_stub_len_m=cp_stub_len_m,
        ground_model=ground_model,
        segs_per_half_wave=segs_per_half_wave,
    )

    with open(nec_path, "w") as fh:
        fh.write("CM NEC2 Long Wire Optimizer Deck\n")
        for c in geo.comments:
            for _card in cm_cards(c.rstrip("\n")):
                fh.write(_card + "\n")
        for w in geo.warnings:
            for _card in cm_cards("WARNING: " + w):
                fh.write(_card + "\n")
        fh.write("CE\n")
        for gw in geo.gw_lines:
            fh.write(gw)
        fh.write(f"GE {geo.ge_flag}\n")
        fh.write(ld_card(wire_conductivity))
        fh.write(geo.gn_line)
        fh.write(geo.ex_line)

        _rp_set = set()
        if rp_freqs_mhz:
            _rp_set = {round(float(f), 4) for f in rp_freqs_mhz}
        _d_theta = 90.0  / max(1, rp_n_theta - 1)
        _d_phi   = 360.0 / max(1, rp_n_phi)

        for f in freqs_mhz:
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            # RP itself triggers execution (writes RADIATION PATTERN together with
            # ANTENNA INPUT PARAMETERS for this FR block). An XQ after RP would
            # re-solve the structure a second time (two MATRIX TIMING entries per
            # frequency instead of one), so XQ is only written when no RP is
            # requested for this frequency — that's the impedance-only case.
            if round(f, 4) in _rp_set:
                fh.write(
                    f"RP 0 {rp_n_theta} {rp_n_phi} 1000 "
                    f"0.0 0.0 {_d_theta:.4f} {_d_phi:.4f} 0.0\n"
                )
            else:
                fh.write("XQ\n")
        fh.write("EN\n")

    return geo


# ═══════════════════════════════════════════════════════════════════════════
# RUN NEC2C
# ═══════════════════════════════════════════════════════════════════════════

def run_nec2c(binary: str, nec_path: str, out_path: str,
              timeout: int = 60) -> bool:
    """
    Run the NEC2 engine, auto-adapting the command-line syntax:

      • nec2c (classic):  nec2c -i INPUT -o OUTPUT
      • onec  (OpenNEC):  onec -o OUTPUT INPUT

    Returns True on success, False on failure.
    """
    kind = _nec2_engine_kind(binary)
    if kind == "onec":
        cmd = [binary, "-o", out_path, nec_path]
    else:
        cmd = [binary, "-i", nec_path, "-o", out_path]

    try:
        result = subprocess.run(
            cmd,
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
    # Derived from the geometry (feedpoint height, CP far-end height, CP length).
    # Reported for information only — it is no longer an input.
    cp_angle_deg: float = 0.0

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

    # ── Radiation performance (filled only by the pattern re-ranking pass) ──
    # band_gain_max : peak gain of the whole hemisphere, dBi
    # band_toa      : elevation of that peak, degrees above the horizon
    # band_gain_toa : gain at the TARGET take-off angle, dBi — this is what the
    #                 score uses, because the peak alone says nothing about
    #                 whether the power goes where the user wants it.
    band_gain_max: Dict[str, float] = field(default_factory=dict)
    band_toa:      Dict[str, float] = field(default_factory=dict)
    band_gain_toa: Dict[str, float] = field(default_factory=dict)
    gain_toa_mean: Optional[float] = None   # mean of band_gain_toa (active bands)
    toa_worst_deg: Optional[float] = None   # highest (worst) TOA across active bands
    pattern_ok:    bool  = False            # True once pattern data was obtained
    score_gain:    float = 0.0              # −gain_weight × gain_toa_mean
    # Final ordering key.  Equals score_combined until the radiation pass runs.
    score_final:   float = 999.0

    # nec2_used:  a NEC2 run happened and supplied at least one band's
    #             impedance (independent of whether that data is trustworthy).
    # nec2_ok:    the NEC2 result, if any, is trustworthy — cleared when the
    #             geometry sits inside the ground singularity, when a band
    #             fell back to the empirical model under --strict, or when
    #             the run failed outright. This is the field ranking/Pareto
    #             use to decide which candidates may win.
    nec2_used:  bool = True
    nec2_ok:    bool = True
    note:       str  = ""

    # Sloping wire: z of the far (non-feedpoint) end; None = horizontal wire
    wire_slope_end_m: Optional[float] = None

    # Counterpoise: z actually reached by its far (non-feedpoint) end, and the
    # horizontal distance from the mast to that end.
    cp_end_z_m: Optional[float] = None
    cp_reach_m: Optional[float] = None

    # Segmentation density (segments per half wave) that produced these
    # impedances, and the measured convergence drift when --converge ran.
    segs_per_half_wave: Optional[int] = None
    conv_r_drift_pct: Optional[float] = None   # |R(spw) − R(finest)| / R(finest)
    conv_x_drift_ohm: Optional[float] = None   # |X(spw) − X(finest)|, worst band


def _vswr_score_single(vswr: float) -> float:
    """
    Map a VSWR value to a penalty score:
      ≤1.5 → 0, ≤3.0 → linear 0–1, ≤6.0 → linear 1–3, >6 → 3 + log

    The ≤6.0 segment starts at 1.0 (score at vswr=3.0) and must add up to
    exactly 3.0 by vswr=6.0, i.e. it must add 2.0 over that span:
      1.0 + (vswr - 3.0) / 1.5  at vswr=6.0  →  1.0 + (6.0 - 3.0) / 1.5
        = 1.0 + 3.0 / 1.5 = 1.0 + 2.0 = 3.0 ✓
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
    run: Optional[NEC2Run] = None,     # NEC2 run for this candidate, if available
    cp_angle_deg: float = 0.0,         # derived from geometry; informational
    cp_end_z_m: Optional[float] = None,
    cp_reach_m: Optional[float] = None,
    nec2_strict: bool = False,
) -> CandidateResult:
    """
    Compute the aggregate quality score for a candidate geometry.

    VSWR scoring: active bands only (as selected by --active-bands).
    Avoidance scoring: ALL defined bands, regardless of the active flag.

    If NEC2 run results are provided they are used; otherwise the empirical
    formulas are used as a fast fallback — UNLESS nec2_strict=True, in which
    case any band whose frequency is not found in the NEC2 output is marked
    as failed (VSWR=999, nec2_ok=False) rather than silently falling back.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        raise ValueError("No active bands defined")

    res = CandidateResult(wire_len_m=wire_len_m, cp_len_m=cp_len_m,
                          cp_angle_deg=cp_angle_deg,
                          cp_end_z_m=cp_end_z_m,
                          cp_reach_m=cp_reach_m,
                          nec2_used=(run is not None),
                          nec2_ok=(run is not None))

    # Surface parser-level diagnostics (e.g. the ANTENNA INPUT PARAMETERS
    # block-count mismatch or duplicate-impedance heuristic in
    # parse_nec2_output) so a candidate that got wiped out to NaN/VSWR-999
    # shows *why* instead of just silently vanishing from the ranking.
    if run is not None and getattr(run, "note", ""):
        res.note = (res.note + " " + run.note).strip()

    vswr_penalties = []
    avoidances = []

    # ── VSWR scoring: ACTIVE bands only ────────────────────────────────
    for cr in active:
        freq = cr.freq_mhz

        best_vswr = None
        best_R: Optional[float] = None
        best_X: Optional[float] = None
        imp_src = "empirical"

        if run is not None:
            fmap = run.freq_map()
            if fmap:
                key = min(fmap.keys(), key=lambda k: abs(k - freq))
                _tol = freq_match_tol_mhz(freq)
                # parse_nec2_output() deliberately writes R = X = NaN (and
                # vswr50 = 999, plus the reason in run.note) when it detects a
                # bad block split.  A NaN impedance is NOT NEC2 data, so it
                # must not be consumed here: math.hypot() would yield a NaN
                # reflection coefficient, `nan < 1` is False, and the result
                # would silently degrade to VSWR 999 while still being stamped
                # imp_src="NEC2" / nec2_ok=True — leaving a failed parse
                # eligible for pareto_front() and presented by the report as
                # trustworthy.  Treat it exactly like a missing frequency: fall
                # through to the strict (NEC2-MISS) or empirical branch below,
                # both of which clear nec2_ok.
                if (abs(key - freq) <= _tol
                        and not math.isnan(fmap[key].R_ohm)
                        and not math.isnan(fmap[key].X_ohm)):
                    fp = fmap[key]
                    R_ant, X_ant = fp.R_ohm, fp.X_ohm
                    # An n:1 impedance transformer scales BOTH R and X by 1/n
                    if unun_ratio > 1.0:
                        R_in = R_ant / unun_ratio
                        X_in = X_ant / unun_ratio   # X must also be divided by n
                    else:
                        R_in, X_in = R_ant, X_ant
                    g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
                    best_vswr = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
                    best_R, best_X = R_ant, X_ant
                    imp_src = "NEC2"

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
                best_X = -1500.0 * math.sin(2.0 * arg)
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
        if imp_src == "NEC2":
            res.band_cp_src[cr.band] = "NEC2"
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
    inactive = [r for r in calc_rows if not r.active]
    for cr in inactive:
        if cr.band in res.band_R_ant:
            continue
        freq = cr.freq_mhz
        found_R: Optional[float] = None
        found_X: Optional[float] = None
        found_src = "empirical"
        if run is not None:
            fmap = run.freq_map()
            if fmap:
                key = min(fmap.keys(), key=lambda k: abs(k - freq))
                _tol = freq_match_tol_mhz(freq)
                # Same NaN guard as the active-band loop above: a wiped-out
                # parse must not be stored as an NEC2 impedance.
                if (abs(key - freq) <= _tol
                        and not math.isnan(fmap[key].R_ohm)
                        and not math.isnan(fmap[key].X_ohm)):
                    fp = fmap[key]
                    found_R, found_X = fp.R_ohm, fp.X_ohm
                    found_src = "NEC2"
        if found_R is None and not nec2_strict:
            lhalf = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio_l = wire_len_m / lhalf if lhalf else 0.0
            arg = math.pi * ratio_l
            cos2 = math.cos(arg) ** 2
            found_R = max(1.0, 50.0 * (80.0 ** cos2))
            found_X = -1500.0 * math.sin(2.0 * arg)
            found_src = "empirical"
        if found_R is not None:
            res.band_R_ant[cr.band]   = round(found_R, 2)
            res.band_X_ant[cr.band]   = round(found_X, 2)
            res.band_imp_src[cr.band] = found_src

    # ── Avoidance score: computed over ALL defined bands ────────────────
    # The metric itself lives in band_avoidance_score(); see there for why only
    # every OTHER λ/4 multiple is a resonance to avoid and why which one it
    # is depends on the transformer ratio.  Range 0…1, so the −0.25 weight
    # and the _avoidance_rating() thresholds carry over unchanged.
    #
    # NOTE: this is ratio-dependent.  Anything that changes `unun_ratio`
    # after the fact MUST recompute it (see _rescore_all()).
    _w = resonance_preference(unun_ratio)
    for cr in calc_rows:
        avoidance = band_avoidance_score(wire_len_m, cr.freq_mhz, unun_ratio,
                                         weights=_w)
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

    # −0.25 (not −0.5) because score_avoidance_active now spans 0…1 instead
    # of the old clamped 0…0.25; the contribution to the ranking is unchanged.
    res.score_combined = (mean_vswr_penalty
                          + 1.5 * worst_vswr_penalty
                          - 0.25 * res.score_avoidance_active
                          - 0.1 * cp_avoid_mean)

    # No pattern data at this stage (the sweep deck carries no RP card), so the
    # final key is the impedance score alone.  evaluate_pattern() adds the
    # radiation term later, for the shortlisted candidates only.
    res.score_gain  = 0.0
    res.score_final = res.score_combined

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
    use_counterpoise: bool = True,
) -> List[Tuple[float, float]]:
    """Return all (wire_len, cp_len) grid combinations to evaluate.

    Points are clamped to [wire_min, wire_max] / [cp_min, cp_max] so that
    non-integer step sizes (e.g. 0.3 m over a 2 m range) never produce
    candidates outside the requested bounds.

    With use_counterpoise=False the counterpoise axis collapses to the single
    value 0.0 m, so only the radiator length is swept.

    An inverted window (min > max) or a non-positive step is a caller error and
    raises ValueError.  Returning an empty list instead would let the run reach
    the output stage with zero candidates, where the plotters and the boundary
    check all assume at least one point exists.
    """
    if wire_step <= 0:
        raise ValueError(f"wire_step must be > 0 (got {wire_step}).")
    if wire_min > wire_max:
        raise ValueError(
            f"Empty radiator search window: wire_min ({wire_min:.3f} m) is "
            f"greater than wire_max ({wire_max:.3f} m)."
        )
    n_w = round((wire_max - wire_min) / wire_step)
    wires = [round(min(wire_min + i * wire_step, wire_max), 3) for i in range(n_w + 1)]

    if not use_counterpoise:
        return [(w, 0.0) for w in wires]

    if cp_step <= 0:
        raise ValueError(f"cp_step must be > 0 (got {cp_step}).")
    if cp_min > cp_max:
        raise ValueError(
            f"Empty counterpoise search window: cp_min ({cp_min:.3f} m) is "
            f"greater than cp_max ({cp_max:.3f} m)."
        )
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
    wire_height_m: float = DEFAULT_HEIGHT_M,
    cp_height_m: Optional[float] = None,   # None → = wire_height_m
    cp_end_height_m: Optional[float] = None,   # None → level with wire_height_m
    wire_slope_end_m: Optional[float] = None,  # None → horizontal
    use_counterpoise: bool = True,
    verbose: bool = False,
) -> List[CandidateResult]:
    if use_counterpoise:
        print(f"\n  {Fore.YELLOW}WARNING: the empirical impedance formulas depend only on "
              f"the radiator length and the frequency — the counterpoise is NOT modelled. "
              f"Every candidate sharing a wire length scores identically on VSWR, so the "
              f"counterpoise length reported by this mode comes from the lambda/4 heuristic "
              f"bonus alone (weight 0.1 out of a scale of ~10), not from any impedance "
              f"calculation. Re-run with --mode nec2 to optimise the counterpoise."
              f"{Style.RESET_ALL}\n")
    if wire_slope_end_m is not None:
        print(f"\n  {Fore.YELLOW}WARNING: --wire-slope-end-height is set but mode is empirical. "
              f"Empirical impedance formulas assume a horizontal wire and will give "
              f"inaccurate results for a sloped geometry. "
              f"Re-run with --mode nec2 for accurate results.{Style.RESET_ALL}\n")
    cp_z_target = _cp_end_z(wire_height_m, cp_end_height_m, cp_height_m, WIRE_RADIUS_M)
    results = []
    total = len(grid)
    for i, (w, c) in enumerate(grid):
        if verbose and i % max(1, total // 20) == 0:
            pct = i * 100 // total
            print(T("sweep_empirical_pct").format(pct, i, total, w, c), end="\r")
        # Geometry is resolved per candidate: the CP angle and reach follow from
        # the CP length and the requested far-end height.
        if use_counterpoise:
            _cvl, _chr, _cbot, _cx, _cz = _cp_geometry(c, wire_height_m, cp_z_target)
            _cang = _cp_angle_from_geometry(_cx, wire_height_m, _cz)
        else:
            c, _cx, _cz, _cang = 0.0, None, None, 0.0
        r = score_candidate(
            w, c, calc_rows, unun_ratio,
            cp_angle_deg=_cang,
            cp_end_z_m=_cz,
            cp_reach_m=_cx,
        )
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
    cp_end_height_m: Optional[float] = None,   # None → level with wire_height_m
    wire_slope_end_m: Optional[float] = None,  # None → horizontal wire
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,
    verbose: bool = True,
) -> List[CandidateResult]:
    """
    Full NEC2 sweep.  For each (wire, cp) pair we run nec2c once on the deck
    built from the requested geometry (radiator far-end height + counterpoise
    far-end height), then score it with the NEC2 impedance data.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        raise ValueError("No active bands defined")
    freqs  = [cr.freq_mhz for cr in calc_rows]   # ALL bands

    # Fail fast: sweeping thousands of decks that all lack a return conductor
    # is never what the user wants.
    if not use_counterpoise and no_cp_return == "reject":
        raise NoReturnPathError(
            "NEC2 mode with --no-counterpoise requires a return-path model "
            "(--no-cp-return ground-rod|coax-stub); NEC-2 cannot feed a wire "
            "against nothing."
        )

    # Fail fast: the feedpoint height applies to every point of the grid, so an
    # unusable height is a run-level error, not thousands of skipped candidates.
    _gm_eff = ("perfect" if (not use_counterpoise and no_cp_return == "ground-rod")
               else ground_model)
    validate_feedpoint_height(wire_height_m, freqs, _gm_eff)

    cp_z_target = _cp_end_z(wire_height_m, cp_end_height_m, cp_height_m, WIRE_RADIUS_M)

    results: List[CandidateResult] = []
    total = len(grid)
    done  = 0
    _warned_geom = False

    with tempfile.TemporaryDirectory(prefix="nec2opt_") as tmpdir:
        for w, c in grid:
            done += 1
            # CP angle and reach are consequences of (cp length, far-end height)
            if use_counterpoise:
                _cvl, _chr, _cbot, _cp_x, _cp_z = _cp_geometry(c, wire_height_m, cp_z_target)
                cp_angle_deg = _cp_angle_from_geometry(_cp_x, wire_height_m, _cp_z)
                angle_label = f"{_cp_z:.2f} m / {cp_angle_deg:.1f}°"
            else:
                c, _cp_x, _cp_z, cp_angle_deg = 0.0, None, None, 0.0
                angle_label = "—"
            if verbose:
                print(T("sweep_nec2_progress").format(done, total, w, c, angle_label), end="\r")

            tag   = (f"w{w:.3f}_c{c:.3f}_e{_cp_z:.3f}" if _cp_z is not None
                     else f"w{w:.3f}_nocp")
            nec_p = os.path.join(tmpdir, tag + ".nec")
            out_p = os.path.join(tmpdir, tag + ".out")

            try:
                _geo = write_nec_deck(
                    nec_path=nec_p,
                    wire_len_m=w,
                    cp_len_m=c,
                    freqs_mhz=freqs,
                    wire_height_m=wire_height_m,
                    wire_slope_end_m=wire_slope_end_m,
                    cp_height_m=cp_height_m,
                    cp_end_height_m=cp_z_target,
                    ground_cond=ground_cond,
                    ground_diel=ground_diel,
                    wire_radius_m=WIRE_RADIUS_M,
                    use_counterpoise=use_counterpoise,
                    no_cp_return=no_cp_return,
                    cp_stub_len_m=cp_stub_len_m,
                    ground_model=ground_model,
                    segs_per_half_wave=segs_per_half_wave,
                )
                # The geometry builder may have clamped a wire end away from
                # the ground singularity.  Report it once, not once per point.
                if _geo.warnings and not _warned_geom:
                    _warned_geom = True
                    print()
                    for _wmsg in _geo.warnings:
                        print(f"  {Fore.YELLOW}WARNING: {_wmsg}{Style.RESET_ALL}")
                # Always report the geometry that ended up in the deck: the
                # builder may have raised a wire end off the ground, and a
                # candidate whose printed end height differs from the simulated
                # one is exactly the kind of silent mismatch this tool exists
                # to avoid.
                if _geo.cp_z_end is not None:
                    _cp_z = _geo.cp_z_end
                    _cp_x = (_geo.cp_x_end if _geo.cp_x_end is not None else _cp_x)
                    cp_angle_deg = _geo.cp_angle_deg
            except ValueError as _geom_err:
                # Wire too short to reach the sloped far-end height — skip silently.
                cand = CandidateResult(
                    wire_len_m=w, cp_len_m=c, cp_angle_deg=cp_angle_deg,
                    score_combined=999.0, score_vswr_raw=999.0,
                    score_vswr=999.0, score_avoidance=0.0,
                    nec2_used=False, nec2_ok=False,
                    note=f"geometry invalid: {_geom_err}",
                    wire_slope_end_m=wire_slope_end_m,
                    cp_end_z_m=_cp_z, cp_reach_m=_cp_x,
                )
                results.append(cand)
                continue

            run: Optional[NEC2Run] = None
            _parse_exc: Optional[BaseException] = None
            if run_nec2c(nec2c_bin, nec_p, out_p):
                try:
                    _r = parse_nec2_output(out_p, debug=False, explicit_nec_path=nec_p)
                    if _r is not None and not _r.freq_map():
                        _r = None
                    run = _r
                except Exception as _e:
                    _parse_exc = _e

            if run is None:
                _note = f"NEC2 failed: parser raised {_parse_exc!r}" if _parse_exc is not None else "NEC2 failed"
                cand = CandidateResult(
                    wire_len_m=w, cp_len_m=c, cp_angle_deg=cp_angle_deg,
                    score_combined=999.0, score_vswr_raw=999.0,
                    score_vswr=999.0, score_avoidance=0.0,
                    nec2_used=False, nec2_ok=False, note=_note,
                    wire_slope_end_m=wire_slope_end_m,
                    cp_end_z_m=_cp_z, cp_reach_m=_cp_x,
                )
                results.append(cand)
            else:
                cand = score_candidate(
                    wire_len_m=w,
                    cp_len_m=c,
                    calc_rows=calc_rows,
                    unun_ratio=unun_ratio,
                    run=run,
                    cp_angle_deg=cp_angle_deg,
                    cp_end_z_m=_cp_z,
                    cp_reach_m=_cp_x,
                    nec2_strict=True,
                )
                cand.wire_slope_end_m = wire_slope_end_m
                cand.segs_per_half_wave = _geo.segs_per_half_wave
                if not _geo.ok:
                    # Geometry sat inside the NEC-2 ground singularity: nec2c
                    # returns numbers without complaining, so flag them here.
                    cand.nec2_ok = False
                    cand.note = (cand.note + " geometry too close to ground "
                                             "(NEC2 result unreliable)").strip()
                results.append(cand)

    if verbose:
        print(T("sweep_nec2_done").format(total))

    return results


# ═══════════════════════════════════════════════════════════════════════════
# RADIATION PERFORMANCE:  GAIN AT THE TARGET TAKE-OFF ANGLE
# ═══════════════════════════════════════════════════════════════════════════

def gain_at_elevation(rp_rows: List[Tuple[float, float, float]],
                      elev_deg: float) -> Optional[float]:
    """
    Best gain (over all azimuths) at a FIXED elevation angle.

    `rp_rows` are (theta_nec, phi, dBi) triples straight from the RP table,
    where theta_nec is measured from the zenith, so the requested elevation
    corresponds to theta = 90 − elev_deg.  For every azimuth the gain is
    linearly interpolated (in dB) between the two theta rows that bracket the
    cut, then the maximum over azimuth is returned — that is the gain the
    station actually gets at that take-off angle if the antenna is pointed
    the right way.  Returns None when there is nothing to interpolate.
    """
    if not rp_rows:
        return None
    theta_cut = 90.0 - float(elev_deg)
    by_phi: Dict[float, List[Tuple[float, float]]] = {}
    for (t, p, db) in rp_rows:
        by_phi.setdefault(round(p, 2), []).append((t, db))

    best: Optional[float] = None
    for _pk, tdb in by_phi.items():
        tdb.sort(key=lambda x: x[0])
        ths = [x[0] for x in tdb]
        dbs = [x[1] for x in tdb]
        if len(ths) == 1:
            val = dbs[0]
        elif theta_cut <= ths[0]:
            val = dbs[0]
        elif theta_cut >= ths[-1]:
            val = dbs[-1]
        else:
            val = float(_np_interp1(theta_cut, ths, dbs))
        if best is None or val > best:
            best = val
    return best


def evaluate_pattern(
    cand: "CandidateResult",
    calc_rows: List[CalcRow],
    nec2c_bin: str,
    wire_height_m: float,
    cp_height_m: Optional[float],
    ground_cond: float,
    ground_diel: float,
    target_toa_deg: float = DEFAULT_TARGET_TOA_DEG,
    gain_weight: float = DEFAULT_GAIN_WEIGHT,
    cp_end_height_m: Optional[float] = None,
    wire_slope_end_m: Optional[float] = None,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,
) -> bool:
    """
    Run one NEC2 deck WITH RP cards for the active bands and fill the
    candidate's radiation fields (peak gain, take-off angle, gain at the
    target take-off angle) and its radiation score term.

    Mutates `cand` in place and returns True when pattern data was obtained.
    """
    active = [cr for cr in calc_rows if cr.active]
    if not active or not nec2c_bin:
        return False
    active_freqs = [cr.freq_mhz for cr in active]

    with tempfile.TemporaryDirectory(prefix="nec2opt_rp_") as td:
        nec_p = os.path.join(td, "pattern.nec")
        out_p = os.path.join(td, "pattern.out")
        try:
            write_nec_deck(
                nec_path=nec_p,
                wire_len_m=cand.wire_len_m,
                cp_len_m=cand.cp_len_m,
                freqs_mhz=active_freqs,
                wire_height_m=wire_height_m,
                wire_slope_end_m=wire_slope_end_m,
                cp_height_m=cp_height_m,
                cp_end_height_m=cp_end_height_m,
                ground_cond=ground_cond,
                ground_diel=ground_diel,
                wire_radius_m=WIRE_RADIUS_M,
                use_counterpoise=use_counterpoise,
                no_cp_return=no_cp_return,
                cp_stub_len_m=cp_stub_len_m,
                ground_model=ground_model,
                segs_per_half_wave=segs_per_half_wave,
                rp_freqs_mhz=active_freqs,
            )
        except ValueError:
            return False

        if not run_nec2c(nec2c_bin, nec_p, out_p, timeout=180):
            return False
        try:
            run = parse_nec2_output(out_p, debug=False, explicit_nec_path=nec_p)
        except Exception as _e:
            cand.note = (cand.note + "; " if cand.note else "") + f"pattern parse raised {_e!r}"
            return False
        if run is None:
            return False

    fmap = run.freq_map()
    if not fmap:
        return False

    got = False
    gains_at_toa: List[float] = []
    for cr in active:
        key = min(fmap.keys(), key=lambda k: abs(k - cr.freq_mhz))
        if abs(key - cr.freq_mhz) > freq_match_tol_mhz(cr.freq_mhz):
            continue
        fp = fmap[key]
        if not fp.rp_rows:
            continue
        got = True
        cand.band_gain_max[cr.band] = round(fp.gain_dbi, 2)
        cand.band_toa[cr.band]      = round(fp.toa_deg, 1)
        g = gain_at_elevation(fp.rp_rows, target_toa_deg)
        if g is not None:
            cand.band_gain_toa[cr.band] = round(g, 2)
            gains_at_toa.append(g)

    if not got:
        return False

    cand.pattern_ok = True
    if gains_at_toa:
        cand.gain_toa_mean = sum(gains_at_toa) / len(gains_at_toa)
        cand.score_gain    = -gain_weight * cand.gain_toa_mean
    if cand.band_toa:
        cand.toa_worst_deg = max(cand.band_toa.values())
    cand.score_final = cand.score_combined + cand.score_gain
    return True


# ═══════════════════════════════════════════════════════════════════════════
# SEGMENTATION CONVERGENCE SELF-CHECK
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ConvergenceRow:
    """One segmentation density of the convergence check, per band."""
    segs_per_half_wave: int = 0
    segs_wire: int = 0
    segs_cp:   int = 0
    seg_len_wire_m: float = 0.0
    seg_len_cp_m:   float = 0.0
    band_R: Dict[str, float] = field(default_factory=dict)
    band_X: Dict[str, float] = field(default_factory=dict)
    ok: bool = True


@dataclass
class ConvergenceReport:
    """Result of re-running the winning geometry at finer segmentation."""
    rows: List[ConvergenceRow] = field(default_factory=list)
    base_spw: int = 0
    finest_spw: int = 0
    max_r_drift_pct: float = 0.0          # worst |ΔR|/R between base and finest
    max_x_drift_ohm: float = 0.0          # worst |ΔX| between base and finest
    x_tol_ohm: float = 0.0                # tolerance the worst X drift was judged against
    x_drift_bands: List[str] = field(default_factory=list)    # X drift over tolerance
    sign_flip_bands: List[str] = field(default_factory=list)  # X changes sign
    converged_r: bool = True              # max_r_drift_pct <= CONVERGENCE_R_TOL_PCT
    converged_x: bool = True              # every band inside its X tolerance, no sign flip
    converged: bool = True                # converged_r AND converged_x
    ran: bool = False
    note: str = ""

    def r_uncertainty_pct(self) -> float:
        """Measured R uncertainty if the check ran, else the model estimate."""
        if self.ran and self.rows:
            return max(self.max_r_drift_pct, SEGS_UNCERTAINTY_FLOOR_PCT)
        return estimated_imp_uncertainty_pct(self.base_spw or None)

    def x_uncertainty_ohm(self) -> Optional[float]:
        """Measured X uncertainty in ohm, or None when --converge did not run.

        There is deliberately no fallback estimate.  The segmentation model
        behind r_uncertainty_pct() is fitted to R, and X drifts by a wholly
        different amount, so reusing the R percentage for X understates it by
        roughly an order of magnitude.  None means "unknown", and the callers
        print X without a +/- figure instead of inventing one.
        """
        if self.ran and self.rows:
            return max(self.max_x_drift_ohm, SEGS_X_UNCERTAINTY_FLOOR_OHM)
        return None


def check_segmentation_convergence(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    nec2c_bin: str,
    base_spw: int,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,
    cp_height_m: Optional[float] = None,
    cp_end_height_m: Optional[float] = None,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    factors: Tuple[float, ...] = CONVERGENCE_FACTORS,
    verbose: bool = True,
) -> ConvergenceReport:
    """
    Re-run the winning geometry at base, 2× and 4× segmentation and report how
    far R and X still move.

    NEC-2 impedances at the segmentation densities normally used for pattern
    work are NOT converged: R typically keeps climbing and X can still change
    sign.  This check turns that from an invisible bias into a number printed
    next to the result, so R/X are published with the precision they have.
    """
    rep = ConvergenceReport(base_spw=int(base_spw))
    active = [cr for cr in calc_rows if cr.active]
    freqs_all = [cr.freq_mhz for cr in calc_rows]
    if not active or not freqs_all or not nec2c_bin:
        rep.note = "convergence check skipped (no NEC2 engine or no active bands)"
        return rep

    highest_f = max(freqs_all)
    spws: List[int] = [int(base_spw)]
    for f in factors:
        spw = min(int(round(base_spw * f)), SEGS_PER_HALF_WAVE_MAX)
        if spw > spws[-1]:
            spws.append(spw)

    with tempfile.TemporaryDirectory(prefix="nec2conv_") as tmpdir:
        for spw in spws:
            nec_p = os.path.join(tmpdir, f"conv_{spw}.nec")
            out_p = os.path.join(tmpdir, f"conv_{spw}.out")
            row = ConvergenceRow(segs_per_half_wave=spw)
            try:
                geo = write_nec_deck(
                    nec_path=nec_p,
                    wire_len_m=best.wire_len_m,
                    cp_len_m=best.cp_len_m,
                    freqs_mhz=freqs_all,
                    wire_height_m=wire_height_m,
                    wire_slope_end_m=(wire_slope_end_m if wire_slope_end_m is not None
                                      else best.wire_slope_end_m),
                    cp_height_m=cp_height_m,
                    cp_end_height_m=cp_end_height_m,
                    ground_cond=ground_cond,
                    ground_diel=ground_diel,
                    wire_radius_m=WIRE_RADIUS_M,
                    use_counterpoise=use_counterpoise,
                    no_cp_return=no_cp_return,
                    cp_stub_len_m=cp_stub_len_m,
                    ground_model=ground_model,
                    segs_per_half_wave=spw,
                )
            except (ValueError, NoReturnPathError) as err:
                rep.note = f"convergence check aborted: {err}"
                return rep

            row.segs_wire = _segs(best.wire_len_m, highest_f, spw)
            row.seg_len_wire_m = (best.wire_len_m / row.segs_wire) if row.segs_wire else 0.0
            if use_counterpoise and best.cp_len_m > 1e-9:
                # Use the deck's actual counterpoise geometry (which the
                # vertical-hang branch can resolve to a different reach than
                # the requested cp_len_m), not a value recomputed from
                # best.cp_len_m alone — see DeckGeometry.segs_cp.
                if geo.segs_cp:
                    row.segs_cp = geo.segs_cp
                    # geo.cp_len_deck_m is measured from the RESOLVED feedpoint
                    # height, which is not always the requested wire_height_m.
                    _cp_len_deck = (geo.cp_len_deck_m if geo.cp_len_deck_m > 0.0
                                    else best.cp_len_m)
                    row.seg_len_cp_m = _cp_len_deck / row.segs_cp
                else:
                    row.segs_cp = _segs_at_length(best.cp_len_m, row.seg_len_wire_m)
                    row.seg_len_cp_m = best.cp_len_m / row.segs_cp
            if verbose:
                print(T("converge_running").format(spw, row.segs_wire, row.segs_cp),
                      end="\r")

            if not run_nec2c(nec2c_bin, nec_p, out_p, timeout=300):
                row.ok = False
                rep.rows.append(row)
                continue
            try:
                run = parse_nec2_output(out_p, debug=False, explicit_nec_path=nec_p)
            except Exception:
                run = None
            if run is None or not run.freq_map():
                row.ok = False
                rep.rows.append(row)
                continue

            fmap = run.freq_map()
            for cr in active:
                if not fmap:
                    continue
                key = min(fmap.keys(), key=lambda k: abs(k - cr.freq_mhz))
                _tol = freq_match_tol_mhz(cr.freq_mhz)
                if abs(key - cr.freq_mhz) > _tol:
                    continue
                fp = fmap[key]
                row.band_R[cr.band] = fp.R_ohm
                row.band_X[cr.band] = fp.X_ohm
            rep.rows.append(row)

    if verbose:
        print(" " * 78, end="\r")

    good = [r for r in rep.rows if r.ok and r.band_R]
    if len(good) < 2:
        rep.note = "convergence check incomplete (NEC2 run failed at one density)"
        rep.rows = rep.rows or []
        return rep

    rep.ran = True
    base_row, fine_row = good[0], good[-1]
    rep.base_spw   = base_row.segs_per_half_wave
    rep.finest_spw = fine_row.segs_per_half_wave
    for b, R_fine in fine_row.band_R.items():
        R_base = base_row.band_R.get(b)
        if R_base is None or abs(R_fine) < 1e-9:
            continue
        rep.max_r_drift_pct = max(rep.max_r_drift_pct,
                                  abs(R_base - R_fine) / abs(R_fine) * 100.0)
    for b, X_fine in fine_row.band_X.items():
        X_base = base_row.band_X.get(b)
        if X_base is None:
            continue
        drift = abs(X_base - X_fine)
        rep.max_x_drift_ohm = max(rep.max_x_drift_ohm, drift)
        # Judge X against its OWN tolerance, band by band, scaled to that
        # band's |Z|.  A verdict driven by R alone signs off on a reactance
        # that may still be moving by hundreds of ohm.
        tol_b = convergence_x_tol_ohm(math.hypot(fine_row.band_R.get(b, 0.0), X_fine))
        rep.x_tol_ohm = max(rep.x_tol_ohm, tol_b)
        if drift > tol_b:
            rep.x_drift_bands.append(b)
        if X_base * X_fine < 0.0:
            rep.sign_flip_bands.append(b)
    rep.converged_r = rep.max_r_drift_pct <= CONVERGENCE_R_TOL_PCT
    rep.converged_x = not rep.x_drift_bands and not rep.sign_flip_bands
    rep.converged = rep.converged_r and rep.converged_x
    return rep


def convergence_lines(rep: ConvergenceReport,
                      calc_rows: List[CalcRow]) -> List[str]:
    """Render the convergence report as plain text lines (console + report)."""
    out: List[str] = []
    if rep is None or not rep.ran:
        if rep is not None and rep.note:
            out.append(rep.note)
        return out
    active = [cr for cr in calc_rows if cr.active]
    good = [r for r in rep.rows if r.ok and r.band_R]
    for cr in active:
        b = cr.band
        if b not in good[-1].band_R:
            continue
        out.append(f"{b} ({cr.freq_mhz:.3f} MHz)")
        out.append(f"    {'seg/½λ':>7}  {'segs w/cp':>11}  {'seg len (m)':>12}  "
                   f"{'R (Ω)':>9}  {'X (Ω)':>9}")
        for row in good:
            R = row.band_R.get(b)
            X = row.band_X.get(b)
            if R is None:
                continue
            out.append(
                f"    {row.segs_per_half_wave:7d}  "
                f"{row.segs_wire:5d}/{row.segs_cp:<5d}  "
                f"{row.seg_len_wire_m:12.3f}  {R:9.1f}  {X:+9.1f}"
            )
    out.append("")
    out.append(T("converge_drift").format(rep.base_spw, rep.finest_spw,
                                          rep.max_r_drift_pct, rep.max_x_drift_ohm))
    if rep.sign_flip_bands:
        out.append(T("converge_sign_flip").format(", ".join(rep.sign_flip_bands)))
    # R and X get separate verdicts: they do not converge at the same rate.
    if rep.converged_r:
        out.append(T("converge_r_ok").format(CONVERGENCE_R_TOL_PCT))
    else:
        out.append(T("converge_warn").format(CONVERGENCE_R_TOL_PCT, rep.finest_spw))
    if rep.converged_x:
        out.append(T("converge_x_ok").format(rep.max_x_drift_ohm, rep.x_tol_ohm))
    else:
        out.append(T("converge_x_warn").format(
            rep.max_x_drift_ohm, rep.x_tol_ohm,
            ", ".join(rep.x_drift_bands) or ", ".join(rep.sign_flip_bands),
            rep.finest_spw))
    _ux = rep.x_uncertainty_ohm()
    if _ux is not None:
        out.append(T("converge_unc_pair").format(rep.r_uncertainty_pct(), _ux))
    return out


def _print_convergence(rep: ConvergenceReport, calc_rows: List[CalcRow]) -> None:
    lines = convergence_lines(rep, calc_rows)
    if not lines:
        return
    print()
    for l in lines:
        if l.startswith("!"):
            print(f"  {Fore.YELLOW}{l}{Style.RESET_ALL}")
        else:
            print(f"  {l}")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# RESULT RANKING & PARETO
# ═══════════════════════════════════════════════════════════════════════════

def rank_results(results: List[CandidateResult]) -> List[CandidateResult]:
    """Best first.  Candidates whose NEC-2 result is not trustworthy —
    geometry inside the ground singularity, empirical fallback, failed run —
    are pushed behind every trustworthy one regardless of their score, so the
    published winner can never be a geometry the tool itself flagged."""
    return sorted(results, key=lambda r: (not r.nec2_ok, r.score_combined))


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
    # Unreliable candidates never enter the front (same rule as rank_results).
    _trust = [r for r in results if r.nec2_ok]
    results = _trust if _trust else results
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

    # The candidate this result was computed against. Kept so callers can
    # detect if `ranked[0]` / `best` has since moved on to a different
    # geometry (e.g. after `_converge_unun()` exits via the oscillation
    # branch or exhausts AUTO_UNUN_PASSES) — see 4.8. `None` for an empty
    # result (no active bands).
    source_geometry: Optional["CandidateResult"] = None


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
                _tol = freq_match_tol_mhz(freq)
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
            X_ant = -1500.0 * math.sin(2.0 * arg)

        band_impedances.append((cr.band, R_ant, X_ant))

    if not band_impedances:
        return UnUnResult()

    result = UnUnResult()
    result.band_impedances = band_impedances
    result.source_geometry = best

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
    top_n: int = 0,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    cp_end_height_m: Optional[float] = None,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_sweep: Optional[int] = None,
    segs_final: Optional[int] = None,
    conv_report: Optional[ConvergenceReport] = None,
    target_toa_deg: float = DEFAULT_TARGET_TOA_DEG,
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
    if use_counterpoise:
        ln(T("report_cp_range").format(cp_range[0], cp_range[1], cp_range[2]))
    else:
        ln(T("report_cp_range_disabled"))
        ln(T("no_cp_banner"))
        if mode == "nec2":
            ln(T("report_return_path").format(
                "ground rod → z=0 (GN 1)" if no_cp_return == "ground-rod"
                else f"coax-braid stub {cp_stub_len_m:.2f} m"))

    if mode == "nec2":
        _gm_eff = ("perfect" if (not use_counterpoise and no_cp_return == "ground-rod")
                   else ground_model)
        _floor_rep = ground_clearance_floor_m([cr.freq_mhz for cr in calc_rows])
        ln(T("report_ground_model").format(
            "GN 1 (perfect ground; wire ends may sit at z=0)" if _gm_eff == "perfect"
            else f"GN 2 (Sommerfeld-Norton); wire-end floor {_floor_rep:.2f} m "
                 f"= {GROUND_CLEAR_FRAC_SAFE:.2f}·λ at the lowest band"))

    if mode == "nec2":
        _spw_rep = segs_final or (ranked[0].segs_per_half_wave if ranked else None) \
                   or SEGS_PER_HALF_WAVE
        _unc_rep = (conv_report.r_uncertainty_pct() if conv_report is not None
                    else estimated_imp_uncertainty_pct(_spw_rep))
        _unc_rep_x = (conv_report.x_uncertainty_ohm() if conv_report is not None
                      else None)
        ln(T("report_segmentation").format(segs_sweep or _spw_rep, _spw_rep))
        ln(T("report_imp_uncertainty").format(
            _unc_rep,
            T("imp_unc_measured") if (conv_report is not None and conv_report.ran)
            else T("imp_unc_estimated")))
        # X is reported on its own line, in ohm: the percentage above is fitted
        # to the R drift and does not describe how far X moves.
        if _unc_rep_x is not None:
            ln(T("report_imp_uncertainty_x").format(_unc_rep_x))
        else:
            ln(T("report_imp_uncertainty_x_none"))

    # Show slope geometry if any ranked result carries it
    _any_slope = next((r.wire_slope_end_m for r in ranked if r.wire_slope_end_m is not None), None)
    if _any_slope is not None:
        ln(T("report_wire_geom_sloped_summary").format(_any_slope))
    else:
        ln(T("report_wire_geom_horizontal"))

    # Show the REQUESTED counterpoise far-end height (identical for every
    # candidate).  The height each candidate actually reaches, and the angle
    # that follows from it, are per-candidate and appear in the table below.
    if use_counterpoise and cp_end_height_m is not None:
        ln(T("report_cp_geom_summary").format(wire_height_m, cp_end_height_m))
        _n_short = sum(1 for r in ranked
                       if r.cp_reach_m is not None and r.cp_reach_m <= 1e-6)
        if _n_short:
            ln(T("report_cp_geom_short").format(_n_short, len(ranked)))
    all_bands_list  = [cr.band for cr in calc_rows]
    active_band_set = set(cr.band for cr in active)
    band_labels = [f"{b}(*)" if b in active_band_set else b for b in all_bands_list]
    ln(T("report_active_bands").format(len(active), len(calc_rows), ', '.join(band_labels)))

    display_total = total_candidates if total_candidates > 0 else len(ranked)
    ln(T("report_total_candidates").format(display_total))
    lines.append("")

    # ── TOP N RANKING ────────────────────────────────────────────────────
    # `ranked` is the FULL ranked list — the winner (ranked[0]) and every
    # downstream deliverable (CSV, .nec deck, plots, PDF) is computed from
    # it. `top_n` only controls how many rows are printed in the table
    # below; it must never be used to slice `ranked` itself, or the report's
    # "best candidate" section silently disappears whenever top_n <= 0.
    top_n = min(top_n, len(ranked)) if top_n > 0 else len(ranked)
    h1(T("report_top_n_header").format(top_n))
    # Defensive check: the table header states one segmentation density for
    # every published result. If some row was never refined to that density
    # (e.g. a future code path only refines the winner), flag it per row
    # instead of silently mixing densities under one claimed value.
    _spw_expect = segs_final or (_spw_rep if mode == "nec2" else None) or SEGS_PER_HALF_WAVE
    _mixed_spw = (mode == "nec2" and any(
        (r.segs_per_half_wave or _spw_expect) != _spw_expect for r in ranked[:top_n]
    ))
    header = (f"  {'#':>3}  {'Wire(m)':>8}  {'CP(m)':>7}  {'CP°':>6}  "
              f"{'Score':>7}  {'meanPen':>9}  {'1.5xWpen':>9}  {'-0.25xAv(a)':>11}  {'-0.1xCPbon':>11}  "
              + "  ".join(f"{b:>7}" for b in bands)
              + "  NEC2" + ("  spw" if _mixed_spw else ""))
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))
    if _mixed_spw:
        ln("WARNING: rows below were not all published at the same segmentation "
           "density — see the 'spw' column.")

    for rank, r in enumerate(ranked[:top_n], 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        # Three distinct states, not two: a NEC2 run inside the ground
        # singularity is NOT the same thing as the empirical fallback.
        if r.nec2_ok:
            nec_flag = "✓"
        elif "geometry too close to ground" in (r.note or ""):
            nec_flag = "!gnd"
        elif "NEC2" in (r.note or ""):
            nec_flag = "fail"
        else:
            nec_flag = "emp"
        # Use stored score_vswr_raw (= mean + 1.5×worst) to avoid re-deriving from
        # rounded band_vswr values — prevents accumulation of rounding error.
        _mean_vswr_pen     = r.score_vswr           # stored mean penalty
        _worst_pen_weighted = r.score_vswr_raw - r.score_vswr  # 1.5 × worst
        # CP bonus contribution = score_vswr_raw − 0.5×avoid_active − score_combined
        _cp_bonus_deduction = -(r.score_vswr_raw
                                - 0.25 * r.score_avoidance_active
                                - r.score_combined)
        _spw_col = f"  {(r.segs_per_half_wave or _spw_expect):4d}" if _mixed_spw else ""
        lines.append(
            f"  {rank:3d}  {r.wire_len_m:8.3f}  {r.cp_len_m:7.3f}  {r.cp_angle_deg:5.1f}°  "
            f"{r.score_combined:7.3f}  {_mean_vswr_pen:9.3f}  {_worst_pen_weighted:9.3f}  "
            f"{-0.25*r.score_avoidance_active:11.4f}  {_cp_bonus_deduction:11.4f}  "
            f"{band_cols}  {nec_flag}{_spw_col}"
        )

    # ── PARETO FRONT ─────────────────────────────────────────────────────
    h1(T("report_pareto_header").format(len(pareto)))
    ln(T("report_pareto_note"))
    lines.append("")
    pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
    _mixed_spw_pareto = (mode == "nec2" and any(
        (r.segs_per_half_wave or _spw_expect) != _spw_expect for r in pareto_ranked
    ))
    if _mixed_spw_pareto:
        ln("WARNING: Pareto rows below were not all published at the same "
           "segmentation density — see the trailing 'spw=' tag on each row.")
    for rank, r in enumerate(pareto_ranked, 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        _spw_tag = (f"  spw={r.segs_per_half_wave or _spw_expect}"
                    if _mixed_spw_pareto else "")
        lines.append(
            f"  {rank:3d}  wire={r.wire_len_m:.3f} m  cp={r.cp_len_m:.3f} m"
            f"  ({r.cp_angle_deg:.1f}°)  score={r.score_combined:.3f}"
            f"  VSWR=[{band_cols}]"
            f"  avoid_active={r.score_avoidance_active:.4f}"
            f"  avoid_all={r.score_avoidance:.4f}"
            f"{_spw_tag}"
        )

    # ── BEST CANDIDATE DETAIL ────────────────────────────────────────────
    if ranked:
        best = ranked[0]
        h1(T("report_best_header"))
        ln(T("report_wire_len").format(best.wire_len_m))
        if not use_counterpoise:
            ln(T("report_cp_disabled"))
        else:
            ln(T("report_cp_len").format(
                best.cp_len_m,
                best.cp_end_z_m if best.cp_end_z_m is not None else wire_height_m,
                best.cp_angle_deg))
        if use_counterpoise and best.cp_end_z_m is not None:
            if best.cp_reach_m is not None and best.cp_reach_m <= 1e-6:
                ln(T("report_cp_geom_vertical"))
            else:
                ln(T("report_cp_geom_detail").format(
                    wire_height_m, best.cp_end_z_m, best.cp_angle_deg,
                    best.cp_reach_m if best.cp_reach_m is not None else 0.0))
        if best.wire_slope_end_m is not None:
            ln(T("report_wire_geom_sloped_detail").format(wire_height_m, best.wire_slope_end_m))
        else:
            ln(T("report_wire_geom_horizontal_const"))
        ln(T("report_combined_score").format(best.score_combined))
        ln(T("report_vswr_penalty").format(best.score_vswr))
        ln(T("report_avoidance_act").format(best.score_avoidance_active))
        ln(T("report_avoidance_all").format(best.score_avoidance))
        ln(T("report_nec2_used").format(T("report_nec2_yes") if best.nec2_used else T("report_nec2_no")))
        if best.nec2_used and not best.nec2_ok:
            ln(T("report_nec2_untrusted"))
            if best.note:
                ln(T("report_nec2_note").format(best.note.strip()))

        # ── Radiation performance ────────────────────────────────────────
        # Printed right next to the VSWR figures: a low VSWR on an antenna
        # whose lobe points at the zenith is not a good antenna, and the
        # report must not let that pass unnoticed.
        if best.pattern_ok and best.band_toa:
            ln("")
            ln(T("radiation_summary_hdr").format(target_toa_deg))
            ln(T("radiation_row_hdr").format(
                T("radiation_col_band"), T("radiation_col_mhz"),
                T("radiation_col_gain"), T("radiation_col_toa"),
                T("radiation_col_gtoa")))
            ln("    " + "─" * 52)
            for _cr in [c for c in calc_rows if c.active]:
                _toa = best.band_toa.get(_cr.band)
                if _toa is None:
                    continue
                _gmax = best.band_gain_max.get(_cr.band, 0.0)
                _gt   = best.band_gain_toa.get(_cr.band, 0.0)
                ln(f"    {_cr.band:>8}  {_cr.freq_mhz:7.3f}  "
                   f"{_gmax:10.2f}  {_toa:6.0f}°  {_gt:12.2f}")
            for _cr in [c for c in calc_rows if c.active]:
                _toa = best.band_toa.get(_cr.band)
                if _toa is not None and _toa >= HIGH_TOA_WARN_DEG:
                    ln("")
                    ln("  " + T("warn_high_toa").format(_cr.band, _toa))

        _tol_r = 1e-6
        _wmin, _wmax, _ = wire_range
        _cmin, _cmax, _ = cp_range
        if _cmin is None or _cmax is None:
            _cmin = _cmax = float("nan")
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
        if use_counterpoise:
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
        _spw_tab = (best.segs_per_half_wave or segs_final or SEGS_PER_HALF_WAVE)
        _unc_tab = (conv_report.r_uncertainty_pct() if conv_report is not None
                    else estimated_imp_uncertainty_pct(_spw_tab))
        _unc_tab_x = (conv_report.x_uncertainty_ohm() if conv_report is not None
                      else None)
        if mode == "nec2":
            ln(T("report_imp_precision_note").format(_spw_tab, _unc_tab))
            if _unc_tab_x is not None:
                ln(T("report_imp_precision_note_x").format(_unc_tab_x))
            else:
                ln(T("report_imp_precision_note_x_none"))
        ln(f"  {'Band':>8}  {'freq MHz':>9}  "
           f"{'R_ant Ω':>14}  {'X_ant Ω':>14}  {'|Z_ant|Ω':>10}  "
           f"{'R_tx Ω':>8}  {'X_tx Ω':>8}  {'|Z_tx|Ω':>9}  "
           f"{'VSWR':>6}  {'Source':>10}")
        ln("  " + "─" * 110)
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
            if mode == "nec2" and src.startswith("NEC2"):
                _u    = abs(R_a) * _unc_tab / 100.0
                _Ra_s = fmt_imp_with_unc(R_a, _u)
                # _unc_tab_x is None when --converge did not run: X is then
                # printed bare rather than carrying the R uncertainty.
                _Xa_s = fmt_imp_with_unc(X_a, _unc_tab_x, signed=True)
            else:
                _Ra_s, _Xa_s = f"{R_a:.1f}", f"{X_a:+.1f}"
            ln(f"  {b:>8}  {f:9.4f}  "
               f"{_Ra_s:>14}  {_Xa_s:>14}  {Z_a:10.1f}  "
               f"{R_t:8.2f}  {X_t:+8.2f}  {Z_t:9.2f}  "
               f"{v:6.2f}  {src:>10}")
        ln(T("report_unun_note").format(unun_ratio))

    # ── SEGMENTATION CONVERGENCE ─────────────────────────────────────────
    if conv_report is not None and conv_report.ran:
        h1(T("report_converge_section"))
        for _cl in convergence_lines(conv_report, calc_rows):
            ln(_cl)

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
      vswr_no_cp   — antenna-side VSWR (no UnUn, ALWAYS the empirical formula,
                     no CP correction — regardless of R_wire_source)
      vswr_with_cp — Tx-side VSWR after UnUn (best stored impedance or empirical fallback)
      R_wire_ohm / X_wire_ohm — antenna-side impedance (NEC2 if available, else
                     empirical — see R_wire_source for which one this row used)
      R_wire_source — "nec2" or "empirical", so a row that mixes an NEC2-derived
                     R_wire_ohm/Z_eff_ohm with the always-empirical vswr_no_cp
                     is identifiable from the file itself, not just this docstring.
    """
    fieldnames = [
        "band", "freq_mhz", "active", "lambda_half_m", "lambda_qtr_m",
        "wire_len_m", "L_over_lhalf", "R_wire_ohm", "X_wire_ohm",
        "R_wire_source",
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
                r_wire_source = "nec2"
            else:
                ratio_emp = w / lhalf if lhalf else 0.0
                arg = math.pi * ratio_emp
                cos2 = math.cos(arg) ** 2
                R = max(1.0, 50 * (80 ** cos2))
                X = 1500 * math.sin(2 * arg)
                r_wire_source = "empirical"

            lhalf_emp = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio_emp = w / lhalf_emp if lhalf_emp else 0.0
            arg_emp = math.pi * ratio_emp
            cos2_emp = math.cos(arg_emp) ** 2
            R_no_cp = max(1.0, 50.0 * (80.0 ** cos2_emp))
            X_no_cp = -1500.0 * math.sin(2.0 * arg_emp)
            # vswr_no_cp: antenna-side VSWR ref 50 Ω, no UnUn, empirical formula.
            # This represents the bare wire impedance before the UnUn transformer.
            vswr_no = _recompute_vswr(R_no_cp, X_no_cp, 1.0)  # ratio=1 → antenna side

            lambda_qtr = lhalf / 2.0 if lhalf else 0.0
            # Avoidance: the SAME number the report prints, not a second
            # opinion.  What used to be here — 2·min(frac, 1−frac) on
            # ratio_qtr % 1.0 — was the superseded "distance from ANY λ/4
            # multiple" metric: it peaks midway between quarter-wave points
            # and is zero at every λ/4 multiple, i.e. anti-correlated with
            # the mod-2, transformer-aware metric score_candidate() uses,
            # which is 1.0 at the resonance class the UnUn actually wants.
            # Both were fed to the same _avoidance_rating() thresholds, so a
            # single run shipped a report and a CSV that contradicted each
            # other on the headline verdict (40 m ★★ GOOD vs ★ MARGINAL,
            # 20 m ★★ GOOD vs ★★★ EXCELLENT).  Prefer the stored value so
            # the two files are identical by construction; fall back to the
            # shared helper for a band the candidate never scored.
            avoid = best.band_avoidance.get(cr.band)
            if avoid is None:
                avoid = band_avoidance_score(w, freq, unun_ratio)
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
                "R_wire_source":  r_wire_source,
                "vswr_no_cp":     round(vswr_no, 3),
                "vswr_with_cp":   _recompute_vswr(R, X, unun_ratio)
                                  if cr.active else "",
                "Z_eff_ohm":      round(math.hypot(R, X), 2),
                "Zcp_ohm":        "",
                "unun_ratio":     unun_ratio,
                "avoidance_score":round(avoid, 4),
                "quality_rating": rating,
                "cp_len_m":       best.cp_len_m,
                # Radiator and counterpoise share one antenna height.
                "cp_height_m":    (cr.wire_height_m if cr.wire_height_m
                                   else (cr.cp_height_m or DEFAULT_HEIGHT_M)),
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
    cp_height_m: Optional[float] = None,   # None → = wire_height_m
    cp_end_height_m: Optional[float] = None,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    wire_radius_m: float = WIRE_RADIUS_M,
    n_elevation: int = 37,
    n_azimuth: int = 72,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,
    wire_conductivity: Optional[float] = None,  # None → WIRE_CONDUCTIVITY
) -> None:
    """
    Write a full NEC2 deck for the best antenna geometry with complete
    radiation pattern (RP) cards for every active band.

    The geometry comes from build_deck_geometry(), exactly like the sweep
    decks, so the exported file is the same model that produced the numbers.
    """
    active = [r for r in calc_rows if r.active]
    freqs_all = [cr.freq_mhz for cr in calc_rows]

    highest_f = max(freqs_all) if freqs_all else 30.0

    # Counterpoise far-end height: explicit argument, else the value recorded on
    # the winning candidate, else --cp-height.
    _cp_end_req = (cp_end_height_m if cp_end_height_m is not None
                   else (best.cp_end_z_m if best.cp_end_z_m is not None else cp_height_m))
    _slope_end = wire_slope_end_m if wire_slope_end_m is not None else best.wire_slope_end_m

    geo = build_deck_geometry(
        wire_len_m=best.wire_len_m,
        cp_len_m=best.cp_len_m,
        freqs_mhz=freqs_all if freqs_all else [highest_f],
        wire_height_m=wire_height_m,
        wire_slope_end_m=_slope_end,
        cp_height_m=cp_height_m,
        cp_end_height_m=_cp_end_req,
        ground_cond=ground_cond,
        ground_diel=ground_diel,
        wire_radius_m=wire_radius_m,
        use_counterpoise=use_counterpoise,
        no_cp_return=no_cp_return,
        cp_stub_len_m=cp_stub_len_m,
        ground_model=ground_model,
        segs_per_half_wave=segs_per_half_wave,
    )

    with open(out_path, "w") as fh:
        fh.write("CM ============================================================\n")
        fh.write("CM  NEC2 Best-Antenna Deck — generated by nec2_length_optimizer\n")
        for c in geo.comments:
            for _card in cm_cards(c.rstrip("\n")):
                fh.write(_card + "\n")
        for w in geo.warnings:
            for _card in cm_cards("WARNING: " + w):
                fh.write(_card + "\n")
        fh.write(f"CM  CP score    : {best.score_combined:.4f}\n")
        for cr in active:
            b = cr.band
            v = best.band_vswr.get(b, 999.0)
            fh.write(f"CM  {b:>6}  {cr.freq_mhz:.4f} MHz  VSWR={v:.2f}\n")
        fh.write("CM ============================================================\n")
        fh.write("CE\n")

        for gw in geo.gw_lines:
            fh.write(gw)
        fh.write(f"GE {geo.ge_flag}\n")
        fh.write(ld_card(wire_conductivity))
        fh.write(geo.gn_line)
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        d_theta = 90.0  / max(1, n_elevation - 1)
        # 360° must divide evenly by the number of GRID STEPS (n_azimuth
        # points spans n_azimuth steps if the last point equals the first,
        # 0°..360°-d_phi). Using n_azimuth directly (not n_azimuth-1) keeps
        # 180° exactly on-grid whenever n_azimuth is even, which is what
        # _snap_phi()'s "front+180°" back-cut relies on.
        d_phi   = 360.0 / max(1, n_azimuth)
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
            else:
                fh.write("XQ\n")

        fh.write("EN\n")

    print(T("nec2_deck_saved").format(out_path))


# ═══════════════════════════════════════════════════════════════════════════
# MATPLOTLIB PLOTS
# ═══════════════════════════════════════════════════════════════════════════

def _np_interp1(x: float, xs: list, ys: list) -> float:
    """Simple 1-D linear interpolation (xs assumed sorted ascending).

    Clamps out-of-range x to the nearest endpoint value, matching
    numpy.interp's default behaviour: ys[0] below xs[0], ys[-1] above xs[-1].
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return ys[i]
            t = (x - x0) / (x1 - x0)
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def plot_radiation_diagrams(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    nec2c_bin: str,
    out_png: str,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    wire_slope_end_m: Optional[float] = None,
    cp_height_m: Optional[float] = None,   # None → = wire_height_m
    cp_end_height_m: Optional[float] = None,
    ground_cond: float = DEFAULT_GROUND_COND,
    ground_diel: float = DEFAULT_GROUND_DIEL,
    n_elevation: int = 73,
    n_azimuth:   int = 72,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
    segs_per_half_wave: Optional[int] = None,   # None → SEGS_PER_HALF_WAVE_FAST
    wire_conductivity: Optional[float] = None,  # None → WIRE_CONDUCTIVITY
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

    _cp_end_req = (cp_end_height_m if cp_end_height_m is not None
                   else (best.cp_end_z_m if best.cp_end_z_m is not None else cp_height_m))
    freqs_all = [cr.freq_mhz for cr in calc_rows]

    d_theta = 90.0  / max(1, n_elevation - 1)
    # See write_best_nec_deck(): n_azimuth (not n_azimuth-1) is the correct
    # divisor here so 180° lands exactly on-grid for even n_azimuth, which
    # the front/back cut logic (phi_front + 180°) depends on.
    d_phi   = 360.0 / max(1, n_azimuth)

    band_patterns: Dict[str, dict] = {}

    with tempfile.TemporaryDirectory(prefix="nec2rad_") as tmpdir:
        nec_path = os.path.join(tmpdir, "best_radiation.nec")
        out_path_nec = os.path.join(tmpdir, "best_radiation.out")

        # Patterns converge with far less segmentation than impedances, and RP
        # runs are the expensive ones, so the coarse density is the default here.
        _spw_rad = int(segs_per_half_wave or SEGS_PER_HALF_WAVE_FAST)

        # Same geometry builder as the sweep: the pattern is computed on the
        # exact model that produced the impedances, return conductor included.
        _rad_slope = wire_slope_end_m if wire_slope_end_m is not None else best.wire_slope_end_m
        try:
            _rad_geo = build_deck_geometry(
                wire_len_m=best.wire_len_m,
                cp_len_m=best.cp_len_m,
                freqs_mhz=freqs_all,
                wire_height_m=wire_height_m,
                wire_slope_end_m=_rad_slope,
                cp_height_m=cp_height_m,
                cp_end_height_m=_cp_end_req,
                ground_cond=ground_cond,
                ground_diel=ground_diel,
                wire_radius_m=WIRE_RADIUS_M,
                use_counterpoise=use_counterpoise,
                no_cp_return=no_cp_return,
                cp_stub_len_m=cp_stub_len_m,
                ground_model=ground_model,
                segs_per_half_wave=_spw_rad,
            )
        except ValueError as _rad_err:
            print(f"  ⚠  Radiation deck geometry invalid: {_rad_err}")
            return

        with open(nec_path, "w") as fh:
            fh.write("CM RP sweep deck\n")
            for c in _rad_geo.comments:
                for _card in cm_cards(c.rstrip("\n")):
                    fh.write(_card + "\n")
            fh.write("CE\n")
            for gw in _rad_geo.gw_lines:
                fh.write(gw)
            fh.write(f"GE {_rad_geo.ge_flag}\n")
            fh.write(ld_card(wire_conductivity))
            fh.write(_rad_geo.gn_line)
            fh.write(_rad_geo.ex_line)

            for cr in active:
                fh.write(f"FR 0 1 0 0 {cr.freq_mhz:.4f} 0\n")
                fh.write(
                    f"RP 0 {n_elevation} {n_azimuth} 1000 "
                    f"0.0 0.0 {d_theta:.4f} {d_phi:.4f} 0.0\n"
                )
            fh.write("EN\n")

        ok = run_nec2c(nec2c_bin, nec_path, out_path_nec, timeout=120)
        if not ok:
            print("  ⚠  NEC2 radiation run failed — skipping radiation diagrams.")
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

        # Use _RE_FREQ6 (defined near the other frequency patterns) since
        # that's the pattern that actually matches nec2c's
        # "FREQUENCY : ... MHz" banner. The previous local pattern here
        # (FREQUENCY = ... MHZ) never matched real nec2c output, silently
        # leaving _cur_freq_ban unset and making the banner-vs-order
        # cross-check below dead code.
        _freq_re = _RE_FREQ6
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
        _expected_rows = max(1, n_elevation * n_azimuth)

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
                in_rp = False
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
                        bucket.append((theta, phi, total_db))   # Bug 3 fix: removed broken dedupe guard

                        if len(bucket) >= _expected_rows:
                            in_rp = False
                    except ValueError:
                        pass

        if not parsed_patterns:
            print(T("warn_no_rp_data"))
            return

        for cr in active:
            freq = cr.freq_mhz
            best_key = min(parsed_patterns.keys(), key=lambda k: abs(k - freq))
            if abs(best_key - freq) > freq_match_tol_mhz(freq):
                print(T("warn_no_rp_freq").format(freq, cr.band))
                continue
            rows = parsed_patterns[best_key]
            if not rows:
                continue

            # ── Elevation cut: chosen from the data, never assumed ─────────
            # The old code hard-coded the φ=0° cut and then mirrored it to
            # fill the left half of the plot.  Both are wrong here:
            #   • φ=0° is the direction the radiator runs along (+x), which
            #     for an end-fed long wire is exactly where the main lobe is
            #     NOT — the drawn cut could miss the real lobe by several dB
            #     and by a large slice of take-off angle;
            #   • the geometry is explicitly asymmetric (radiator to +x,
            #     counterpoise to −x), so mirroring invents a back half that
            #     the simulation never produced.
            # Instead: find the azimuth of the global maximum, draw THAT cut
            # on the right, and draw the REAL φ+180° cut on the left.
            phi_front = 0.0
            phi_back  = 180.0
            elev_front: List[Tuple[float, float]] = []
            elev_back:  List[Tuple[float, float]] = []
            if rows:
                all_db  = [db for (_, _, db) in rows]
                max_db  = max(all_db)

                _phis = sorted({round(p % 360.0, 2) for (_, p, _) in rows})

                def _snap_phi(target: float) -> float:
                    """Nearest φ actually present in the RP grid (wrapping)."""
                    tgt = target % 360.0
                    return min(_phis,
                               key=lambda q: min(abs(q - tgt), 360.0 - abs(q - tgt)))

                _gmax_row = max(rows, key=lambda r: r[2])
                phi_front = _snap_phi(_gmax_row[1])
                phi_back  = _snap_phi(phi_front + 180.0)

                def _cut(phi_val: float) -> List[Tuple[float, float]]:
                    return sorted(
                        [(90.0 - t, db) for (t, p, db) in rows
                         if abs((p % 360.0) - phi_val) < 0.01],
                        key=lambda x: x[0]
                    )

                elev_front = _cut(phi_front)
                elev_back  = _cut(phi_back)

                # TOA is read from the cut that is actually drawn, so the
                # marker always sits on the plotted lobe.  Because the front
                # cut is taken through the global maximum, this also equals
                # the global take-off angle.
                if elev_front:
                    _peak_elev = max(elev_front, key=lambda x: x[1])[0]
                    best_theta = 90.0 - _peak_elev
                else:
                    best_theta = _gmax_row[0]

                # ── Azimuth: horizontal cut at the TOA elevation ────────────
                # The azimuth pattern must be taken at a FIXED elevation angle
                # (the take-off angle, theta = best_theta), not as a
                # max-over-all-theta envelope (which collapses toward the
                # near-omnidirectional zenith response and hides real
                # low-angle directionality).
                #
                # FIX (spike at phi≈0/N on 40m & 20m): the previous
                # nearest-theta-per-phi approach picked, for each phi
                # independently, whichever theta row in the NEC2 grid was
                # closest to theta_cut. Because the grid is not perfectly
                # regular, most phi values snapped to theta = theta_cut±dtheta
                # while one or two phi values (near phi=0) happened to have
                # an exact grid theta closer to theta_cut, picking a
                # different (and much higher-gain) row -> a 1-bin spike.
                # Fix: for every phi, LINEARLY INTERPOLATE gain (in dB)
                # between the two theta rows that bracket theta_cut, so the
                # azimuth cut is at a single consistent elevation for all phi.
                _theta_cut = best_theta if best_theta is not None else 90.0
                _by_phi: dict = {}   # phi_deg (rounded 2 dp) -> list of (theta, db)
                for (_t3, _p3, _db3) in rows:
                    _pk = round(_p3, 2)
                    _by_phi.setdefault(_pk, []).append((_t3, _db3))

                az_data = []
                for _pk, _tdb in _by_phi.items():
                    _tdb.sort(key=lambda x: x[0])
                    _ths = [x[0] for x in _tdb]
                    _dbs = [x[1] for x in _tdb]
                    if len(_ths) == 1:
                        _val = _dbs[0]
                    elif _theta_cut <= _ths[0]:
                        _val = _dbs[0]
                    elif _theta_cut >= _ths[-1]:
                        _val = _dbs[-1]
                    else:
                        _val = float(_np_interp1(_theta_cut, _ths, _dbs))
                    az_data.append((_pk, _val))
                az_data.sort(key=lambda x: x[0])
            else:
                max_db     = -999.0
                az_data    = []
                best_theta = None
                elev_front = []
                elev_back  = []

            toa = 90.0 - (best_theta if best_theta is not None else 90.0)

            band_patterns[cr.band] = {
                "freq_mhz": freq,
                # "elev" stays the front (main-lobe) cut for any consumer that
                # only wants one curve; the plot uses both halves explicitly.
                "elev": elev_front,
                "elev_back": elev_back,
                "elev_phi_front": phi_front,
                "elev_phi_back":  phi_back,
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
                    toa_mirror=True,
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
        # For a full 360° azimuth plot the ring must be a closed circle:
        # linspace(0, 2π, 361) ends exactly at 2π which matplotlib
        # renders as an open arc leaving a visible spoke/seam at North.
        # Fix: for azimuth (theta_max==360) use 362 points with the last
        # point equal to the first (0 rad) so the ring polygon is closed.
        if theta_max == 360:
            _ring_theta = _np.append(
                _np.linspace(0.0, 2 * math.pi, 361, endpoint=False),
                0.0)  # explicit closure back to 0 rad
        else:
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
            # For a full 360° azimuth plot, explicitly close the lobe polygon
            # so ax.plot does not draw a straight chord from the last sample
            # (phi ≈ 360°−dφ or exactly 2π) back to the first (phi = 0°),
            # which on polar axes appears as a sharp spike at North.
            # Guard against double-closing: only append if the last angle is
            # not already within floating-point tolerance of the first.
            if theta_max == 360 and abs(angles_rad[-1] - angles_rad[0]) > 1e-6:
                _angles_c = list(angles_rad) + [angles_rad[0]]
                _r_vals_c = list(r_vals)     + [r_vals[0]]
            else:
                _angles_c = angles_rad
                _r_vals_c = r_vals
            ax.fill(_angles_c, _r_vals_c, color=fill_c, alpha=0.20, zorder=2)
            ax.plot(_angles_c, _r_vals_c, color=stroke,  linewidth=2.0, zorder=4)

        # ── TOA marker ────────────────────────────────────────────────
        if toa_rad is not None and r_vals:
            # The take-off angle belongs to ONE cut.  Drawing it on both sides
            # only made sense while the diagram was a mirror image; with the
            # real back cut on the left it would mark an angle that lobe does
            # not have.
            for _sign in ((+1, -1) if toa_mirror else (+1,)):
                ax.plot([_sign * toa_rad, _sign * toa_rad], [0, dyn_db],
                        color=_TOA_COL, linewidth=1.3,
                        linestyle="--", zorder=5, alpha=0.9)

        # ── Axes ──────────────────────────────────────────────────────
        ax.set_rmax(dyn_db)
        ax.set_rmin(0)
        ax.set_rticks([])
        ax.yaxis.set_visible(False)
        ax.set_theta_direction(-1)
        # For a full 360° azimuth plot do NOT call set_thetamin/set_thetamax.
        # Those activate matplotlib's "wedge mode" which renders visible axis
        # border lines at BOTH 0° and 360°; since they are co-located at North
        # they overlap and produce the thick spike at the top of the diagram.
        # A default full-circle polar axes already covers 0–360° with no border.
        if theta_max != 360:
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
        T("plot_radiation_title").format(best.wire_len_m, best.cp_len_m, f"{best.cp_angle_deg:.1f}°"),
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
        # pat["elev"] / pat["elev_back"]: (elevation_deg, dBi) samples of the
        # two REAL azimuth cuts, φ_front (through the global maximum) and
        # φ_front+180°.  elevation_deg = 90 − theta_nec, so 0° = horizon and
        # 90° = zenith.  The upper hemisphere is drawn as a half-plane:
        #   right half  = φ_front cut,  polar angle = +(90° − elevation)
        #   left half   = φ_back  cut,  polar angle = −(90° − elevation)
        # Nothing is mirrored: both halves come from the simulation.
        ax_el = fig.add_subplot(n_bands, n_cols, row_idx * n_cols + 1,
                                projection="polar")
        ax_el.set_theta_zero_location("N")   # 0 rad points up → zenith at top

        el_tick_degs   = list(range(-90, 91, 15))
        el_tick_labels = []
        for _a in el_tick_degs:
            # el_tick_degs are POLAR angles measured from the zenith spoke
            # (polar = 90 − elevation), so the elevation a tick represents is
            # 90 − |polar|.  The old label used |polar| directly, which put
            # "0°" at the zenith and "90°" at the horizon — the exact inverse
            # of the elevation scale the TOA readout uses, so the TOA marker
            # appeared to sit at 54° while the caption said 36°.
            _elev = 90 - abs(_a)
            el_tick_labels.append(f"{_elev}°" if _elev % 30 == 0 else "")

        _phi_f = pat.get("elev_phi_front", 0.0)
        _phi_b = pat.get("elev_phi_back", 180.0)
        _el_title = T("plot_elev_cut_label").format(band, _phi_f, _phi_b)

        if pat["elev"]:
            # Right half  = the real cut at φ_front (through the main lobe).
            # Left half   = the real cut at φ_front+180°, NOT a mirror image.
            # The geometry is asymmetric, so the two halves genuinely differ;
            # mirroring used to fabricate the back half of every diagram.
            _elevs_f = [e for (e, _) in pat["elev"]]
            _gains_f = [g for (_, g) in pat["elev"]]
            _polar_f = [math.radians(90.0 - e) for e in _elevs_f]   # 0…π/2

            _back = pat.get("elev_back") or []
            if _back:
                _elevs_b = [e for (e, _) in _back]
                _gains_b = [g for (_, g) in _back]
                _polar_b = [-math.radians(90.0 - e) for e in _elevs_b]
                # Left half is traversed from the horizon up to the zenith so
                # the polygon runs continuously into the right half.
                _angles_full = list(reversed(_polar_b)) + list(_polar_f)
                _gains_full  = list(reversed(_gains_b)) + list(_gains_f)
            else:
                _angles_full = list(_polar_f)
                _gains_full  = list(_gains_f)

            toa_r = math.radians(90.0 - pat["toa_deg"])   # convert elev→polar
            _draw_polar(ax_el,
                        _angles_full, _gains_full,
                        _LOBE_EL, _FILL_EL,
                        _el_title, info,
                        toa_rad=toa_r,
                        toa_mirror=False,   # the TOA belongs to the front cut
                        theta_min=-90, theta_max=90,
                        tick_degs=el_tick_degs,
                        tick_labels=el_tick_labels)
        else:
            _draw_polar(ax_el, [], [],
                        _LOBE_EL, _FILL_EL,
                        _el_title, info,
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

            # ── Trim ONLY the exact horizon row (theta=90°) ───────────────
            # At theta=90°, cos(90°)=0 → Z=0 for all phi, making the bottom
            # ring a flat disc at ground level. Keep it trimmed as before.
            # Do NOT trim zenith rows — instead we handle them with an apex fan.
            _dtheta = (_thetas_set[1] - _thetas_set[0]
                       if len(_thetas_set) > 1 else 1.25)
            _horizon_trim  = 90.0 - 0.5 * _dtheta   # trim only the theta=90° row
            _keep_mask = _T < _horizon_trim
            if _keep_mask.sum() < 2:          # safety: always keep ≥2 rows
                _keep_mask = _T < _T[-1]
            _T  = _T[_keep_mask]
            _DB = _DB[_keep_mask, :]

            _TG, _PG = _np.meshgrid(_T, _P, indexing="ij")

            # ── Normalise R via dB-to-amplitude: R = 10^((dB - max)/20) ──
            _R3D_FLOOR = 0.01
            _R = _np.maximum(_R3D_FLOOR, 10.0 ** ((_DB - _raw_max) / 20.0))

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
            # Cap at 35° so the camera never looks nearly straight down —
            # high angles make the zenith cap face-on and exaggerate any
            # remaining depth-sort ordering issues at the pole.
            _toa_deg = pat.get("toa_deg", 30.0)
            if _toa_deg >= 70.0:
                _view_elev = 35   # near-zenith: moderate overhead angle
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

            # ── Render surface: single globally-sorted Poly3DCollection ──────
            #
            # ROOT CAUSE of the "quarter-disk" artifact on 40m / 20m:
            # The previous per-strip approach relied on matplotlib's internal
            # Poly3DCollection depth-sort (zsort='average') to order faces
            # WITHIN each strip correctly.  However matplotlib re-sorts the
            # entire collection after add_collection3d, and the per-face
            # average-Z sort fails on NON-CONVEX surfaces: on a high-TOA
            # pattern the near-zenith back-side faces have the same average Z
            # as near-zenith front-side faces, so the sort is ambiguous and
            # produces the red quarter-disk cap seen on 40m/20m.
            #
            # FIX: collect ALL surface faces in one list, compute each face's
            # camera-depth (dot product of centroid with the camera-in vector),
            # sort globally back-to-front (furthest first), then pass all faces
            # to a SINGLE Poly3DCollection.  Setting shade=False and providing
            # explicit facecolors prevents any further sorting or shading by
            # matplotlib.  This is the only approach that is correct for
            # arbitrary (non-convex, non-monotone) radiation balloon shapes.

            from mpl_toolkits.mplot3d.art3d import Poly3DCollection as _P3C

            _nt, _np2 = _X.shape

            # Ground-plane disc: rendered as a separate collection BEFORE
            # the balloon so it always appears behind the pattern.
            _disc_n_phi  = 72
            _disc_n_r    = 4
            _disc_radius = 0.65
            _disc_z      = -0.02
            _disc_phi_e  = _np.linspace(0, 2 * _np.pi, _disc_n_phi + 1)
            _disc_r_e    = _np.linspace(0, _disc_radius, _disc_n_r + 1)
            _DPg, _DRg   = _np.meshgrid(_disc_phi_e, _disc_r_e)
            _DXg = _DRg * _np.cos(_DPg)
            _DYg = _DRg * _np.sin(_DPg)
            _DZg = _np.full_like(_DRg, _disc_z)
            _disc_verts = []
            for _fi in range(_disc_n_r):
                for _fj in range(_disc_n_phi):
                    _disc_verts.append(_np.array([
                        [_DXg[_fi,   _fj],   _DYg[_fi,   _fj],   _DZg[_fi,   _fj]  ],
                        [_DXg[_fi+1, _fj],   _DYg[_fi+1, _fj],   _DZg[_fi+1, _fj]  ],
                        [_DXg[_fi+1, _fj+1], _DYg[_fi+1, _fj+1], _DZg[_fi+1, _fj+1]],
                        [_DXg[_fi,   _fj+1], _DYg[_fi,   _fj+1], _DZg[_fi,   _fj+1]],
                    ]))
            _disc_poly = _P3C(
                _disc_verts,
                facecolors=[(0.7, 0.7, 0.7, 0.10)] * len(_disc_verts),
                linewidths=0, edgecolors="none",
            )
            ax3d.add_collection3d(_disc_poly)

            # Collect ALL balloon faces with their camera-depth and color,
            # then sort globally back-to-front (furthest face first) so the
            # single Poly3DCollection paints correctly for any non-convex shape.
            _all_verts  = []
            _all_depths = []
            _all_colors = []
            for _fi in range(_nt - 1):
                for _fj in range(_np2 - 1):
                    _v = _np.array([
                        [_X[_fi,   _fj],   _Y[_fi,   _fj],   _Z[_fi,   _fj]  ],
                        [_X[_fi+1, _fj],   _Y[_fi+1, _fj],   _Z[_fi+1, _fj]  ],
                        [_X[_fi+1, _fj+1], _Y[_fi+1, _fj+1], _Z[_fi+1, _fj+1]],
                        [_X[_fi,   _fj+1], _Y[_fi,   _fj+1], _Z[_fi,   _fj+1]],
                    ])
                    _all_verts.append(_v)
                    # Depth = projection of face centroid onto camera-in vector;
                    # larger value = face is further from the camera.
                    _all_depths.append(_np.dot(_v.mean(axis=0), _cam_in))
                    _db_f = (_DB[_fi,   _fj]   + _DB[_fi+1, _fj] +
                             _DB[_fi+1, _fj+1] + _DB[_fi,   _fj+1]) / 4.0
                    _all_colors.append(_cmap(_norm(_db_f)))

            # ── Zenith apex cap: triangles from single apex to first ring ──
            # ROOT CAUSE of the "quarter-disk" on 40m/20m:
            # When zenith rows (theta≈0) were TRIMMED, the open top rim was a
            # circle at theta=pole_trim facing the camera. Back-face culling
            # could not hide it because those faces ARE front-facing from above.
            # They rendered as a solid filled disk cap.
            #
            # CORRECT FIX: do NOT trim zenith rows. Keep theta=0 in the mesh.
            # The pole-averaging above already collapses all DB values at
            # theta=0 to a single mean → all (X,Y,Z) at theta=0 converge to
            # a single apex point (0,0,R_apex).  Instead of quad faces from
            # theta=0 to theta=dtheta (which are degenerate wedges all sharing
            # the same two "top" vertices), build an explicit fan of TRIANGLES
            # from the apex point to successive vertex pairs on the theta=dtheta
            # ring. Triangle fans have well-defined per-face normals and their
            # centroids are spread across 3D space, so depth sorting works
            # perfectly with no disk artifact.
            # Step 1: remove the degenerate quads in row 0 (already in _all_verts
            # but they were built from the unchanged _X/_Y/_Z which now has
            # theta=0 collapsed). We rebuild only the apex triangles instead.
            # The quad loop above starts at _fi=0 so it already added row-0 quads;
            # we discard those and replace with apex triangles.
            if _nt >= 2:
                # Discard the first _np2-1 entries (row-0 degenerate quads)
                _all_verts  = _all_verts[_np2-1:]
                _all_depths = _all_depths[_np2-1:]
                _all_colors = _all_colors[_np2-1:]
                # Build apex fan
                _apex = _np.array([_X[0, :].mean(), _Y[0, :].mean(), _Z[0, :].mean()])
                _apex_db = float(_DB[0, :].mean())
                for _fj in range(_np2 - 1):
                    _tri = _np.array([
                        _apex,
                        [_X[1, _fj],   _Y[1, _fj],   _Z[1, _fj]  ],
                        [_X[1, _fj+1], _Y[1, _fj+1], _Z[1, _fj+1]],
                    ])
                    _all_verts.append(_tri)
                    _all_depths.append(float(_np.dot(_tri.mean(axis=0), _cam_in)))
                    _db_tri = (_apex_db + _DB[1, _fj] + _DB[1, _fj+1]) / 3.0
                    _all_colors.append(_cmap(_norm(_db_tri)))

            # Sort all faces (body quads + apex triangles) back-to-front:
            # largest depth (furthest from camera) drawn first.
            _so = _np.argsort(-_np.array(_all_depths))
            _surf_poly = _P3C(
                [_all_verts[_k]  for _k in _so],
                facecolors=[_all_colors[_k] for _k in _so],
                linewidths=0, edgecolors="none",
            )
            ax3d.add_collection3d(_surf_poly)

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
        ax3d.set_zlim(-0.05, 1.0)
        try:
            # set_box_aspect takes visual proportions, not data ranges.
            # XY axes span 2 units (-1…1), Z spans ~1 unit (0…1).
            # [1,1,0.5] → equal XY with Z half-height = correct hemisphere shape.
            ax3d.set_box_aspect([1.0, 1.0, 0.5])
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

    if not results:
        # Every panel below aggregates over the candidate list (min/max of the
        # scores, the top-10 bar charts); with no candidates they raise on an
        # empty sequence.  There is simply nothing to draw.
        print(T("plot_skipped_no_results"))
        return

    active = [r for r in calc_rows if r.active]

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
# CONSTRUCTION DIAGRAM
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# CONSTRUCTION DIAGRAM  —  label-placement engine + drawing helpers
# ═══════════════════════════════════════════════════════════════════════════

class _LabelPlacer:
    """Collect all Text artists, then resolve overlaps and clamp to axes limits.

    Algorithm
    ---------
    1. Force-directed repulsion (grid of candidate positions derived from the
       original anchor, ranked by distance from anchor).
    2. After converging, hard-clamp every label inside the axes data bbox so
       no part of any label box ever touches the frame.

    This is language-agnostic: Spanish labels are typically longer than English
    ones; the renderer measures each actual pixel extent.
    """

    # Gap (data units) that must remain clear around every label box
    _PAD = 0.08

    def __init__(self):
        self._labels: list = []   # list of (Text artist, priority)
        # priority: lower = moved last (anchored items have priority=0)

    def register(self, artist, priority: int = 5) -> None:
        """Register a Text artist for overlap resolution."""
        if artist is not None:
            self._labels.append((artist, priority))

    # ------------------------------------------------------------------
    def resolve(self, fig, ax, margin: float = 0.15) -> None:
        """Run the full resolve + clamp pass.

        margin  – extra data-unit clearance to keep labels away from the
                  axes frame (in addition to self._PAD).
        """
        if not self._labels:
            return
        try:
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
        except Exception:
            return   # headless / unavailable renderer — skip

        trans_inv = ax.transData.inverted()
        xl0, xl1 = ax.get_xlim()
        yl0, yl1 = ax.get_ylim()

        def _bbox_data(artist):
            """Return (x0,y0,x1,y1) in data coordinates."""
            bb = artist.get_window_extent(renderer=renderer)
            p0 = trans_inv.transform((bb.x0, bb.y0))
            p1 = trans_inv.transform((bb.x1, bb.y1))
            return (min(p0[0], p1[0]), min(p0[1], p1[1]),
                    max(p0[0], p1[0]), max(p0[1], p1[1]))

        def _overlap(a, b):
            pad = self._PAD
            return (a[0] - pad < b[2] + pad and a[2] + pad > b[0] - pad and
                    a[1] - pad < b[3] + pad and a[3] + pad > b[1] - pad)

        def _clamp_artist(artist):
            """Move artist so its bbox stays fully inside the axes limits."""
            x0d, y0d, x1d, y1d = _bbox_data(artist)
            w = x1d - x0d
            h = y1d - y0d
            cx, cy = artist.get_position()
            # offset from centre to bbox origin (depends on ha/va)
            ox = cx - x0d   # how much centre is to the right of bbox left
            oy = cy - y0d   # how much centre is above bbox bottom

            inner_xl0 = xl0 + margin
            inner_xl1 = xl1 - margin
            inner_yl0 = yl0 + margin
            inner_yl1 = yl1 - margin

            # clamp bbox left/right/bottom/top
            new_x0 = max(inner_xl0, min(x0d, inner_xl1 - w))
            new_y0 = max(inner_yl0, min(y0d, inner_yl1 - h))
            new_cx = new_x0 + ox
            new_cy = new_y0 + oy
            if abs(new_cx - cx) > 1e-9 or abs(new_cy - cy) > 1e-9:
                artist.set_position((new_cx, new_cy))
            return _bbox_data(artist)

        # Sort by priority (low priority = pinned / moved last)
        sorted_labels = sorted(self._labels, key=lambda t: -t[1])

        # Iterative repulsion: up to 60 passes
        for _pass in range(60):
            moved = False
            bboxes = [_bbox_data(a) for a, _ in sorted_labels]
            for i, (ai, pi) in enumerate(sorted_labels):
                for j, (aj, pj) in enumerate(sorted_labels):
                    if i >= j:
                        continue
                    if not _overlap(bboxes[i], bboxes[j]):
                        continue
                    # Push the lower-priority one (higher priority number)
                    mover_idx = i if pi >= pj else j
                    mover = sorted_labels[mover_idx][0]
                    bi = bboxes[i]
                    bj = bboxes[j]
                    # overlap extents
                    ox = min(bi[2], bj[2]) - max(bi[0], bj[0]) + self._PAD
                    oy = min(bi[3], bj[3]) - max(bi[1], bj[1]) + self._PAD
                    # push in the direction of least overlap
                    cx_m, cy_m = mover.get_position()
                    # direction: mover relative to the other
                    other_idx = j if mover_idx == i else i
                    bo = bboxes[other_idx]
                    bm = bboxes[mover_idx]
                    sign_x = 1 if (bm[0] + bm[2]) / 2 >= (bo[0] + bo[2]) / 2 else -1
                    sign_y = 1 if (bm[1] + bm[3]) / 2 >= (bo[1] + bo[3]) / 2 else -1
                    if ox <= oy:
                        mover.set_position((cx_m + sign_x * ox, cy_m))
                    else:
                        mover.set_position((cx_m, cy_m + sign_y * oy))
                    fig.canvas.draw()
                    bboxes[mover_idx] = _bbox_data(mover)
                    moved = True
            if not moved:
                break

        # Final clamp: every label must stay inside the axes frame
        fig.canvas.draw()
        for artist, _ in sorted_labels:
            _clamp_artist(artist)
        fig.canvas.draw()


def _dim_line(ax, p0, p1, label, color, text_color, below: bool = False,
              bg="#ffffff", text_frac: float = 0.5, show_label: bool = True):
    """Draw a dimension line with end ticks and an optional centred label.

    Returns the Text artist (or None when show_label=False).
    text_frac  – 0.0 = label at p0, 1.0 = label at p1 (default 0.5).
    show_label – False: draw ticks/line only; caller places the label.
    """
    x0, y0 = p0
    x1, y1 = p1
    ax.plot([x0, x1], [y0, y1], color=color, linewidth=1, linestyle="--",
            alpha=0.8, zorder=3)
    tick = 0.18
    ax.plot([x0, x0], [y0 - tick, y0 + tick], color=color, linewidth=1, alpha=0.8)
    ax.plot([x1, x1], [y1 - tick, y1 + tick], color=color, linewidth=1, alpha=0.8)
    if show_label:
        mx = x0 + (x1 - x0) * text_frac
        my = y0 + (y1 - y0) * text_frac
        offset = -0.32 if below else 0.32
        return ax.text(mx, my + offset, label, color=text_color, fontsize=8.5,
                ha="center", va="center" if not below else "top",
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", facecolor=bg,
                          edgecolor=color, alpha=0.9, linewidth=0.8))
    return None


def _vdim_line(ax, x, z0, z1, label, color, text_color, small: bool = False,
               bg="#ffffff", right: bool = False):
    """Draw a vertical dimension line with end ticks and a rotated side label.

    Returns the Text artist.
    """
    ax.plot([x, x], [z0, z1], color=color, linewidth=1, linestyle="--",
            alpha=0.8, zorder=3)
    tick = 0.12
    ax.plot([x - tick, x + tick], [z0, z0], color=color, linewidth=1, alpha=0.8)
    ax.plot([x - tick, x + tick], [z1, z1], color=color, linewidth=1, alpha=0.8)
    fontsize = 7.5 if small else 8.5
    label_x = x + 0.15 if right else x - 0.15
    return ax.text(label_x, (z0 + z1) / 2, label, color=text_color,
                   fontsize=fontsize, ha="left" if right else "right",
                   va="center", fontweight="bold", rotation=90,
                   bbox=dict(boxstyle="round,pad=0.2", facecolor=bg,
                             edgecolor=color, alpha=0.9, linewidth=0.8))


def plot_construction_diagram(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    unun_ratio: float,
    out_png: str,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    cp_height_m: Optional[float] = None,   # None → = wire_height_m
    cp_end_height_m: Optional[float] = None,
    wire_slope_end_m: Optional[float] = None,
    wire_radius_mm: float = 1.0,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    ground_model: str = DEFAULT_GROUND_MODEL,
) -> None:
    """
    Render a clean, modern, human-readable PNG showing the physical layout
    of the winning antenna (radiator + counterpoise/radials), annotated with
    every dimension needed for construction, plus a per-band summary table.

    All labels are kept inside the graphic box and resolved for overlaps
    regardless of language (Spanish labels are longer than English ones).
    """
    if not HAS_MPL:
        print(T("matplotlib_missing"))
        return

    # ── palette ───────────────────────────────────────────────────────────
    BG      = "#ffffff"
    PANEL   = "#ffffff"
    GRID    = "#d8dee5"
    TEXT    = "#1a2330"
    SUBTEXT = "#5a6b7a"
    ACCENT  = "#1f7fb8"   # radiator
    ACCENT2 = "#c97a1a"   # counterpoise
    GROUND  = "#9aa7b3"

    slope_end = wire_slope_end_m if wire_slope_end_m is not None else best.wire_slope_end_m

    wire_len = best.wire_len_m
    cp_len   = best.cp_len_m if use_counterpoise else 0.0
    draw_cp  = bool(use_counterpoise) and cp_len > 1e-6

    # ── radiator geometry ─────────────────────────────────────────────────
    # The drawing must show the geometry that was actually simulated, so the
    # same ground-clearance rule is applied here.
    _freqs_cd   = [cr.freq_mhz for cr in calc_rows]
    _floor_cd   = ground_clearance_floor_m(_freqs_cd) if _freqs_cd else 0.0
    _perfect_cd = (ground_model == "perfect"
                   or (not use_counterpoise and no_cp_return == "ground-rod"))
    # The feedpoint follows the same ground-clearance rule as every other end
    # (build_deck_geometry() raises it to the floor over a Sommerfeld-Norton
    # ground), and both wires hang from it — so the drawing must start from the
    # resolved height, not the requested one.
    z_near = (float(wire_height_m) if _perfect_cd
              else max(float(wire_height_m), _floor_cd))
    if slope_end is not None:
        z_far = (0.0 if (_perfect_cd and float(slope_end) <= _floor_cd)
                 else max(float(slope_end), _floor_cd))
        rise  = z_near - z_far
        if rise > wire_len:
            # Same geometry rule enforced in build_deck_geometry() for
            # write_nec_deck(): a wire that cannot reach the requested far-end
            # height is not a candidate the NEC-2 deck will build, so the
            # construction diagram must not draw it either. Raising here
            # (instead of silently clamping rise to wire_len, as before)
            # keeps this code path from disagreeing with the deck about what
            # geometry is valid.
            raise ValueError(
                f"wire_height_m ({z_near:.3f} m) - slope_end ({z_far:.4f} m) "
                f"= {rise:.3f} m exceeds wire_len ({wire_len:.3f} m); "
                "wire cannot reach the specified far-end height."
            )
        x_far = math.sqrt(max(0.0, wire_len ** 2 - rise ** 2))
    else:
        z_far = z_near
        x_far = wire_len

    # ── counterpoise geometry ─────────────────────────────────────────────
    _cp_end_req = (cp_end_height_m if cp_end_height_m is not None
                   else (best.cp_end_z_m if best.cp_end_z_m is not None else cp_height_m))
    _cp_z_target = _cp_end_z(z_near, _cp_end_req, cp_height_m, wire_radius_mm / 1000.0)
    # The radiator far end above is clamped to the NEC-2 ground floor; the
    # counterpoise must obey the same rule or the drawing shows a geometry
    # that was never simulated.
    _cp_z_target = (0.0 if (_perfect_cd and _cp_z_target <= _floor_cd)
                    else max(_cp_z_target, _floor_cd))
    _cvl, _chr, cp_bottom_z, _cxe, _cze = _cp_geometry(cp_len, z_near, _cp_z_target)
    cp_angle_deg = _cp_angle_from_geometry(_cxe, z_near, _cze)
    vert_len  = _cvl
    horiz_rem = _chr

    # ── axes limits — computed from geometry alone, with fixed margins ────
    # Margins are generous enough to accommodate any label in either language.
    # The label placer will clamp artists inside these limits afterwards.
    LEFT_MARGIN  = max(cp_len, horiz_rem, _cxe) + 3.5
    RIGHT_MARGIN = max(x_far, wire_len) + 3.0
    TOP_MARGIN   = max(wire_height_m, z_near) + 2.5
    BOT_MARGIN   = 1.6   # room for below-ground dim lines

    xl0 = -LEFT_MARGIN
    xl1 =  RIGHT_MARGIN
    yl0 = -BOT_MARGIN
    yl1 =  TOP_MARGIN

    fig = plt.figure(figsize=(13, 9.5), facecolor=BG)
    gs  = gridspec.GridSpec(1, 1, figure=fig,
                             left=0.07, right=0.97,
                             top=0.97, bottom=0.07)
    ax  = fig.add_subplot(gs[0, 0])
    ax.set_facecolor(PANEL)

    # Set limits early so the label placer can work in stable data coordinates
    ax.set_xlim(xl0, xl1)
    ax.set_ylim(yl0, yl1)
    ax.set_aspect("equal", adjustable="box")

    # ── label placer ──────────────────────────────────────────────────────
    placer = _LabelPlacer()

    # ── ground ────────────────────────────────────────────────────────────
    ax.axhline(0, color=GROUND, linewidth=2.5, zorder=1)
    ax.fill_between([xl0, xl1], -0.4, 0, color=GROUND, alpha=0.35, zorder=0)
    # Ground label: pinned, low priority so it moves last
    t_ground = ax.text(xl0 + 0.2, -0.22, T("construction_ground_label"),
                       color=SUBTEXT, fontsize=8.5, va="center", ha="left")
    placer.register(t_ground, priority=1)

    # ── feed mast ─────────────────────────────────────────────────────────
    ax.plot([0, 0], [0, z_near], color="#5b6b7c", linewidth=4, zorder=2,
            solid_capstyle="round")

    # feedpoint dot + label
    ax.scatter([0], [z_near], s=90, color=ACCENT, edgecolors=TEXT,
               linewidths=1.2, zorder=5)
    t_feed = ax.text(-0.25, z_near + 0.22, T("construction_feedpoint"),
                     fontsize=8.5, color=TEXT, ha="right", fontweight="bold")
    placer.register(t_feed, priority=4)

    # ── radiator wire ─────────────────────────────────────────────────────
    ax.plot([0, x_far], [z_near, z_far], color=ACCENT, linewidth=3.2,
            zorder=4, solid_capstyle="round",
            label=T("construction_radiator_label"))
    ax.scatter([x_far], [z_far], s=60, color=ACCENT, edgecolors=TEXT,
               linewidths=1, zorder=5)

    # optional far-end support pole
    if abs(z_far) > 0.05:
        ax.plot([x_far, x_far], [0, z_far], color="#5b6b7c", linewidth=3,
                zorder=2, linestyle=(0, (4, 3)))

    # ── radiator length label: parallel to wire, above it, centred ────────
    # Normal = 90° CCW from wire direction, always flipped to point upward.
    _rad_dx = x_far
    _rad_dz = z_far - z_near
    _rad_seg = math.sqrt(_rad_dx ** 2 + _rad_dz ** 2) or 1.0
    _nx = -_rad_dz / _rad_seg
    _nz =  _rad_dx / _rad_seg
    if _nz < 0:
        _nx, _nz = -_nx, -_nz
    # Gap large enough that the label bbox bottom edge clears the thick wire
    _label_gap = 0.85
    _rad_mid_x = x_far / 2 + _nx * _label_gap
    _rad_mid_z = (z_near + z_far) / 2 + _nz * _label_gap
    # Clamp rotation to (-90, 90] so text always reads left-to-right
    _rad_angle_deg = math.degrees(math.atan2(_rad_dz, _rad_dx))
    if _rad_angle_deg > 90:
        _rad_angle_deg -= 180
    elif _rad_angle_deg < -90:
        _rad_angle_deg += 180
    t_rad = ax.text(_rad_mid_x, _rad_mid_z,
                    f"{T('construction_dim_radiator')}\n{wire_len:.2f} m",
                    color=TEXT, fontsize=8.5, ha="center", va="center",
                    fontweight="bold",
                    rotation=_rad_angle_deg,
                    rotation_mode="anchor",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor=BG,
                              edgecolor=ACCENT, alpha=0.9, linewidth=0.8))
    placer.register(t_rad, priority=6)

    # ── counterpoise / ground system ──────────────────────────────────────
    cp_x0 = 0
    cp_label_total = f"{cp_len:.2f} m"

    # Helper: place a label above (perpendicular offset from) a line segment.
    # Returns the Text artist.
    def _wire_label(ax, x0, z0, x1, z1, text, color, bg,
                    gap=0.55, fontsize=8.5):
        """Place text centred above the segment (x0,z0)→(x1,z1).

        'Above' means in the direction of the upward-pointing perpendicular.
        Rotation is clamped to (-90, 90] so text always reads left-to-right.
        """
        dx = x1 - x0; dz = z1 - z0
        seg_len = math.sqrt(dx ** 2 + dz ** 2) or 1.0
        # 90° CCW normal: (-dz, dx)/len
        nx = -dz / seg_len; nz = dx / seg_len
        if nz < 0:          # always point upward
            nx, nz = -nx, -nz
        mx = (x0 + x1) / 2 + nx * gap
        mz = (z0 + z1) / 2 + nz * gap
        # Raw wire angle in (-180, 180]
        angle = math.degrees(math.atan2(dz, dx))
        # Clamp so text reads left-to-right (never upside-down)
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        return ax.text(mx, mz, text, color=TEXT, fontsize=fontsize,
                       ha="center", va="center", fontweight="bold",
                       rotation=angle, rotation_mode="anchor",
                       bbox=dict(boxstyle="round,pad=0.25", facecolor=bg,
                                 edgecolor=color, alpha=0.9, linewidth=0.8))

    if not draw_cp:
        # Antenna without counterpoise: draw the RETURN CONDUCTOR that the
        # model actually uses (ground rod or coax-braid stub).  Leaving it out
        # would show a wire fed against nothing, which is exactly the model
        # NEC-2 cannot solve.
        if no_cp_return == "ground-rod":
            _ret_bottom = 0.0
            _ret_txt    = T("construction_return_rod")
        else:
            _ret_bottom = max(0.0 if _perfect_cd else _floor_cd,
                              z_near - max(0.0, float(cp_stub_len_m)))
            _ret_txt    = T("construction_return_stub").format(z_near - _ret_bottom)
        ax.plot([0.0, 0.0], [z_near, _ret_bottom],
                color=ACCENT2, linewidth=3, zorder=3,
                label=T("construction_return_label"))
        ax.scatter([0.0], [_ret_bottom], s=55, color=ACCENT2,
                   edgecolors=TEXT, linewidths=1, zorder=5)
        # Placed to the RIGHT of the mast (not the left, like the "Support
        # height" dimension label) so the two never overlap: both share the
        # same vertical range next to x=0, and the force-directed placer
        # cannot reliably separate two same-side labels that start on top
        # of each other.
        t_nocp = ax.text(0.4, (z_near + _ret_bottom) / 2.0, _ret_txt,
                         color=ACCENT2, fontsize=9, ha="left", va="center",
                         fontweight="bold",
                         bbox=dict(boxstyle="round,pad=0.25", facecolor=BG,
                                   edgecolor=ACCENT2, alpha=0.9, linewidth=0.8))
        placer.register(t_nocp, priority=6)

    elif vert_len > 0.01:
        # Bent wire: angled segment down then horizontal remainder
        ax.plot([cp_x0, -_cxe], [z_near, cp_bottom_z],
                color=ACCENT2, linewidth=3, zorder=3, linestyle=(0, (1, 0)))
        ax.plot([-_cxe, -(_cxe + horiz_rem)], [cp_bottom_z, cp_bottom_z],
                color=ACCENT2, linewidth=3, zorder=3,
                label=T("construction_cp_label"))
        ax.scatter([-(_cxe + horiz_rem)], [cp_bottom_z],
                   s=55, color=ACCENT2, edgecolors=TEXT, linewidths=1, zorder=5)

        # CP length label: above the horizontal segment (or angled if no horiz)
        if horiz_rem > 0.05:
            # Above the horizontal segment
            t_cp = _wire_label(ax, -_cxe, cp_bottom_z, -(_cxe + horiz_rem), cp_bottom_z,
                               f"{T('construction_dim_cp')}\n{cp_label_total}",
                               ACCENT2, BG, gap=0.5)
        else:
            # Above the angled segment
            t_cp = _wire_label(ax, cp_x0, z_near, -_cxe, cp_bottom_z,
                               f"{T('construction_dim_cp')}\n{cp_label_total}",
                               ACCENT2, BG, gap=0.5)
        placer.register(t_cp, priority=7)

        # Angle annotation on the angled segment
        if vert_len > 0.05:
            t_ang = ax.text(cp_x0 + 0.15, (z_near + cp_bottom_z) / 2,
                            f"{cp_angle_deg:.1f}°", color=ACCENT2, fontsize=8,
                            rotation=90, va="center", ha="left",
                            bbox=dict(boxstyle="round,pad=0.15", facecolor=BG,
                                      edgecolor="none", alpha=0.85))
            placer.register(t_ang, priority=3)

        # Ground-level reach dim line
        _cp_reach_x = _cxe + horiz_rem
        t_reach = _dim_line(ax, (0, -0.9), (-_cp_reach_x, -0.9),
                            f"{T('construction_dim_cp_reach')}\n{_cp_reach_x:.2f} m",
                            color=ACCENT2, text_color=TEXT, below=True, bg=BG)
        placer.register(t_reach, priority=5)

    else:
        # Straight wire at angle
        ax.plot([cp_x0, -_cxe], [z_near, _cze],
                color=ACCENT2, linewidth=3, zorder=3,
                label=T("construction_cp_label"))
        ax.scatter([cp_x0, -_cxe], [z_near, _cze],
                   s=55, color=ACCENT2, edgecolors=TEXT, linewidths=1, zorder=5)

        # CP label above the wire segment
        t_cp = _wire_label(ax, cp_x0, z_near, -_cxe, _cze,
                           f"{T('construction_dim_cp')}\n{cp_label_total}",
                           ACCENT2, BG, gap=0.5)
        placer.register(t_cp, priority=7)

        # Ground-level reach dim line
        t_reach = _dim_line(ax, (0, -0.9), (-_cxe, -0.9),
                            f"{T('construction_dim_cp_reach')}\n{_cxe:.2f} m",
                            color=ACCENT2, text_color=TEXT, below=True, bg=BG)
        placer.register(t_reach, priority=5)

    # ── height annotations ────────────────────────────────────────────────
    t_ht = _vdim_line(ax, -1.1, 0, z_near,
                      f"{T('construction_dim_height')}\n{z_near:.2f} m",
                      color="#5b6b7c", text_color=TEXT, bg=BG)
    placer.register(t_ht, priority=4)

    # Counterpoise far-end height (mirrors the radiator's far-end height label)
    if draw_cp and abs(_cze - z_near) > 0.02:
        t_cpht = _vdim_line(ax, -_cxe - 0.9, 0, _cze,
                            f"{T('construction_dim_cp_end')}\n{_cze:.2f} m",
                            color=ACCENT2, text_color=TEXT,
                            small=True, bg=BG)
        placer.register(t_cpht, priority=3)

    # ── far-end height label (sloped radiator) ────────────────────────────
    # Place label above and to the right of the far endpoint so it never
    # overlaps the wire or the endpoint dot.
    # A short diagonal leader runs from the dot to the label anchor.
    if abs(z_far - z_near) > 0.05:
        _ldr_x = x_far + 0.5   # leader endpoint: slightly right of dot
        _ldr_z = z_far + 0.5   # and above it — clear of the wire
        ax.plot([x_far, _ldr_x], [z_far, _ldr_z],
                color=ACCENT, linewidth=1, linestyle="--", alpha=0.8, zorder=3)
        t_fh = ax.text(_ldr_x + 0.1, _ldr_z,
                       f"{T('construction_dim_far_height')}\n{z_far:.2f} m",
                       color=TEXT, fontsize=8.5, ha="left", va="bottom",
                       fontweight="bold",
                       bbox=dict(boxstyle="round,pad=0.25", facecolor=BG,
                                 edgecolor=ACCENT, alpha=0.9, linewidth=0.8))
        placer.register(t_fh, priority=6)

    # ── sloped: horizontal support distance ───────────────────────────────
    if slope_end is not None:
        t_supp = _dim_line(ax, (0, -0.9), (x_far, -0.9),
                           f"{T('construction_dim_far_support')}\n{x_far:.2f} m",
                           color=ACCENT, text_color=TEXT, below=True, bg=BG)
        placer.register(t_supp, priority=5)

    # ── axes decoration ───────────────────────────────────────────────────
    ax.set_xlabel(T("construction_xlabel"), color=SUBTEXT, fontsize=9)
    ax.set_ylabel(T("construction_ylabel"), color=SUBTEXT, fontsize=9)
    ax.tick_params(colors=SUBTEXT, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.6)
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.85,
              facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)

    # ── wire diameter caption ───────────────────────────────────────────
    # The gauge simulated is exactly as load-bearing for R/Q as the lengths
    # above, so the builder must be able to read it off the plan, not just
    # know it was baked into the deck as a silent default.
    _wire_diam_mm = 2.0 * wire_radius_mm
    t_diam = ax.text(
        0.99, 0.02, f"{T('construction_spec_wire_diam')}: {_wire_diam_mm:.2f} mm",
        transform=ax.transAxes, color=SUBTEXT, fontsize=8.5,
        ha="right", va="bottom", style="italic",
    )
    placer.register(t_diam, priority=2)

    # ── resolve all label overlaps and clamp inside the axes box ─────────
    placer.resolve(fig, ax, margin=0.18)

    plt.savefig(out_png, dpi=170, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(T("construction_saved").format(out_png))


# ═══════════════════════════════════════════════════════════════════════════
# PDF BROCHURE EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def write_pdf_brochure(
    best: "CandidateResult",
    calc_rows: List[CalcRow],
    unun_ratio: float,
    mode: str,
    out_path: str,
    construction_png: Optional[str] = None,
    radiation_png: Optional[str] = None,
    wire_height_m: float = DEFAULT_HEIGHT_M,
    unun_result: Optional["UnUnResult"] = None,
    use_counterpoise: bool = True,
    no_cp_return: str = DEFAULT_NO_CP_RETURN,
    cp_stub_len_m: float = DEFAULT_CP_STUB_LEN_M,
    segs_final: Optional[int] = None,
    conv_report: Optional["ConvergenceReport"] = None,
) -> bool:
    """
    Render a modern, commercial-brochure-style PDF datasheet summarising the
    optimisation result.  Order of sections:

        1. Cover / configuration overview
        2. Construction diagram
        3. Performance report (specs + per-band table)
        4. Best candidate detailed breakdown
        5. UnUn ratio analysis
        6. Radiation pattern diagrams

    Returns True on success, False if reportlab is unavailable or required
    images are missing.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            Image as RLImage, HRFlowable, PageBreak,
        )
        from reportlab.platypus.flowables import KeepTogether
    except ImportError:
        print(T("pdf_skip_no_reportlab"))
        return False

    if not construction_png or not os.path.isfile(construction_png):
        construction_png = None
    if not radiation_png or not os.path.isfile(radiation_png):
        radiation_png = None

    # ── palette ────────────────────────────────────────────────────────
    NAVY    = colors.HexColor("#0f2a43")
    ACCENT  = colors.HexColor("#1f7a8c")
    ACCENT2 = colors.HexColor("#22a699")
    LIGHT   = colors.HexColor("#f4f7f9")
    GREY    = colors.HexColor("#6b7785")
    GOOD    = colors.HexColor("#1f9d55")
    WARN    = colors.HexColor("#d18f00")
    BAD     = colors.HexColor("#c0392b")

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "BrTitle", parent=styles["Title"], fontSize=24, leading=28,
        textColor=NAVY, spaceAfter=2, alignment=TA_LEFT)
    style_subtitle = ParagraphStyle(
        "BrSubtitle", parent=styles["Normal"], fontSize=12, leading=15,
        textColor=ACCENT, spaceAfter=10, alignment=TA_LEFT)
    style_h1 = ParagraphStyle(
        "BrH1", parent=styles["Heading1"], fontSize=15, leading=18,
        textColor=NAVY, spaceBefore=14, spaceAfter=8)
    style_h2 = ParagraphStyle(
        "BrH2", parent=styles["Heading2"], fontSize=11, leading=14,
        textColor=ACCENT, spaceBefore=8, spaceAfter=4)
    style_body = ParagraphStyle(
        "BrBody", parent=styles["Normal"], fontSize=9.5, leading=13.5,
        textColor=colors.HexColor("#222b33"))
    style_small = ParagraphStyle(
        "BrSmall", parent=styles["Normal"], fontSize=8, leading=10.5,
        textColor=GREY)
    style_kpi_label = ParagraphStyle(
        "BrKpiLabel", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.white, alignment=TA_CENTER)
    style_kpi_value = ParagraphStyle(
        "BrKpiValue", parent=styles["Normal"], fontSize=15, leading=18,
        textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold")

    story = []

    # ── HEADER / COVER BAND ───────────────────────────────────────────────
    if best.cp_end_z_m is not None:
        cp_type_label = (f"{wire_height_m:.2f} m → {best.cp_end_z_m:.2f} m"
                         f"  ({best.cp_angle_deg:.1f}°)")
    else:
        cp_type_label = f"{best.cp_angle_deg:.1f}°"
    if not use_counterpoise:
        # Name the conductor the model actually feeds against, so the brochure
        # never suggests the wire was worked against nothing.
        cp_type_label = (T("pdf_spec_cp_none_rod") if no_cp_return == "ground-rod"
                         else T("pdf_spec_cp_none_stub").format(cp_stub_len_m))

    header_tbl = Table(
        [[Paragraph(T("pdf_brand_title"), style_title),
          Paragraph(f"{best.wire_len_m:.2f} m", style_kpi_value)],
         [Paragraph(T("pdf_brand_subtitle"), style_subtitle),
          Paragraph(T("pdf_spec_wire_len").upper(), style_kpi_label)]],
        colWidths=[125 * mm, 45 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("BACKGROUND", (1, 0), (1, 1), NAVY),
        ("SPAN", (1, 0), (1, 0)),
        ("SPAN", (1, 1), (1, 1)),
        ("TOPPADDING", (1, 0), (1, 1), 8),
        ("BOTTOMPADDING", (1, 0), (1, 1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (1, 0), (1, -1), 8),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT2, spaceBefore=6, spaceAfter=10))

    # ── CONFIGURATION OVERVIEW ─────────────────────────────────────────────
    story.append(Paragraph(T("pdf_section_overview"), style_h1))

    active = [r for r in calc_rows if r.active]
    band_names = ", ".join(cr.band for cr in active)
    slope_note = ""
    if best.wire_slope_end_m is not None:
        slope_note = (T("report_wire_geom_sloped_detail")
                       .format(wire_height_m, best.wire_slope_end_m))
    else:
        slope_note = T("report_wire_geom_horizontal_const")

    spec_rows = [
        [T("pdf_spec_wire_len"),  f"{best.wire_len_m:.3f} m"],
        [T("pdf_spec_cp_len"),    (f"{best.cp_len_m:.3f} m" if use_counterpoise
                                   else cp_type_label)],
        [T("pdf_spec_cp_type"),   cp_type_label],
        [T("pdf_spec_height"),    f"{wire_height_m:.2f} m"],
        [T("pdf_spec_wire_diam"), f"{WIRE_RADIUS_M * 2000.0:.2f} mm"],
        [T("pdf_spec_unun"),      f"{unun_ratio:g} : 1"],
        [T("pdf_spec_bands"),     band_names],
        [T("pdf_spec_mode"),      mode.upper()],
        [T("pdf_spec_score"),     f"{best.score_combined:.3f}"],
        [T("pdf_detail_geometry"), slope_note],
    ]
    # Take-off angle of the lowest active band: the single number that tells
    # the reader whether this antenna works the horizon or the clouds.
    if best.pattern_ok and best.band_toa:
        _low_band = min(
            [c for c in calc_rows if c.active and c.band in best.band_toa],
            key=lambda c: c.freq_mhz, default=None)
        if _low_band is not None:
            _t = best.band_toa[_low_band.band]
            _g = best.band_gain_max.get(_low_band.band)
            _txt = f"{_t:.0f}\u00b0 ({_low_band.band}"
            _txt += f", {_g:.1f} dBi)" if _g is not None else ")"
            spec_rows.append([T("pdf_spec_toa"), _txt])
    spec_table = Table(
        [[Paragraph(f"<b>{k}</b>", style_body), Paragraph(v, style_body)]
         for k, v in spec_rows],
        colWidths=[60 * mm, 110 * mm],
    )
    spec_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(KeepTogether(spec_table))
    story.append(Spacer(1, 6 * mm))

    # ── 1. CONSTRUCTION DIAGRAM ────────────────────────────────────────────
    if construction_png:
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(construction_png) as _im:
                iw, ih = _im.size
            avail_w = 170 * mm
            avail_h = 150 * mm
            scale = min(avail_w / iw, avail_h / ih)
            img = RLImage(construction_png, width=iw * scale, height=ih * scale)
            img.hAlign = "CENTER"
            story.append(img)
        except Exception:
            story.append(Paragraph("(construction diagram unavailable)", style_small))
    else:
        story.append(Paragraph("(construction diagram unavailable)", style_small))

    story.append(PageBreak())

    # ── 2. PERFORMANCE REPORT ──────────────────────────────────────────────
    story.append(Paragraph(T("pdf_section_performance"), style_h1))

    table_data = [[T("pdf_col_band"), T("pdf_col_freq"), T("pdf_col_vswr"), T("pdf_col_rating")]]
    row_colors = []
    for cr in active:
        b = cr.band
        v = best.band_vswr.get(b, 999.0)
        a = best.band_avoidance.get(b, 0.0)
        rating = re.sub(r'[^\w\s★]', '', _avoidance_rating(a)).strip()
        if v <= 1.5:
            vcolor = GOOD
        elif v <= 3.0:
            vcolor = ACCENT2
        elif v <= 6.0:
            vcolor = WARN
        else:
            vcolor = BAD
        table_data.append([b, f"{cr.freq_mhz:.3f}", f"{v:.2f}", rating])
        row_colors.append(vcolor)

    perf_table = Table(table_data, colWidths=[35 * mm, 35 * mm, 35 * mm, 65 * mm])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
    for i, c in enumerate(row_colors, start=1):
        style_cmds.append(("TEXTCOLOR", (2, i), (2, i), c))
        style_cmds.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
    perf_table.setStyle(TableStyle(style_cmds))
    story.append(KeepTogether([Paragraph(T("pdf_section_perband"), style_h2), perf_table]))
    story.append(Spacer(1, 6 * mm))

    # NEC2 / impedance details
    if any(b in best.band_R_ant for b in (cr.band for cr in active)):
        # Same rounding-to-uncertainty rule as the text report's per-band
        # table (see fmt_imp_with_unc / imp_uncertainties): printing R_ant to
        # five significant figures when the segmentation error is ~3% of R
        # is false precision, and the PDF is the document most likely to be
        # printed and taken to the bench. R_tx/X_tx are the UnUn-transformed
        # values, so they carry the same relative uncertainty as R_ant/X_ant
        # even though we don't recompute a separate absolute figure for them
        # here — matching the text report, which also leaves them bare.
        _spw_tab = (best.segs_per_half_wave or segs_final or SEGS_PER_HALF_WAVE)
        _unc_tab = (conv_report.r_uncertainty_pct() if conv_report is not None
                    else estimated_imp_uncertainty_pct(_spw_tab))
        _unc_tab_x = (conv_report.x_uncertainty_ohm() if conv_report is not None
                      else None)
        imp_data = [[T("pdf_col_band"), T("pdf_col_r_ant"), T("pdf_col_x_ant"),
                     T("pdf_col_r_tx"), T("pdf_col_x_tx"), T("pdf_col_source")]]
        for cr in active:
            b = cr.band
            R_a = best.band_R_ant.get(b, 0.0)
            X_a = best.band_X_ant.get(b, 0.0)
            src = best.band_imp_src.get(b, "?")
            if mode == "nec2" and src.startswith("NEC2"):
                _u = abs(R_a) * _unc_tab / 100.0
                Ra_s = fmt_imp_with_unc(R_a, _u)
                # _unc_tab_x is None when --converge did not run: X is then
                # printed bare rather than carrying the R uncertainty.
                Xa_s = fmt_imp_with_unc(X_a, _unc_tab_x, signed=True)
            else:
                Ra_s, Xa_s = f"{R_a:.1f}", f"{X_a:+.1f}"
            imp_data.append([
                b,
                Ra_s,
                Xa_s,
                f"{best.band_R_tx.get(b, 0.0):.2f}",
                f"{best.band_X_tx.get(b, 0.0):+.2f}",
                src,
            ])
        imp_table = Table(imp_data, colWidths=[22 * mm, 28 * mm, 28 * mm, 28 * mm, 28 * mm, 36 * mm])
        imp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(KeepTogether([Paragraph(T("report_per_band_imp"), style_h2), imp_table]))
        if mode == "nec2":
            _x_note = (T("pdf_imp_precision_x_measured").format(_unc_tab_x)
                       if _unc_tab_x is not None else "")
            story.append(Paragraph(
                T("pdf_imp_precision_note").format(_spw_tab, _unc_tab, _x_note),
                style_small))
        story.append(Spacer(1, 6 * mm))

    # ── 2b. BEST CANDIDATE — DETAILED BREAKDOWN ───────────────────────────
    detail_data = [
        [T("pdf_detail_wire_len"),   f"{best.wire_len_m:.3f} m"],
        [T("pdf_detail_cp_len"),     (f"{best.cp_len_m:.3f} m  ({best.cp_angle_deg:.1f}° from vertical"
                                      + (f", end z={best.cp_end_z_m:.3f} m)" if best.cp_end_z_m is not None else ")"))],
    ]
    if best.wire_slope_end_m is not None:
        detail_data.append([T("pdf_detail_geometry"),
                             T("report_wire_geom_sloped_detail").format(wire_height_m, best.wire_slope_end_m)])
    else:
        detail_data.append([T("pdf_detail_geometry"), T("pdf_geom_horizontal")])
    detail_data += [
        [T("pdf_detail_score"),        f"{best.score_combined:.4f}"],
        [T("pdf_detail_vswr_penalty"), f"{best.score_vswr:.4f}"],
        [T("pdf_detail_avoid_act"),    f"{best.score_avoidance_active:.4f}"],
        [T("pdf_detail_avoid_all"),    f"{best.score_avoidance:.4f}"],
        [T("pdf_detail_nec2"),         T("report_nec2_yes") if best.nec2_used else T("report_nec2_no")],
    ]
    if best.nec2_used and not best.nec2_ok:
        detail_data.append([T("pdf_detail_nec2_trust"),
                             (T("report_nec2_untrusted").strip()
                              + ((" " + best.note.strip()) if best.note else ""))])
    if best.pattern_ok and best.band_toa:
        _parts = []
        for _c in [c for c in calc_rows if c.active]:
            _t = best.band_toa.get(_c.band)
            if _t is None:
                continue
            _g = best.band_gain_max.get(_c.band, 0.0)
            _parts.append(f"{_c.band}: {_g:.1f} dBi @ {_t:.0f}\u00b0")
        if _parts:
            detail_data.append([T("pdf_detail_gain"), "; ".join(_parts)])
    detail_table = Table(
        [[Paragraph(f"<b>{row[0]}</b>", style_body), Paragraph(str(row[1]), style_body)]
         for row in detail_data],
        colWidths=[70 * mm, 100 * mm],
    )
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(KeepTogether([Paragraph(T("report_best_header"), style_h1), detail_table]))
    story.append(Spacer(1, 4 * mm))

    # Per-band avoidance + VSWR quality table
    active_bands_list = [cr for cr in calc_rows if cr.active]
    if active_bands_list:
        pb_hdr = [T("construction_col_band"), T("construction_col_freq"),
                  T("construction_col_vswr"), T("construction_col_quality"),
                  T("pdf_col_avoidance")]
        pb_data = [pb_hdr]
        pb_vswr_colors = []
        for cr in active_bands_list:
            b = cr.band
            v = best.band_vswr.get(b, 999.0)
            a = best.band_avoidance.get(b, 0.0)
            rating = re.sub(r'[^\w\s★]', '', _avoidance_rating(a)).strip()
            if v <= 1.5:
                vlabel = T("vswr_excellent"); vc = GOOD
            elif v <= 3.0:
                vlabel = T("vswr_good");      vc = ACCENT2
            elif v <= 6.0:
                vlabel = T("vswr_marginal");  vc = WARN
            else:
                vlabel = T("vswr_poor");      vc = BAD
            pb_data.append([b, f"{cr.freq_mhz:.3f}", f"{v:.2f}  {vlabel}", rating, f"{a:.4f}"])
            pb_vswr_colors.append(vc)
        pb_table = Table(pb_data, colWidths=[20 * mm, 22 * mm, 42 * mm, 46 * mm, 22 * mm])
        pb_style = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]
        for _i, _vc in enumerate(pb_vswr_colors, start=1):
            pb_style.append(("TEXTCOLOR", (2, _i), (2, _i), _vc))
            pb_style.append(("FONTNAME",  (2, _i), (2, _i), "Helvetica-Bold"))
        pb_table.setStyle(TableStyle(pb_style))
        story.append(KeepTogether(pb_table))
        story.append(Spacer(1, 6 * mm))

    # ── 2c. UnUn RATIO ANALYSIS ───────────────────────────────────────────
    if unun_result is not None:
        cont_n = unun_result.best_continuous_ratio
        boundary_note = ""
        if cont_n >= 99.5:
            boundary_note = "  " + T("report_unun_cont_hit_upper")
        elif cont_n <= 1.5:
            boundary_note = "  " + T("report_unun_cont_hit_lower")

        bands_active = [cr.band for cr in calc_rows if cr.active]

        unun_summary = [
            [T("pdf_unun_used_label"),
             f"{unun_ratio:.1f}:1"],
            [T("pdf_unun_continuous_label"),
             f"{cont_n:.2f}:1  ({T('pdf_unun_penalty_label')}: "
             f"{unun_result.best_continuous_score:.4f}){boundary_note}"],
            [T("pdf_unun_best_std_label"),
             f"{unun_result.best_standard_ratio:.0f}:1  ("
             f"{T('pdf_unun_penalty_label')}: "
             f"{unun_result.best_standard_score:.4f})"],
        ]
        cur_score = unun_result.ratio_score.get(unun_ratio, 999.0)
        std_n = unun_result.best_standard_ratio
        std_score = unun_result.best_standard_score
        if cur_score > 0 and (cur_score - std_score) > 0.001 and abs(std_n - unun_ratio) > 0.5:
            unun_summary.append([
                T("pdf_unun_recommendation"),
                T("report_unun_improve").format(std_n, cur_score - std_score, 100.0 * (cur_score - std_score) / cur_score),
            ])
        else:
            unun_summary.append([T("pdf_unun_recommendation"), T("report_unun_already_optimal").format(unun_ratio)])

        unun_sum_table = Table(
            [[Paragraph(f"<b>{row[0]}</b>", style_body), Paragraph(str(row[1]), style_body)]
             for row in unun_summary],
            colWidths=[60 * mm, 110 * mm],
        )
        unun_sum_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(KeepTogether([Paragraph(T("report_unun_section"), style_h1), unun_sum_table]))
        story.append(Spacer(1, 4 * mm))

        # Standard ratio sweep table
        sweep_hdr = [T("pdf_col_ratio"), T("pdf_col_score")] + \
                    [f"{T('pdf_col_vswr')}@{b}" for b in bands_active]
        sweep_data = [sweep_hdr]
        for n in sorted(unun_result.ratio_score.keys()):
            score = unun_result.ratio_score[n]
            row = [f"{n:.4g}:1", f"{score:.4f}"]
            for b in bands_active:
                row.append(f"{unun_result.ratio_band_vswr[n].get(b, 999):.2f}")
            sweep_data.append(row)

        n_cols_sweep = len(sweep_hdr)
        col_w_each = 170 * mm / n_cols_sweep
        sweep_table = Table(sweep_data, colWidths=[col_w_each] * n_cols_sweep)
        sweep_style = [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]
        # Highlight best standard ratio row and current ratio row
        for _ri, n in enumerate(sorted(unun_result.ratio_score.keys()), start=1):
            if n == unun_result.best_standard_ratio:
                sweep_style.append(("BACKGROUND", (0, _ri), (-1, _ri), GOOD))
                sweep_style.append(("TEXTCOLOR",  (0, _ri), (-1, _ri), colors.white))
            elif n == unun_ratio:
                sweep_style.append(("BACKGROUND", (0, _ri), (-1, _ri), colors.HexColor("#eef4ff")))
        sweep_table.setStyle(TableStyle(sweep_style))
        story.append(KeepTogether([Paragraph(T("report_std_sweep"), style_h2), sweep_table]))

        # Per-band antenna-side impedance and optimal ratio
        if unun_result.band_impedances:
            story.append(Spacer(1, 4 * mm))
            imp_hdr2 = [T("pdf_col_band"), T("pdf_col_r_ant"), T("pdf_col_x_ant"),
                        T("pdf_col_z_ant"), T("pdf_col_theta"),
                        T("pdf_col_best_ratio")]
            imp_data2 = [imp_hdr2]
            for bname, R_a, X_a in unun_result.band_impedances:
                Z_a   = math.hypot(R_a, X_a)
                theta = math.degrees(math.atan2(X_a, R_a))
                opt_n = unun_result.per_band_best_ratio.get(bname)
                opt_n_str = f"{opt_n:.2f}:1" if opt_n is not None else T("pdf_na")
                imp_data2.append([bname, f"{R_a:.1f}", f"{X_a:+.1f}",
                                   f"{Z_a:.1f}", f"{theta:+.1f}", opt_n_str])
            imp_table2 = Table(imp_data2,
                colWidths=[20 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm, 44 * mm])
            imp_table2.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6dee3")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d6dee3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(KeepTogether([Paragraph(T("report_ant_impedance"), style_h2), imp_table2]))
        story.append(Spacer(1, 6 * mm))
    story.append(PageBreak())
    story.append(Paragraph(T("pdf_section_radiation"), style_h1))
    if radiation_png:
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(radiation_png) as _im:
                iw, ih = _im.size
            avail_w = 170 * mm
            avail_h = 220 * mm
            scale = min(avail_w / iw, avail_h / ih)
            img = RLImage(radiation_png, width=iw * scale, height=ih * scale)
            img.hAlign = "CENTER"
            story.append(img)
        except Exception:
            story.append(Paragraph("(radiation diagrams unavailable)", style_small))
    else:
        story.append(Paragraph("(radiation diagrams unavailable — NEC2 mode required)", style_small))

    # ── FOOTER NOTE ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.6, color=GREY, spaceAfter=4))
    story.append(Paragraph(T("pdf_footer"), style_small))

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(
            doc.pagesize[0] - 15 * mm, 12 * mm,
            f"{T('pdf_brand_title')} — {best.wire_len_m:.2f} m / {best.cp_len_m:.2f} m "
            f"{cp_type_label}    |    {doc.page}")
        canvas.setStrokeColor(ACCENT2)
        canvas.setLineWidth(1.2)
        canvas.line(15 * mm, 16 * mm, doc.pagesize[0] - 15 * mm, 16 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=15 * mm, bottomMargin=20 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
        title=T("pdf_brand_title"), author="NEC2 Antenna Length Optimizer",
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# UNUN / TRANSMATCH DESIGN CALCULATORS
# ═══════════════════════════════════════════════════════════════════════════
#
# Port of the "UnUn-Transmatch.xlsx" workbook (LU3VEA, CC0 v1.0):
#   • Sheet "UnUn Calculator"       → unun_design() + unun_multiband()
#   • Sheet "Transmatch Calculator" → transmatch_design()
#   • Sheet "Toroid_Database"       → TOROID_DB
#
# Every routine is pure (no I/O, no GUI dependency) so the CLI, the report
# writer and the Tk GUI can all share exactly the same numbers.

# Core name → geometry / magnetics.  AL in nH/N², dimensions in mm, Ae in cm².
TOROID_DB: Dict[str, Dict[str, float]] = {
    # B_sat (mT): approximate recommended flux-density ceiling for RF (HF)
    # duty, per material — NOT a single "all FT- cores" constant. Mix 43 and
    # Mix 61 in particular differ substantially in saturation flux density.
    "FT-114-43": {"material": "Ferrite Mix 43",    "AL": 510.0,  "OD": 29.0,  "ID": 19.0,  "H": 7.5,  "Ae": 0.38, "B_sat": 200.0},
    "FT-140-43": {"material": "Ferrite Mix 43",    "AL": 885.0,  "OD": 35.6,  "ID": 22.9,  "H": 12.7, "Ae": 0.63, "B_sat": 200.0},
    "FT-240-43": {"material": "Ferrite Mix 43",    "AL": 1075.0, "OD": 61.0,  "ID": 35.6,  "H": 12.7, "Ae": 1.52, "B_sat": 200.0},
    "FT-114-31": {"material": "Ferrite Mix 31",    "AL": 800.0,  "OD": 29.0,  "ID": 19.0,  "H": 7.5,  "Ae": 0.38, "B_sat": 200.0},
    "FT-140-31": {"material": "Ferrite Mix 31",    "AL": 1390.0, "OD": 35.6,  "ID": 22.9,  "H": 12.7, "Ae": 0.63, "B_sat": 200.0},
    "FT-240-31": {"material": "Ferrite Mix 31",    "AL": 1800.0, "OD": 61.0,  "ID": 35.6,  "H": 12.7, "Ae": 1.52, "B_sat": 200.0},
    "FT-114-52": {"material": "Ferrite Mix 52",    "AL": 175.0,  "OD": 29.0,  "ID": 19.0,  "H": 7.5,  "Ae": 0.38, "B_sat": 200.0},
    "FT-140-52": {"material": "Ferrite Mix 52",    "AL": 225.0,  "OD": 35.6,  "ID": 22.9,  "H": 12.7, "Ae": 0.63, "B_sat": 200.0},
    "FT-240-52": {"material": "Ferrite Mix 52",    "AL": 300.0,  "OD": 61.0,  "ID": 35.6,  "H": 12.7, "Ae": 1.52, "B_sat": 200.0},
    "FT-114-61": {"material": "Ferrite Mix 61",    "AL": 79.3,   "OD": 29.0,  "ID": 19.0,  "H": 7.5,  "Ae": 0.38, "B_sat": 236.0},
    "FT-140-61": {"material": "Ferrite Mix 61",    "AL": 140.0,  "OD": 35.6,  "ID": 22.9,  "H": 12.7, "Ae": 0.63, "B_sat": 236.0},
    "FT-240-61": {"material": "Ferrite Mix 61",    "AL": 170.0,  "OD": 61.0,  "ID": 35.6,  "H": 12.7, "Ae": 1.52, "B_sat": 236.0},
    "T-130-2":   {"material": "Iron Powder Mix 2", "AL": 11.0,   "OD": 33.0,  "ID": 19.8,  "H": 11.1, "Ae": 0.85, "B_sat": 300.0},
    "T-200-2":   {"material": "Iron Powder Mix 2", "AL": 12.0,   "OD": 50.8,  "ID": 31.8,  "H": 14.0, "Ae": 1.58, "B_sat": 300.0},
    "T-130-6":   {"material": "Iron Powder Mix 6", "AL": 9.6,    "OD": 33.0,  "ID": 19.8,  "H": 11.1, "Ae": 0.85, "B_sat": 300.0},
    "T-200-6":   {"material": "Iron Powder Mix 6", "AL": 11.6,   "OD": 50.8,  "ID": 31.8,  "H": 14.0, "Ae": 1.58, "B_sat": 300.0},
}

DEFAULT_TOROID = "FT-240-31"

# ── Core loss model ────────────────────────────────────────────────────────
#
# At HF a ferrite transformer is almost never limited by flux saturation: it
# is limited by CORE HEATING.  The saturation figure (Faraday) is a
# low-frequency limit — it rises linearly with frequency and with the number
# of primary turns, so above a couple of MHz it returns absurd numbers
# (kilovolts, hundreds of kW) while the real core is cooking at 150 W.
#
# The loss model used here:
#   1. µ = µ′ − jµ″ for the material at the working frequency (table below).
#   2. Q_core = µ′/µ″ → parallel loss resistance across the primary,
#      Rp = X_Lp · Q_core.
#   3. The load (r_in) and Rp sit in parallel across the primary, so the
#      fraction of input power that ends up as heat in the core is
#      r_in/(r_in + Rp).
#   4. The core can dissipate P_diss for a given temperature rise, from its
#      radiating surface area (Micrometals' surface-rise relation).
#   5. Continuous power limit = P_diss · (r_in + Rp)/r_in.
#
# µ′/µ″ values are read off the manufacturers' published curves (Fair-Rite
# mixes 31/43/52/61; Micrometals iron powder 2/6) and rounded.  They are
# engineering approximations — good for a factor-of-1.5 power estimate, NOT
# datasheet-grade numbers.  Interpolation is log-log in frequency.
MU_COMPLEX: Dict[str, List[Tuple[float, float, float]]] = {
    # material → [(f_MHz, µ′, µ″), …] ascending in frequency
    "Ferrite Mix 31": [
        (0.1, 1400.0,   15.0), (0.5, 1200.0, 130.0), (1.0,  900.0, 400.0),
        (3.0,  250.0,  380.0), (7.0,   80.0, 220.0), (10.0,  55.0, 175.0),
        (14.0,  40.0,  140.0), (21.0,  28.0, 105.0), (30.0,  20.0,  80.0),
    ],
    "Ferrite Mix 43": [
        (0.1,  800.0,    5.0), (0.5,  790.0,  15.0), (1.0,  780.0,  25.0),
        (3.0,  700.0,   90.0), (7.0,  500.0, 250.0), (10.0, 380.0, 300.0),
        (14.0, 250.0,  300.0), (21.0, 150.0, 250.0), (30.0, 100.0, 200.0),
    ],
    "Ferrite Mix 52": [
        (0.1,  250.0,    2.0), (1.0,  250.0,   6.0), (3.0,  245.0,  15.0),
        (7.0,  235.0,   35.0), (10.0, 225.0,  55.0), (14.0, 200.0,  90.0),
        (21.0, 160.0,  130.0), (30.0, 110.0, 150.0),
    ],
    "Ferrite Mix 61": [
        (0.1,  125.0,    0.3), (1.0,  125.0,   1.0), (3.0,  125.0,   2.5),
        (7.0,  125.0,    5.0), (10.0, 124.0,   8.0), (14.0, 120.0,  15.0),
        (21.0, 115.0,   30.0), (30.0, 100.0,  60.0),
    ],
    # Iron powder is very low loss across HF (that is what it is for).
    "Iron Powder Mix 2": [
        (0.1,   10.0,  0.005), (1.0,  10.0,  0.02), (7.0,  10.0, 0.06),
        (14.0,  10.0,   0.12), (30.0,  9.8,  0.30),
    ],
    "Iron Powder Mix 6": [
        (0.1,    8.5,  0.004), (1.0,   8.5,  0.015), (7.0,  8.5, 0.045),
        (14.0,   8.5,   0.09), (30.0,  8.4,   0.22),
    ],
}

# Temperature rise the power rating is quoted for.  40 °C over ambient is the
# usual amateur design target for a sealed-enclosure antenna transformer.
CORE_DELTA_T_C = 40.0


def core_mu(material: str, freq_mhz: float) -> Tuple[float, float]:
    """
    (µ′, µ″) for `material` at `freq_mhz`, log-log interpolated from
    MU_COMPLEX and clamped to the table's end points.

    Returns (nan, nan) for an unknown material so callers can degrade to the
    saturation figure instead of inventing a loss number.
    """
    tbl = MU_COMPLEX.get(material)
    if not tbl or freq_mhz <= 0:
        return float("nan"), float("nan")
    if freq_mhz <= tbl[0][0]:
        return tbl[0][1], tbl[0][2]
    if freq_mhz >= tbl[-1][0]:
        return tbl[-1][1], tbl[-1][2]
    for (f0, p0, q0), (f1, p1, q1) in zip(tbl, tbl[1:]):
        if f0 <= freq_mhz <= f1:
            t = math.log(freq_mhz / f0) / math.log(f1 / f0)
            mu_p = math.exp(math.log(p0) + t * math.log(p1 / p0))
            mu_pp = math.exp(math.log(max(q0, 1e-6))
                             + t * math.log(max(q1, 1e-6) / max(q0, 1e-6)))
            return mu_p, mu_pp
    return tbl[-1][1], tbl[-1][2]


def core_surface_area_cm2(core_d: Dict[str, float]) -> float:
    """
    Radiating surface of a toroid (both flat faces + outer wall + bore wall),
    in cm², from the OD/ID/H millimetre dimensions in TOROID_DB.
    """
    od = float(core_d["OD"]); idm = float(core_d["ID"]); h = float(core_d["H"])
    faces = 2.0 * (math.pi / 4.0) * (od ** 2 - idm ** 2)      # mm²
    outer = math.pi * od * h
    bore = math.pi * idm * h
    return (faces + outer + bore) / 100.0                      # mm² → cm²


def core_dissipation_w(a_surf_cm2: float, delta_t_c: float = CORE_DELTA_T_C) -> float:
    """
    Power a core of `a_surf_cm2` can dissipate for a `delta_t_c` surface
    temperature rise in still air, from the Micrometals relation
    ΔT(°C) = (P[mW] / A[cm²])^0.833  →  P = A · ΔT^(1/0.833).
    """
    if a_surf_cm2 <= 0 or delta_t_c <= 0:
        return 0.0
    return a_surf_cm2 * (delta_t_c ** (1.0 / 0.833)) / 1000.0   # mW → W

# E24 (5 %) preferred-value mantissas, as used by the workbook.
E24_MANTISSA = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
                3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1, 10.0]

# Copper resistivity used by the workbook's resistance column (Ω·m).
_RHO_CU = 1.724e-8
_MU0_H_PER_M = 4.0 * math.pi * 1e-7   # vacuum permeability


def _skin_effect_ratio(f_mhz: float, wire_dia_mm: float) -> float:
    """R_RF / R_DC for round copper wire at f_mhz (thick-wire limit d>>delta).

    Coil windings run at HF, where skin depth is tens of microns and the AC
    resistance is roughly an order of magnitude above DC (e.g. ~10x for 1 mm
    wire at 7 MHz, delta ~= 25 um).  Using bare DC resistance for an RF coil
    understates the loss substantially, so this factor is applied wherever a
    winding resistance is reported.  Floored at 1.0 (never below the DC
    value); this is a first-order approximation, not an exact Bessel-function
    solution.
    """
    if f_mhz <= 0 or wire_dia_mm <= 0:
        return 1.0
    delta_m = math.sqrt(_RHO_CU / (math.pi * f_mhz * 1e6 * _MU0_H_PER_M))
    if not math.isfinite(delta_m) or delta_m <= 0:
        return 1.0
    return max(1.0, (wire_dia_mm * 1e-3) / (4.0 * delta_m))


def e24_snap(value: float) -> float:
    """Snap a capacitance (or any positive value) to the nearest E24 step."""
    if value is None or not math.isfinite(value) or value <= 0:
        return float("nan")
    decade = 10.0 ** math.floor(math.log10(value))
    mant = value / decade
    best = min(E24_MANTISSA, key=lambda m: abs(m - mant))
    return round(best * decade, 6)


def _vswr_from_z(r: float, x: float, z0: float) -> float:
    """VSWR of load R+jX referenced to a real Z0."""
    if z0 <= 0:
        return float("nan")
    num = (r - z0) ** 2 + x * x
    den = (r + z0) ** 2 + x * x
    if den <= 0:
        return float("nan")
    g = math.sqrt(num / den)
    g = min(g, 0.999999)
    return (1.0 + g) / (1.0 - g)


def _gamma_from_z(r: float, x: float, z0: float) -> float:
    num = (r - z0) ** 2 + x * x
    den = (r + z0) ** 2 + x * x
    if den <= 0:
        return 1.0
    return math.sqrt(num / den)


def comp_reactance(comp_type: str, value: float, freq_mhz: float) -> float:
    """
    Reactance (Ω) of the fixed series component at an arbitrary frequency.

    comp_type: 'L' → value in µH   (X = +2πfL)
               'C' → value in pF   (X = −1/(2πfC))
    """
    if not value or freq_mhz <= 0:
        return 0.0
    if comp_type == "L":
        return 2.0 * math.pi * freq_mhz * value          # µH · MHz → Ω
    if comp_type == "C":
        return -1.0e6 / (2.0 * math.pi * freq_mhz * value)  # pF, MHz → Ω
    return 0.0


def unun_design(freq_mhz: float,
                r_in: float,
                x_in: float,
                r_out: float,
                x_out: float,
                core: str = DEFAULT_TOROID,
                np_turns: int = 15,
                wire_dia_mm: float = 2.0,
                fixed_ratio: Optional[float] = None,
                core_type: str = "core",
                coil_dia_mm: float = 50.0,
                space_mm: float = 1.0) -> Dict[str, object]:
    """
    Full UnUn / autotransformer design (workbook sheet "UnUn Calculator").

    fixed_ratio: when None (default), the impedance ratio is COMPENSATED
    automatically from r_out / r_in (matches the load as closely as the
    winding allows). When a positive number is given, that ratio (e.g. 9,
    49, 64) is used AS-IS instead — the turns are derived from it directly
    and r_out no longer drives the ratio (it is still used, unchanged, for
    the reactance-compensation and multi-band sections below).

    core_type: "core" (default) builds on a ferrite/powdered-iron toroid
    from TOROID_DB, exactly as before. "air" builds an air-core UnUn as a
    single-layer solenoid instead — same winding-ratio and reactance-
    compensation math (sections 2/2.1/3), but the winding geometry and the
    inductance (section 4) come from `coil_dia_mm` (former diameter) and
    `space_mm` (gap between turns), via the same Wheeler formula used by
    the Transmatch calculator, instead of the toroid's ID/OD/H/AL. Ferrite-
    only figures that have no air-core equivalent (max buildable turns from
    the bore, flux density, saturation, core loss / power rating) are not
    computed; the caller shows those sections as "not applicable" for air
    core instead of rendering ferrite numbers with a fabricated core.

    Returns a dict of numbers plus short status codes ('ok', 'err', 'warn',
    'high', 'limited', 'insufficient') that the caller renders in its own
    language.
    """
    is_air = (core_type == "air")
    core_d = None if is_air else TOROID_DB.get(core, TOROID_DB[DEFAULT_TOROID])
    r_in = max(float(r_in), 1e-9)
    freq_mhz = max(float(freq_mhz), 1e-9)
    np_turns = max(int(np_turns), 1)
    wire_dia_mm = max(float(wire_dia_mm), 1e-6)
    coil_dia_mm = max(float(coil_dia_mm), 1e-6)
    space_mm = max(float(space_mm), 0.0)

    # ── 2. Transformer properties ──────────────────────────────────────
    ratio_mode = "fixed" if fixed_ratio is not None and fixed_ratio > 0 else "compensate"
    ratio = float(fixed_ratio) if ratio_mode == "fixed" else r_out / r_in
    turns_ratio = math.sqrt(max(ratio, 0.0))
    ns_calc = np_turns * turns_ratio
    ns_act = max(int(round(ns_calc)), 1)
    if is_air:
        # No bore to fill on an air-core former — turns are limited only by
        # the winding length the builder chooses, which isn't a fixed input
        # here. There is no equivalent "maximum turns" figure to check.
        max_turns = None
    else:
        max_turns = int(round(0.8 * ((math.pi * core_d["ID"]) / wire_dia_mm)))
    ratio_act = (ns_act / np_turns) ** 2
    # x_out reflected to the PRIMARY (transceiver) side through the actual
    # turns ratio. This is informational only — it is NOT the plane used
    # to size the compensation component below (see comp_ref_plane).
    x_transformed = x_out / ratio_act if ratio_act else float("nan")

    # ── 2.1 Autotransformer winding ────────────────────────────────────
    # Valid only for the step-up case (ratio > 1): the primary tap sits
    # at n_tap turns and n_above additional turns are wound on top of it to
    # reach n_total. For ratio <= 1 that geometry is inverted (the tap
    # would have to sit ABOVE the total winding), so ns_act < np_turns and
    # n_above would silently go negative. Flag it instead of returning a
    # bogus winding count. In COMPENSATE mode ratio == r_out/r_in, so this
    # is equivalent to the old r_out > r_in test; in FIXED-ratio mode the
    # ratio itself (not r_out vs r_in) is what determines the geometry.
    autotransformer_ok = ratio > 1.0
    n_total = ns_act
    n_tap = np_turns
    n_above = n_total - n_tap
    if not autotransformer_ok:
        winding_code = "warn"
    elif n_above < 0:
        winding_code = "warn"
    else:
        winding_code = "ok"
    ratio_check = (n_total / n_tap) ** 2 if n_tap else float("nan")
    if is_air:
        pitch_mm = wire_dia_mm + space_mm
        wire_per_turn_m = round(math.pi * (coil_dia_mm / 1000.0), 3)
    else:
        wire_per_turn_m = round(math.pi * ((core_d["OD"] + core_d["ID"]) / 2.0) / 1000.0, 3)
    wire_total_m = round(n_total * wire_per_turn_m, 2)

    # ── 3. Reactance compensation ────────────────────────────────────────
    # Reference plane: LOAD side (antenna side), matching unun_multiband(),
    # which adds the component's reactance to X *before* dividing by ratio
    # (x_in_comp = (x + xc) / ratio). The series component is sized to
    # cancel x_out down to whatever residual is wanted at the TRANSMITTER
    # port (x_in) — x_in = 0 (the default) means "cancel it fully", but a
    # non-zero x_in (e.g. a known feedline/connector offset the operator
    # wants to pre-compensate for) is honoured too. x_in is specified at
    # the primary/transceiver plane, so it must be reflected to the load
    # plane before it can be combined with x_out: multiplying by ratio_act
    # is the inverse of x_transformed (which reflects load → primary), so
    # x_in * ratio_act is x_in's equivalent at the load plane.
    # The component must be installed on the antenna side of the winding;
    # if it is instead installed on the primary/transceiver side, its
    # value has to be computed from (x_out - x_in*ratio_act) reflected
    # through ratio_act, not from this load-plane figure directly.
    comp_ref_plane = "load"  # antenna side; matches unun_multiband()
    x_in_reflected = float(x_in) * ratio_act if ratio_act else 0.0
    x_comp = -(float(x_out) - x_in_reflected)
    if x_comp > 0:
        comp_kind, comp_unit = "L", "µH"
        comp_value = x_comp / (2.0 * math.pi * freq_mhz)          # µH
        comp_std = e24_snap(comp_value)
    elif x_comp < 0:
        comp_kind, comp_unit = "C", "pF"
        comp_value = 1.0e6 / (2.0 * math.pi * freq_mhz * abs(x_comp))   # pF
        comp_std = e24_snap(comp_value)
    else:
        comp_kind, comp_unit = "none", "-"
        comp_value = 0.0
        comp_std = 0.0

    # ── 4. Magnetics ───────────────────────────────────────────────────
    if is_air:
        # Single-layer air-core solenoid (Wheeler), same formula and inputs
        # (coil diameter, wire diameter, turn spacing) as the Transmatch
        # calculator's winding. There is no AL value on an air core.
        al = float("nan")
        lp_uh = wheeler_solenoid_uh(np_turns, coil_dia_mm, wire_dia_mm, space_mm)
        xlp = 2.0 * math.pi * freq_mhz * lp_uh
        mag_ok = xlp >= 4.0 * r_in
    else:
        al = core_d["AL"]
        lp_uh = al * (np_turns ** 2) / 1000.0
        xlp = 2.0 * math.pi * freq_mhz * lp_uh
        mag_ok = xlp >= 4.0 * r_in

    # ── 5. Core loss, saturation & power handling ──────────────────────
    #
    # Two independent limits, and the rating is the LOWER of the two:
    #
    #   • Flux (saturation): Faraday, V̂ = B̂·2πf·Np·Ae.  Scales with f and Np,
    #     so it is the binding limit only at the bottom of the spectrum.  At
    #     7 MHz on an FT-240 it returns kilovolts — a number that means
    #     nothing on its own and must never be presented as "the" rating.
    #
    #   • Heat (core loss): the real HF limit.  See the MU_COMPLEX block for
    #     the model.  An FT-240-43 at 7 MHz lands around 150–200 W continuous,
    #     which is what such a transformer actually survives; the same core in
    #     mix 31 lands an order of magnitude lower, because mix 31 above ~5 MHz
    #     is a choke material, not a transformer material.  The saturation
    #     figure cannot see that difference at all.
    #
    # None of this applies to an air core: there is no ferrite to saturate
    # and no core loss to dissipate. Every figure in this section is left
    # as None/NaN for air core, and the caller shows the section as "not
    # applicable" instead of a fabricated ferrite rating.
    if is_air:
        material = None
        ae_cm2 = float("nan")
        b_max_mt = float("nan")
        v_peak = float("nan")
        p_sat = float("nan")
        mu_p = mu_pp = float("nan")
        a_surf_cm2 = float("nan")
        p_diss_w = float("nan")
        q_core = rp_core = core_loss_frac = float("nan")
        loss_pct = float("nan")
        p_thermal = None
        p_max = float("nan")
        p_limited_by = "n/a"
        power_code = "n/a"
    else:
        material = core_d["material"]
        ae_cm2 = core_d["Ae"]
        b_max_mt = core_d.get("B_sat", 200.0 if core.startswith("FT-") else 300.0)
        v_peak = round((b_max_mt / 1000.0) * 2.0 * math.pi * (freq_mhz * 1e6)
                       * np_turns * (ae_cm2 * 1e-4), 1)
        p_sat = round(v_peak ** 2 / (2.0 * r_in))      # flux-limited (LF limit)

        mu_p, mu_pp = core_mu(core_d["material"], freq_mhz)
        a_surf_cm2 = round(core_surface_area_cm2(core_d), 1)
        p_diss_w = round(core_dissipation_w(a_surf_cm2, CORE_DELTA_T_C), 2)

        if mu_p == mu_p and mu_pp and mu_pp > 0:       # NaN-safe
            q_core = mu_p / mu_pp
            rp_core = xlp * q_core                      # Ω across the primary
            core_loss_frac = r_in / (r_in + rp_core)    # of input power
            p_thermal = round(p_diss_w * (r_in + rp_core) / r_in)
            loss_pct = round(100.0 * core_loss_frac, 2)
        else:                                           # material not tabulated
            q_core = float("nan")
            rp_core = float("nan")
            core_loss_frac = float("nan")
            p_thermal = None
            loss_pct = float("nan")

        # Rating = the binding limit.  Continuous / key-down (100 % duty);
        # SSB voice averages roughly half that, so it tolerates ~2x this.
        p_max = p_sat if p_thermal is None else min(p_sat, p_thermal)
        p_limited_by = ("flux" if p_thermal is None or p_sat <= p_thermal
                        else "heat")

        # Thresholds describe real continuous power, not saturation headroom.
        # With no loss data for the material there IS no power rating — the
        # flux figure alone would announce "high power" for a core that
        # might cook at 20 W.  Say "unknown" instead of guessing.
        if p_thermal is None:
            power_code = "unknown"
        elif p_max >= 1000:
            power_code = "high"
        elif p_max >= 400:
            power_code = "ok"
        elif p_max >= 100:
            power_code = "limited"
        else:
            power_code = "insufficient"

    # Legacy aliases: older report code read p_avg/sat_code.  They now carry
    # the loss-aware figure, so nothing silently keeps quoting the flux limit.
    p_avg = p_max
    sat_code = power_code

    return {
        "core": core, "core_type": core_type, "material": material,
        "freq_mhz": freq_mhz, "r_in": r_in, "x_in": float(x_in),
        "r_out": float(r_out), "x_out": float(x_out),
        "np": np_turns, "wire_dia_mm": wire_dia_mm,
        "coil_dia_mm": coil_dia_mm, "space_mm": space_mm,
        "ratio_mode": ratio_mode,
        "ratio": ratio, "turns_ratio": turns_ratio,
        "ns_calc": ns_calc, "ns": ns_act,
        "max_turns": max_turns,
        "turns_ok": (True if max_turns is None else ns_act <= max_turns),
        "ratio_actual": ratio_act, "x_transformed": x_transformed,
        "n_total": n_total, "n_tap": n_tap, "n_above": n_above,
        "autotransformer_ok": autotransformer_ok, "winding_code": winding_code,
        "ratio_check": ratio_check,
        "wire_per_turn_m": wire_per_turn_m, "wire_total_m": wire_total_m,
        "x_comp": x_comp, "comp_kind": comp_kind, "comp_unit": comp_unit,
        "comp_value": comp_value, "comp_std": comp_std,
        "comp_ref_plane": comp_ref_plane, "x_in_reflected": x_in_reflected,
        "al": al, "lp_uh": lp_uh, "xlp": xlp, "mag_ok": mag_ok,
        "ae_cm2": ae_cm2, "b_max_mt": b_max_mt,
        "v_peak": v_peak, "p_sat": p_sat,
        "mu_prime": mu_p, "mu_dprime": mu_pp, "q_core": q_core,
        "rp_core": rp_core, "core_loss_frac": core_loss_frac,
        "loss_pct": loss_pct,
        "a_surf_cm2": a_surf_cm2, "delta_t_c": CORE_DELTA_T_C,
        "p_diss_w": p_diss_w, "p_thermal": p_thermal,
        "p_max": p_max, "p_limited_by": p_limited_by,
        "power_code": power_code,
        # legacy keys (same value as p_max / power_code)
        "p_avg": p_avg, "sat_code": sat_code,
    }


def unun_multiband(bands: List[Dict[str, object]],
                   comp_kind: str,
                   comp_value: float,
                   ratio: float,
                   z0: float = 50.0) -> List[Dict[str, object]]:
    """
    Section 6 of the workbook — multi-band effect of ONE fixed series
    component placed on the load side of the UnUn.

    bands: [{'band': '40m', 'freq_mhz': 7.1, 'R': 450.0, 'X': 150.0}, …]
    Returns one row per band with VSWR before/after compensation.
    """
    rows: List[Dict[str, object]] = []
    ratio = max(float(ratio), 1e-9)
    for b in bands:
        f = float(b.get("freq_mhz") or 0.0)
        r = float(b.get("R") or 0.0)
        x = float(b.get("X") or 0.0)
        if f <= 0 or r <= 0:
            continue
        xc = comp_reactance(comp_kind, comp_value, f)
        r_in_plain = r / ratio
        x_in_plain = x / ratio
        r_in_comp = r / ratio
        x_in_comp = (x + xc) / ratio
        v_plain = _vswr_from_z(r_in_plain, x_in_plain, z0)
        v_comp = _vswr_from_z(r_in_comp, x_in_comp, z0)
        rows.append({
            "band": b.get("band", ""), "freq_mhz": f, "R": r, "X": x,
            "x_comp": xc, "z_in_r": r_in_comp, "z_in_x": x_in_comp,
            "vswr_plain": v_plain, "vswr_comp": v_comp,
            "delta": v_plain - v_comp,
        })
    return rows


def transmatch_tap_error(t_ref: int, ratios: List[float]) -> float:
    """
    Worst relative error in the REALISED tap resistance for a reference of
    `t_ref` turns, as a fraction (0.02 = 2 %).

    A tap sits on a whole turn, so the realised ratio is round(t_ref·n)/t_ref
    and the realised resistance is Z₀·(round(t_ref·n)/t_ref)² instead of the
    requested Z₀·n².  This is the quantisation error the builder actually
    gets, and it is what decides whether t_ref is fine enough.
    """
    t_ref = int(t_ref)
    if t_ref <= 0:
        return float("inf")
    worst = 0.0
    for n in ratios:
        if not n or n <= 0:
            continue
        turns = max(1, int(round(t_ref * n)))
        worst = max(worst, abs((turns / float(t_ref)) ** 2 / (n * n) - 1.0))
    return worst


# Medhurst's empirical self-capacitance of a single-layer solenoid:
#
#     C_self [pF] = H(l/D) · D [cm]
#
# with H tabulated against the length-to-diameter ratio.  Values from
# R. G. Medhurst, "H.F. Resistance and Self-Capacitance of Single-Layer
# Solenoids", Wireless Engineer, 1947.
_MEDHURST_H: Tuple[Tuple[float, float], ...] = (
    (0.10, 0.96), (0.15, 0.79), (0.20, 0.70), (0.25, 0.645), (0.30, 0.60),
    (0.35, 0.57), (0.40, 0.54),  (0.50, 0.50), (0.60, 0.48), (0.70, 0.46),
    (0.80, 0.455), (1.00, 0.46), (1.50, 0.47), (2.00, 0.485), (3.00, 0.51),
    (4.00, 0.53), (5.00, 0.56),  (7.00, 0.61), (10.0, 0.67), (15.0, 0.75),
    (20.0, 0.81), (25.0, 0.86),  (30.0, 0.92), (40.0, 1.03), (50.0, 1.12),
)


def medhurst_self_c_pf(coil_dia_mm: float, win_len_mm: float) -> float:
    """Self-capacitance of a single-layer solenoid, in pF (Medhurst).

    `coil_dia_mm` is the diameter over the WIRE CENTRES (former + one wire
    diameter), i.e. twice the radius the inductance formula uses.  H is
    interpolated on log(l/D) between the tabulated points and held flat
    outside the table.
    """
    d_cm = max(float(coil_dia_mm), 1e-9) / 10.0
    l_cm = max(float(win_len_mm), 1e-9) / 10.0
    ratio = l_cm / d_cm
    if ratio <= _MEDHURST_H[0][0]:
        h = _MEDHURST_H[0][1]
    elif ratio >= _MEDHURST_H[-1][0]:
        h = _MEDHURST_H[-1][1]
    else:
        h = _MEDHURST_H[-1][1]
        for (r0, h0), (r1, h1) in zip(_MEDHURST_H, _MEDHURST_H[1:]):
            if r0 <= ratio <= r1:
                w = ((math.log(ratio) - math.log(r0))
                     / (math.log(r1) - math.log(r0))) if r1 > r0 else 0.0
                h = h0 + w * (h1 - h0)
                break
    return h * d_cm


def solenoid_srf_mhz(l_uh: float, c_pf: float) -> float:
    """Self-resonant frequency of a solenoid, in MHz, from L and C_self."""
    try:
        if not (math.isfinite(l_uh) and math.isfinite(c_pf)) or l_uh <= 0 or c_pf <= 0:
            return float("nan")
        return 1.0 / (2.0 * math.pi * math.sqrt(l_uh * 1e-6 * c_pf * 1e-12)) / 1e6
    except (ValueError, ZeroDivisionError):
        return float("nan")


def wheeler_solenoid_uh(turns: int, coil_dia_mm: float, wire_dia_mm: float,
                        space_mm: float) -> float:
    """Wheeler's approximation for a single-layer air-core solenoid, in µH.

    Same formula used inline by the Transmatch calculator (`_wheeler_uh`
    there): coil_dia_mm is the diameter over the wire centres (former
    diameter + one wire diameter), space_mm is the gap between adjacent
    turns (so pitch = wire_dia_mm + space_mm). Kept as a standalone
    function so the UnUn air-core path can reuse the exact same physics
    without depending on the Transmatch tab's closures.
    """
    turns = int(turns)
    if turns <= 0:
        return float("nan")
    wire_dia_mm = max(float(wire_dia_mm), 1e-6)
    pitch_mm = wire_dia_mm + max(float(space_mm), 0.0)
    radius_in = (max(float(coil_dia_mm), 1e-6) / 2.0) / 25.4
    len_in = ((turns - 1) * pitch_mm + wire_dia_mm) / 25.4
    den = 9.0 * radius_in + 10.0 * len_in
    return (radius_in ** 2 * turns ** 2) / den if den > 0 else float("nan")


def transmatch_tref_floor(l_min_uh: float,
                          radius_in: float,
                          pitch_mm: float,
                          wire_dia_mm: float,
                          ratios: List[float],
                          t_min: int = TRANSMATCH_MIN_TREF) -> int:
    """Hard lower bound on the Z₀ reference winding.

    The maximum of three terms: the absolute floor, the head-room needed to
    put at least 5 turns below the lowest tap, and the turns needed for the
    t_ref-turn portion to reach L_min.  Nothing — including the self-resonance
    cap — may push the reference below this: doing so would break the port
    inductance or the tap grid itself.
    """
    ratios = [r for r in ratios if r and r > 0]
    if not ratios or radius_in <= 0:
        return int(t_min)
    pitch_in = pitch_mm / 25.4
    wire_in = wire_dia_mm / 25.4
    try:
        term_a = math.ceil(5.0 / min(ratios))

        def _wheeler(turns: int) -> float:
            _len_in = max((turns - 1) * pitch_in + wire_in, 1e-9)
            _den = 9.0 * radius_in + 10.0 * _len_in
            return (radius_in ** 2 * turns ** 2) / _den if _den > 0 else 0.0

        term_b = 5
        if l_min_uh and math.isfinite(l_min_uh) and l_min_uh > 0:
            term_b = 0
            for _n in range(1, 2001):
                if _wheeler(_n) >= l_min_uh:
                    term_b = _n
                    break
            if term_b == 0:          # unreachable on this former — cap and warn
                term_b = 2000
        return max(int(t_min), int(term_a), int(term_b))
    except (ValueError, ZeroDivisionError):
        return int(t_min)


def transmatch_min_turns(l_min_uh: float,
                         radius_in: float,
                         pitch_mm: float,
                         wire_dia_mm: float,
                         ratios: List[float],
                         tol: float = TRANSMATCH_TAP_TOL,
                         t_min: int = TRANSMATCH_MIN_TREF,
                         t_max: int = TRANSMATCH_MAX_TREF) -> int:
    """
    Workbook cell C10 — minimum number of turns at the Z₀ tap so that the
    coil reaches L_min while still providing every requested turns ratio.

    The workbook floor of 5 turns is not usable as a design value: with
    typical HF loads the inductance and head-room terms come out at 2–3, so
    the floor decided t_ref on nearly every run and the realisable tap grid
    became Z₀·(k/5)² = 2, 8, 18, 32, 50 … Ω — coarse enough that the tap the
    user winds can be several percent off the R it was computed for.  The
    reference is therefore raised until no tap misses its target resistance
    by more than `tol` (default 2 %), within [t_min, t_max].  When no
    reference in that range meets the tolerance (very low ratios need a very
    long coil), the one with the smallest worst-case error is returned.
    """
    ratios = [r for r in ratios if r and r > 0]
    if not ratios or radius_in <= 0:
        return int(t_min)
    try:
        # Inductance and head-room give the FLOOR; quantisation decides how
        # far above that floor the reference has to go.  (The floor itself is
        # shared with transmatch_design(), which needs it to know how far the
        # self-resonance cap is allowed to shorten the winding.)
        base = transmatch_tref_floor(l_min_uh, radius_in, pitch_mm,
                                     wire_dia_mm, ratios, t_min)
        best_t, best_err = base, transmatch_tap_error(base, ratios)
        for _t in range(base, max(base, int(t_max)) + 1):
            _err = transmatch_tap_error(_t, ratios)
            if _err <= tol:
                return _t
            if _err < best_err:
                best_t, best_err = _t, _err
        return best_t
    except (ValueError, ZeroDivisionError):
        return int(t_min)


def transmatch_design(taps: List[Dict[str, object]],
                      z0: float = 50.0,
                      wire_dia_mm: float = 1.0,
                      core_dia_mm: float = 50.0,
                      space_mm: float = 1.0,
                      t_ref: Optional[int] = None) -> Dict[str, object]:
    """
    Full air-core transmatch (tapped autotransformer) design — workbook
    sheet "Transmatch Calculator".

    taps: [{'band':'40m','freq_mhz':7.15,'R':75.0,'X':-12.0,'active':True}, …]
          Only active taps with R > 0 and f > 0 take part.

    Returns {'taps': [...per-tap rows...], 'coil': {...}, 'totals': {...}}.
    """
    z0 = max(float(z0), 1e-9)
    wire_dia_mm = max(float(wire_dia_mm), 1e-6)
    core_dia_mm = max(float(core_dia_mm), 1e-6)
    pitch_mm = wire_dia_mm + max(float(space_mm), 0.0)
    radius_mm = (core_dia_mm + wire_dia_mm) / 2.0
    radius_in = radius_mm / 25.4

    live = [t for t in taps
            if t.get("active", True)
            and float(t.get("freq_mhz") or 0) > 0
            and float(t.get("R") or 0) > 0]

    f_min = min((float(t["freq_mhz"]) for t in live), default=0.0)
    f_max = max((float(t["freq_mhz"]) for t in live), default=0.0)
    l_min_uh = (4.0 * z0 / (2.0 * math.pi * f_min)) if f_min > 0 else float("nan")
    ratios = [math.sqrt(float(t["R"]) / z0) for t in live]

    # ── Geometry helpers, needed BEFORE the reference is fixed ───────────
    # The self-resonance check has to be able to price a candidate reference,
    # so the inductance/length formulas are defined up here rather than after
    # the tap loop.
    def _wheeler_uh(turns: int) -> float:
        if turns <= 0:
            return float("nan")
        _len_in = ((turns - 1) * pitch_mm + wire_dia_mm) / 25.4
        _den = 9.0 * radius_in + 10.0 * _len_in
        return (radius_in ** 2 * turns ** 2) / _den if _den > 0 else float("nan")

    def _win_len_mm(turns: int) -> float:
        return ((turns - 1) * pitch_mm + wire_dia_mm) if turns > 0 else 0.0

    def _srf_of_turns(turns: int) -> float:
        """SRF in MHz of a winding of `turns` turns on this former."""
        if turns <= 0:
            return float("nan")
        return solenoid_srf_mhz(
            _wheeler_uh(turns),
            medhurst_self_c_pf(2.0 * radius_mm, _win_len_mm(turns)))

    def _n_total_for(tr: int) -> int:
        """Total turns the winding needs for a given Z0 reference."""
        if tr <= 0:
            return 0
        return max(int(tr), max((max(1, int(round(tr * n))) for n in ratios),
                                default=0))

    # Largest winding whose self-resonance still clears the highest band by
    # TRANSMATCH_SRF_MARGIN.  Above this the coil stops being a transformer.
    n_srf_max = 0
    if f_max > 0:
        _target = TRANSMATCH_SRF_MARGIN * f_max
        for _n in range(1, 2001):
            _srf = _srf_of_turns(_n)
            if not math.isfinite(_srf) or _srf < _target:
                break
            n_srf_max = _n

    t_ref_auto = transmatch_min_turns(
        l_min_uh if math.isfinite(l_min_uh) else 0.0,
        radius_in, pitch_mm, wire_dia_mm, ratios)
    t_ref_floor = transmatch_tref_floor(
        l_min_uh if math.isfinite(l_min_uh) else 0.0,
        radius_in, pitch_mm, wire_dia_mm, ratios)
    t_ref_used = int(t_ref) if t_ref else t_ref_auto

    # Cap the AUTO reference so the winding stays below its own self-resonance.
    # An explicit user reference is never overridden — it is only flagged.
    # The cap can never go below t_ref_floor: the port inductance and the
    # 5-turns-below-the-lowest-tap head-room are hard requirements, so when the
    # floor and the SRF limit are in conflict the coil is reported as unusable
    # rather than silently rebuilt into something that does not match.
    srf_cap_applied = False
    if (not t_ref) and n_srf_max > 0 and f_max > 0:
        _tr = int(t_ref_used)
        while _tr > t_ref_floor and _n_total_for(_tr) > n_srf_max:
            _tr -= 1
        if _tr < t_ref_used:
            srf_cap_applied = True
            t_ref_used = _tr

    rows: List[Dict[str, object]] = []

    # The winding runs from turn 0 upwards, so the wire between taps has to be
    # accumulated in ASCENDING TURN ORDER.  `live` is in band-entry order and R
    # is not monotonic with frequency, so walking it directly adds the back-and-
    # forth excursions along the coil (measured: 6729 mm claimed for a 23-turn
    # coil that needs 3685 mm — 83 % over).  The taps are therefore ordered by
    # turn count for the wire/resistance accounting, while `rows` keeps the
    # user's band order for display.
    _wire_mm_per_turn = math.pi * (core_dia_mm + wire_dia_mm)
    _turns_of: Dict[int, int] = {}
    for _i, _t in enumerate(live):
        _turns_of[_i] = max(1, int(round(t_ref_used * math.sqrt(float(_t["R"]) / z0))))
    _d_turns_of: Dict[int, int] = {}
    _prev = 0
    for _i in sorted(_turns_of, key=lambda k: _turns_of[k]):
        _d_turns_of[_i] = _turns_of[_i] - _prev
        _prev = _turns_of[_i]

    for _idx, t in enumerate(live):
        f = float(t["freq_mhz"])
        r = float(t["R"])
        x = float(t.get("X") or 0.0)
        n = math.sqrt(r / z0)
        turns = _turns_of[_idx]
        d_turns = _d_turns_of[_idx]
        sec_wire_mm = d_turns * _wire_mm_per_turn
        sec_rdc_mohm = (sec_wire_mm * 4.0 * _RHO_CU * 1e6
                        / (math.pi * wire_dia_mm ** 2)
                        * _skin_effect_ratio(f, wire_dia_mm))
        # Wire from turn 0 up to THIS tap — a property of the tap, not of the
        # position the band happens to occupy in the input list.
        cum_wire = turns * _wire_mm_per_turn

        z_mag = math.hypot(r, x)
        phase = math.degrees(math.atan2(x, r))

        # The tap sits on a WHOLE turn, so the realised turns ratio is
        # turns/t_ref, not the ideal sqrt(R/Z0).  Scoring the ideal ratio makes
        # R match perfectly by construction and hides the quantisation error,
        # which is the dominant one on short coils (~1/turns in R).
        #
        # r_p = R/n^2 is itself the IDEAL-autotransformer relation, i.e. it
        # assumes unity coupling (k = 1) between the tapped portion and the
        # whole winding. A single-layer air-core coil does not deliver that:
        # its coupling sits well below unity, and the untapped turns' own
        # reactance appears in parallel rather than vanishing. The realised
        # transformation will therefore be off by more than the tap-
        # quantisation error modelled above — treat r_p/x_p as an upper
        # bound on how well the match will land, not a prediction of it.
        n_real = turns / float(t_ref_used) if t_ref_used else n
        scale = n_real ** 2
        # R the winding actually presents at this tap (the figure the builder
        # will measure), next to the R the band asked for.
        r_real = z0 * scale
        r_err_pct = (r_real / r - 1.0) * 100.0 if r > 0 else 0.0
        r_p = r / scale
        x_p = x / scale
        g = _gamma_from_z(r_p, x_p, z0)
        swr = (1.0 + g) / (1.0 - g) if g < 1 else 999.0
        rl = -20.0 * math.log10(max(g, 1e-9))
        ml = max(0.0, -10.0 * math.log10(max(1.0 - g * g, 1e-12)))
        refl_pct = g * g * 100.0
        # Quantisation alone (X = 0): tells the user whether raising t_ref pays.
        _gq = _gamma_from_z(r_p, 0.0, z0)
        swr_quant = (1.0 + _gq) / (1.0 - _gq) if _gq < 1 else 999.0

        w = 2.0 * math.pi * f * 1e6      # rad/s
        # Series compensation cancels the transformed reactance X'.
        ser_l_uh = abs(x_p) / w * 1e6 if x_p < 0 else None
        ser_c_pf = 1.0 / (w * abs(x_p)) * 1e12 if x_p > 0 else None
        # Shunt compensation cancels the susceptance at the tap port.  Derived
        # from the TRANSFORMED impedance so it follows the realised turns ratio
        # (with the ideal ratio this reduces to the previous r·x/(z0·|Z|²)).
        denom = r_p * r_p + x_p * x_p
        b = (x_p / denom) if denom else 0.0
        sh_l_uh = (-1.0 / (w * b)) * 1e6 if b < 0 else None
        sh_c_pf = (b / w) * 1e12 if b > 0 else None

        x5 = 0.05 * x_p                 # residual after 95 % compensation
        g5 = _gamma_from_z(r_p, x5, z0)
        swr5 = (1.0 + g5) / (1.0 - g5) if g5 < 1 else 999.0

        # ── Winding shunt reactance at this tap ──────────────────────────
        # The turns BELOW the tap sit directly across the antenna port; their
        # reactance is in parallel with the antenna, and the ideal-transformer
        # model r_p = R/n² assumes it is infinite.  It is not: on a 640 ohm
        # 15 m tap of an 85-turn coil it comes out around 10 kohm, a ratio of
        # only 16.  Below TRANSMATCH_SHUNT_RATIO_MIN the tap is loading the
        # coil rather than transforming through it.
        x_wind = 2.0 * math.pi * f * 1e6 * _wheeler_uh(turns) * 1e-6
        wind_ratio = (x_wind / z_mag) if (z_mag > 0 and math.isfinite(x_wind)) \
            else float("nan")
        wind_ok = bool(math.isfinite(wind_ratio)
                       and wind_ratio >= TRANSMATCH_SHUNT_RATIO_MIN)
        # Turns ABOVE the tap are left open-circuit and form a coupled stub;
        # the lumped model does not see them at all.  Reported so the builder
        # knows how much winding is hanging off the top of the tap.
        srf_tap = _srf_of_turns(turns)
        tap_below_srf = bool(math.isfinite(srf_tap) and f < srf_tap)

        rows.append({
            "band": t.get("band", ""), "freq_mhz": f, "R": r, "X": x,
            "turns_ratio": n, "turns_ratio_real": n_real,
            "turns": turns, "d_turns": d_turns, "swr_quant": swr_quant,
            "r_real": r_real, "r_err_pct": r_err_pct,
            "r_transformed": r_p,
            "sec_wire_mm": sec_wire_mm, "sec_rdc_mohm": sec_rdc_mohm,
            "cum_wire_mm": cum_wire,
            "z_mag": z_mag, "phase_deg": phase,
            "swr": swr, "return_loss_db": rl, "mismatch_db": ml,
            "refl_pct": refl_pct, "swr_5pct": swr5,
            "x_wind_ohm": x_wind, "wind_ratio": wind_ratio, "wind_ok": wind_ok,
            "srf_tap_mhz": srf_tap, "tap_below_srf": tap_below_srf,
            "x_transformed": x_p,
            "ser_l_uh": ser_l_uh, "ser_c_pf": ser_c_pf,
            "sh_l_uh": sh_l_uh, "sh_c_pf": sh_c_pf,
            "ser_l_nh": (round(ser_l_uh * 1000.0) if ser_l_uh else None),
            "ser_c_e24": (e24_snap(ser_c_pf) if ser_c_pf else None),
            "sh_l_nh": (round(sh_l_uh * 1000.0) if sh_l_uh else None),
            "sh_c_e24": (e24_snap(sh_c_pf) if sh_c_pf else None),
        })

    # The winding has to span the highest ANTENNA tap *and* the Z0 tap, which
    # sits at t_ref turns: with every R below Z0 all antenna taps land below
    # t_ref and the old max() described a coil shorter than its own 50 Ω port.
    n_total = max(int(t_ref_used), max((r["turns"] for r in rows), default=0))
    total_wire_mm = n_total * _wire_mm_per_turn
    total_rdc_mohm = (total_wire_mm * 4.0 * _RHO_CU * 1e6
                      / (math.pi * wire_dia_mm ** 2)
                      * _skin_effect_ratio(f_max, wire_dia_mm))

    # Turns above each tap hang open and form a coupled stub the lumped model
    # cannot see; carried per row so the builder knows they are there.
    for _r in rows:
        _r["n_above"] = max(0, n_total - int(_r["turns"]))

    win_len_mm = _win_len_mm(n_total)
    win_len_in = win_len_mm / 25.4
    l_uh = _wheeler_uh(n_total)
    # The X_L >= 4·Z0 criterion applies at the 50 Ω port, so it must be checked
    # against the inductance of the t_ref-turn PORTION, not the whole winding —
    # Wheeler is quadratic in turns, so the full coil overstates it by
    # (n_total/t_ref)² (measured: 19.93 µH vs 2.00 µH for 23 vs 5 turns).
    l_port_uh = _wheeler_uh(int(t_ref_used))
    x_l = 2.0 * math.pi * f_min * l_port_uh if (f_min and math.isfinite(l_port_uh)) else float("nan")
    l_ok = bool(math.isfinite(l_port_uh) and math.isfinite(l_min_uh)
                and l_port_uh >= l_min_uh)

    # ── Self-resonance of the finished winding ──────────────────────────
    c_self_pf = medhurst_self_c_pf(2.0 * radius_mm, win_len_mm)
    srf_mhz = solenoid_srf_mhz(l_uh, c_self_pf)
    srf_needed_mhz = TRANSMATCH_SRF_MARGIN * f_max if f_max > 0 else float("nan")
    srf_ok = bool(math.isfinite(srf_mhz) and math.isfinite(srf_needed_mhz)
                  and srf_mhz >= srf_needed_mhz)
    # Bands that sit at or above the coil's own resonance: for these the
    # autotransformer model does not apply at all and the SWR figures in the
    # tap table are meaningless, not merely optimistic.
    bands_above_srf = [str(r["band"]) for r in rows
                       if math.isfinite(srf_mhz) and float(r["freq_mhz"]) >= srf_mhz]
    # Full-winding shunt reactance at the top band — the figure that says how
    # hard the coil itself is loading the antenna port.
    x_wind_total = (2.0 * math.pi * f_max * 1e6 * l_uh * 1e-6
                    if (f_max > 0 and math.isfinite(l_uh)) else float("nan"))
    shunt_warn_bands = [str(r["band"]) for r in rows if not r["wind_ok"]]
    coil_ok = bool(l_ok and srf_ok and not shunt_warn_bands)

    return {
        "taps": rows,
        "totals": {
            "n_total": n_total,
            "l_port_uh": l_port_uh,
            "total_wire_mm": total_wire_mm,
            "total_rdc_mohm": total_rdc_mohm,
            "t_ref": t_ref_used,
            "t_ref_auto": t_ref_auto,
            "t_ref_floor": t_ref_floor,
            "srf_cap_applied": srf_cap_applied,
        },
        "coil": {
            "z0": z0,
            "former_dia_mm": core_dia_mm, "wire_dia_mm": wire_dia_mm,
            "pitch_mm": pitch_mm, "n_total": n_total,
            "win_len_mm": win_len_mm, "radius_mm": radius_mm,
            "radius_in": radius_in, "win_len_in": win_len_in,
            "l_uh": l_uh, "x_l": x_l, "f_min_mhz": f_min, "f_max_mhz": f_max,
            "l_min_uh": l_min_uh, "l_ok": l_ok,
            "c_self_pf": c_self_pf, "srf_mhz": srf_mhz,
            "srf_needed_mhz": srf_needed_mhz, "srf_margin": TRANSMATCH_SRF_MARGIN,
            "srf_ok": srf_ok, "n_srf_max": n_srf_max,
            "srf_cap_applied": srf_cap_applied,
            "bands_above_srf": bands_above_srf,
            "x_wind_total_ohm": x_wind_total,
            "shunt_warn_bands": shunt_warn_bands,
            "shunt_ratio_min": TRANSMATCH_SHUNT_RATIO_MIN,
            "coil_ok": coil_ok,
        },
    }


# ── Transmatch construction drawing (PNG) ─────────────────────────────────
#
# Mechanical/constructional view of the tapped air-core autotransformer:
# former, winding, every tap position (turn number and distance from the
# cold end) and all the dimensions needed to actually wind the coil.
# The result is a standalone PNG so it can be reused elsewhere (reports,
# PDFs, documentation, web pages …).

_TM_PNG_STRINGS = {
    "en": {
        "title":     "Transmatch — construction drawing",
        "subtitle":  "Tapped air-core autotransformer · dimensions in mm",
        "cold":      "cold end\n(ground)",
        "hot":       "free end",
        "in_tap":    "INPUT {z0} Ω (TX) · turn {n}",
        "out_tap":   "{band} · turn {n} · R {r} Ω",
        "wind_len":  "winding length = {v} mm",
        "former":    "former Ø {v} mm",
        "pitch":     "pitch p = {v} mm",
        "turn_dim":  "turn {n}: {v} mm",
        "note":      ("Turns are counted from the cold (grounded) end.  Tap distance = "
                      "(turn − 1) × pitch + wire Ø ⁄ 2.\nWind in a single layer, same "
                      "direction throughout; scrape the enamel at each tap and solder a "
                      "short pigtail without cutting the wire."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "es": {
        "title":     "Transmatch — plano constructivo",
        "subtitle":  "Autotransformador al aire con tomas · cotas en mm",
        "cold":      "extremo frío\n(masa)",
        "hot":       "extremo libre",
        "in_tap":    "ENTRADA {z0} Ω (TX) · espira {n}",
        "out_tap":   "{band} · espira {n} · R {r} Ω",
        "wind_len":  "longitud del bobinado = {v} mm",
        "former":    "formador Ø {v} mm",
        "pitch":     "paso p = {v} mm",
        "turn_dim":  "espira {n}: {v} mm",
        "note":      ("Las espiras se cuentan desde el extremo frío (a masa).  Distancia de "
                      "la toma = (espira − 1) × paso + Ø hilo ⁄ 2.\nBobine en una sola capa y "
                      "siempre en el mismo sentido; raspe el esmalte en cada toma y suelde una "
                      "colita sin cortar el hilo."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "it": {
        "title":     "Transmatch — disegno costruttivo",
        "subtitle":  "Autotrasformatore in aria con prese · quote in mm",
        "cold":      "estremo freddo\n(massa)",
        "hot":       "estremo libero",
        "in_tap":    "INGRESSO {z0} Ω (TX) · spira {n}",
        "out_tap":   "{band} · spira {n} · R {r} Ω",
        "wind_len":  "lunghezza avvolgimento = {v} mm",
        "former":    "supporto Ø {v} mm",
        "pitch":     "passo p = {v} mm",
        "turn_dim":  "spira {n}: {v} mm",
        "note":      ("Le spire si contano dall'estremo freddo (a massa).  Distanza della "
                      "presa = (spira − 1) × passo + Ø filo ⁄ 2.\nAvvolgere in un solo strato, "
                      "sempre nello stesso verso; raschiare lo smalto a ogni presa e saldare uno "
                      "spezzone corto senza tagliare il filo."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
}


def _tm_n(value, nd: int = 1, lang: str = "en", dash: str = "—") -> str:
    """Locale-aware number formatting for the drawing labels."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(f):
        return dash
    s = f"{f:,.{nd}f}"
    if lang in ("es", "it"):                # 1,234.5 → 1.234,5
        s = s.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")
    return s


def transmatch_coil_png(res: Dict[str, object],
                        out_png: str,
                        lang: str = "en",
                        dpi: int = 150,
                        strings: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[str]:
    """
    Render the constructional drawing of the transmatch coil described by
    `res` (the dict returned by transmatch_design) into `out_png`.

    `strings`: optional override for the title/label table, keyed the same
    way as _TM_PNG_STRINGS (by language). Defaults to _TM_PNG_STRINGS so
    the Transmatch tab's own calls are unaffected; unun_solenoid_png()
    passes its own UnUn-flavoured table here instead of mutating the
    module-level Transmatch strings.

    Returns the file path, or None if matplotlib is unavailable or the
    design is empty.
    """
    if not HAS_MPL:
        return None
    _strings = strings if strings is not None else _TM_PNG_STRINGS
    L = _strings.get(lang, _strings["en"])
    coil = dict(res.get("coil") or {})
    tot = dict(res.get("totals") or {})
    taps = list(res.get("taps") or [])

    D = float(coil.get("former_dia_mm") or 0.0)          # former diameter
    dw = float(coil.get("wire_dia_mm") or 0.0)           # wire diameter
    pitch = float(coil.get("pitch_mm") or 0.0)           # mm per turn
    n_tot = int(coil.get("n_total") or 0)
    win_len = float(coil.get("win_len_mm") or 0.0)
    z0 = float(coil.get("z0") or 50.0)
    t_ref = int(tot.get("t_ref") or 0)
    if n_tot <= 0 or D <= 0 or pitch <= 0:
        return None

    def x_of(turn: float) -> float:
        """Axial position (mm) of the centre of a given turn, from the cold end."""
        return (float(turn) - 1.0) * pitch + dw / 2.0

    # ── tap list (merged when several bands land on the same turn) ────────
    marks: Dict[int, Dict[str, object]] = {}
    if t_ref > 0:
        marks[t_ref] = {"turn": t_ref, "input": True, "labels": [
            L["in_tap"].format(z0=_tm_n(z0, 0, lang), n=t_ref)]}
    for r in taps:
        k = int(r.get("turns") or 0)
        if k <= 0:
            continue
        txt = L["out_tap"].format(band=r.get("band", ""), n=k,
                                  r=_tm_n(r.get("R"), 0, lang))
        m = marks.setdefault(k, {"turn": k, "input": False, "labels": []})
        m["labels"].append(txt)
    mk = [marks[k] for k in sorted(marks)]
    n_mk = len(mk)

    # ── geometry of the canvas (all in mm) ───────────────────────────────
    ext = max(6.0, pitch * 1.5)                  # former overhang each side
    lead_step = max(7.0, D * 0.16)               # vertical spacing of tap leads
    top_pad = 8.0 + lead_step * max(n_mk, 1)
    dim_step = max(6.5, D * 0.14)
    bot_pad = 16.0 + dim_step * (n_mk + 1) + 8.0

    # Enough room on the right for the longest tap label (estimated from the
    # character count, converted from typographic points to drawing mm).
    lab_chars = max((len("  ·  ".join(m["labels"])) for m in mk), default=0)
    fig_w = 12.0
    ax_w_in = fig_w * 0.955
    x0 = -ext - 26.0
    x1 = win_len + ext + max(40.0, win_len * 0.30)
    for _ in range(3):                           # converge the right margin
        mm_per_pt = (x1 - x0) / (ax_w_in * 72.0)
        need = 14.0 + lab_chars * 8.2 * 0.56 * mm_per_pt
        x1 = win_len + ext + max(40.0, win_len * 0.30, need)
    y0, y1 = -D / 2.0 - bot_pad, D / 2.0 + top_pad

    span_x, span_y = (x1 - x0), (y1 - y0)
    fig_h = min(13.5, max(5.2, ax_w_in * span_y / max(span_x, 1e-6) / 0.82 + 0.9))

    C_FORM = "#EBE4D6"
    C_FORM_E = "#9A9384"
    C_WIRE = "#1F4E79"
    C_TAP = "#B3261E"
    C_IN = "#0F7B3E"
    C_DIM = "#5A5A5A"

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    gs = gridspec.GridSpec(1, 1, left=0.03, right=0.985,
                           top=0.88, bottom=0.07)
    ax = fig.add_subplot(gs[0, 0])
    ax.set_facecolor("white")
    ax.axis("off")
    ax.set_aspect("equal")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)

    # ── former (tube) ────────────────────────────────────────────────────
    from matplotlib.patches import Rectangle, Ellipse
    cap_w = max(D * 0.22, pitch * 1.2)
    ax.add_patch(Rectangle((-ext, -D / 2.0), win_len + 2 * ext, D,
                           facecolor=C_FORM, edgecolor=C_FORM_E,
                           linewidth=1.0, zorder=1))
    for xc in (-ext, win_len + ext):
        ax.add_patch(Ellipse((xc, 0.0), width=cap_w, height=D,
                             facecolor=C_FORM, edgecolor=C_FORM_E,
                             linewidth=1.0, zorder=1.2))
    ax.plot([x0 + 8, win_len + ext + cap_w], [0, 0], color=C_FORM_E,
            lw=0.8, ls=(0, (8, 4, 2, 4)), zorder=1.3)

    # ── winding ──────────────────────────────────────────────────────────
    tap_turns = {m["turn"]: m for m in mk}
    turn_w = min(max(pitch * 1.9, D * 0.10), D * 0.34)
    lw_wire = max(1.0, min(4.0, dw * 1.6))
    for k in range(1, n_tot + 1):
        xc = x_of(k)
        is_tap = k in tap_turns
        col = (C_IN if (is_tap and tap_turns[k]["input"]) else
               C_TAP if is_tap else C_WIRE)
        ax.add_patch(Ellipse((xc, 0.0), width=turn_w, height=D + dw,
                             facecolor="none", edgecolor=col,
                             linewidth=lw_wire + (0.9 if is_tap else 0.0),
                             zorder=3 if is_tap else 2))

    # cold-end and free-end leads
    ax.plot([x_of(1) - turn_w / 2.0, -ext - 14.0], [-D / 2.0 + 1.0, -D / 2.0 - 6.0],
            color=C_WIRE, lw=lw_wire, zorder=3)
    ax.plot([-ext - 20.0, -ext - 8.0], [-D / 2.0 - 6.0, -D / 2.0 - 6.0],
            color=C_WIRE, lw=lw_wire, zorder=3)
    for i, gl in enumerate((7.0, 4.6, 2.4)):          # ground symbol
        ax.plot([-ext - 14.0 - gl, -ext - 14.0 + gl],
                [-D / 2.0 - 9.5 - i * 2.2] * 2, color=C_WIRE, lw=1.4, zorder=3)
    ax.plot([-ext - 14.0, -ext - 14.0], [-D / 2.0 - 6.0, -D / 2.0 - 9.5],
            color=C_WIRE, lw=1.2, zorder=3)
    ax.text(-ext - 14.0, -D / 2.0 - 17.0, L["cold"], ha="center", va="top",
            fontsize=8.0, color=C_WIRE)
    ax.plot([x_of(n_tot) + turn_w / 2.0, win_len + ext + cap_w * 0.9],
            [D / 2.0 - 1.0, D / 2.0 + 3.0], color=C_WIRE, lw=lw_wire, zorder=3)
    ax.text(win_len + ext + cap_w * 1.05, D / 2.0 + 2.0, L["hot"], ha="left",
            va="top", fontsize=8.0, color=C_WIRE)

    # ── tap leads and labels ─────────────────────────────────────────────
    for i, m in enumerate(mk):
        xc = x_of(m["turn"])
        y_lead = D / 2.0 + 11.0 + lead_step * i
        col = C_IN if m["input"] else C_TAP
        ax.plot([xc, xc], [D / 2.0 + dw / 2.0, y_lead], color=col, lw=1.5, zorder=4)
        ax.plot([xc, xc + max(9.0, pitch * 2.2)], [y_lead, y_lead],
                color=col, lw=1.5, zorder=4)
        ax.plot([xc], [D / 2.0 + dw / 2.0], marker="o", ms=4.2, color=col, zorder=5)
        ax.text(xc + max(11.0, pitch * 2.6), y_lead, "  ·  ".join(m["labels"]),
                ha="left", va="center", fontsize=8.2, color=col,
                fontweight="bold" if m["input"] else "normal", zorder=6,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.2))

    # ── dimensions ───────────────────────────────────────────────────────
    def dim_h(xa, xb, y, text, color=C_DIM, fs=8.0):
        ax.annotate("", xy=(xa, y), xytext=(xb, y),
                    arrowprops=dict(arrowstyle="<->", color=color, lw=1.0,
                                    shrinkA=0, shrinkB=0), zorder=4)
        for xx in (xa, xb):
            ax.plot([xx, xx], [y - 1.6, y + 1.6], color=color, lw=0.8, zorder=4)
        ax.text((xa + xb) / 2.0, y + 1.8, text, ha="center", va="bottom",
                fontsize=fs, color=color)

    y_dim = -D / 2.0 - 16.0
    dim_h(0.0, win_len, y_dim, L["wind_len"].format(v=_tm_n(win_len, 1, lang)))
    for i, m in enumerate(mk):
        xc = x_of(m["turn"])
        yy = y_dim - dim_step * (i + 1)
        col = C_IN if m["input"] else C_TAP
        ax.plot([xc, xc], [D / 2.0 + dw / 2.0, yy], color=col, lw=0.6,
                ls=(0, (4, 3)), alpha=0.55, zorder=1.5)
        dim_h(0.0, xc, yy,
              L["turn_dim"].format(n=m["turn"], v=_tm_n(xc, 1, lang)),
              color=col, fs=7.6)

    # former diameter (vertical)
    xv = -ext - 12.0
    ax.annotate("", xy=(xv, -D / 2.0), xytext=(xv, D / 2.0),
                arrowprops=dict(arrowstyle="<->", color=C_DIM, lw=1.0,
                                shrinkA=0, shrinkB=0), zorder=4)
    ax.text(xv - 2.5, 0.0, L["former"].format(v=_tm_n(D, 1, lang)),
            ha="center", va="center", rotation=90, fontsize=8.0, color=C_DIM)

    # pitch call-out between the first two turns
    if n_tot >= 2:
        yp = D / 2.0 + 3.5
        dim_h(x_of(1), x_of(2), yp, L["pitch"].format(v=_tm_n(pitch, 2, lang)),
              fs=7.6)

    fig.suptitle(L["title"], fontsize=14, fontweight="bold", color=C_WIRE,
                 x=0.03, ha="left", y=0.975)
    fig.text(0.03, 0.932, L["subtitle"], fontsize=9.5, color="#555555",
             ha="left", va="top")
    fig.text(0.03, 0.012, L["note"], fontsize=7.6, color="#555555",
             ha="left", va="bottom")
    fig.text(0.985, 0.012, L["gen"], fontsize=7.0, color="#8A8A8A",
             ha="right", va="bottom")

    d = os.path.dirname(os.path.abspath(out_png))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    plt.savefig(out_png, dpi=dpi, facecolor="white")
    plt.close(fig)
    return out_png


# ── UnUn toroid construction drawing (PNG) ────────────────────────────────
#
# Mechanical/constructional view of the toroidal autotransformer: the core
# (top view + cross-section), the winding turns, the primary tap and the
# free end, plus the dimensions needed to actually wind it. Mirrors
# transmatch_coil_png() above so both pages share the same visual language.

_UT_PNG_STRINGS = {
    "en": {
        "title":    "UnUn Toroid — construction drawing",
        "subtitle": "Tapped toroidal autotransformer · core {core} · dimensions in mm",
        "top_view": "Top view",
        "cross":    "Cross-section",
        "start":    "start\n(ground / cold end)",
        "hot":      "free end\n(load, N_t)",
        "in_tap":   "TX tap · turn {n}\n(N_tap, {r} Ω)",
        "od":       "OD {v} mm",
        "id":       "ID {v} mm",
        "h":        "H {v} mm",
        "turns":    "{n} turns total",
        "wire":     "wire Ø {v} mm",
        "note":     ("Turns are counted from the grounded (cold) start. Wind in a single "
                     "layer, evenly spaced around the core, same direction throughout; "
                     "scrape the enamel at the tap and solder a short pigtail without "
                     "cutting the wire."),
        "gen":      "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "es": {
        "title":    "Toroide UnUn — plano constructivo",
        "subtitle": "Autotransformador toroidal con toma · núcleo {core} · cotas en mm",
        "top_view": "Vista superior",
        "cross":    "Corte transversal",
        "start":    "inicio\n(masa / extremo frío)",
        "hot":      "extremo libre\n(carga, N_t)",
        "in_tap":   "toma TX · espira {n}\n(N_tap, {r} Ω)",
        "od":       "OD {v} mm",
        "id":       "ID {v} mm",
        "h":        "H {v} mm",
        "turns":    "{n} espiras totales",
        "wire":     "hilo Ø {v} mm",
        "note":     ("Las espiras se cuentan desde el inicio a masa (extremo frío). Bobine "
                     "en una sola capa, repartida uniformemente alrededor del núcleo y "
                     "siempre en el mismo sentido; raspe el esmalte en la toma y suelde una "
                     "colita sin cortar el hilo."),
        "gen":      "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "it": {
        "title":    "Toroide UnUn — disegno costruttivo",
        "subtitle": "Autotrasformatore toroidale con presa · nucleo {core} · quote in mm",
        "top_view": "Vista dall'alto",
        "cross":    "Sezione trasversale",
        "start":    "inizio\n(massa / estremo freddo)",
        "hot":      "estremo libero\n(carico, N_t)",
        "in_tap":   "presa TX · spira {n}\n(N_tap, {r} Ω)",
        "od":       "OD {v} mm",
        "id":       "ID {v} mm",
        "h":        "H {v} mm",
        "turns":    "{n} spire totali",
        "wire":     "filo Ø {v} mm",
        "note":     ("Le spire si contano a partire dall'inizio a massa (estremo freddo). Avvolgere "
                     "in un solo strato, distribuito uniformemente attorno al nucleo e "
                     "sempre nello stesso verso; raschiare lo smalto sulla presa e saldare uno "
                     "spezzone corto senza tagliare il filo."),
        "gen":      "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
}


def unun_toroid_png(design: Dict[str, object],
                    out_png: str,
                    lang: str = "en",
                    dpi: int = 150) -> Optional[str]:
    """
    Render the constructional drawing of the UnUn toroid described by
    `design` (the dict returned by unun_design()) into `out_png`: a top
    view of the core with the winding and tap, plus a cross-section
    showing OD/ID/H.

    Returns the file path, or None if matplotlib is unavailable or the
    design is incomplete.
    """
    if not HAS_MPL:
        return None
    if design.get("core_type") == "air":
        # No toroid to draw for an air-core UnUn — the caller shows a
        # text note instead of this constructional drawing.
        return None
    L = _UT_PNG_STRINGS.get(lang, _UT_PNG_STRINGS["en"])

    core_name = str(design.get("core") or DEFAULT_TOROID)
    core_d = TOROID_DB.get(core_name, TOROID_DB[DEFAULT_TOROID])
    OD = float(core_d.get("OD") or 0.0)
    ID = float(core_d.get("ID") or 0.0)
    H = float(core_d.get("H") or 0.0)
    n_total = int(design.get("n_total") or 0)
    n_tap = int(design.get("n_tap") or 0)
    wire_dia_mm = float(design.get("wire_dia_mm") or 0.0)
    r_out = design.get("r_out")
    if OD <= 0 or ID <= 0 or n_total <= 0:
        return None

    C_CORE = "#5A4A3A"
    C_CORE_E = "#2E241A"
    C_WIRE = "#1F4E79"
    C_TAP = "#B3261E"
    C_START = "#0F7B3E"
    C_DIM = "#5A5A5A"

    fig = plt.figure(figsize=(11.0, 7.2), facecolor="white")
    gs = gridspec.GridSpec(1, 2, left=0.045, right=0.98, top=0.80, bottom=0.20,
                           width_ratios=[1.15, 1.0], wspace=0.28)

    # ── left panel: top view (core + winding + tap) ─────────────────────
    ax = fig.add_subplot(gs[0, 0])
    ax.set_facecolor("white")
    ax.axis("off")
    ax.set_aspect("equal")
    R_out, R_in = OD / 2.0, ID / 2.0
    pad = max(18.0, OD * 0.28)
    ax.set_xlim(-R_out - pad, R_out + pad)
    ax.set_ylim(-R_out - pad * 1.75, R_out + pad * 1.55)

    from matplotlib.patches import Circle, Annulus
    try:
        ax.add_patch(Annulus((0, 0), R_out, R_out - R_in,
                             facecolor=C_CORE, edgecolor=C_CORE_E, linewidth=1.2, zorder=1))
    except Exception:                      # Annulus needs matplotlib >= 3.5
        ax.add_patch(Circle((0, 0), R_out, facecolor=C_CORE, edgecolor=C_CORE_E,
                            linewidth=1.2, zorder=1))
        ax.add_patch(Circle((0, 0), R_in, facecolor="white", edgecolor=C_CORE_E,
                            linewidth=1.2, zorder=1.1))

    # winding turns, evenly spaced around the core, starting at the bottom
    # (angle = -90°) and going clockwise back up to the start.
    start_ang = -90.0
    tap_idx = max(1, min(n_tap, n_total))
    r_mid = (R_out + R_in) / 2.0
    r_wire_out, r_wire_in = R_out + wire_dia_mm * 0.9, R_in - wire_dia_mm * 0.9
    lw_wire = max(1.0, min(3.2, wire_dia_mm * 1.4))
    for k in range(1, n_total + 1):
        ang = math.radians(start_ang + 360.0 * (k - 0.5) / n_total)
        ca, sa = math.cos(ang), math.sin(ang)
        is_tap = (k == tap_idx)
        is_start = (k == 1)
        col = C_START if is_start else (C_TAP if is_tap else C_WIRE)
        ax.plot([r_wire_in * ca, r_wire_out * ca], [r_wire_in * sa, r_wire_out * sa],
                color=col, lw=lw_wire + (0.8 if (is_tap or is_start) else 0.0),
                zorder=3 if (is_tap or is_start) else 2, solid_capstyle="round")

    # start lead (ground) and free-end lead
    a0 = math.radians(start_ang + 360.0 * 0.5 / n_total)
    lead0_y = -R_out - pad * 0.55
    ax.plot([r_wire_out * math.cos(a0), r_wire_out * math.cos(a0) - pad * 0.35],
            [r_wire_out * math.sin(a0), lead0_y],
            color=C_START, lw=lw_wire, zorder=3)
    ax.text(r_wire_out * math.cos(a0) - pad * 0.4, lead0_y,
            L["start"], ha="right", va="center", fontsize=7.6, color=C_START)

    a1 = math.radians(start_ang + 360.0 * (n_total - 0.5) / n_total)
    lead1_y = -R_out - pad * 0.9
    ax.plot([r_wire_out * math.cos(a1), r_wire_out * math.cos(a1) + pad * 0.35],
            [r_wire_out * math.sin(a1), lead1_y],
            color=C_WIRE, lw=lw_wire, zorder=3)
    ax.text(r_wire_out * math.cos(a1) + pad * 0.4, lead1_y,
            L["hot"], ha="left", va="center", fontsize=7.6, color=C_WIRE)

    # tap lead and label — pushed clear of the start/end leads when the tap
    # angle falls close to the bottom of the ring (common on low turn counts,
    # where the tap can land right next to turn 1 or the last turn).
    at = math.radians(start_ang + 360.0 * (tap_idx - 0.5) / n_total)
    near_bottom = (abs(((math.degrees(at) - start_ang + 180.0) % 360.0) - 180.0)
                   < 360.0 / max(n_total, 1) * 1.5)
    ax.plot([r_wire_out * math.cos(at)], [r_wire_out * math.sin(at)],
            marker="o", ms=4.5, color=C_TAP, zorder=5)
    r_txt = "" if r_out is None else f"{float(r_out):.0f}"
    if near_bottom:
        side = 1.0 if math.cos(at) >= 0 else -1.0
        lx, ly = side * (R_out + pad * 0.55), 0.0
        ax.plot([r_wire_out * math.cos(at), lx], [r_wire_out * math.sin(at), ly],
                color=C_TAP, lw=lw_wire, zorder=4)
        ax.text(lx + side * pad * 0.05, ly, L["in_tap"].format(n=n_tap, r=r_txt),
                ha="left" if side > 0 else "right", va="center", fontsize=8.0,
                color=C_TAP, fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", pad=1.0), zorder=6)
    else:
        ax.plot([r_wire_out * math.cos(at), (R_out + pad * 0.65) * math.cos(at)],
                [r_wire_out * math.sin(at), (R_out + pad * 0.65) * math.sin(at)],
                color=C_TAP, lw=lw_wire, zorder=4)
        ax.text((R_out + pad * 0.7) * math.cos(at), (R_out + pad * 0.7) * math.sin(at),
                L["in_tap"].format(n=n_tap, r=r_txt),
                ha="left" if math.cos(at) >= 0 else "right",
                va="center", fontsize=8.0, color=C_TAP, fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none", pad=1.0), zorder=6)

    # OD / ID dimension call-outs
    ax.annotate("", xy=(-R_out, R_out + pad * 0.35), xytext=(R_out, R_out + pad * 0.35),
                arrowprops=dict(arrowstyle="<->", color=C_DIM, lw=1.0,
                                shrinkA=0, shrinkB=0), zorder=4)
    ax.text(0, R_out + pad * 0.42, L["od"].format(v=_tm_n(OD, 1, lang)),
            ha="center", va="bottom", fontsize=8.2, color=C_DIM)
    ax.annotate("", xy=(-R_in, 0.0), xytext=(R_in, 0.0),
                arrowprops=dict(arrowstyle="<->", color=C_DIM, lw=1.0,
                                shrinkA=0, shrinkB=0), zorder=4)
    ax.text(0, R_in * 0.12 if R_in else 0, L["id"].format(v=_tm_n(ID, 1, lang)),
            ha="center", va="bottom", fontsize=7.6, color=C_DIM)

    ax.text(0, -(R_out + pad * 1.32), L["turns"].format(n=n_total),
            ha="center", va="top", fontsize=8.4, color=C_WIRE)
    ax.set_title(L["top_view"], fontsize=10.5, color="#333333", pad=10)

    # ── right panel: cross-section (former height H, wire diameter) ─────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor("white")
    ax2.axis("off")
    ax2.set_aspect("equal")
    span = max(R_out * 1.3, H * 3.0, 20.0)
    ax2.set_xlim(-span, span * 1.18)
    ax2.set_ylim(-span * 0.75, span * 0.95)

    from matplotlib.patches import Rectangle
    ax2.add_patch(Rectangle((-R_out, -H / 2.0), R_out - R_in, H,
                            facecolor=C_CORE, edgecolor=C_CORE_E, linewidth=1.2, zorder=1))
    ax2.add_patch(Rectangle((R_in, -H / 2.0), R_out - R_in, H,
                            facecolor=C_CORE, edgecolor=C_CORE_E, linewidth=1.2, zorder=1))
    n_show = min(n_total, 14)
    for i in range(n_show):
        for sgn in (-1.0, 1.0):
            xc = sgn * (R_in + (R_out - R_in) * (0.15 + 0.7 * (i + 0.5) / max(n_show, 1)))
            ax2.add_patch(Circle((xc, 0.0), wire_dia_mm / 2.0, facecolor="none",
                                 edgecolor=C_WIRE, linewidth=max(0.8, lw_wire * 0.6), zorder=2))

    # H dimension
    xv = R_out + max(6.0, span * 0.08)
    ax2.annotate("", xy=(xv, -H / 2.0), xytext=(xv, H / 2.0),
                arrowprops=dict(arrowstyle="<->", color=C_DIM, lw=1.0,
                                shrinkA=0, shrinkB=0), zorder=4)
    ax2.text(xv + max(3.0, span * 0.03), 0.0, L["h"].format(v=_tm_n(H, 1, lang)),
            ha="left", va="center", fontsize=8.2, color=C_DIM, rotation=90)
    # OD dimension (bottom)
    yb = -H / 2.0 - max(8.0, span * 0.1)
    ax2.annotate("", xy=(-R_out, yb), xytext=(R_out, yb),
                arrowprops=dict(arrowstyle="<->", color=C_DIM, lw=1.0,
                                shrinkA=0, shrinkB=0), zorder=4)
    ax2.text(0, yb - max(2.0, span * 0.04), L["od"].format(v=_tm_n(OD, 1, lang)),
            ha="center", va="top", fontsize=7.8, color=C_DIM)
    ax2.text(0, -(span * 0.68), L["wire"].format(v=_tm_n(wire_dia_mm, 2, lang)),
            ha="center", va="top", fontsize=8.0, color=C_WIRE)
    ax2.set_title(L["cross"], fontsize=10.5, color="#333333", pad=10)

    fig.suptitle(L["title"], fontsize=14, fontweight="bold", color=C_WIRE,
                 x=0.03, ha="left", y=0.975)
    fig.text(0.03, 0.925, L["subtitle"].format(core=core_name), fontsize=9.5,
             color="#555555", ha="left", va="top")
    fig.text(0.03, 0.045, L["note"], fontsize=7.6, color="#555555",
             ha="left", va="bottom", wrap=True)
    fig.text(0.98, 0.012, L["gen"], fontsize=7.0, color="#8A8A8A",
             ha="right", va="bottom")

    d = os.path.dirname(os.path.abspath(out_png))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    plt.savefig(out_png, dpi=dpi, facecolor="white")
    plt.close(fig)
    return out_png


# ── UnUn air-core (solenoid) construction drawing (PNG) ───────────────────
#
# For an air-core UnUn the winding IS a tapped single-layer solenoid, the
# same physical object the Transmatch calculator draws. Rather than
# duplicating transmatch_coil_png()'s geometry code, this reshapes the
# UnUn air-core design dict into the same {"coil", "totals", "taps"} shape
# transmatch_coil_png() expects and calls it directly, with UnUn-flavoured
# (not Transmatch-flavoured) title/label strings.

_UNUN_SOLENOID_PNG_STRINGS = {
    "en": {
        "title":     "UnUn (air core) — construction drawing",
        "subtitle":  "Tapped air-core autotransformer · dimensions in mm",
        "cold":      "cold end\n(ground)",
        "hot":       "free end",
        "in_tap":    "PRIMARY (TX side) {z0} Ω · turn {n}",
        "out_tap":   "SECONDARY (antenna side) · turn {n} · R {r} Ω",
        "wind_len":  "winding length = {v} mm",
        "former":    "former Ø {v} mm",
        "pitch":     "pitch p = {v} mm",
        "turn_dim":  "turn {n}: {v} mm",
        "note":      ("Turns are counted from the cold (grounded) end.  Tap distance = "
                      "(turn − 1) × pitch + wire Ø ⁄ 2.\nWind in a single layer, same "
                      "direction throughout; scrape the enamel at each tap and solder a "
                      "short pigtail without cutting the wire."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "es": {
        "title":     "UnUn (núcleo de aire) — plano constructivo",
        "subtitle":  "Autotransformador al aire con tomas · cotas en mm",
        "cold":      "extremo frío\n(masa)",
        "hot":       "extremo libre",
        "in_tap":    "PRIMARIO (lado TX) {z0} Ω · espira {n}",
        "out_tap":   "SECUNDARIO (lado antena) · espira {n} · R {r} Ω",
        "wind_len":  "longitud del bobinado = {v} mm",
        "former":    "formador Ø {v} mm",
        "pitch":     "paso p = {v} mm",
        "turn_dim":  "espira {n}: {v} mm",
        "note":      ("Las espiras se cuentan desde el extremo frío (a masa).  Distancia de "
                      "la toma = (espira − 1) × paso + Ø hilo ⁄ 2.\nBobine en una sola capa y "
                      "siempre en el mismo sentido; raspe el esmalte en cada toma y suelde una "
                      "colita sin cortar el hilo."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
    "it": {
        "title":     "UnUn (nucleo d'aria) — disegno costruttivo",
        "subtitle":  "Autotrasformatore in aria con prese · quote in mm",
        "cold":      "estremo freddo\n(massa)",
        "hot":       "estremo libero",
        "in_tap":    "PRIMARIO (lato TX) {z0} Ω · spira {n}",
        "out_tap":   "SECONDARIO (lato antenna) · spira {n} · R {r} Ω",
        "wind_len":  "lunghezza avvolgimento = {v} mm",
        "former":    "supporto Ø {v} mm",
        "pitch":     "passo p = {v} mm",
        "turn_dim":  "spira {n}: {v} mm",
        "note":      ("Le spire si contano dall'estremo freddo (a massa).  Distanza della "
                      "presa = (spira − 1) × passo + Ø filo ⁄ 2.\nAvvolgere in un solo strato, "
                      "sempre nello stesso verso; raschiare lo smalto a ogni presa e saldare uno "
                      "spezzone corto senza tagliare il filo."),
        "gen":       "NEC2 Antenna Length Optimizer (LU3VEA, CC0 v1.0)",
    },
}


def unun_solenoid_png(design: Dict[str, object],
                      out_png: str,
                      lang: str = "en",
                      dpi: int = 150) -> Optional[str]:
    """
    Render the constructional drawing of an air-core UnUn as a tapped
    single-layer solenoid, reusing transmatch_coil_png()'s geometry with
    UnUn-specific title/labels.  `design` is the dict returned by
    unun_design(core_type="air", ...).

    Two marks are shown on the winding: the PRIMARY tap at n_tap turns
    (from the cold/grounded end) and the SECONDARY end at n_total turns —
    the same n_tap / n_total the UnUn results text and the toroid drawing
    already use, just placed on a straight winding instead of a ring.

    Returns the file path, or None if matplotlib is unavailable, the
    design is not an air-core design, or the geometry is incomplete.
    """
    if not HAS_MPL:
        return None
    if design.get("core_type") != "air":
        return None

    wire_dia_mm = float(design.get("wire_dia_mm") or 0.0)
    space_mm = float(design.get("space_mm") or 0.0)
    coil_dia_mm = float(design.get("coil_dia_mm") or 0.0)
    n_total = int(design.get("n_total") or 0)
    n_tap = int(design.get("n_tap") or 0)
    r_in = float(design.get("r_in") or 50.0)
    r_out = float(design.get("r_out") or 0.0)
    if n_total <= 0 or coil_dia_mm <= 0 or wire_dia_mm <= 0:
        return None

    pitch_mm = wire_dia_mm + max(space_mm, 0.0)
    win_len_mm = (n_total - 1) * pitch_mm + wire_dia_mm

    # Reshape into exactly the {"coil", "totals", "taps"} shape
    # transmatch_coil_png() expects, with UnUn's primary/secondary standing
    # in for Transmatch's Z0-reference/per-band taps.
    res = {
        "coil": {
            "z0": r_in,
            "former_dia_mm": coil_dia_mm, "wire_dia_mm": wire_dia_mm,
            "pitch_mm": pitch_mm, "n_total": n_total,
            "win_len_mm": win_len_mm,
        },
        "totals": {"t_ref": n_tap},
        "taps": ([{"band": "", "turns": n_total, "R": r_out}]
                 if n_total != n_tap else []),
    }

    return transmatch_coil_png(
        res, out_png, lang=lang, dpi=dpi,
        strings=_UNUN_SOLENOID_PNG_STRINGS)


def load_band_impedances_csv(path: str) -> Tuple[List[Dict[str, object]], float]:
    """
    Read an optimizer CSV (export_best_csv) and return
    ([{'band','freq_mhz','R','X','active'}, …], unun_ratio).
    """
    bands: List[Dict[str, object]] = []
    ratio = 1.0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                f = float(row.get("freq_mhz") or 0)
                r = float(row.get("R_wire_ohm") or 0)
                x = float(row.get("X_wire_ohm") or 0)
            except (TypeError, ValueError):
                continue
            bands.append({
                "band": (row.get("band") or "").strip(),
                "freq_mhz": f, "R": r, "X": x,
                "active": (row.get("active") or "").strip().upper() == "YES",
            })
            try:
                ratio = float(row.get("unun_ratio") or ratio)
            except (TypeError, ValueError):
                pass
    return bands, ratio


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nec2_length_optimizer.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=T("ap_description"),
    )
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
    p.add_argument("--height", "--antenna-height", metavar="M", type=float,
                   default=None, dest="height",
                   help=T("ap_height").format(DEFAULT_HEIGHT_M))
    p.add_argument("--wire-slope-end-height", metavar="M", type=float, default=None,
                   help=(
                       "Height of the far (non-feedpoint) wire end above ground in metres. "
                       "0.0 = wire end at ground level (sloping/diagonal wire). "
                       "Omit to keep the default horizontal flat wire. "
                       "When set, NEC2 mode is forced; empirical formulas do not apply."
                   ))
    p.add_argument("--cp-end-height", metavar="M", type=float, default=None,
                   help=T("ap_cp_end_height"))
    p.add_argument("--no-counterpoise", action="store_true",
                   dest="no_counterpoise",
                   help=T("ap_no_counterpoise"))
    p.add_argument("--no-cp-return", choices=list(NO_CP_RETURN_CHOICES),
                   default=DEFAULT_NO_CP_RETURN, dest="no_cp_return",
                   help=T("ap_no_cp_return"))
    p.add_argument("--cp-stub-len", metavar="M", type=float,
                   default=DEFAULT_CP_STUB_LEN_M, dest="cp_stub_len",
                   help=T("ap_cp_stub_len").format(DEFAULT_CP_STUB_LEN_M))
    p.add_argument("--ground-model", choices=list(GROUND_MODEL_CHOICES),
                   default=DEFAULT_GROUND_MODEL, dest="ground_model",
                   help=T("ap_ground_model"))
    p.add_argument("--ground-cond", metavar="S/M", type=float,
                   default=DEFAULT_GROUND_COND,
                   help=T("ap_ground_cond").format(DEFAULT_GROUND_COND))
    p.add_argument("--ground-diel", metavar="EPS", type=float,
                   default=DEFAULT_GROUND_DIEL,
                   help=T("ap_ground_diel").format(DEFAULT_GROUND_DIEL))
    p.add_argument("--wire-diameter", metavar="MM", type=float, default=None,
                   dest="wire_diameter",
                   help=T("ap_wire_diameter").format(WIRE_RADIUS_M * 2000.0))
    p.add_argument("--wire-material", choices=sorted(WIRE_MATERIALS),
                   default=DEFAULT_WIRE_MATERIAL, dest="wire_material",
                   help=T("ap_wire_material").format(", ".join(sorted(WIRE_MATERIALS))))
    p.add_argument("--wire-conductivity", metavar="S/M", type=float, default=None,
                   dest="wire_conductivity",
                   help=T("ap_wire_conductivity").format(
                       WIRE_MATERIALS[DEFAULT_WIRE_MATERIAL]))
    p.add_argument("--segs-per-half-wave", metavar="N", type=int, default=None,
                   help=T("help_segs_per_half_wave").format(
                       SEGS_PER_HALF_WAVE_SWEEP, SEGS_PER_HALF_WAVE_FINE))
    p.add_argument("--fast", action="store_true",
                   help=T("help_fast").format(SEGS_PER_HALF_WAVE_FAST))
    p.add_argument("--converge", action="store_true",
                   help=T("help_converge"))
    p.add_argument("--target-toa", metavar="DEG", type=float,
                   default=DEFAULT_TARGET_TOA_DEG,
                   help=T("ap_target_toa"))
    p.add_argument("--gain-weight", metavar="W", type=float,
                   default=DEFAULT_GAIN_WEIGHT,
                   help=T("ap_gain_weight"))
    p.add_argument("--rerank-top", metavar="N", type=int,
                   default=DEFAULT_RERANK_TOP_N,
                   help=T("ap_rerank_top"))
    def _positive_int(value):
        ivalue = int(value)
        if ivalue < 1:
            raise argparse.ArgumentTypeError(
                f"--top-n must be >= 1 (got {value})")
        return ivalue

    p.add_argument("--top-n", metavar="N", type=_positive_int, default=20,
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
    p.add_argument("--out-construction", metavar="FILE", default="antenna_construction.png",
                   help=T("ap_out_construction"))
    p.add_argument("--out-pdf", metavar="FILE", default="antenna_brochure.pdf",
                   help=T("ap_out_pdf"))
    p.add_argument("--retry", metavar="N", type=int, default=0,
                   help=T("ap_retry"))
    p.add_argument("--no-interactive", action="store_true",
                   help=T("ap_no_interactive"))
    p.add_argument("--quiet", "-q", action="store_true",
                   help=T("ap_quiet"))
    p.add_argument("--lang", metavar="LANG", default="",
                   choices=["", "en", "es", "it"],
                   help=T("ap_lang"))
    p.add_argument("--gui", action="store_true",
                   help=T("ap_gui"))
    return p


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    global WIRE_RADIUS_M, WIRE_CONDUCTIVITY
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
    if _unknown:
        parser.print_usage(sys.stderr)
        print(f"{Fore.RED}" + T("err_unknown_args").format(" ".join(_unknown)) + f"{Style.RESET_ALL}")
        sys.exit(2)
    # Language already initialised above; honour an explicit flag in the full parse too.
    _init_lang(getattr(args, "lang", ""))
    verbose = not args.quiet

    # ── Define bands from the command line ───────────────────────────────
    calc_rows: List[CalcRow]

    # A counterpoise-less antenna needs no CP inputs at all, so every
    # counterpoise setting becomes optional (and ignored) in that mode.
    use_counterpoise = not getattr(args, "no_counterpoise", False)

    # ── Sanity-check numeric inputs before anything downstream uses them ──
    # (step sizes feed a division in build_search_grid; min/max bound a
    # search grid that mustn't be empty; height and ground constants feed
    # NEC2 cards that will happily accept nonsense and either crash deep
    # in the pipeline or silently model something unphysical.)
    _HEIGHT_HARD_FLOOR_M = 0.01  # 1 cm: below this the geometry is degenerate
    _bad = []

    for _name, _val in (("--wire-step", args.wire_step),
                         ("--cp-step", args.cp_step)):
        if _val is not None and _val <= 0:
            _bad.append(f"{_name} must be > 0 (got {_val})")

    if args.wire_min is not None and args.wire_max is not None \
            and args.wire_min > args.wire_max:
        _bad.append(f"--wire-min ({args.wire_min}) must be ≤ --wire-max ({args.wire_max})")

    if args.cp_min is not None and args.cp_max is not None \
            and args.cp_min > args.cp_max:
        _bad.append(f"--cp-min ({args.cp_min}) must be ≤ --cp-max ({args.cp_max})")

    if args.height is not None and args.height <= _HEIGHT_HARD_FLOOR_M:
        _bad.append(
            f"--height must be > {_HEIGHT_HARD_FLOOR_M} m (got {args.height}); "
            f"a wire at or below ground level cannot be modelled"
        )

    if args.ground_cond is not None and args.ground_cond < 0:
        _bad.append(f"--ground-cond must be ≥ 0 S/m (got {args.ground_cond})")

    if args.ground_diel is not None and args.ground_diel < 1:
        _bad.append(f"--ground-diel must be ≥ 1 (got {args.ground_diel})")

    if _bad:
        print(f"{Fore.RED}Invalid input:{Style.RESET_ALL}")
        for _b in _bad:
            print(f"{Fore.RED}    {_b}{Style.RESET_ALL}")
        sys.exit(1)

    _missing = []
    if not args.bands:
        _missing.append("--bands  (e.g. --bands 40m,20m,15m)")
    if args.wire_len is None:
        _missing.append("--wire-len  (starting wire length in metres)")
    if use_counterpoise and args.cp_len is None:
        _missing.append("--cp-len  (starting counterpoise length in metres)")
    if _missing:
        print(f"{Fore.RED}" + T("err_missing_args") + f"{Style.RESET_ALL}")
        for m in _missing:
            print(f"{Fore.RED}    {m}{Style.RESET_ALL}")
        print(f"{Fore.RED}" + T("err_supply_args") + f"{Style.RESET_ALL}")
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

    _wire_len_init = args.wire_len
    if not use_counterpoise:
        args.cp_len = 0.0
        print(f"  {Fore.YELLOW}" + T("no_cp_banner") + f"{Style.RESET_ALL}")
    _cp_len_init   = args.cp_len
    # One height for the whole antenna — radiator and counterpoise alike.
    _height_val    = args.height if args.height is not None else DEFAULT_HEIGHT_M

    calc_rows = []
    for _bn, _fmhz in zip(_band_names, _freqs_mhz):
        _row = CalcRow()
        _row.band       = _bn
        _row.freq_mhz   = _fmhz
        _row.active     = (_bn in _active_set)
        _row.wire_len_m = _wire_len_init
        _row.cp_len_m   = _cp_len_init
        _row.cp_height_m   = _height_val
        _row.wire_height_m = _height_val
        _row.num_radials   = 1
        _row.unun_ratio    = AUTO_UNUN_SEED   # seed only; optimised later
        calc_rows.append(_row)

    print(T("band_source_cli"))
    print(T("bands_defined").format(len(calc_rows), ', '.join(_band_names)))

    active = [r for r in calc_rows if r.active]
    if not active:
        print(f"{Fore.RED}" + T("no_active_bands") + f"{Style.RESET_ALL}")
        sys.exit(1)

    print(T("active_bands").format(len(active), len(calc_rows), ', '.join(r.band for r in active)))
    print(T("frequencies").format([r.freq_mhz for r in active]))

    # ── UnUn ratio (always automatic) ─────────────────────────────────────
    # The user no longer chooses a ratio: the optimizer sweeps the geometry,
    # finds the best UnUn for it and then re-ranks everything under that ratio
    # (see "UnUn optimisation" below).  AUTO_UNUN_SEED only scores the very
    # first sweep, before there is a geometry to optimise the ratio for.
    unun_ratio = AUTO_UNUN_SEED
    print(T("unun_auto_mode"))

    # ── Resolve range / height defaults ──────────────────────────────────
    # --wire-len and --cp-len are mandatory, so they always centre the search
    # window unless explicit min/max bounds are given.
    _MARGIN = args.margin

    if args.wire_min is None or args.wire_max is None:
        ref_wire = args.wire_len
        print(T("search_margin").format(_MARGIN, "--wire-len", ref_wire))
        if args.wire_min is None:
            args.wire_min = max(1.0, round(ref_wire - _MARGIN, 3))
            print(T("wire_min").format(args.wire_min))
        if args.wire_max is None:
            args.wire_max = round(ref_wire + _MARGIN, 3)
            print(T("wire_max").format(args.wire_max))

    if not use_counterpoise:
        # No counterpoise: the CP axis collapses to a single 0 m point.
        args.cp_min = 0.0
        args.cp_max = 0.0
    elif args.cp_min is None or args.cp_max is None:
        ref_cp = args.cp_len
        print(T("cp_margin").format(_MARGIN, "--cp-len", ref_cp))
        if args.cp_min is None:
            args.cp_min = max(1.0, round(ref_cp - _MARGIN, 3))
            print(T("cp_min").format(args.cp_min))
        if args.cp_max is None:
            args.cp_max = round(ref_cp + _MARGIN, 3)
            print(T("cp_max").format(args.cp_max))

    # ── Antenna height ────────────────────────────────────────────────────
    # A single height now describes the whole antenna: the radiator and the
    # counterpoise both start at the feedpoint, so their height is by
    # definition the same value.
    if args.height is None:
        args.height = DEFAULT_HEIGHT_M
        print(T("ant_height").format(args.height, T("ant_height_default")))
    else:
        print(T("ant_height").format(args.height, T("ant_height_arg")))

    # Keep the legacy attribute names in sync — every downstream consumer
    # (NEC deck writer, plots, report, CSV export) reads these two, and they
    # are now guaranteed to hold the same value.
    args.wire_height = args.height
    args.cp_height   = args.height

    # ── Build search grid ────────────────────────────────────────────────
    # Guard: when a sloped wire is requested the minimum wire length must be
    # at least the vertical drop (wire_height − slope_end), otherwise every
    # short point in the grid will fail with a geometry error.
    _slope_guard = getattr(args, "wire_slope_end_height", None)
    _all_freqs_guard = [cr.freq_mhz for cr in calc_rows]
    _floor_guard = ground_clearance_floor_m(_all_freqs_guard)
    _perfect_gnd = (getattr(args, "ground_model", DEFAULT_GROUND_MODEL) == "perfect"
                    or (not use_counterpoise
                        and getattr(args, "no_cp_return", DEFAULT_NO_CP_RETURN) == "ground-rod"))
    if _slope_guard is not None and not _perfect_gnd and _slope_guard < _floor_guard:
        # Announce the clamp once, up front, instead of letting nec2c return
        # garbage for every point of the sweep.
        print(f"  {Fore.YELLOW}" + T("warn_slope_below_floor").format(
            float(_slope_guard), _floor_guard, GROUND_CLEAR_FRAC_SAFE) + f"{Style.RESET_ALL}")
    if _slope_guard is not None and args.wire_height is not None:
        _z_far_guard = (0.0 if _perfect_gnd and _slope_guard <= _floor_guard
                        else max(float(_slope_guard), _floor_guard))
        _rise_guard  = args.wire_height - _z_far_guard
        if _rise_guard > 0 and args.wire_min < _rise_guard:
            _old_min = args.wire_min
            args.wire_min = math.ceil(_rise_guard / args.wire_step) * args.wire_step
            print(
                f"  {Fore.YELLOW}AVISO: wire_min ajustado de {_old_min:.2f} m a "
                f"{args.wire_min:.2f} m porque el desnivel vertical del hilo "
                f"({_rise_guard:.3f} m) supera el mínimo anterior. "
                f"Un hilo más corto no puede llegar a la altura final especificada."
                f"{Style.RESET_ALL}"
            )
            # The --wire-min ≤ --wire-max check ran on the ORIGINAL arguments,
            # long before this adjustment.  Raising wire_min above wire_max
            # here would leave an empty grid that is only noticed much later,
            # as a crash in the plotting stage after part of the output set has
            # already been written.
            if args.wire_min > args.wire_max:
                print(f"{Fore.RED}ERROR: el desnivel vertical del hilo "
                      f"({_rise_guard:.3f} m) obliga a wire_min = "
                      f"{args.wire_min:.2f} m, por encima de wire_max = "
                      f"{args.wire_max:.2f} m: no queda ninguna longitud de "
                      f"hilo que pueda alcanzar la altura final pedida. "
                      f"Amplíe --wire-max, baje --height o suba "
                      f"--wire-slope-end-height.{Style.RESET_ALL}")
                sys.exit(1)

    wire_range = (args.wire_min, args.wire_max, args.wire_step)
    cp_range   = (args.cp_min,  args.cp_max,  args.cp_step)
    try:
        grid = build_search_grid(*wire_range, *cp_range,
                                 use_counterpoise=use_counterpoise)
    except ValueError as _grid_err:
        print(f"{Fore.RED}ERROR: {_grid_err}{Style.RESET_ALL}")
        sys.exit(1)
    _n_wire = round((args.wire_max - args.wire_min) / args.wire_step) + 1
    _n_cp = (
        1 if not use_counterpoise
        else round((args.cp_max - args.cp_min) / args.cp_step) + 1
    )
    print(T("grid_size").format(_n_wire, _n_cp, len(grid)))

    # ── Counterpoise far-end height ───────────────────────────────
    # The counterpoise is built exactly like the sloping radiator: it runs from
    # the feedpoint down to this height, so its angle follows from the CP length
    # instead of being entered separately.
    _cp_end_src = (T("cp_end_height_src_arg") if args.cp_end_height is not None
                   else T("cp_end_height_src_cph"))
    if not use_counterpoise:
        args.cp_end_height = None
    if args.cp_end_height is not None and args.cp_end_height < 0.0:
        print(f"{Fore.RED}ERROR: --cp-end-height cannot be negative "
              f"(got {args.cp_end_height}).{Style.RESET_ALL}")
        sys.exit(1)
    cp_end_height = _cp_end_z(args.wire_height, args.cp_end_height, args.cp_height,
                               WIRE_RADIUS_M)
    if use_counterpoise:
        print(T("cp_end_height_msg").format(cp_end_height) + f"  {_cp_end_src}")

    # A counterpoise can only reach the requested far-end height if it is at
    # least as long as the vertical drop.  Shorter ones hang straight down, so
    # warn instead of silently ignoring the setting.
    _cp_drop_needed = args.wire_height - cp_end_height
    if use_counterpoise and _cp_drop_needed > 1e-9:
        if args.cp_max <= _cp_drop_needed:
            print(f"  {Fore.YELLOW}" + T("cp_end_height_warn_all").format(
                args.cp_min, args.cp_max, cp_end_height,
                args.wire_height, _cp_drop_needed) + f"{Style.RESET_ALL}")
        elif args.cp_min <= _cp_drop_needed:
            print(f"  {Fore.CYAN}" + T("cp_end_height_warn_some").format(
                _cp_drop_needed, cp_end_height, args.wire_height) + f"{Style.RESET_ALL}")

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

    # ── No-counterpoise return path: validate before sweeping ────────────
    if not use_counterpoise:
        if mode == "nec2" and args.no_cp_return == "reject":
            print(f"{Fore.RED}" + T("err_no_return_path") + f"{Style.RESET_ALL}")
            sys.exit(1)
        if mode == "nec2":
            _ret_label = ("ground rod → z=0 (perfect ground, GN 1)"
                          if args.no_cp_return == "ground-rod"
                          else f"coax-braid stub {args.cp_stub_len:.2f} m")
            print("  " + T("no_cp_return_msg").format(_ret_label))

    # ── Ground model summary ─────────────────────────────────────────────
    if mode == "nec2":
        _gm_eff = args.ground_model
        if not use_counterpoise and args.no_cp_return == "ground-rod":
            _gm_eff = "perfect"
        print("  " + T("ground_model_msg").format(
            "GN 1 (perfect)" if _gm_eff == "perfect" else "GN 2 (Sommerfeld-Norton)",
            ground_clearance_floor_m([cr.freq_mhz for cr in calc_rows]),
            GROUND_CLEAR_FRAC_SAFE))

    # ── Feedpoint height: validate before sweeping ───────────────────────
    # The feedpoint is never clamped away from the ground singularity — moving
    # it would simulate a different antenna — so an unusable height is an error
    # here, not a silent correction thousands of decks later.
    _all_freqs_feed = [cr.freq_mhz for cr in calc_rows]
    _gm_feed = (args.ground_model if mode == "nec2" else "perfect")
    if mode == "nec2" and not use_counterpoise and args.no_cp_return == "ground-rod":
        _gm_feed = "perfect"
    if args.wire_height is not None and float(args.wire_height) < 0.0:
        print(f"{Fore.RED}" + T("err_feedpoint_below_ground").format(
            float(args.wire_height)) + f"{Style.RESET_ALL}")
        sys.exit(1)
    if mode == "nec2":
        try:
            validate_feedpoint_height(args.wire_height, _all_freqs_feed, _gm_feed)
        except FeedpointHeightError:
            print(f"{Fore.RED}" + T("err_feedpoint_too_low").format(
                float(args.wire_height),
                ground_clearance_hard_min_m(_all_freqs_feed),
                GROUND_CLEAR_FRAC_HARD) + f"{Style.RESET_ALL}")
            sys.exit(1)

    # ── Force NEC2 mode when a slope is requested ─────────────────────────
    _slope = getattr(args, "wire_slope_end_height", None)
    if _slope is not None and mode == "empirical":
        print(f"  {Fore.YELLOW}INFO: --wire-slope-end-height requires NEC2 mode; "
              f"switching to --mode nec2.{Style.RESET_ALL}")
        if nec2c_bin is None:
            print(f"{Fore.RED}" + T("nec2c_required") + f"{Style.RESET_ALL}")
            sys.exit(1)
        mode = "nec2"

    # ── Segmentation policy ──────────────────────────────────────────────
    # The sweep may run coarse (--fast) because the RANKING is robust to
    # segmentation, but every number that gets published — the best-candidate
    # run, the exported deck, the report — is recomputed at the fine density,
    # because the IMPEDANCES are not.
    if args.segs_per_half_wave is not None:
        _spw_user  = max(5, min(int(args.segs_per_half_wave), SEGS_PER_HALF_WAVE_MAX))
        segs_sweep = segs_final = _spw_user
    else:
        segs_sweep = SEGS_PER_HALF_WAVE_FAST if args.fast else SEGS_PER_HALF_WAVE_SWEEP
        segs_final = SEGS_PER_HALF_WAVE_FINE
    segs_pattern = segs_final if args.segs_per_half_wave is not None else SEGS_PER_HALF_WAVE_FAST

    # ── Wire diameter ────────────────────────────────────────────────────
    # Every deck writer, the counterpoise clamp (_cp_end_z) and the
    # construction diagram default to WIRE_RADIUS_M, so — exactly like
    # WIRE_CONDUCTIVITY below — the CLI choice is applied once, here, and
    # cannot end up differing between the sweep, the exported deck, the
    # radiation run and the drawing.
    if getattr(args, "wire_diameter", None) is not None:
        if args.wire_diameter <= 0.0:
            print(f"{Fore.RED}ERROR: --wire-diameter must be > 0 "
                  f"(got {args.wire_diameter}).{Style.RESET_ALL}")
            sys.exit(1)
        WIRE_RADIUS_M = float(args.wire_diameter) / 2000.0
    print(T("wire_diam_msg").format(WIRE_RADIUS_M * 2000.0, WIRE_RADIUS_M * 1000.0))

    # ── Conductor losses ─────────────────────────────────────────────────
    # Every deck writer reads WIRE_CONDUCTIVITY, so the choice is applied once,
    # here, and cannot end up differing between the sweep, the exported deck
    # and the radiation run.
    _mat = getattr(args, "wire_material", DEFAULT_WIRE_MATERIAL)
    if getattr(args, "wire_conductivity", None) is not None:
        WIRE_CONDUCTIVITY = max(0.0, float(args.wire_conductivity))
        _mat = f"{_mat} (σ overridden)"
    else:
        WIRE_CONDUCTIVITY = WIRE_MATERIALS.get(_mat, WIRE_MATERIALS[DEFAULT_WIRE_MATERIAL])

    if WIRE_CONDUCTIVITY > 0.0:
        print(T("wire_loss_msg").format(_mat, WIRE_CONDUCTIVITY))
    else:
        print(f"{Fore.YELLOW}" + T("wire_loss_perfect") + f"{Style.RESET_ALL}")

    if mode == "nec2":
        print("  " + T("segs_msg").format(
            segs_sweep, segs_final, estimated_imp_uncertainty_pct(segs_final)))
        if segs_sweep < SEGS_PER_HALF_WAVE_SWEEP:
            print(f"  {Fore.YELLOW}" + T("segs_fast_warn").format(
                segs_sweep, estimated_imp_uncertainty_pct(segs_sweep))
                + f"{Style.RESET_ALL}")

    # ── Helper: run one sweep and return (results, ranked, pareto_ranked) ─
    def _run_sweep(w_min: float, w_max: float, cp_min: float, cp_max: float):
        _grid = build_search_grid(w_min, w_max, args.wire_step,
                                  cp_min, cp_max, args.cp_step,
                                  use_counterpoise=use_counterpoise)
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
                cp_end_height_m=cp_end_height,
                wire_slope_end_m=_slope,
                use_counterpoise=use_counterpoise,
                no_cp_return=args.no_cp_return,
                cp_stub_len_m=args.cp_stub_len,
                ground_model=args.ground_model,
                segs_per_half_wave=segs_sweep,
                verbose=verbose,
            )
        else:
            if use_counterpoise:
                print(f"  {Fore.YELLOW}" + T("warn_empirical_cp_geometry") + f"{Style.RESET_ALL}")
            _res = empirical_sweep(
                grid=_grid,
                calc_rows=calc_rows,
                unun_ratio=unun_ratio,
                wire_height_m=args.wire_height,
                cp_height_m=args.cp_height,
                cp_end_height_m=cp_end_height,
                wire_slope_end_m=_slope,
                use_counterpoise=use_counterpoise,
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
        _c_at_max = use_counterpoise and abs(_best.cp_len_m - cp_max) < _TOL
        _c_at_min = use_counterpoise and abs(_best.cp_len_m - cp_min) < _TOL
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

    _retry_used  = 0

    def _expand_window() -> bool:
        """Run the --retry expansion loop from the CURRENT window and scores.

        Returns True when at least one expansion improved the best score.  The
        loop is a function because it has to run twice: once under the seed
        UnUn ratio, and again after the transformer has been chosen, since the
        ratio changes which geometry wins and therefore where the optimum sits
        (see the post-UnUn boundary re-check below).
        """
        nonlocal results, ranked, pareto_ranked, pareto, _retry_used
        nonlocal _cur_w_min, _cur_w_max, _cur_cp_min, _cur_cp_max
        _improved = False

        while _retry_used < _retry_max:
            (w_at_max, w_at_min,
             c_at_max, c_at_min,
             _hw, _hc) = _check_boundaries(ranked,
                                           _cur_w_min, _cur_w_max,
                                           _cur_cp_min, _cur_cp_max)

            _need_retry = w_at_max or w_at_min or c_at_max or c_at_min
            if not _need_retry:
                print(f"\n  {Fore.GREEN}" + T("retry_converged").format(_retry_used)
                      + f"{Style.RESET_ALL}")
                break

            _retry_used += 1
            _retry_n = _retry_used
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

            # The expansions above pin one edge of the window to the current
            # best length and clamp the other to 1.0 m, so a best length below
            # 1.0 m can invert the window.  build_search_grid() now rejects
            # that outright, so collapse it to a single point instead.
            _new_w_max  = max(_new_w_max,  _new_w_min)
            _new_cp_max = max(_new_cp_max, _new_cp_min)

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
                _improved = True
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

        return _improved

    def _publish_bounds() -> None:
        """Copy the working window back onto args (final boundary warnings)."""
        args.wire_min = _cur_w_min
        args.wire_max = _cur_w_max
        args.cp_min   = _cur_cp_min
        args.cp_max   = _cur_cp_max

    _expand_window()
    _publish_bounds()

    # ── UnUn optimisation (fully automatic) ──────────────────────────────
    # The transformer ratio is never entered by the user.  The optimiser
    # alternates between the two coupled unknowns until they agree:
    #
    #   1. rank the geometries under the ratio currently in use;
    #   2. compute the best UnUn ratio for the best geometry;
    #   3. if that ratio differs, re-score every candidate with it and rank
    #      again — the ranking and the ratio must always match.
    #
    # Re-scoring reuses the stored antenna-side impedances, so no NEC2 sweep is
    # repeated; only the full-band NEC2 run of the current best geometry (used
    # to fill in bands missing from the sweep) is refreshed each pass.
    unun_result: Optional[UnUnResult] = None
    best_run_h: Optional[NEC2Run] = None
    best_run_v: Optional[NEC2Run] = None
    conv_report: Optional[ConvergenceReport] = None

    def _full_band_run(cand: "CandidateResult") -> Optional[NEC2Run]:
        """Full-band NEC2 run for one geometry (None when not in NEC2 mode)."""
        if mode != "nec2" or not nec2c_bin:
            return None
        all_freqs = [cr.freq_mhz for cr in calc_rows]
        _h = args.height if args.height is not None else DEFAULT_HEIGHT_M
        with tempfile.TemporaryDirectory(prefix="nec2opt_unun_") as _td:
            _nec = os.path.join(_td, "best_antenna.nec")
            _out = os.path.join(_td, "best_antenna.out")
            write_nec_deck(
                nec_path=_nec,
                wire_len_m=cand.wire_len_m,
                cp_len_m=cand.cp_len_m,
                freqs_mhz=all_freqs,
                wire_height_m=_h,
                wire_slope_end_m=_slope,
                cp_height_m=_h,
                cp_end_height_m=cp_end_height,
                ground_cond=args.ground_cond,
                ground_diel=args.ground_diel,
                wire_radius_m=WIRE_RADIUS_M,
                use_counterpoise=use_counterpoise,
                no_cp_return=args.no_cp_return,
                cp_stub_len_m=args.cp_stub_len,
                ground_model=args.ground_model,
                segs_per_half_wave=segs_final,
            )
            if not run_nec2c(nec2c_bin, _nec, _out):
                return None
            try:
                _run = parse_nec2_output(_out, debug=False,
                                         explicit_nec_path=_nec)
            except Exception:
                return None
        if _run is not None and not _run.freq_map():
            return None
        return _run

    def _rescore_all(cands: List[CandidateResult],
                     ratio: float) -> List[CandidateResult]:
        """Re-evaluate every candidate under a new UnUn ratio.

        Antenna-side impedances ARE geometry-only and are therefore reused;
        everything the transformer touches is rebuilt: the divisor, the
        Tx-side impedances, the VSWR figures, the avoidance scores and the
        aggregate scores.

        The avoidance block is emphatically NOT geometry-only — it was
        carried forward unchanged here, which left every candidate scored
        with the AUTO_UNUN_SEED weights no matter where the search
        converged.  resonance_preference() exists precisely to invert the
        odd/even polarity between a low-ratio feed and a 49:1/64:1 EFHW
        feed, so a wire that is ★★★ EXCELLENT at the final ratio could be
        printed as ✗ RESONANCE RISK (or the reverse), and the stale
        score_avoidance_active also perturbed score_combined through its
        −0.25 term and hence the ranking itself.
        """
        import copy as _copy
        _active_rows = [_cr for _cr in calc_rows if _cr.active]
        _w = resonance_preference(ratio)
        out: List[CandidateResult] = []
        for _c in cands:
            _new = _copy.copy(_c)
            _new.band_vswr = {}
            _new.band_R_tx = {}
            _new.band_X_tx = {}
            _vswr_penalties_r = []
            for _ar in _active_rows:
                _R = _c.band_R_ant.get(_ar.band)
                _X = _c.band_X_ant.get(_ar.band)
                if _R is None or _X is None or math.isnan(_R) or math.isnan(_X):
                    _v = 999.0
                    _new.band_R_tx[_ar.band] = 0.0
                    _new.band_X_tx[_ar.band] = 0.0
                else:
                    _v = _vswr_for_ratio(_R, _X, ratio)
                    _new.band_R_tx[_ar.band] = round(_R / ratio, 3)
                    _new.band_X_tx[_ar.band] = round(_X / ratio, 3)
                _new.band_vswr[_ar.band] = round(_v, 3)
                _vswr_penalties_r.append(_vswr_score_single(_v))
            _n = len(_vswr_penalties_r)
            _mean  = sum(_vswr_penalties_r) / _n if _n else 999.0
            _worst = max(_vswr_penalties_r) if _vswr_penalties_r else 999.0
            _new.score_vswr     = _mean
            _new.score_vswr_raw = _mean + 1.5 * _worst

            # ── Avoidance: ratio-dependent, so rebuilt from scratch ──────
            # Same shape as score_candidate(): band_avoidance over ALL
            # defined bands, score_avoidance over all, score_avoidance_active
            # over the active ones only.  A fresh dict is mandatory — _new is
            # a SHALLOW copy, so mutating _c.band_avoidance in place would
            # corrupt the candidate this one was copied from.
            _new.band_avoidance = {}
            _avoid_all = []
            for _cr in calc_rows:
                _av = band_avoidance_score(_c.wire_len_m, _cr.freq_mhz, ratio,
                                           weights=_w)
                _new.band_avoidance[_cr.band] = round(_av, 4)
                _avoid_all.append(_av)
            _new.score_avoidance = (sum(_avoid_all) / len(_avoid_all)
                                    if _avoid_all else 0.0)
            _avoid_act = [_new.band_avoidance[_ar.band] for _ar in _active_rows
                          if _ar.band in _new.band_avoidance]
            _new.score_avoidance_active = (sum(_avoid_act) / len(_avoid_act)
                                           if _avoid_act else 0.0)

            _cp_avoid_scores = []
            for _ar in _active_rows:
                _lq = C_MHZ / (4.0 * _ar.freq_mhz)
                _cp_ratio = _c.cp_len_m / _lq
                _mod2 = _cp_ratio % 2.0
                _dist = abs(_mod2 - 1.0)
                _cp_avoid_scores.append(0.25 * math.cos(math.pi * _dist / 2.0) ** 2)
            _cp_avoid_mean = (sum(_cp_avoid_scores) / len(_cp_avoid_scores)
                              if _cp_avoid_scores else 0.0)
            _new.score_combined = (_mean
                                   + 1.5 * _worst
                                   - 0.25 * _new.score_avoidance_active
                                   - 0.1 * _cp_avoid_mean)
            # The radiation term is geometry-only (the transformer cannot move
            # a lobe), so it survives the re-score untouched.
            _new.score_final = _new.score_combined + _new.score_gain
            out.append(_new)
        return out

    def _converge_unun() -> None:
        """Alternate ranking ↔ transformer ratio until the two agree."""
        nonlocal unun_ratio, results, ranked, pareto_ranked
        nonlocal unun_result, best_run_h
        _seen_ratios = {unun_ratio}
        for _pass in range(AUTO_UNUN_PASSES):
            _best = ranked[0]
            best_run_h = _full_band_run(_best)
            unun_result = find_best_unun(
                best=_best,
                calc_rows=calc_rows,
                current_unun=unun_ratio,
                run_h=best_run_h,
                run_v=best_run_v,
                nec2_strict=(mode == "nec2"),
            )
            _recommended = unun_result.best_standard_ratio
            if abs(_recommended - unun_ratio) < 1e-9:
                break                       # ratio and ranking agree — done
            if _recommended in _seen_ratios:
                # Oscillation between two ratios: keep the better-scoring one.
                if unun_result.ratio_score[_recommended] < unun_result.ratio_score[unun_ratio] - 1e-9:
                    unun_ratio = _recommended
                    for _cr in calc_rows:
                        _cr.unun_ratio = unun_ratio
                    results = _rescore_all(results, unun_ratio)
                    ranked = rank_results(results)
                    pareto_ranked = sorted(pareto_front(results),
                                           key=lambda r: r.score_combined)
                break
            print(T("unun_auto_pass").format(_pass + 1, unun_ratio, _recommended))
            unun_ratio = _recommended
            _seen_ratios.add(unun_ratio)
            for _cr in calc_rows:
                _cr.unun_ratio = unun_ratio
            results = _rescore_all(results, unun_ratio)
            ranked = rank_results(results)
            pareto_ranked = sorted(pareto_front(results),
                                   key=lambda r: r.score_combined)
        for _cr in calc_rows:
            _cr.unun_ratio = unun_ratio

    if ranked:
        print(T("optimising_unun"))
        _converge_unun()

        # ── Boundary re-check under the FINAL transformer ratio ───────────
        # The whole --retry expansion above ran while the candidates were
        # still scored with AUTO_UNUN_SEED.  Re-scoring reorders the
        # geometries already swept, but it cannot reach a geometry outside
        # the window that was explored under the seed — so if the winner
        # under the final ratio sits on an edge, the window is expanded again
        # and the ratio re-converged on the new candidates.  The two are
        # coupled, so this alternates until the window stops moving or the
        # --retry budget runs out.
        for _post_pass in range(AUTO_UNUN_PASSES):
            (w_at_max, w_at_min,
             c_at_max, c_at_min,
             _hw, _hc) = _check_boundaries(ranked,
                                           _cur_w_min, _cur_w_max,
                                           _cur_cp_min, _cur_cp_max)
            if not (w_at_max or w_at_min or c_at_max or c_at_min):
                if _post_pass:
                    print(f"  {Fore.GREEN}" + T("retry_post_unun_ok")
                          + f"{Style.RESET_ALL}")
                break
            if _retry_used >= _retry_max:
                print(f"\n  {Fore.YELLOW}" + T("retry_budget_spent")
                      + f"{Style.RESET_ALL}")
                break
            print(f"\n  {Fore.YELLOW}" + T("retry_post_unun").format(unun_ratio)
                  + f"{Style.RESET_ALL}")
            _ratio_before = unun_ratio
            if not _expand_window():
                break                       # window moved nowhere better
            _publish_bounds()
            _converge_unun()
            if abs(unun_ratio - _ratio_before) < 1e-9:
                # Same transformer on a better geometry: one more boundary
                # check is enough, the loop above will end it.
                continue

        _publish_bounds()
        best = ranked[0]
        for _cr in calc_rows:
            _cr.unun_ratio = unun_ratio

        # ── Final refinement of the winning geometry ────────────────────
        # The sweep may have run coarse; the numbers that get published must
        # not.  Re-score the winner on a full-band run at the fine density.
        # The UnUn ratio was chosen from the coarse impedances, so it is
        # re-checked against the refined ones — otherwise the report shows a
        # transformer picked from numbers it no longer prints.
        def _refine_candidate(cand: "CandidateResult"):
            """Recompute one candidate's impedances at the fine density."""
            _run = _full_band_run(cand)
            if _run is None:
                return cand, None
            _r = score_candidate(
                wire_len_m=cand.wire_len_m,
                cp_len_m=cand.cp_len_m,
                calc_rows=calc_rows,
                unun_ratio=unun_ratio,
                run=_run,
                cp_angle_deg=cand.cp_angle_deg,
                cp_end_z_m=cand.cp_end_z_m,
                cp_reach_m=cand.cp_reach_m,
                nec2_strict=True,
            )
            _r.wire_slope_end_m   = cand.wire_slope_end_m
            _r.nec2_used          = cand.nec2_used
            _r.nec2_ok            = cand.nec2_ok
            _r.note               = cand.note
            _r.segs_per_half_wave = segs_final
            return _r, _run

        def _swap_in_results(old_cand, new_cand):
            """Replace `old_cand` with `new_cand` inside `results` (by identity),
            so `results` never holds a stale copy of a candidate that has since
            been refined. Falls back to appending if the old object can't be
            found (should not normally happen)."""
            for _i, _r in enumerate(results):
                if _r is old_cand:
                    results[_i] = new_cand
                    return
            results.append(new_cand)

        def _refine_and_sync(cand):
            """Refine one candidate at the fine density and keep `results`
            (and therefore every view derived from it — `ranked`, `pareto`,
            `pareto_ranked`) pointing at the refined object instead of the
            stale sweep-density one."""
            _r, _run = _refine_candidate(cand)
            if _run is not None:
                _swap_in_results(cand, _r)
            return _r, _run

        if mode == "nec2" and nec2c_bin:
            # Refine every candidate that will actually be PUBLISHED — that
            # means the winner, the rest of the Pareto front, AND every row
            # that will appear in the "TOP N CANDIDATES" table (args.top_n,
            # default 20) — so the report table and the Pareto section never
            # mix segmentation densities, and so score_combined is only ever
            # compared between numbers computed at the same density.
            #
            # A coarse score is optimistic relative to the fine one (see the
            # module's own R/X-vs-segmentation notes above), so a candidate
            # that only *looks* top-N at sweep density can still need
            # refining — and, symmetrically, refining candidates can change
            # who the true top-N are (a refined score can fall out of the
            # window, letting the next coarse candidate rise into it). We
            # therefore refine the coarse top-N/Pareto union and iterate:
            # after each pass, re-rank and check whether the (now partly
            # refined) top-N/Pareto window still contains an un-refined
            # candidate; if so, refine it too. This converges in a handful
            # of passes because each pass either refines a previously-coarse
            # candidate (finite supply, strictly decreasing) or stops.
            _report_top_n = max(0, int(getattr(args, "top_n", 0) or 0))

            def _needs_refine(cand):
                return (cand.segs_per_half_wave or segs_sweep) < segs_final

            def _select_to_refine():
                _sel = {id(best): best}
                for _p in pareto:
                    _sel.setdefault(id(_p), _p)
                _cur_ranked = rank_results(results)
                for _r in _cur_ranked[:_report_top_n]:
                    _sel.setdefault(id(_r), _r)
                return _sel

            _refined_by_id = {}
            _pass = 0
            while True:
                _pass += 1
                _to_refine = {cid: c for cid, c in _select_to_refine().items()
                              if _needs_refine(c)}
                if not _to_refine:
                    break
                if _pass == 1:
                    if len(_to_refine) > 1:
                        print(T("refining_best").format(segs_final) +
                              f" ({len(_to_refine)} candidates)")
                    else:
                        print(T("refining_best").format(segs_final))
                else:
                    print(T("refining_best").format(segs_final) +
                          f" ({len(_to_refine)} more — top-{_report_top_n}/Pareto "
                          f"window shifted after refinement)")

                for _cid, _cand in _to_refine.items():
                    _ref, _fine_run = _refine_and_sync(_cand)
                    if _fine_run is None:
                        print(f"  {Fore.YELLOW}" + T("refining_best_failed") + f"{Style.RESET_ALL}")
                        continue
                    _refined_by_id[_cid] = _ref
                    if _cand is best:
                        best, best_run_h = _ref, _fine_run

                # Rebuild every derived view from the now-consistent
                # `results` so `ranked`, `pareto`, and `pareto_ranked` all
                # agree on which object (and which segmentation density)
                # represents each candidate before the next pass decides
                # whether the top-N/Pareto window has shifted.
                ranked        = rank_results(results)
                pareto        = pareto_front(results)
                pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
                best          = ranked[0] if ranked else best

            # Final rebuild — a no-op if the loop above already left things
            # consistent, but keeps this block correct even when nothing
            # needed refining (e.g. --segs-per-half-wave was given, so
            # segs_sweep == segs_final and every candidate is already fine).
            ranked        = rank_results(results)
            pareto        = pareto_front(results)
            pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
            best          = ranked[0] if ranked else best

            if best_run_h is not None:
                _uu = find_best_unun(
                    best=best, calc_rows=calc_rows, current_unun=unun_ratio,
                    run_h=best_run_h, run_v=None, nec2_strict=True,
                )
                if abs(_uu.best_standard_ratio - unun_ratio) > 1e-9:
                    # The refined impedances point at a different transformer.
                    print(f"  {Fore.YELLOW}" + T("unun_refined_change").format(
                        unun_ratio, _uu.best_standard_ratio) + f"{Style.RESET_ALL}")
                    unun_ratio = _uu.best_standard_ratio
                    for _cr in calc_rows:
                        _cr.unun_ratio = unun_ratio
                    results       = _rescore_all(results, unun_ratio)
                    ranked        = rank_results(results)
                    pareto        = pareto_front(results)
                    pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
                    best          = ranked[0] if ranked else best
                    # Re-scoring under the new ratio can reshuffle the top-N
                    # / Pareto window the same way the initial refinement
                    # pass could — a candidate that wasn't in that window
                    # under the old ratio can enter it now, still at sweep
                    # density. Re-run the same converge-to-fixed-point
                    # refinement used above rather than refining `best`
                    # alone, or a non-winner row in the reshuffled top-N
                    # table could stay published at the coarse density.
                    _pass = 0
                    while True:
                        _pass += 1
                        _to_refine = {cid: c for cid, c in _select_to_refine().items()
                                      if _needs_refine(c)}
                        if not _to_refine:
                            break
                        print(T("refining_best").format(segs_final) +
                              f" ({len(_to_refine)} — top-{_report_top_n}/Pareto "
                              f"window shifted after UnUn re-scoring)")
                        for _cid, _cand in _to_refine.items():
                            _ref2, _fine_run2 = _refine_and_sync(_cand)
                            if _fine_run2 is None:
                                print(f"  {Fore.YELLOW}" + T("refining_best_failed") + f"{Style.RESET_ALL}")
                                continue
                            if _cand is best:
                                best, best_run_h = _ref2, _fine_run2
                        ranked        = rank_results(results)
                        pareto        = pareto_front(results)
                        pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)
                        best          = ranked[0] if ranked else best
                    _uu = find_best_unun(
                        best=best, calc_rows=calc_rows, current_unun=unun_ratio,
                        run_h=best_run_h, run_v=None, nec2_strict=True,
                    )
                unun_result = _uu

        # ── Radiation re-ranking of the shortlist ───────────────────────
        # Until this point the ranking knows nothing about where the power
        # goes: the sweep decks carry no RP card, so a candidate whose main
        # lobe points at the zenith scores exactly like one that puts the
        # same power at 20°.  The N best impedance candidates are therefore
        # re-simulated WITH a pattern and re-ordered by
        #     score_final = score_combined − gain_weight × gain(target TOA)
        # This costs N extra NEC2 runs, not one per grid point.
        _rerank_n = max(0, int(getattr(args, "rerank_top", DEFAULT_RERANK_TOP_N)))
        _gain_w   = float(getattr(args, "gain_weight", DEFAULT_GAIN_WEIGHT))
        _tgt_toa  = float(getattr(args, "target_toa", DEFAULT_TARGET_TOA_DEG))
        if (mode == "nec2" and nec2c_bin and _rerank_n > 0 and _gain_w > 0.0):
            _shortlist = [r for r in ranked[:_rerank_n] if r.nec2_ok]
            if _shortlist:
                print("\n" + T("gain_rerank_header").format(len(_shortlist), _tgt_toa))
                _h_rr = args.height if args.height is not None else DEFAULT_HEIGHT_M
                _spw_rr = max(SEGS_PER_HALF_WAVE_FAST, int(segs_sweep or SEGS_PER_HALF_WAVE_FAST))
                _any_pattern = False
                for _i, _cand in enumerate(_shortlist, 1):
                    if verbose:
                        print(T("gain_rerank_progress").format(
                            _i, len(_shortlist), _cand.wire_len_m, _cand.cp_len_m),
                            end="\r")
                    _ok_pat = evaluate_pattern(
                        cand=_cand,
                        calc_rows=calc_rows,
                        nec2c_bin=nec2c_bin,
                        wire_height_m=_h_rr,
                        cp_height_m=_h_rr,
                        ground_cond=args.ground_cond,
                        ground_diel=args.ground_diel,
                        target_toa_deg=_tgt_toa,
                        gain_weight=_gain_w,
                        cp_end_height_m=cp_end_height,
                        wire_slope_end_m=_slope,
                        use_counterpoise=use_counterpoise,
                        no_cp_return=args.no_cp_return,
                        cp_stub_len_m=args.cp_stub_len,
                        ground_model=args.ground_model,
                        segs_per_half_wave=_spw_rr,
                    )
                    _any_pattern = _any_pattern or _ok_pat
                if verbose:
                    print(" " * 70, end="\r")

                if not _any_pattern:
                    print(f"  {Fore.YELLOW}" + T("gain_rerank_failed")
                          + f"{Style.RESET_ALL}")
                else:
                    # Show what the pattern data changed, candidate by candidate.
                    print(T("gain_rerank_table_hdr").format(
                        "wire", "cp", "VSWR sc.", f"dBi@{_tgt_toa:.0f}°",
                        "TOA", "final"))
                    print("    " + "─" * 62)
                    for _c in _shortlist:
                        _g = ("%8.2f" % _c.gain_toa_mean) if _c.gain_toa_mean is not None else "     ---"
                        _t = ("%6.0f°" % _c.toa_worst_deg) if _c.toa_worst_deg is not None else "    ---"
                        print(f"    {_c.wire_len_m:6.2f}  {_c.cp_len_m:9.2f}  "
                              f"{_c.score_combined:9.3f}  {_g:>10}  {_t:>8}  "
                              f"{_c.score_final:10.3f}")

                    def _order_with_pattern(cands):
                        """Rank with the radiation term where it is known.

                        Candidates that were re-simulated are ordered by
                        score_final; the rest keep their impedance ordering
                        behind them, since comparing a candidate carrying a
                        gain bonus against one that never got measured would
                        just reward whoever happened to be simulated."""
                        _ev   = [r for r in cands if r.pattern_ok]
                        _rest = [r for r in cands if not r.pattern_ok]
                        return (sorted(_ev,   key=lambda r: r.score_final)
                                + sorted(_rest, key=lambda r: r.score_combined))

                    def _publish(cand):
                        """Refine one candidate and keep its radiation data."""
                        _rf, _run = _refine_candidate(cand)
                        if _run is None:
                            return cand, None
                        # _refine_candidate rebuilds the candidate from the
                        # NEC2 run, so the pattern results have to be carried
                        # across or they would be silently dropped.
                        _rf.band_gain_max = dict(cand.band_gain_max)
                        _rf.band_toa      = dict(cand.band_toa)
                        _rf.band_gain_toa = dict(cand.band_gain_toa)
                        _rf.gain_toa_mean = cand.gain_toa_mean
                        _rf.toa_worst_deg = cand.toa_worst_deg
                        _rf.pattern_ok    = cand.pattern_ok
                        _rf.score_gain    = cand.score_gain
                        _rf.score_final   = _rf.score_combined + _rf.score_gain
                        return _rf, _run

                    _prev_best = ranked[0]
                    ranked     = _order_with_pattern(ranked)
                    _new_best  = ranked[0]

                    if _new_best is not _prev_best:
                        _dg = ((_new_best.gain_toa_mean or 0.0)
                               - (_prev_best.gain_toa_mean or 0.0))
                        print(f"  {Fore.YELLOW}" + T("gain_rerank_changed").format(
                            _new_best.wire_len_m, _new_best.cp_len_m,
                            _dg, _tgt_toa) + f"{Style.RESET_ALL}")
                        # The new winner must be published with the same
                        # fine-density impedances and the same transformer
                        # check the previous winner received.
                        best = _new_best
                        _ref3, _fine_run3 = _publish(best)
                        if _fine_run3 is not None:
                            ranked[0], best, best_run_h = _ref3, _ref3, _fine_run3

                        # The transformer was chosen for the OLD winner.  A
                        # different geometry can want a different ratio, and
                        # publishing a ranking built on one ratio next to a
                        # transformer picked for another is exactly the silent
                        # mismatch this tool exists to avoid.
                        _uu3 = find_best_unun(
                            best=best, calc_rows=calc_rows,
                            current_unun=unun_ratio,
                            run_h=best_run_h, run_v=None, nec2_strict=True,
                        )
                        if abs(_uu3.best_standard_ratio - unun_ratio) > 1e-9:
                            print(f"  {Fore.YELLOW}" + T("unun_refined_change").format(
                                unun_ratio, _uu3.best_standard_ratio)
                                + f"{Style.RESET_ALL}")
                            unun_ratio = _uu3.best_standard_ratio
                            for _cr in calc_rows:
                                _cr.unun_ratio = unun_ratio
                            # Re-scoring copies the candidates, so the measured
                            # radiation term travels with them (a transformer
                            # cannot move a lobe).
                            results = _rescore_all(results, unun_ratio)
                            ranked  = _order_with_pattern(rank_results(results))
                            pareto_ranked = sorted(pareto_front(results),
                                                   key=lambda r: r.score_combined)
                            _ref4, _fine_run4 = _publish(ranked[0])
                            if _fine_run4 is not None:
                                ranked[0], best, best_run_h = _ref4, _ref4, _fine_run4
                            else:
                                best = ranked[0]
                            _uu3 = find_best_unun(
                                best=best, calc_rows=calc_rows,
                                current_unun=unun_ratio,
                                run_h=best_run_h, run_v=None, nec2_strict=True,
                            )
                        unun_result = _uu3
                    else:
                        print(f"  {Fore.GREEN}" + T("gain_rerank_kept")
                              + f"{Style.RESET_ALL}")
                        best = ranked[0]

        # ── Segmentation convergence self-check (--converge) ────────────
        if args.converge and mode == "nec2" and nec2c_bin:
            print(T("converge_header").format(
                best.segs_per_half_wave or segs_final,
                ", ".join(f"{f:g}x" for f in CONVERGENCE_FACTORS)))
            conv_report = check_segmentation_convergence(
                best=best,
                calc_rows=calc_rows,
                nec2c_bin=nec2c_bin,
                base_spw=int(best.segs_per_half_wave or segs_final),
                wire_height_m=args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M,
                wire_slope_end_m=_slope,
                cp_height_m=args.cp_height,
                cp_end_height_m=cp_end_height,
                ground_cond=args.ground_cond,
                ground_diel=args.ground_diel,
                use_counterpoise=use_counterpoise,
                no_cp_return=args.no_cp_return,
                cp_stub_len_m=args.cp_stub_len,
                ground_model=args.ground_model,
                verbose=verbose,
            )
            _print_convergence(conv_report, calc_rows)
            if conv_report.ran:
                best.conv_r_drift_pct = conv_report.max_r_drift_pct
                best.conv_x_drift_ohm = conv_report.max_x_drift_ohm

        # `_converge_unun()` can exit (oscillation break, or the pass
        # budget running out — AUTO_UNUN_PASSES) with `ranked[0]` having
        # moved on to a geometry different from the one `unun_result` was
        # actually computed against, and `best` may since have been
        # reassigned to that newer `ranked[0]` too — see 4.8. Recompute
        # once against the geometry we are about to print so the header
        # and the numbers under it always describe the same antenna.
        if unun_result is not None and unun_result.source_geometry is not best:
            best_run_h = _full_band_run(best)
            unun_result = find_best_unun(
                best=best,
                calc_rows=calc_rows,
                current_unun=unun_ratio,
                run_h=best_run_h,
                run_v=best_run_v,
                nec2_strict=(mode == "nec2"),
            )

        print(f"\n  {Fore.GREEN}" + T("unun_auto_selected").format(unun_ratio)
              + f"{Style.RESET_ALL}")
        print(T("unun_auto_geometry").format(best.wire_len_m, best.cp_len_m))

        if unun_result is not None:
            print(f"\n  {Fore.CYAN}" + T("unun_analysis_header").format(
                best.wire_len_m, best.cp_len_m) + f"{Style.RESET_ALL}")
            print(T("unun_current").format(unun_ratio,
                                           unun_result.ratio_score[unun_ratio]))
            print(T("unun_best_std").format(unun_result.best_standard_ratio,
                                            unun_result.best_standard_score))
            print(T("unun_continuous").format(unun_result.best_continuous_ratio,
                                              unun_result.best_continuous_score))

            active_bands = [cr.band for cr in calc_rows if cr.active]
            print(f"\n    {'Band':>8}  {'VSWR':>9}  {'Best ratio':>12}  {'VSWR@best':>10}")
            print(f"    {'':─<8}  {'':─<9}  {'':─<12}  {'':─<10}")
            for b in active_bands:
                cur_v = best.band_vswr.get(b, 999.0)
                opt_n = unun_result.per_band_best_ratio.get(b, None)
                opt_v = unun_result.per_band_best_vswr.get(b, None)
                opt_n_str = f"{opt_n:10.2f}:1" if opt_n is not None else f"{'N/A (no NEC2)':>11}"
                opt_v_str = f"{opt_v:10.3f}"   if opt_v is not None else f"{'---':>10}"
                print(f"    {b:>8}  {cur_v:9.2f}  {opt_n_str}  {opt_v_str}")
            print()

    # ── Display best candidate ─────────────────────────────────────────────
    if ranked:
        best = ranked[0]
        print(f"\n  {Fore.GREEN}" + T("best_candidate") + f"{Style.RESET_ALL}"
              f"  wire = {best.wire_len_m:.3f} m   cp = {best.cp_len_m:.3f} m"
              f"   ({best.cp_angle_deg:.1f}°)")
        print(T("combined_score").format(best.score_combined))
        print(T("vswr_penalty").format(best.score_vswr))
        print(T("avoidance_mean").format(best.score_avoidance))

        # ── Radiation performance of the winner ──────────────────────────
        # A VSWR figure on its own has hidden a zenith-pointing antenna more
        # than once, so gain and take-off angle are printed next to it, per
        # band, and a high TOA is called out explicitly.
        _tgt_toa_show = float(getattr(args, "target_toa", DEFAULT_TARGET_TOA_DEG))
        if best.pattern_ok and best.band_toa:
            print(f"\n  {Fore.CYAN}"
                  + T("radiation_summary_hdr").format(_tgt_toa_show)
                  + f"{Style.RESET_ALL}")
            print(T("radiation_row_hdr").format(
                T("radiation_col_band"), T("radiation_col_mhz"),
                T("radiation_col_gain"), T("radiation_col_toa"),
                T("radiation_col_gtoa")))
            print("    " + "─" * 52)
            for cr in [c for c in calc_rows if c.active]:
                b     = cr.band
                _gmax = best.band_gain_max.get(b)
                _toa  = best.band_toa.get(b)
                _gt   = best.band_gain_toa.get(b)
                if _toa is None:
                    continue
                _toa_col = (Fore.RED if _toa >= HIGH_TOA_WARN_DEG else
                            Fore.YELLOW if _toa >= 45.0 else Fore.GREEN)
                print(f"    {b:>8}  {cr.freq_mhz:7.3f}  "
                      f"{(_gmax if _gmax is not None else 0.0):10.2f}  "
                      f"{_toa_col}{_toa:6.0f}°{Style.RESET_ALL}  "
                      f"{(_gt if _gt is not None else 0.0):12.2f}")
            # Conductor loss actually measured by NEC2, when the run reported a
            # power budget.  Silent when it did not — the figure is either real
            # or absent, never assumed.
            _effs = []
            if best_run_h is not None:
                _fm = best_run_h.freq_map()
                for cr in [c for c in calc_rows if c.active]:
                    _fp = None
                    if _fm:
                        _key = min(_fm.keys(), key=lambda k: abs(k - cr.freq_mhz))
                        _tol = freq_match_tol_mhz(cr.freq_mhz)
                        if abs(_key - cr.freq_mhz) <= _tol:
                            _fp = _fm[_key]
                    if _fp is not None and getattr(_fp, "efficiency", None) is not None:
                        _effs.append(_fp.efficiency)
            if _effs:
                print(T("conductor_efficiency").format(
                    100.0 * sum(_effs) / len(_effs)))

            for cr in [c for c in calc_rows if c.active]:
                _toa = best.band_toa.get(cr.band)
                if _toa is not None and _toa >= HIGH_TOA_WARN_DEG:
                    print(f"\n  {Fore.RED}"
                          + T("warn_high_toa").format(cr.band, _toa)
                          + f"{Style.RESET_ALL}")
        elif mode == "nec2":
            print(f"  {Fore.YELLOW}" + T("warn_no_radiation_data")
                  + f"{Style.RESET_ALL}")

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
        # Segmentation uncertainty on the antenna-side impedances: measured by
        # --converge when it ran, estimated from the segmentation otherwise.
        _unc_pct = (conv_report.r_uncertainty_pct() if conv_report is not None
                    else estimated_imp_uncertainty_pct(best.segs_per_half_wave))
        _unc_x = (conv_report.x_uncertainty_ohm() if conv_report is not None
                  else None)
        if mode == "nec2":
            print("    " + T("impedance_uncertainty_note").format(
                best.segs_per_half_wave or segs_final, _unc_pct,
                T("imp_unc_measured") if (conv_report is not None and conv_report.ran)
                else T("imp_unc_estimated")))
            print("    " + (T("imp_unc_x_measured").format(_unc_x)
                            if _unc_x is not None else T("imp_unc_x_estimated")))
        hdr = (f"    {'Band':>8}  {'MHz':>7}  "
               f"{'R_ant':>13}  {'X_ant':>13}  {'|Z_ant|':>8}  "
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
            if mode == "nec2" and src.startswith("NEC2"):
                _u = abs(R_a) * _unc_pct / 100.0
                _Ra_s = fmt_imp_with_unc(R_a, _u)
                _Xa_s = fmt_imp_with_unc(X_a, _unc_x, signed=True)
            else:
                _Ra_s, _Xa_s = f"{R_a:.1f}", f"{X_a:+.1f}"
            print(f"    {b:>8}  {cr.freq_mhz:7.3f}  "
                  f"{_Ra_s:>13}  {_Xa_s:>13}  {Z_a:8.1f}  "
                  f"{R_t:7.2f}  {X_t:+7.2f}  {Z_t:7.2f}  "
                  f"{vswr_color}{v:5.2f}{Style.RESET_ALL}  {src:>8}")
        print()

    # ── Write outputs ────────────────────────────────────────────────────
    print(T("writing_outputs"))

    # The ranking and the ratio were reconciled by the automatic UnUn pass, so
    # every output (report, CSV, plots, NEC deck, PDF) uses the same value.
    export_unun = unun_ratio

    report = write_report(
        ranked=ranked,
        pareto=pareto_ranked,
        calc_rows=calc_rows,
        unun_ratio=unun_ratio,
        wire_range=(args.wire_min, args.wire_max, args.wire_step),
        cp_range=(args.cp_min, args.cp_max, args.cp_step),
        mode=mode,
        out_path=args.out_txt,
        unun_result=unun_result,
        total_candidates=len(results),
        top_n=args.top_n,
        wire_height_m=args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M,
        cp_end_height_m=cp_end_height,
        use_counterpoise=use_counterpoise,
        no_cp_return=args.no_cp_return,
        cp_stub_len_m=args.cp_stub_len,
        ground_model=args.ground_model,
        segs_sweep=segs_sweep,
        segs_final=segs_final,
        conv_report=conv_report,
        target_toa_deg=float(getattr(args, "target_toa", DEFAULT_TARGET_TOA_DEG)),
    )
    print(T("report_saved").format(args.out_txt))

    if ranked:
        export_best_csv(ranked[0], calc_rows, export_unun, args.out_csv)
        print(T("csv_best_saved").format(args.out_csv, export_unun))

    if results:
        plot_results(results, pareto, ranked, calc_rows, unun_ratio, args.out_png)

    _wh_out  = args.height if args.height is not None else DEFAULT_HEIGHT_M
    _cph_out = _wh_out          # counterpoise shares the antenna height

    if ranked:
        try:
            plot_construction_diagram(
                best=ranked[0],
                calc_rows=calc_rows,
                unun_ratio=export_unun,
                out_png=args.out_construction,
                wire_height_m=_wh_out,
                cp_height_m=_cph_out,
                cp_end_height_m=cp_end_height,
                wire_slope_end_m=_slope,
                wire_radius_mm=WIRE_RADIUS_M * 1000.0,
                use_counterpoise=use_counterpoise,
                no_cp_return=args.no_cp_return,
                cp_stub_len_m=args.cp_stub_len,
                ground_model=args.ground_model,
            )
        except ValueError as _cd_err:
            # The same geometry validation used by write_nec_deck() now runs
            # here too, so a winning candidate whose geometry cannot be drawn
            # cannot be silently rendered either. This should not trigger for
            # a candidate that already produced a successful NEC2 run, but if
            # it does, report it instead of aborting the whole run: the report
            # (.txt) and CSV above are already written.
            print(T("construction_plot_skipped").format(_cd_err))

    if ranked:
        write_best_nec_deck(
            best=ranked[0],
            calc_rows=calc_rows,
            out_path=args.out_nec,
            wire_height_m=_wh_out,
            wire_slope_end_m=_slope,
            cp_height_m=_cph_out,
            cp_end_height_m=cp_end_height,
            ground_cond=args.ground_cond,
            ground_diel=args.ground_diel,
            wire_radius_m=WIRE_RADIUS_M,
            use_counterpoise=use_counterpoise,
            no_cp_return=args.no_cp_return,
            cp_stub_len_m=args.cp_stub_len,
            ground_model=args.ground_model,
            segs_per_half_wave=segs_final,
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
            cp_end_height_m=cp_end_height,
            ground_cond=args.ground_cond,
            ground_diel=args.ground_diel,
            use_counterpoise=use_counterpoise,
            no_cp_return=args.no_cp_return,
            cp_stub_len_m=args.cp_stub_len,
            ground_model=args.ground_model,
            segs_per_half_wave=segs_pattern,
        )
    elif ranked and mode != "nec2":
        print(T("radiation_nec2_only_inline").format(mode))

    if ranked:
        print(T("pdf_generating"))
        _rad_png = args.out_radiation if (mode == "nec2" and nec2c_bin
                                           and os.path.isfile(args.out_radiation)) else None
        _ok = write_pdf_brochure(
            best=ranked[0],
            calc_rows=calc_rows,
            unun_ratio=export_unun,
            mode=mode,
            out_path=args.out_pdf,
            construction_png=args.out_construction,
            radiation_png=_rad_png,
            wire_height_m=_wh_out,
            unun_result=unun_result,
            use_counterpoise=use_counterpoise,
            no_cp_return=args.no_cp_return,
            cp_stub_len_m=args.cp_stub_len,
            segs_final=segs_final,
            conv_report=conv_report,
        )
        if _ok:
            print(T("pdf_saved").format(args.out_pdf))

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
        import tkinter  # probe availability first
    except ImportError:
        print("ERROR: tkinter is not available in this Python installation.")
        print("Install it (e.g. 'sudo apt install python3-tk') and retry.")
        sys.exit(1)

    # ── All GUI code is inlined below so the file is self-contained ──────

    import threading as _threading
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    from pathlib import Path

    # ── Band reference data ───────────────────────────────────────────────
    # Use the module-level table/finder directly (defined above, already in
    # scope) instead of a private GUI copy that silently drifts out of sync
    # and omits engines (onec/OpenNEC) and platforms (Windows) the CLI
    # already supports.
    _KNOWN_BANDS = BAND_CENTRE_FREQ_MHZ.keys()

    def _gui_find_nec2c() -> str:
        """Non-interactive wrapper around the module-level find_nec2c().

        interactive=False so it never calls input() (there is no console
        prompt to answer from a GUI callback); returns "" instead of None
        so callers can keep using a falsy-string check.
        """
        return find_nec2c(interactive=False) or ""

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
            "bands_label":        "Bands (comma-separated):",
            "known_prefix":       "Known: ",
            "freqs_label":        "Frequencies (MHz, optional):",
            "freqs_hint":         ("Leave empty for known amateur bands (auto-resolved). "
                                   "Required only for unrecognised band names."),
            "wire_len":           "Starting wire length (m):",
            "cp_len":             "Starting CP length (m):",
            "active_bands_lf":    "Active Bands (VSWR Scoring)",
            "active_bands_desc":  ("Override which bands are scored for VSWR. "
                                   "Leave empty to score every band listed above."),
            "active_bands":       "Active bands:",
            "active_bands_eg":    "(e.g.  40m,20m)",
            "optlang_lf":         "Optimizer Language",
            "optlang_label":      "Language:",
            "optlang_hint":       "auto = detected from system locale",
            "margin_lf":          "Auto-derived Margin",
            "margin_label":       "Search margin (±):",
            "margin_hint":        "m   Applied around the wire & CP starting lengths.",
            "wire_range_lf":      "Wire Length Range  (overrides margin)",
            "leave_empty_wire":   "Leave min/max empty to use margin.",
            "use_cp_chk":         "Use counterpoise",
            "use_cp_hint":         "uncheck for an antenna with no counterpoise (radiator only)",
            "no_cp_return_lf":    "Return Path Without Counterpoise",
            "no_cp_return_hint":  ("NEC-2 has no implicit return path: a wire fed at its end against "
                                   "nothing is an open circuit, not an antenna. Choose how the return "
                                   "conductor is modelled."),
            "no_cp_rod":          "Ground rod: vertical conductor from the feedpoint to z=0 (forces perfect ground, GN 1)",
            "no_cp_stub":         "Coax-braid stub: short vertical stub for the common-mode path (real ground kept)",
            "no_cp_reject":       "Reject: refuse NEC2 mode without a counterpoise (empirical mode only)",
            "cp_stub_len_lbl":    "Coax-braid stub length:",
            "cp_stub_len_hint":   "m   Only used by the coax-braid stub model.",
            "ground_model_lf":    "Ground Model",
            "ground_model_som":   "Sommerfeld-Norton (real ground) — wire ends kept 0.05·λ clear of ground",
            "ground_model_per":   "Perfect ground (GN 1) — wire ends may sit at exactly z=0 (real ground connection)",
            "ground_model_hint":  ("NEC-2 is singular near a Sommerfeld-Norton ground; a wire end at 1 mm "
                                   "gives garbage without any error message. A galvanic ground connection "
                                   "needs GN 1 (or NEC-4)."),
            "wire_conductor_lf":  "Conductor",
            "wire_diam_lbl":      "Wire diameter:",
            "wire_diam_hint":     "For an HF end-fed, diameter moves R and especially Q.",
            "wire_material_lbl": "Material:",
            "wire_cond_override_lbl": "Conductivity override (σ):",
            "wire_cond_override_hint": ("Optional. Leave blank to use the selected material's conductivity. "
                                        "Overrides the material choice above when set."),
            "segs_lf":            "Accuracy / Segmentation",
            "segs_mode_fine":     ("Accurate (sweep %d, published results %d seg/half wave) — recommended"
                                   % (SEGS_PER_HALF_WAVE_SWEEP, SEGS_PER_HALF_WAVE_FINE)),
            "segs_mode_fast":     ("Fast sweep (%d seg/half wave) — ranking only, the winner "
                                   "is still recomputed accurately" % SEGS_PER_HALF_WAVE_FAST),
            "segs_mode_custom":   "Custom segments per half wave:",
            "segs_converge_cb":   "Run the convergence check on the winning geometry (2x / 4x segmentation)",
            "segs_hint":          ("21 segments per half wave is enough for radiation patterns but not for "
                                   "impedance: R comes out ~14% low and the reactance has the wrong sign. "
                                   "The sign only settles above ~60 segments per half wave, which is why the "
                                   "published impedances are recomputed there."),
            "cp_range_lf":        "Counterpoise Length Range  (overrides margin)",
            "rad_lf":             "Radiation / Take-off Angle",
            "rad_target_toa_lbl": "Target take-off angle (°):",
            "rad_gain_weight_lbl":"Gain weight (0 = off):",
            "rad_rerank_top_lbl": "Candidates re-simulated with pattern:",
            "rad_hint":           ("The sweep scores impedance only, so an antenna that fires straight up "
                                   "scores the same as one that puts the power at a low angle. The best N "
                                   "candidates are therefore re-simulated with a full radiation pattern and "
                                   "re-ordered by score_combined − weight × gain at the target take-off "
                                   "angle. Set the weight to 0 to rank by VSWR alone."),
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
            "height_lbl":         "antenna height:",
            "wire_slope_end_lbl": "slope-end-height:",
            "cp_end_height_lbl":  "cp-end-height:",
            "height_hint":        "Feedpoint height above ground — radiator and counterpoise share it  (default 8 m)",
            "wire_slope_end_hint": "Far-end height for sloped wire  (0 = ground; leave blank for horizontal)",
            "cp_end_height_hint": "Far-end height of the counterpoise  (0 = ground; leave blank to keep it level)",
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
            "run_btn":            "▶  Run Optimizer",
            "stop_btn":           "■  Stop",
            "show_report_btn":    "📄  Show Report",
            "show_radiation_btn": "📡  Show Radiation Pattern",
            "show_pdf_btn":       "📑  Show Final Report (PDF)",
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
            "hint_height":        "antenna height above ground (radiator + counterpoise)",
            "hint_cp_end_height": "height reached by the far end of the counterpoise",
            "hint_conductivity":  "soil conductivity in S/m",
            "hint_permittivity":  "relative permittivity (dielectric constant)",
            "hint_out_txt":       "ranked results text report",
            "hint_out_png":       "score heat-map + VSWR bar charts",
            "hint_out_csv":       "best candidate in CSV format",
            "hint_out_nec":          "NEC2 input deck for best geometry",
            "hint_out_rad":          "radiation pattern PNG (NEC2 only)",
            "hint_out_construction": "antenna construction diagram PNG",
            "hint_out_pdf":          "PDF brochure with full results (requires reportlab)",
            # ── UnUn / Transmatch tab ─────────────────────────────────
            "tab_ut":             "  UnUn / Transmatch  ",
            "ut_sub_unun":        "  UnUn  ",
            "ut_sub_tm":          "  Transmatch  ",
            "ut_ant_lf":          "Antenna Data  (auto-filled when the optimizer finishes — editable)",
            "ut_reload_btn":      "⟳  Reload from optimizer",
            "ut_band":            "Band:",
            "ut_freq":            "Frequency (MHz):",
            "ut_rout":            "Load R_out (Ω):",
            "ut_xout":            "Load X_out (Ω):",
            "ut_rin":             "Input R_in (Ω):",
            "ut_xin":             "Input X_in target (Ω):",
            "ut_manual":          "(manual)",
            "ut_no_data":         "No optimizer results loaded — values can be typed by hand.",
            "ut_loaded":          "Antenna data loaded: {n} bands  ({file})",
            "ut_load_err":        "Could not read the optimizer CSV:\n{e}",
            "ut_csv_missing":     "CSV not found:\n{file}\n\nRun the optimizer first (Run tab).",
            "ut_core_lf":         "UnUn Transformer & Core",
            "ut_core_type":       "Core / Air:",
            "ut_core_type_core":  "Core (toroid)",
            "ut_core_type_air":   "Air (solenoid)",
            "ut_ratio_mode":      "Compensate / Ratio:",
            "ut_ratio_compensate":"Compensate (auto, from R_out / R_in)",
            "ut_ratio_fixed":     "Fixed ratio",
            "ut_ratio_val":       "Ratio (N²):",
            "ut_core":            "Toroid core:",
            "ut_np":              "Primary turns (Np):",
            "ut_wire":            "Wire diameter (mm):",
            "ut_coil_dia":        "Coil former diameter (mm):",
            "ut_space":           "Space between turns (mm):",
            "ut_air_note":        ("Air-core UnUn: single-layer solenoid. Toroid magnetics, "
                                   "saturation and core-loss/power figures below do not apply "
                                   "and are not shown."),
            "ut_res_lf":          "UnUn Results",
            "ut_mb_lf":           "Multi-band Reactive Compensation Analysis",
            "ut_mb_note":         ("A fixed series component cancels the reactance only at the design "
                                   "frequency; on the other bands it over- or under-compensates. "
                                   "Blue values below are editable."),
            "ut_mb_auto":         "auto (from Section 3)",
            "ut_mb_type":         "Compensation type:",
            "ut_mb_val":          "Component value:",
            "ut_mb_ratio":        "UnUn impedance ratio (N²):",
            "ut_mb_z0":           "Reference impedance Z₀ (Ω):",
            "ut_export_btn":      "💾  Export TXT…",
            "ut_export_done":     "Report saved:\n{file}",
            # UnUn result labels
            "ut_r_sec2":          "2.  UNUN TRANSFORMER PROPERTIES",
            "ut_r_ratio":         "Impedance ratio (Rout/Rin)",
            "ut_r_ratio_fixed":   "Impedance ratio (fixed, user-set)",
            "ut_r_tratio":        "Turns ratio (Ns/Np)",
            "ut_r_nscalc":        "Calculated secondary turns (Ns)",
            "ut_r_ns":            "Actual secondary turns (rounded)",
            "ut_r_maxturns":      "Max turns that fit the core",
            "ut_r_ratioact":      "Actual impedance ratio (from turns)",
            "ut_r_xtrans":        "Transformed load reactance at input",
            "ut_r_sec21":         "2.1  AUTOTRANSFORMER WINDING",
            "ut_r_nt":            "Total winding turns (Nt)",
            "ut_r_ntap":          "Input tap turns (N_tap)",
            "ut_r_nabove":        "Turns above tap (Nt − N_tap)",
            "ut_r_ratiochk":      "Ratio check (Nt/N_tap)²",
            "ut_r_wpt":           "Wire length per turn",
            "ut_r_wtot":          "Total wire length required",
            "ut_r_sec3":          "3.  REACTANCE COMPENSATION",
            "ut_r_xcomp":         "Required compensation reactance",
            "ut_r_ctype":         "Component type needed",
            "ut_r_cval":          "Computed value",
            "ut_r_cstd":          "Standard value (E24 / rounded)",
            "ut_r_sec4":          "4.  TOROID MAGNETICS & DESIGN CHECK",
            "ut_r_al":            "Core AL value",
            "ut_r_lp":            "Primary inductance (Lp)",
            "ut_r_xlp":           "Primary reactance (XLp) @ freq",
            "ut_r_check":         "Design check (XLp ≥ 4·Rin)",
            "ut_r_sec5":          "5.  CORE LOSS, SATURATION & MAX POWER",
            "ut_r_ae":            "Core effective area (Ae)",
            "ut_r_bmax":          "Max flux density (Bmax)",
            "ut_r_vpeak":         "Max input voltage before saturation",
            "ut_r_pavg":          "Flux (saturation) limit — LF limit only",
            "ut_r_mu":            "Complex permeability µ′ / µ″ @ freq",
            "ut_r_qcore":         "Core Q (µ′/µ″)",
            "ut_r_rp":            "Core loss resistance (Rp = XLp·Q)",
            "ut_r_loss":          "Core loss (fraction of input power)",
            "ut_r_surf":          "Radiating surface area",
            "ut_r_pdiss":         "Dissipation for {dt:.0f} °C rise",
            "ut_r_pther":         "Thermal (core-loss) limit — continuous",
            "ut_r_pmax":          "MAX POWER (lower of the two, key-down)",
            "ut_r_sat":           "Power handling",
            "ut_st_lim_flux":     "binding limit: FLUX (saturation)",
            "ut_st_lim_heat":     "binding limit: HEAT (core loss)",
            "ut_st_mu_na":        "material not tabulated — heat limit unknown, flux limit only",
            "ut_st_na":           "n/a (air core)",
            "ut_st_sec5_na":      "n/a — no ferrite core: no saturation limit, no core loss.",
            "ut_st_ns_ok":        "OK — Ns fits the core",
            "ut_st_ns_err":       "ERROR — Ns exceeds the core limit; use a bigger core or lower ratio",
            "ut_st_wind_warn":    "N/A — invalid for a step-down winding (tap would sit above the total winding)",
            "ut_st_mag_ok":       "ADEQUATE",
            "ut_st_mag_warn":     "WARNING — increase primary turns",
            "ut_st_sat_high":     "HIGH POWER — ≥ 1 kW continuous",
            "ut_st_sat_ok":       "OK — 400 W … 1 kW continuous (legal-limit SSB with margin)",
            "ut_st_sat_lim":      "LIMITED — 100 … 400 W continuous; barefoot only",
            "ut_st_sat_ins":      "INSUFFICIENT — under 100 W; lossier material at this "
                                  "frequency than the job needs, or too few turns",
            "ut_st_sat_unk":      "UNKNOWN — no loss data for this material; flux limit only, "
                                  "do NOT read it as a power rating",
            "ut_r_ind":           "Inductor (series L)",
            "ut_r_cap":           "Capacitor (series C)",
            "ut_r_none":          "None (purely resistive load)",
            "ut_note_unun":       ("Note: the ratio matches the resistive part only.  Cancel the "
                                   "reactance separately with the series L/C of Section 3.  Derate "
                                   "50 % for continuous digital modes (FT8, WSPR)."),
            "ut_dia_lf":          "Construction Drawing",
            "ut_dia_save":        "  💾  Save PNG…  ",
            "ut_dia_upd":         "  🔄  UPDATE DRAWING  ",
            "ut_dia_click":       "Click on the drawing to see it full size.",
            "ut_dia_empty":       "Press UPDATE DRAWING to build it from the data on this page.",
            "ut_dia_stale":       "The data changed — press UPDATE DRAWING to redraw it.",
            "ut_dia_file":        "PNG: {file}",
            "ut_dia_none":        "matplotlib is not installed — the drawing cannot be generated.",
            "ut_dia_err":         "The drawing could not be generated: {e}",
            "ut_dia_saved":       "Drawing saved to:\n{file}",
            "ut_dia_title":       "UnUn Toroid — construction drawing",
            # Multi-band table columns
            "utc_band":           "Band",
            "utc_freq":           "f (MHz)",
            "utc_r":              "R (Ω)",
            "utc_x":              "X (Ω)",
            "utc_xcomp":          "X comp (Ω)",
            "utc_zin":            "Z in (Ω)",
            "utc_vswr_plain":     "VSWR w/o comp",
            "utc_vswr_comp":      "VSWR with comp",
            "utc_delta":          "Δ VSWR",
            # Transmatch
            "ut_tm_glob_lf":      "Global Settings",
            "ut_tm_z0":           "Target output impedance Z₀ (Ω):",
            "ut_tm_wire":         "Wire diameter (mm):",
            "ut_tm_core":         "Coil former diameter (mm):",
            "ut_tm_space":        "Space between turns (mm):",
            "ut_tm_tref":         "Turns at the Z₀ tap:",
            "ut_tm_tref_auto":    "auto",
            "ut_tm_tref_hint":    "suggested: {n}",
            "ut_tm_taps_lf":      "Tap Impedances  (auto-filled from the optimizer — editable)",
            "ut_tm_tap":          "Tap",
            "ut_tm_columns_lbl":  "Table columns:",
            "ut_tm_active":       "Active",
            "ut_tm_dia_lf":       "Construction Drawing",
            "ut_tm_dia_save":     "  💾  Save PNG…  ",
            "ut_tm_dia_upd":      "  🔄  UPDATE DRAWING  ",
            "ut_tm_dia_click":    "Click on the drawing to see it full size.",
            "ut_tm_dia_empty":    "Press UPDATE DRAWING to build it from the data on this page.",
            "ut_tm_dia_stale":    "The data changed — press UPDATE DRAWING to redraw it.",
            "ut_tm_dia_file":     "PNG: {file}",
            "ut_tm_dia_none":     "matplotlib is not installed — the drawing cannot be generated.",
            "ut_tm_dia_err":      "The drawing could not be generated: {e}",
            "ut_tm_dia_saved":    "Drawing saved to:\n{file}",
            "ut_tm_dia_title":    "Transmatch — construction drawing",
            "ut_tm_win_lf":       "Winding Design & RF Performance",
            "ut_tm_comp_lf":      "Compensation Network  (series / shunt L-C per tap)",
            "ut_tm_coil_lf":      "Air-core Coil Geometry & Inductance  (Wheeler)",
            "ut_tm_guide":        ("SWR ≤ 1.5 excellent · 1.5–3.0 acceptable · > 3.0 poor.  "
                                   "Positive X (inductive) is cancelled by a series C; negative X "
                                   "(capacitive) by a series L.  Use NP0/C0G or silver mica caps."),
            # Transmatch table columns
            "utt_n":              "n = √(R/Z₀)",
            "utt_rreal":          "R realised (Ω)",
            "utt_rerr":           "ΔR (%)",
            "utt_turns":          "Turns",
            "utt_dturns":         "Δ turns",
            "utt_wire":           "Wire (mm)",
            "utt_rdc":            "R_rf (mΩ)",
            "utt_cum":            "Cum. wire (mm)",
            "utt_z":              "|Z| (Ω)",
            "utt_phase":          "Phase (°)",
            "utt_swr":            "SWR",
            "utt_rl":             "RL (dB)",
            "utt_ml":             "ML (dB)",
            "utt_refl":           "Refl. (%)",
            "utt_xp":             "X' (Ω)",
            "utt_serl":           "Series L (nH)",
            "utt_serc":           "Series C E24 (pF)",
            "utt_shl":            "Shunt L (nH)",
            "utt_shc":            "Shunt C E24 (pF)",
            "utt_swr5":           "SWR (5 % resid.)",
            # Coil summary labels
            "utk_pitch":          "Winding pitch (mm/turn)",
            "utk_n":              "Total turns N",
            "utk_len":            "Winding length",
            "utk_rad":            "Coil radius",
            "utk_l":              "Inductance L (Wheeler)",
            "utk_xl":             "Reactance X_L at f_min",
            "utk_lmin":           "Minimum L required",
            "utk_lok":            "L sufficient for the lowest tap?",
            "utk_cself":          "Self-capacitance (Medhurst)",
            "utk_srf":            "Self-resonant frequency",
            "utk_srfneed":        "SRF required ({m}x f_max = {f} MHz)",
            "utk_srfok":          "Winding below self-resonance?",
            "utk_nsrf":           "Max turns allowed by SRF",
            "utk_xwind":          "Winding shunt reactance at f_max",
            "utk_wire":           "Total wire length",
            "utk_rdc":            "Total RF resistance",
            "utk_yes":            "YES",
            "utk_no":             "NO — increase turns",
            "utk_srf_no":         "NO — the coil self-resonates in band",
            "utk_srf_cap":        ("! The reference winding was shortened to {n} turns to keep "
                                   "the coil below its own self-resonance."),
            "utk_srf_bad":        ("! SELF-RESONANCE: SRF {srf} MHz is below {need} MHz. "
                                   "Above the SRF the winding is not an autotransformer and "
                                   "the tap model R/n^2 does not hold. Affected bands: {b}. "
                                   "Use a larger former, wider spacing or a separate coil per band."),
            "utk_srf_floor":      ("! The self-resonance cap could not be applied: the port "
                                   "inductance and tap head-room already require {n} turns. "
                                   "This former cannot cover these bands with one coil."),
            "utk_shunt_bad":      ("! WINDING LOADING: the turns below the tap shunt the antenna "
                                   "port with less than {r}x |Z| on {b}; the transformed values "
                                   "for those bands are optimistic."),
            "utk_above":          ("Note: {n} turns hang above the highest tap, open-circuit. "
                                   "They form a coupled stub that this model does not include."),
            "lang_switch":        "ES",
            "footer_author":      "Author: Emiliano Gonzalez (LU3VEA) — lu3vea@gmail.com",
            "footer_license":     "License: CC0 v1.0",
            "footer_project":     "Project: ",
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
            "bands_label":        "Bandas (separadas por coma):",
            "known_prefix":       "Conocidas: ",
            "freqs_label":        "Frecuencias (MHz, opcional):",
            "freqs_hint":         ("Dejar vacío para bandas amateur conocidas (auto). "
                                   "Requerido sólo para nombres de banda no reconocidos."),
            "wire_len":           "Longitud inicial del hilo (m):",
            "cp_len":             "Longitud inicial del CP (m):",
            "active_bands_lf":    "Bandas Activas (Puntuación VSWR)",
            "active_bands_desc":  ("Anula qué bandas se puntúan para el VSWR. "
                                   "Dejar vacío para evaluar todas las bandas listadas arriba."),
            "active_bands":       "Bandas activas:",
            "active_bands_eg":    "(ej.  40m,20m)",
            "optlang_lf":         "Idioma del Optimizador",
            "optlang_label":      "Idioma:",
            "optlang_hint":       "auto = detectado del idioma del sistema",
            "margin_lf":          "Margen Derivado Automáticamente",
            "margin_label":       "Margen de búsqueda (±):",
            "margin_hint":        "m   Aplicado alrededor de las longitudes iniciales de hilo y CP.",
            "wire_range_lf":      "Rango de Longitud del Hilo  (anula margen)",
            "leave_empty_wire":   "Dejar mín/máx vacío para usar el margen.",
            "use_cp_chk":         "Usar Contrapeso",
            "use_cp_hint":         "desmarque para una antena sin contrapeso (sólo radiador)",
            "no_cp_return_lf":    "Camino de Retorno Sin Contrapeso",
            "no_cp_return_hint":  ("NEC-2 no tiene camino de retorno implícito: un hilo alimentado en su "
                                   "extremo contra nada es un circuito abierto, no una antena. Elija cómo "
                                   "se modela el conductor de retorno."),
            "no_cp_rod":          "Pica de tierra: conductor vertical desde la alimentación hasta z=0 (fuerza tierra perfecta, GN 1)",
            "no_cp_stub":         "Muñón de coaxil: tramo vertical corto para el modo común (mantiene tierra real)",
            "no_cp_reject":       "Rechazar: no permitir modo NEC2 sin contrapeso (sólo modo empírico)",
            "cp_stub_len_lbl":    "Longitud del muñón de coaxil:",
            "cp_stub_len_hint":   "m   Sólo se usa con el modelo de muñón de coaxil.",
            "ground_model_lf":    "Modelo de Tierra",
            "ground_model_som":   "Sommerfeld-Norton (tierra real) — extremos a 0,05·λ del suelo como mínimo",
            "ground_model_per":   "Tierra perfecta (GN 1) — los extremos pueden quedar exactamente en z=0 (conexión real a tierra)",
            "ground_model_hint":  ("NEC-2 es singular cerca de una tierra Sommerfeld-Norton; un extremo a 1 mm "
                                   "da basura sin emitir ningún error. Una conexión galvánica a tierra requiere "
                                   "GN 1 (o NEC-4)."),
            "wire_conductor_lf":  "Conductor",
            "wire_diam_lbl":      "Diámetro del hilo:",
            "wire_diam_hint":     "En un end-fed de HF, el diámetro afecta R y sobre todo la Q.",
            "wire_material_lbl": "Material:",
            "wire_cond_override_lbl": "Sustituir conductividad (σ):",
            "wire_cond_override_hint": ("Opcional. Déjelo en blanco para usar la conductividad del material "
                                        "seleccionado. Si se completa, sustituye al material elegido arriba."),
            "segs_lf":            "Precisión / Segmentación",
            "segs_mode_fine":     ("Precisa (barrido %d, resultados publicados %d seg/media onda) — recomendada"
                                   % (SEGS_PER_HALF_WAVE_SWEEP, SEGS_PER_HALF_WAVE_FINE)),
            "segs_mode_fast":     ("Barrido rápido (%d seg/media onda) — sólo para ordenar; la ganadora "
                                   "se recalcula igual con precisión" % SEGS_PER_HALF_WAVE_FAST),
            "segs_mode_custom":   "Segmentos por media onda a medida:",
            "segs_converge_cb":   "Comprobar la convergencia de la geometría ganadora (segmentación 2x / 4x)",
            "segs_hint":          ("21 segmentos por media onda basta para diagramas pero no para impedancia: "
                                   "R sale ~14% baja y el signo de la reactancia es erróneo. El signo sólo se "
                                   "asienta por encima de ~60 seg/media onda, y por eso las impedancias "
                                   "publicadas se recalculan allí."),
            "cp_range_lf":        "Rango de Longitud del Contrapeso  (anula margen)",
            "rad_lf":             "Radiación / Ángulo de Despegue",
            "rad_target_toa_lbl": "Ángulo de despegue objetivo (°):",
            "rad_gain_weight_lbl":"Peso de la ganancia (0 = desactivado):",
            "rad_rerank_top_lbl": "Candidatos resimulados con patrón:",
            "rad_hint":           ("El barrido puntúa sólo impedancia, así que una antena que dispara hacia "
                                   "arriba puntúa igual que otra que pone la potencia a ángulo bajo. Por eso "
                                   "los N mejores candidatos se resimulan con diagrama de radiación completo "
                                   "y se reordenan por score_combined − peso × ganancia al ángulo de despegue "
                                   "objetivo. Poné el peso en 0 para ordenar sólo por ROE."),
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
            "height_lbl":         "altura de la antena:",
            "wire_slope_end_lbl": "slope-end-height:",
            "cp_end_height_lbl":  "cp-end-height:",
            "height_hint":        "Altura del punto de alimentación — común al radiador y al contrapeso  (por defecto 8 m)",
            "wire_slope_end_hint": "Altura del extremo lejano para hilo inclinado  (0 = suelo; dejar vacío para hilo horizontal)",
            "cp_end_height_hint": "Altura del extremo lejano del contrapeso  (0 = suelo; dejar vacío para dejarlo a nivel)",
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
            "run_btn":            "▶  Ejecutar Optimizador",
            "stop_btn":           "■  Detener",
            "show_report_btn":    "📄  Ver Informe",
            "show_radiation_btn": "📡  Ver Patrón de Radiación",
            "show_pdf_btn":       "📑  Ver Informe Final (PDF)",
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
            "hint_height":        "altura de la antena sobre el suelo (radiador + contrapeso)",
            "hint_cp_end_height": "altura que alcanza el extremo lejano del contrapeso",
            "hint_conductivity":  "conductividad del suelo en S/m",
            "hint_permittivity":  "permitividad relativa (constante dieléctrica)",
            "hint_out_txt":       "informe de texto con resultados ordenados",
            "hint_out_png":       "mapa de calor de puntuación + gráficos VSWR",
            "hint_out_csv":       "mejor candidato en formato CSV",
            "hint_out_nec":          "archivo de entrada NEC2 para mejor geometría",
            "hint_out_rad":          "PNG de patrón de radiación (solo NEC2)",
            "hint_out_construction": "PNG del diagrama de construcción de la antena",
            "hint_out_pdf":          "folleto PDF con resultados completos (requiere reportlab)",
            # ── Pestaña UnUn / Transmatch ─────────────────────────────
            "tab_ut":             "  UnUn / Transmatch  ",
            "ut_sub_unun":        "  UnUn  ",
            "ut_sub_tm":          "  Transmatch  ",
            "ut_ant_lf":          "Datos de la Antena  (se completan al terminar el optimizador — editables)",
            "ut_reload_btn":      "⟳  Recargar del optimizador",
            "ut_band":            "Banda:",
            "ut_freq":            "Frecuencia (MHz):",
            "ut_rout":            "R_out de carga (Ω):",
            "ut_xout":            "X_out de carga (Ω):",
            "ut_rin":             "R_in de entrada (Ω):",
            "ut_xin":             "X_in de entrada deseada (Ω):",
            "ut_manual":          "(manual)",
            "ut_no_data":         "Sin resultados del optimizador — los valores pueden cargarse a mano.",
            "ut_loaded":          "Datos de antena cargados: {n} bandas  ({file})",
            "ut_load_err":        "No se pudo leer el CSV del optimizador:\n{e}",
            "ut_csv_missing":     "No se encontró el CSV:\n{file}\n\nEjecute primero el optimizador (pestaña Ejecutar).",
            "ut_core_lf":         "Transformador UnUn y Núcleo",
            "ut_core_type":       "Núcleo / Aire:",
            "ut_core_type_core":  "Núcleo (toroide)",
            "ut_core_type_air":   "Aire (solenoide)",
            "ut_ratio_mode":      "Compensar / Relación:",
            "ut_ratio_compensate":"Compensar (automático, de R_out / R_in)",
            "ut_ratio_fixed":     "Relación fija",
            "ut_ratio_val":       "Relación (N²):",
            "ut_core":            "Núcleo toroidal:",
            "ut_np":              "Espiras primario (Np):",
            "ut_wire":            "Diámetro del hilo (mm):",
            "ut_coil_dia":        "Diámetro del formador de bobina (mm):",
            "ut_space":           "Separación entre espiras (mm):",
            "ut_air_note":        ("UnUn de núcleo de aire: solenoide de una sola capa. Los datos "
                                   "de magnetismo del toroide, saturación y pérdida/potencia del "
                                   "núcleo no aplican y no se muestran."),
            "ut_res_lf":          "Resultados del UnUn",
            "ut_mb_lf":           "Análisis Multibanda de Compensación Reactiva",
            "ut_mb_note":         ("Un componente serie fijo cancela la reactancia sólo en la frecuencia "
                                   "de diseño; en las demás bandas sobre o sub-compensa. "
                                   "Los valores de abajo son editables."),
            "ut_mb_auto":         "auto (de la Sección 3)",
            "ut_mb_type":         "Tipo de compensación:",
            "ut_mb_val":          "Valor del componente:",
            "ut_mb_ratio":        "Relación de impedancia del UnUn (N²):",
            "ut_mb_z0":           "Impedancia de referencia Z₀ (Ω):",
            "ut_export_btn":      "💾  Exportar TXT…",
            "ut_export_done":     "Informe guardado:\n{file}",
            # Etiquetas de resultados del UnUn
            "ut_r_sec2":          "2.  PROPIEDADES DEL TRANSFORMADOR UNUN",
            "ut_r_ratio":         "Relación de impedancias (Rout/Rin)",
            "ut_r_ratio_fixed":   "Relación de impedancias (fija, definida por el usuario)",
            "ut_r_tratio":        "Relación de espiras (Ns/Np)",
            "ut_r_nscalc":        "Espiras secundario calculadas (Ns)",
            "ut_r_ns":            "Espiras secundario reales (redondeadas)",
            "ut_r_maxturns":      "Máximo de espiras que entran en el núcleo",
            "ut_r_ratioact":      "Relación de impedancias real (por espiras)",
            "ut_r_xtrans":        "Reactancia de carga transformada a la entrada",
            "ut_r_sec21":         "2.1  BOBINADO DEL AUTOTRANSFORMADOR",
            "ut_r_nt":            "Espiras totales del bobinado (Nt)",
            "ut_r_ntap":          "Espiras hasta la toma de entrada (N_tap)",
            "ut_r_nabove":        "Espiras sobre la toma (Nt − N_tap)",
            "ut_r_ratiochk":      "Verificación de relación (Nt/N_tap)²",
            "ut_r_wpt":           "Longitud de hilo por espira",
            "ut_r_wtot":          "Longitud total de hilo necesaria",
            "ut_r_sec3":          "3.  COMPENSACIÓN DE REACTANCIA",
            "ut_r_xcomp":         "Reactancia de compensación necesaria",
            "ut_r_ctype":         "Tipo de componente necesario",
            "ut_r_cval":          "Valor calculado",
            "ut_r_cstd":          "Valor normalizado (E24 / redondeado)",
            "ut_r_sec4":          "4.  MAGNETISMO DEL TOROIDE Y VERIFICACIÓN",
            "ut_r_al":            "Valor AL del núcleo",
            "ut_r_lp":            "Inductancia del primario (Lp)",
            "ut_r_xlp":           "Reactancia del primario (XLp) @ frec.",
            "ut_r_check":         "Verificación de diseño (XLp ≥ 4·Rin)",
            "ut_r_sec5":          "5.  PÉRDIDAS DEL NÚCLEO, SATURACIÓN Y POTENCIA MÁXIMA",
            "ut_r_ae":            "Área efectiva del núcleo (Ae)",
            "ut_r_bmax":          "Densidad de flujo máxima (Bmax)",
            "ut_r_vpeak":         "Tensión máxima antes de saturar",
            "ut_r_pavg":          "Límite por flujo (sat.) — sólo en LF",
            "ut_r_mu":            "Permeabilidad compleja µ′ / µ″ @ frec.",
            "ut_r_qcore":         "Q del núcleo (µ′/µ″)",
            "ut_r_rp":            "Resistencia de pérdidas (Rp = XLp·Q)",
            "ut_r_loss":          "Pérdida en el núcleo (fracción de P entrada)",
            "ut_r_surf":          "Superficie de disipación",
            "ut_r_pdiss":         "Disipación para {dt:.0f} °C de aumento",
            "ut_r_pther":         "Límite térmico (por pérdidas) — continuo",
            "ut_r_pmax":          "POTENCIA MÁXIMA (el menor, portadora cont.)",
            "ut_st_lim_flux":     "límite dominante: FLUJO (saturación)",
            "ut_st_lim_heat":     "límite dominante: CALOR (pérdidas del núcleo)",
            "ut_st_mu_na":        "material no tabulado — límite térmico desconocido, sólo por flujo",
            "ut_st_na":           "n/d (núcleo de aire)",
            "ut_st_sec5_na":      "n/d — sin núcleo de ferrita: no hay límite de saturación ni pérdida de núcleo.",
            "ut_r_sat":           "Manejo de potencia",
            "ut_st_ns_ok":        "OK — Ns entra en el núcleo",
            "ut_st_ns_err":       "ERROR — Ns supera el límite del núcleo; use un núcleo mayor o baje la relación",
            "ut_st_wind_warn":    "N/D — inválido para un devanado paso-abajo (la toma quedaría sobre el total)",
            "ut_st_mag_ok":       "ADECUADO",
            "ut_st_mag_warn":     "ATENCIÓN — aumente las espiras del primario",
            "ut_st_sat_high":     "ALTA POTENCIA — ≥ 1 kW continuos",
            "ut_st_sat_ok":       "OK — 400 W … 1 kW continuos (SSB a potencia legal con margen)",
            "ut_st_sat_lim":      "LIMITADO — 100 … 400 W continuos; sólo sin lineal",
            "ut_st_sat_ins":      "INSUFICIENTE — menos de 100 W; material demasiado disipativo a esta "
                                  "frecuencia, o pocas espiras",
            "ut_st_sat_unk":      "DESCONOCIDO — sin datos de pérdidas para este material; sólo límite "
                                  "por flujo, NO es una especificación de potencia",
            "ut_r_ind":           "Inductor (L serie)",
            "ut_r_cap":           "Capacitor (C serie)",
            "ut_r_none":          "Ninguno (carga puramente resistiva)",
            "ut_note_unun":       ("Nota: la relación adapta sólo la parte resistiva.  Cancele la "
                                   "reactancia aparte con el L/C serie de la Sección 3.  Reduzca un "
                                   "50 % para modos digitales continuos (FT8, WSPR)."),
            "ut_dia_lf":          "Plano Constructivo",
            "ut_dia_save":        "  💾  Guardar PNG…  ",
            "ut_dia_upd":         "  🔄  ACTUALIZAR GRÁFICO  ",
            "ut_dia_click":       "Haga clic en el plano para verlo a tamaño completo.",
            "ut_dia_empty":       "Pulse ACTUALIZAR GRÁFICO para generarlo con los datos de esta página.",
            "ut_dia_stale":       "Los datos cambiaron — pulse ACTUALIZAR GRÁFICO para redibujarlo.",
            "ut_dia_file":        "PNG: {file}",
            "ut_dia_none":        "matplotlib no está instalado — no se puede generar el plano.",
            "ut_dia_err":         "No se pudo generar el plano: {e}",
            "ut_dia_saved":       "Plano guardado en:\n{file}",
            "ut_dia_title":       "Toroide UnUn — plano constructivo",
            # Columnas de la tabla multibanda
            "utc_band":           "Banda",
            "utc_freq":           "f (MHz)",
            "utc_r":              "R (Ω)",
            "utc_x":              "X (Ω)",
            "utc_xcomp":          "X comp (Ω)",
            "utc_zin":            "Z entrada (Ω)",
            "utc_vswr_plain":     "ROE sin comp",
            "utc_vswr_comp":      "ROE con comp",
            "utc_delta":          "Δ ROE",
            # Transmatch
            "ut_tm_glob_lf":      "Parámetros Globales",
            "ut_tm_z0":           "Impedancia de salida objetivo Z₀ (Ω):",
            "ut_tm_wire":         "Diámetro del hilo (mm):",
            "ut_tm_core":         "Diámetro del formador de bobina (mm):",
            "ut_tm_space":        "Separación entre espiras (mm):",
            "ut_tm_tref":         "Espiras en la toma de Z₀:",
            "ut_tm_tref_auto":    "auto",
            "ut_tm_tref_hint":    "sugerido: {n}",
            "ut_tm_taps_lf":      "Impedancias por Toma  (se completan desde el optimizador — editables)",
            "ut_tm_tap":          "Toma",
            "ut_tm_columns_lbl":  "Columnas de la tabla:",
            "ut_tm_active":       "Activa",
            "ut_tm_dia_lf":       "Plano Constructivo",
            "ut_tm_dia_save":     "  💾  Guardar PNG…  ",
            "ut_tm_dia_upd":      "  🔄  ACTUALIZAR GRÁFICO  ",
            "ut_tm_dia_click":    "Haga clic en el plano para verlo a tamaño completo.",
            "ut_tm_dia_empty":    "Pulse ACTUALIZAR GRÁFICO para generarlo con los datos de esta página.",
            "ut_tm_dia_stale":    "Los datos cambiaron — pulse ACTUALIZAR GRÁFICO para redibujarlo.",
            "ut_tm_dia_file":     "PNG: {file}",
            "ut_tm_dia_none":     "matplotlib no está instalado — no se puede generar el plano.",
            "ut_tm_dia_err":      "No se pudo generar el plano: {e}",
            "ut_tm_dia_saved":    "Plano guardado en:\n{file}",
            "ut_tm_dia_title":    "Transmatch — plano constructivo",
            "ut_tm_win_lf":       "Diseño del Bobinado y Comportamiento de RF",
            "ut_tm_comp_lf":      "Red de Compensación  (L-C serie / paralelo por toma)",
            "ut_tm_coil_lf":      "Geometría e Inductancia de la Bobina al Aire  (Wheeler)",
            "ut_tm_guide":        ("ROE ≤ 1,5 excelente · 1,5–3,0 aceptable · > 3,0 pobre.  "
                                   "La X positiva (inductiva) se cancela con C serie; la negativa "
                                   "(capacitiva) con L serie.  Use capacitores NP0/C0G o de mica plateada."),
            # Columnas de las tablas del transmatch
            "utt_n":              "n = √(R/Z₀)",
            "utt_rreal":          "R realizada (Ω)",
            "utt_rerr":           "ΔR (%)",
            "utt_turns":          "Espiras",
            "utt_dturns":         "Δ espiras",
            "utt_wire":           "Hilo (mm)",
            "utt_rdc":            "R_rf (mΩ)",
            "utt_cum":            "Hilo acum. (mm)",
            "utt_z":              "|Z| (Ω)",
            "utt_phase":          "Fase (°)",
            "utt_swr":            "ROE",
            "utt_rl":             "RL (dB)",
            "utt_ml":             "PD (dB)",
            "utt_refl":           "Reflej. (%)",
            "utt_xp":             "X' (Ω)",
            "utt_serl":           "L serie (nH)",
            "utt_serc":           "C serie E24 (pF)",
            "utt_shl":            "L paralelo (nH)",
            "utt_shc":            "C paralelo E24 (pF)",
            "utt_swr5":           "ROE (5 % resid.)",
            # Resumen de la bobina
            "utk_pitch":          "Paso del bobinado (mm/espira)",
            "utk_n":              "Espiras totales N",
            "utk_len":            "Longitud del bobinado",
            "utk_rad":            "Radio de la bobina",
            "utk_l":              "Inductancia L (Wheeler)",
            "utk_xl":             "Reactancia X_L en f_min",
            "utk_lmin":           "L mínima requerida",
            "utk_lok":            "¿L suficiente para la toma más baja?",
            "utk_cself":          "Autocapacidad (Medhurst)",
            "utk_srf":            "Frecuencia de autorresonancia",
            "utk_srfneed":        "FAR requerida ({m}x f_max = {f} MHz)",
            "utk_srfok":          "¿Bobinado por debajo de la autorresonancia?",
            "utk_nsrf":           "Espiras máximas admitidas por la FAR",
            "utk_xwind":          "Reactancia paralelo del bobinado en f_max",
            "utk_srf_no":         "NO — la bobina autorresuena dentro de banda",
            "utk_srf_cap":        ("! El bobinado de referencia se acortó a {n} espiras para "
                                   "mantener la bobina por debajo de su autorresonancia."),
            "utk_srf_bad":        ("! AUTORRESONANCIA: la FAR de {srf} MHz está por debajo de "
                                   "{need} MHz. Por encima de la FAR el bobinado no es un "
                                   "autotransformador y el modelo R/n^2 no vale. Bandas "
                                   "afectadas: {b}. Usar un formador mayor, más separación o "
                                   "una bobina por banda."),
            "utk_srf_floor":      ("! No se pudo aplicar el límite de autorresonancia: la "
                                   "inductancia de puerto y el margen de tomas ya exigen {n} "
                                   "espiras. Este formador no cubre estas bandas con una sola bobina."),
            "utk_shunt_bad":      ("! CARGA DEL BOBINADO: las espiras por debajo de la toma ponen "
                                   "en paralelo con el puerto de antena menos de {r}x |Z| en {b}; "
                                   "los valores transformados de esas bandas son optimistas."),
            "utk_above":          ("Nota: {n} espiras quedan por encima de la toma más alta, al "
                                   "aire. Forman un stub acoplado que este modelo no incluye."),
            "utk_wire":           "Longitud total de hilo",
            "utk_rdc":            "Resistencia total en RF",
            "utk_yes":            "SÍ",
            "utk_no":             "NO — aumente las espiras",
            "lang_switch":        "IT",
            "footer_author":      "Autor: Emiliano Gonzalez (LU3VEA) — lu3vea@gmail.com",
            "footer_license":     "Licencia: CC0 v1.0",
            "footer_project":     "Proyecto: ",
        },
        "it": {
            "title": "GUI dell'Ottimizzatore di Lunghezza Antenna NEC2",
            "header_title": 'Ottimizzatore di Lunghezza Antenna NEC2',
            "header_subtitle": '  •  GUI Interattiva',
            "optimizer_script": "Script dell'ottimizzatore:",
            "browse": 'Sfoglia…',
            "font_label": 'Font:',
            "tab_input": '  Banda / Sorgente  ',
            "tab_search": '  Intervallo di Ricerca  ',
            "tab_physics": '  Fisica  ',
            "tab_output": '  File di Output  ',
            "tab_run": '  Esegui  ',
            "band_source_lf": 'Origine Banda',
            "bands_label": 'Bande (separate da virgola):',
            "known_prefix": 'Note: ',
            "freqs_label": 'Frequenze (MHz, opzionale):',
            "freqs_hint": 'Lasciare vuoto per le bande amatoriali note (risolte automaticamente). Richiesto solo per nomi di banda non riconosciuti.',
            "wire_len": 'Lunghezza iniziale del filo (m):',
            "cp_len": 'Lunghezza iniziale del CP (m):',
            "active_bands_lf": 'Bande Attive (Valutazione ROS)',
            "active_bands_desc": 'Sostituisce quali bande vengono valutate per il ROS. Lasciare vuoto per valutare tutte le bande elencate sopra.',
            "active_bands": 'Bande attive:',
            "active_bands_eg": '(es.  40m,20m)',
            "optlang_lf": "Lingua dell'Ottimizzatore",
            "optlang_label": 'Lingua:',
            "optlang_hint": 'auto = rilevata dal locale di sistema',
            "margin_lf": 'Margine Auto-derivato',
            "margin_label": 'Margine di ricerca (±):',
            "margin_hint": 'm   Applicato attorno alle lunghezze iniziali di filo e CP.',
            "wire_range_lf": 'Intervallo Lunghezza Filo  (sostituisce il margine)',
            "leave_empty_wire": 'Lasciare min/max vuoti per usare il margine.',
            "use_cp_chk": 'Usa contrappeso',
            "use_cp_hint": "deselezionare per un'antenna senza contrappeso (solo radiatore)",
            "no_cp_return_lf": 'Percorso di Ritorno Senza Contrappeso',
            "no_cp_return_hint": "NEC-2 non ha un percorso di ritorno implicito: un filo alimentato al suo estremo contro il nulla è un circuito aperto, non un'antenna. Scegliere come viene modellato il conduttore di ritorno.",
            "no_cp_rod": 'Picchetto di terra: conduttore verticale dal punto di alimentazione a z=0 (forza terra perfetta, GN 1)',
            "no_cp_stub": 'Stub di calza coassiale: breve stub verticale per il percorso di modo comune (terra reale mantenuta)',
            "no_cp_reject": 'Rifiuta: rifiuta la modalità NEC2 senza contrappeso (solo modalità empirica)',
            "cp_stub_len_lbl": 'Lunghezza stub di calza coassiale:',
            "cp_stub_len_hint": 'm   Usato solo dal modello a stub di calza coassiale.',
            "ground_model_lf": 'Modello di Terra',
            "ground_model_som": 'Sommerfeld-Norton (terra reale) — estremi del filo mantenuti a 0,05·λ dal suolo',
            "ground_model_per": 'Terra perfetta (GN 1) — gli estremi del filo possono trovarsi esattamente a z=0 (connessione reale a terra)',
            "ground_model_hint": 'NEC-2 è singolare vicino a una terra Sommerfeld-Norton; un estremo di filo a 1 mm restituisce valori insensati senza alcun messaggio di errore. Una connessione galvanica a terra richiede GN 1 (o NEC-4).',
            "wire_conductor_lf": 'Conduttore',
            "wire_diam_lbl": 'Diametro del filo:',
            "wire_diam_hint": 'Per un end-fed HF, il diametro influisce su R e soprattutto su Q.',
            "wire_material_lbl": 'Materiale:',
            "wire_cond_override_lbl": 'Sostituzione conducibilità (σ):',
            "wire_cond_override_hint": 'Opzionale. Lasciare vuoto per usare la conducibilità del materiale selezionato. Se impostato, sostituisce la scelta del materiale sopra.',
            "segs_lf": 'Precisione / Segmentazione',
            "segs_mode_fine":     ("Accurata (scansione %d, risultati pubblicati %d seg/mezza onda) — consigliata"
                                   % (SEGS_PER_HALF_WAVE_SWEEP, SEGS_PER_HALF_WAVE_FINE)),
            "segs_mode_fast":     ("Scansione rapida (%d seg/mezza onda) — solo per classifica, il vincitore "
                                   "viene comunque ricalcolato accuratamente" % SEGS_PER_HALF_WAVE_FAST),
            "segs_mode_custom": 'Segmenti personalizzati per mezza onda:',
            "segs_converge_cb": 'Esegue la verifica di convergenza sulla geometria vincente (segmentazione 2x / 4x)',
            "segs_hint": "21 segmenti per mezza onda bastano per i diagrammi di radiazione ma non per l'impedenza: R risulta ~14% bassa e la reattanza ha il segno sbagliato. Il segno si stabilizza solo sopra i ~60 segmenti per mezza onda, motivo per cui le impedenze pubblicate vengono ricalcolate lì.",
            "cp_range_lf": 'Intervallo Lunghezza Contrappeso  (sostituisce il margine)',
            "rad_lf": 'Radiazione / Angolo di Decollo',
            "rad_target_toa_lbl": 'Angolo di decollo obiettivo (°):',
            "rad_gain_weight_lbl": 'Peso del guadagno (0 = disattivo):',
            "rad_rerank_top_lbl": 'Candidati riesaminati con diagramma:',
            "rad_hint": "La scansione valuta solo l'impedenza, quindi un'antenna che irradia dritto verso l'alto ottiene lo stesso punteggio di una che concentra la potenza a un angolo basso. I migliori N candidati vengono quindi risimulati con un diagramma di radiazione completo e riordinati per score_combined − peso × guadagno all'angolo di decollo obiettivo. Impostare il peso a 0 per classificare solo per ROS.",
            "leave_empty_cp": 'Lasciare min/max vuoti per usare il margine.',
            "retry_lf": 'Nuovo Tentativo Automatico al Raggiungimento del Limite',
            "max_retries": 'Tentativi massimi:',
            "retry_hint": 'Se il miglior candidato tocca il minimo/massimo, sposta la finestra e riesegue (0 = disattivato).',
            "report_opts_lf": 'Opzioni Report',
            "top_n": 'Migliori N candidati nel report:',
            "nec2_engine_lf": 'Motore NEC2',
            "eval_mode": 'Modalità di valutazione:',
            "auto_mode": 'Automatica (NEC2 se trovato, altrimenti empirica)',
            "nec2_mode": 'NEC2 (richiede il binario nec2c)',
            "empirical_mode": 'Solo empirica (veloce, nessun binario necessario)',
            "nec2c_binary": 'Binario nec2c:',
            "auto_detect_btn": 'Rilevamento automatico',
            "nec2c_hint": 'Lasciare vuoto per il rilevamento automatico.',
            "antenna_geom_lf": "Geometria dell'Antenna",
            "height_lbl": 'altezza antenna:',
            "wire_slope_end_lbl": 'altezza estremo inclinato:',
            "cp_end_height_lbl": 'altezza estremo cp:',
            "height_hint": 'Altezza del punto di alimentazione sopra il suolo — condivisa da radiatore e contrappeso  (predefinito 8 m)',
            "wire_slope_end_hint": "Altezza dell'estremo lontano per filo inclinato  (0 = suolo; lasciare vuoto per orizzontale)",
            "cp_end_height_hint": "Altezza dell'estremo lontano del contrappeso  (0 = suolo; lasciare vuoto per mantenerlo a livello)",
            "ground_lf": 'Parametri del Terreno',
            "conductivity": 'Conducibilità (σ):',
            "cond_unit": 'S/m   (0,005 = terreno medio)',
            "permittivity": 'Permittività (εᵣ):',
            "perm_hint": '(13 = terreno medio)',
            "quick_presets": 'Preimpostazioni rapide:',
            "preset_poor": 'Molto scarso (roccia/deserto)',
            "preset_avg": 'Terreno medio',
            "preset_good": 'Buon terreno',
            "preset_excel": 'Eccellente (terreno agricolo)',
            "preset_salt": 'Acqua salata',
            "misc_lf": 'Opzioni Varie',
            "quiet_flag": "quiet  (sopprime l'output di avanzamento)",
            "no_interact": 'no-interactive  (non chiede conferma; esce se mancano input)',
            "workdir_lf": 'Cartella di Lavoro / Output',
            "outdir_label": 'Cartella di output:',
            "workdir_hint": "L'ottimizzatore verrà avviato con questa come cartella di lavoro.",
            "outfiles_lf": 'Nomi dei File di Output',
            "txt_tip": 'Report testuale classificato',
            "png_tip": 'Mappa di calore del punteggio + grafici a barre ROS',
            "csv_tip": 'Miglior candidato in formato CSV di analisi banda',
            "nec_tip": 'Deck di ingresso NEC2 per la miglior geometria',
            "rad_tip": 'PNG del diagramma di radiazione (solo modalità NEC2)',
            "cmd_preview_lf": 'Anteprima Comando',
            "run_btn": '▶  Esegui Ottimizzatore',
            "stop_btn": '■  Ferma',
            "show_report_btn": '📄  Mostra Report',
            "show_radiation_btn": '📡  Mostra Diagramma di Radiazione',
            "show_pdf_btn": '📑  Mostra Report Finale (PDF)',
            "idle": 'Inattivo',
            "console_lf": 'Output Console',
            "clear_btn": 'Pulisci',
            "running": 'In esecuzione…',
            "stopped": "Fermato dall'utente",
            "finished_ok": 'Completato con successo ✓',
            "exit_code": 'Il processo è terminato con codice {rc}',
            "thread_error": 'Errore: {e}',
            "script_nf_title": 'Script non trovato',
            "script_nf_msg": "Script dell'ottimizzatore non trovato:\n{script}\n\nImpostare il percorso corretto nella scheda 'Banda / Sorgente'.",
            "cfg_err_title": 'Errore di configurazione',
            "dir_err_title": 'Errore di cartella',
            "dir_err_msg": 'Impossibile creare la cartella di output:\n{e}',
            "done_title": 'Completato',
            "done_msg": 'Ottimizzazione completata!\n\nAprire il file di report?\n{report}',
            "hint_wire_len": "lunghezza totale dell'elemento radiante",
            "hint_cp_len": 'lunghezza del radiale di contrappeso / terra',
            "hint_margin": '±finestra di ricerca attorno alla lunghezza iniziale',
            "hint_wire_min": 'lunghezza minima del filo da testare',
            "hint_wire_max": 'lunghezza massima del filo da testare',
            "hint_wire_step": 'passo della griglia tra le lunghezze del filo',
            "hint_cp_min": 'lunghezza minima del CP da testare',
            "hint_cp_max": 'lunghezza massima del CP da testare',
            "hint_cp_step": 'passo della griglia tra le lunghezze del CP',
            "hint_max_retries": 'numero di tentativi quando il migliore tocca il limite',
            "hint_top_n": 'candidati elencati nel report testuale',
            "hint_height": "altezza dell'antenna sopra il suolo (radiatore + contrappeso)",
            "hint_cp_end_height": "altezza raggiunta dall'estremo lontano del contrappeso",
            "hint_conductivity": 'conducibilità del suolo in S/m',
            "hint_permittivity": 'permittività relativa (costante dielettrica)',
            "hint_out_txt": 'report testuale dei risultati classificati',
            "hint_out_png": 'mappa di calore del punteggio + grafici a barre ROS',
            "hint_out_csv": 'miglior candidato in formato CSV',
            "hint_out_nec": 'deck di ingresso NEC2 per la miglior geometria',
            "hint_out_rad": 'PNG del diagramma di radiazione (solo NEC2)',
            "hint_out_construction": "PNG del disegno costruttivo dell'antenna",
            "hint_out_pdf": 'brochure PDF con i risultati completi (richiede reportlab)',
            "tab_ut": '  UnUn / Transmatch  ',
            "ut_sub_unun": '  UnUn  ',
            "ut_sub_tm": '  Transmatch  ',
            "ut_ant_lf": "Dati Antenna  (compilati automaticamente al termine dell'ottimizzatore — modificabili)",
            "ut_reload_btn": "⟳  Ricarica dall'ottimizzatore",
            "ut_band": 'Banda:',
            "ut_freq": 'Frequenza (MHz):',
            "ut_rout": 'Carico R_out (Ω):',
            "ut_xout": 'Carico X_out (Ω):',
            "ut_rin": 'Ingresso R_in (Ω):',
            "ut_xin": 'Ingresso X_in desiderato (Ω):',
            "ut_manual": '(manuale)',
            "ut_no_data": "Nessun risultato dell'ottimizzatore caricato — i valori possono essere digitati a mano.",
            "ut_loaded": 'Dati antenna caricati: {n} bande  ({file})',
            "ut_load_err": "Impossibile leggere il CSV dell'ottimizzatore:\n{e}",
            "ut_csv_missing": "CSV non trovato:\n{file}\n\nEseguire prima l'ottimizzatore (scheda Esegui).",
            "ut_core_lf": 'Trasformatore UnUn e Nucleo',
            "ut_core_type": 'Nucleo / Aria:',
            "ut_core_type_core": 'Nucleo (toroide)',
            "ut_core_type_air": 'Aria (solenoide)',
            "ut_ratio_mode": 'Compensa / Rapporto:',
            "ut_ratio_compensate": 'Compensa (automatico, da R_out / R_in)',
            "ut_ratio_fixed": 'Rapporto fisso',
            "ut_ratio_val": 'Rapporto (N²):',
            "ut_core": 'Nucleo toroidale:',
            "ut_np": 'Spire primarie (Np):',
            "ut_wire": 'Diametro del filo (mm):',
            "ut_coil_dia": 'Diametro del supporto della bobina (mm):',
            "ut_space": 'Spazio tra le spire (mm):',
            "ut_air_note": ("UnUn a nucleo d'aria: solenoide a strato singolo. I dati di "
                            "magnetismo del toroide, saturazione e perdita/potenza del nucleo "
                            "qui sotto non si applicano e non vengono mostrati."),
            "ut_res_lf": 'Risultati UnUn',
            "ut_mb_lf": 'Analisi di Compensazione Reattiva Multibanda',
            "ut_mb_note": 'Un componente serie fisso annulla la reattanza solo alla frequenza di progetto; sulle altre bande sovra- o sotto-compensa. I valori blu sotto sono modificabili.',
            "ut_mb_auto": 'auto (dalla Sezione 3)',
            "ut_mb_type": 'Tipo di compensazione:',
            "ut_mb_val": 'Valore del componente:',
            "ut_mb_ratio": 'Rapporto di impedenza UnUn (N²):',
            "ut_mb_z0": 'Impedenza di riferimento Z₀ (Ω):',
            "ut_export_btn": '💾  Esporta TXT…',
            "ut_export_done": 'Report salvato:\n{file}',
            "ut_r_sec2": '2.  PROPRIETÀ DEL TRASFORMATORE UNUN',
            "ut_r_ratio": 'Rapporto di impedenza (Rout/Rin)',
            "ut_r_ratio_fixed": 'Rapporto di impedenza (fisso, impostato)',
            "ut_r_tratio": 'Rapporto di spire (Ns/Np)',
            "ut_r_nscalc": 'Spire secondarie calcolate (Ns)',
            "ut_r_ns": 'Spire secondarie effettive (arrotondate)',
            "ut_r_maxturns": 'Massime spire che entrano nel nucleo',
            "ut_r_ratioact": 'Rapporto di impedenza effettivo (dalle spire)',
            "ut_r_xtrans": "Reattanza di carico trasformata all'ingresso",
            "ut_r_sec21": '2.1  AVVOLGIMENTO AUTOTRASFORMATORE',
            "ut_r_nt": "Spire totali dell'avvolgimento (Nt)",
            "ut_r_ntap": 'Spire della presa di ingresso (N_tap)',
            "ut_r_nabove": 'Spire sopra la presa (Nt − N_tap)',
            "ut_r_ratiochk": 'Verifica rapporto (Nt/N_tap)²',
            "ut_r_wpt": 'Lunghezza filo per spira',
            "ut_r_wtot": 'Lunghezza totale di filo richiesta',
            "ut_r_sec3": '3.  COMPENSAZIONE DELLA REATTANZA',
            "ut_r_xcomp": 'Reattanza di compensazione richiesta',
            "ut_r_ctype": 'Tipo di componente necessario',
            "ut_r_cval": 'Valore calcolato',
            "ut_r_cstd": 'Valore standard (E24 / arrotondato)',
            "ut_r_sec4": '4.  MAGNETISMO DEL TOROIDE E VERIFICA PROGETTUALE',
            "ut_r_al": 'Valore AL del nucleo',
            "ut_r_lp": 'Induttanza primaria (Lp)',
            "ut_r_xlp": 'Reattanza primaria (XLp) @ freq',
            "ut_r_check": 'Verifica progettuale (XLp ≥ 4·Rin)',
            "ut_r_sec5": '5.  PERDITA NEL NUCLEO, SATURAZIONE E POTENZA MASSIMA',
            "ut_r_ae": 'Area effettiva del nucleo (Ae)',
            "ut_r_bmax": 'Densità di flusso massima (Bmax)',
            "ut_r_vpeak": 'Tensione di ingresso massima prima della saturazione',
            "ut_r_pavg": 'Limite di flusso (saturazione) — solo limite BF',
            "ut_r_mu": 'Permeabilità complessa µ′ / µ″ @ freq',
            "ut_r_qcore": 'Q del nucleo (µ′/µ″)',
            "ut_r_rp": 'Resistenza di perdita del nucleo (Rp = XLp·Q)',
            "ut_r_loss": "Perdita nel nucleo (frazione della potenza d'ingresso)",
            "ut_r_surf": 'Superficie radiante',
            "ut_r_pdiss": 'Dissipazione per un aumento di {dt:.0f} °C',
            "ut_r_pther": 'Limite termico (perdita nucleo) — continuo',
            "ut_r_pmax": 'POTENZA MASSIMA (la minore delle due, a chiave premuta)',
            "ut_r_sat": 'Capacità di potenza',
            "ut_st_lim_flux": 'limite vincolante: FLUSSO (saturazione)',
            "ut_st_lim_heat": 'limite vincolante: CALORE (perdita nucleo)',
            "ut_st_mu_na": 'materiale non tabulato — limite di calore sconosciuto, solo limite di flusso',
            "ut_st_na": 'n/d (nucleo d\'aria)',
            "ut_st_sec5_na": "n/d — nessun nucleo in ferrite: nessun limite di saturazione, nessuna perdita nel nucleo.",
            "ut_st_ns_ok": 'OK — Ns entra nel nucleo',
            "ut_st_ns_err": 'ERRORE — Ns supera il limite del nucleo; usare un nucleo più grande o un rapporto minore',
            "ut_st_wind_warn": "N/D — non valido per un avvolgimento step-down (la presa sarebbe sopra l'avvolgimento totale)",
            "ut_st_mag_ok": 'ADEGUATO',
            "ut_st_mag_warn": 'ATTENZIONE — aumentare le spire primarie',
            "ut_st_sat_high": 'ALTA POTENZA — ≥ 1 kW continui',
            "ut_st_sat_ok": 'OK — 400 W … 1 kW continui (SSB al limite legale con margine)',
            "ut_st_sat_lim": 'LIMITATO — 100 … 400 W continui; solo barefoot',
            "ut_st_sat_ins": 'INSUFFICIENTE — sotto i 100 W; materiale più dissipativo a questa frequenza di quanto serva, oppure troppo poche spire',
            "ut_st_sat_unk": 'SCONOSCIUTO — nessun dato di perdita per questo materiale; solo limite di flusso, NON leggerlo come una potenza nominale',
            "ut_r_ind": 'Induttore (L in serie)',
            "ut_r_cap": 'Condensatore (C in serie)',
            "ut_r_none": 'Nessuno (carico puramente resistivo)',
            "ut_note_unun": "Nota: il rapporto adatta solo la parte resistiva.  Annullare la reattanza separatamente con l'L/C serie della Sezione 3.  Deratare del 50 % per modi digitali continui (FT8, WSPR).",
            "ut_dia_lf": 'Disegno Costruttivo',
            "ut_dia_save": '  💾  Salva PNG…  ',
            "ut_dia_upd": '  🔄  AGGIORNA DISEGNO  ',
            "ut_dia_click": 'Fare clic sul disegno per vederlo a grandezza intera.',
            "ut_dia_empty": 'Premere AGGIORNA DISEGNO per costruirlo dai dati di questa pagina.',
            "ut_dia_stale": 'I dati sono cambiati — premere AGGIORNA DISEGNO per ridisegnarlo.',
            "ut_dia_file": 'PNG: {file}',
            "ut_dia_none": 'matplotlib non è installato — il disegno non può essere generato.',
            "ut_dia_err": 'Il disegno non può essere generato: {e}',
            "ut_dia_saved": 'Disegno salvato in:\n{file}',
            "ut_dia_title": 'Toroide UnUn — disegno costruttivo',
            "utc_band": 'Banda',
            "utc_freq": 'f (MHz)',
            "utc_r": 'R (Ω)',
            "utc_x": 'X (Ω)',
            "utc_xcomp": 'X comp (Ω)',
            "utc_zin": 'Z in (Ω)',
            "utc_vswr_plain": 'ROS senza comp',
            "utc_vswr_comp": 'ROS con comp',
            "utc_delta": 'Δ ROS',
            "ut_tm_glob_lf": 'Impostazioni Globali',
            "ut_tm_z0": 'Impedenza di uscita obiettivo Z₀ (Ω):',
            "ut_tm_wire": 'Diametro del filo (mm):',
            "ut_tm_core": 'Diametro del supporto della bobina (mm):',
            "ut_tm_space": 'Spazio tra le spire (mm):',
            "ut_tm_tref": 'Spire alla presa Z₀:',
            "ut_tm_tref_auto": 'auto',
            "ut_tm_tref_hint": 'suggerito: {n}',
            "ut_tm_taps_lf": "Impedenze delle Prese  (compilate automaticamente dall'ottimizzatore — modificabili)",
            "ut_tm_tap": 'Presa',
            "ut_tm_columns_lbl": 'Colonne della tabella:',
            "ut_tm_active": 'Attiva',
            "ut_tm_dia_lf": 'Disegno Costruttivo',
            "ut_tm_dia_save": '  💾  Salva PNG…  ',
            "ut_tm_dia_upd": '  🔄  AGGIORNA DISEGNO  ',
            "ut_tm_dia_click": 'Fare clic sul disegno per vederlo a grandezza intera.',
            "ut_tm_dia_empty": 'Premere AGGIORNA DISEGNO per costruirlo dai dati di questa pagina.',
            "ut_tm_dia_stale": 'I dati sono cambiati — premere AGGIORNA DISEGNO per ridisegnarlo.',
            "ut_tm_dia_file": 'PNG: {file}',
            "ut_tm_dia_none": 'matplotlib non è installato — il disegno non può essere generato.',
            "ut_tm_dia_err": 'Il disegno non può essere generato: {e}',
            "ut_tm_dia_saved": 'Disegno salvato in:\n{file}',
            "ut_tm_dia_title": 'Transmatch — disegno costruttivo',
            "ut_tm_win_lf": 'Progetto Avvolgimento e Prestazioni RF',
            "ut_tm_comp_lf": 'Rete di Compensazione  (L-C serie / derivazione per presa)',
            "ut_tm_coil_lf": 'Geometria e Induttanza Bobina in Aria  (Wheeler)',
            "ut_tm_guide": 'ROS ≤ 1.5 eccellente · 1.5–3.0 accettabile · > 3.0 scarso.  La X positiva (induttiva) viene annullata da un C in serie; la X negativa (capacitiva) da una L in serie.  Usare condensatori NP0/C0G o a mica argentata.',
            "utt_n": 'n = √(R/Z₀)',
            "utt_rreal": 'R realizzata (Ω)',
            "utt_rerr": 'ΔR (%)',
            "utt_turns": 'Spire',
            "utt_dturns": 'Δ spire',
            "utt_wire": 'Filo (mm)',
            "utt_rdc": 'R_rf (mΩ)',
            "utt_cum": 'Filo cum. (mm)',
            "utt_z": '|Z| (Ω)',
            "utt_phase": 'Fase (°)',
            "utt_swr": 'ROS',
            "utt_rl": 'RL (dB)',
            "utt_ml": 'ML (dB)',
            "utt_refl": 'Rifl. (%)',
            "utt_xp": "X' (Ω)",
            "utt_serl": 'L serie (nH)',
            "utt_serc": 'C serie E24 (pF)',
            "utt_shl": 'L derivazione (nH)',
            "utt_shc": 'C derivazione E24 (pF)',
            "utt_swr5": 'ROS (5 % resid.)',
            "utk_pitch": 'Passo avvolgimento (mm/spira)',
            "utk_n": 'Spire totali N',
            "utk_len": 'Lunghezza avvolgimento',
            "utk_rad": 'Raggio bobina',
            "utk_l": 'Induttanza L (Wheeler)',
            "utk_xl": 'Reattanza X_L a f_min',
            "utk_lmin": 'L minima richiesta',
            "utk_lok": 'L sufficiente per la presa più bassa?',
            "utk_cself": 'Autocapacità (Medhurst)',
            "utk_srf": 'Frequenza di autorisonanza',
            "utk_srfneed": 'SRF richiesta ({m}x f_max = {f} MHz)',
            "utk_srfok": "Avvolgimento sotto l'autorisonanza?",
            "utk_nsrf": 'Spire massime consentite dalla SRF',
            "utk_xwind": "Reattanza di derivazione dell'avvolgimento a f_max",
            "utk_wire": 'Lunghezza totale del filo',
            "utk_rdc": 'Resistenza RF totale',
            "utk_yes": 'SÌ',
            "utk_no": 'NO — aumentare le spire',
            "utk_srf_no": 'NO — la bobina va in autorisonanza in banda',
            "utk_srf_cap": "! L'avvolgimento di riferimento è stato accorciato a {n} spire per mantenere la bobina sotto la propria autorisonanza.",
            "utk_srf_bad": "! AUTORISONANZA: la SRF di {srf} MHz è inferiore a {need} MHz. Sopra la SRF l'avvolgimento non è più un autotrasformatore e il modello di presa R/n^2 non è valido. Bande interessate: {b}. Usare un supporto più grande, una spaziatura maggiore o una bobina separata per banda.",
            "utk_srf_floor": "! Non è stato possibile applicare il limite di autorisonanza: l'induttanza di porta e il margine della presa richiedono già {n} spire. Questo supporto non può coprire queste bande con una sola bobina.",
            "utk_shunt_bad": "! CARICO DELL'AVVOLGIMENTO: le spire sotto la presa derivano la porta dell'antenna con meno di {r}x |Z| su {b}; i valori trasformati per quelle bande sono ottimistici.",
            "utk_above": 'Nota: {n} spire pendono sopra la presa più alta, a circuito aperto. Formano uno stub accoppiato che questo modello non include.',
            "lang_switch": 'EN',
            "footer_author": "Autore: Emiliano Gonzalez (LU3VEA) — lu3vea@gmail.com",
            "footer_license": "Licenza: CC0 v1.0",
            "footer_project": "Progetto: ",
        },
    }

    # ── Help-badge tooltip strings ──────────────────────────────────────────
    #
    # One entry per modifiable control, keyed the same way as _GUI_STRINGS.
    # Only English is mandatory (used as the fallback for any language/key
    # not yet translated); Spanish/Italian entries are provided for the
    # fields most likely to need clarification. Every string is well under
    # the 1024-character limit enforced by _HelpBadge.
    _GUI_HELP: Dict[str, Dict[str, str]] = {
        "en": {
            "help_bands": "Comma-separated list of ham bands to model, e.g. 40m,20m,15m. Names must match one of the known bands shown below, or you must also supply --freqs.",
            "help_freqs": "Optional comma-separated centre frequencies in MHz, one per band, in the same order as the bands list. Required only for bands not in the known-bands table.",
            "help_wire_len": "Total length of the sloping radiator wire, in meters. This is the starting point the optimizer sweeps around while searching for the best-performing length.",
            "help_cp_len": "Length of the counterpoise (ground) wire, in meters. Only used when 'Use counterpoise' is enabled; ignored for counterpoise-free configurations.",
            "help_active_bands": "Optional comma-separated subset of the bands list to actually optimize for (e.g. restrict a 3-band model to just 40m,20m). Leave empty to use all bands.",
            "help_optlang": "Language used for on-screen and report text generated by the optimizer itself (independent of this GUI's own language, set with the globe button).",
            "help_margin": "Safety margin added to feedline/component ratings when checking match quality, expressed as a multiplier. Higher values are more conservative.",
            "help_wire_range": "Lower and upper bounds (in meters) the optimizer is allowed to try for the radiator length during the search sweep.",
            "help_use_cp": "Enable to include a counterpoise/ground wire in the antenna model. Disable to model a counterpoise-free (e.g. vertical-only) configuration instead.",
            "help_nocp_mode": "How the antenna is grounded when no counterpoise wire is used: choose the radial, ground-stake, or stub-based scheme that matches your installation.",
            "help_stub_len": "Length in meters of the matching/loading stub used in counterpoise-free mode. Only applies when a stub-based grounding option is selected.",
            "help_radiator_height": "Height above ground, in meters, of the radiator wire's ends. Affects ground-reflection modeling and feed-point impedance.",
            "help_rad_target_toa": "Desired radiation take-off angle in degrees. Candidate geometries are scored on the modeled gain at this elevation angle, not on how close the pattern's peak comes to it.",
            "help_rad_gain_weight": "How strongly peak gain (versus VSWR match) influences the aggregate score. Higher values favor high-gain geometries even if match is slightly worse.",
            "help_rad_rerank_top": "Number of top VSWR-ranked candidates that are then re-ordered by radiation-pattern score before the final ranking is produced.",
            "help_cp_range": "Lower and upper bounds (in meters) the optimizer is allowed to try for the counterpoise length during the search sweep.",
            "help_geometry_height": "Physical installation height in meters for this part of the antenna geometry, used to build the NEC2 wire model.",
            "help_height": "Feed-point height above ground, in meters. Both the radiator and the counterpoise hang from this same point, so it affects both.",
            "help_wire_slope_end": "Height in meters of the far end of the radiator wire. Leave empty for a horizontal wire; set lower than the feed height for a sloping (inverted-V-like) run.",
            "help_cp_end_height": "Height in meters of the far end of the counterpoise wire. Leave empty to use the same height as the feed point.",
            "help_retry": "Number of times to automatically retry a failed nec2c run (e.g. after a transient solver error) before giving up on that candidate.",
            "help_topn": "How many top-ranked candidate geometries to keep and report at the end of the search, ordered by aggregate score.",
            "help_ground_cond": "Ground conductivity in Siemens/meter used by NEC2's Sommerfeld ground model. Typical average ground is around 0.005 S/m.",
            "help_ground_diel": "Relative dielectric constant (permittivity) of the ground, used together with conductivity in NEC2's ground model. Typical average ground is about 13.",
            "help_ground_model": "Which ground model NEC2 uses for the simulation: perfect (lossless, fastest), average real ground, or a custom conductivity/permittivity pair you enter yourself.",
            "help_wire_diam": "Physical diameter of the antenna wire in millimeters. Thicker wire slightly broadens bandwidth and changes the exact resonant length.",
            "help_wire_material": "Conductor material of the antenna wire (copper, copperweld, aluminum, etc.), used to look up its electrical conductivity for loss calculations.",
            "help_wire_conductivity": "Electrical conductivity of the wire material in Siemens/meter, used directly when 'custom' material is selected instead of a preset.",
            "help_segs": "Number of NEC2 segments per half-wavelength. Coarse values are fine for quick sweeps; the winning geometry should be re-checked at a finer setting.",
            "help_segs_custom": "Custom segments-per-half-wavelength value used instead of the fast/normal/fine presets. Very low values distort resistance and reactance.",
            "help_converge": "When enabled, re-runs the winning geometry at 2x and 4x the segmentation to show how much R and X still change, as a convergence check.",
            "help_outdir": "Folder where the report, plot, and CSV files from this run will be written. Created automatically if it does not already exist.",
            "help_out_filenames": "File name used for this particular output artifact (report, radiation-pattern file, or PDF) inside the chosen output folder.",
            "help_quiet": "Suppress the detailed progress log during the run and only print the final summary and any warnings or errors.",
            "help_no_interact": "Never pause to ask questions interactively (e.g. for locating nec2c); fail immediately instead if something required is missing.",
            "help_nec2c_path": "Full path to the nec2c executable used to run each simulation. Leave the auto-detected value unless you have a non-standard install location.",
            "help_calc_mode": "Which engine computes antenna performance: automatic (prefers nec2c if available), always nec2c, or a fast built-in empirical approximation.",
            "help_script_path": "Path to this optimizer script, used to build the command line shown in the preview box below. Change only if you moved the script.",
            "help_ut_band": "Ham band this UnUn/Transmatch calculation is being performed for; selects which antenna feed-point impedance is used as the source data.",
            "help_ut_reload_export": "Reload re-reads the antenna feed-point impedances from the optimizer's latest CSV output for the selected band. Export TXT saves the current UnUn/Transmatch results shown below to a text file.",
            "help_ut_core_type": "Whether the transformer/choke uses a toroidal ferrite/powder core (checked) or an air-core winding (unchecked).",
            "help_ut_core": "Specific core part number/material to use for the turns-ratio and saturation calculations.",
            "help_ut_ratio_mode": "How the impedance transformation ratio is chosen: automatically from the antenna data, or manually fixed by you.",
            "help_ut_mb_auto": "Automatically choose the number of turns per side of a multi-band-capable winding based on the selected bands.",
            "help_ut_mb_kind": "Winding configuration used for multi-band operation (e.g. tapped, bifilar, trifilar) when automatic turn selection is enabled.",
            "help_tm_tref": "Automatically pick a matching-network topology/reference design instead of specifying component values by hand.",
            "help_tm_table_b": "Frequency band this row of the matching-network table applies to.",
            "help_tm_table_f": "Frequency in MHz used to evaluate this row's matching-network component values.",
            "help_tm_table_r": "Feed-point resistance (real part of impedance, in Ohms) used for this row's matching calculation.",
            "help_tm_table_x": "Feed-point reactance (imaginary part of impedance, in Ohms) used for this row's matching calculation.",
            "help_tm_table_active": "Whether this band row is included when computing/displaying the matching network results.",
            "help_tm_table": "Band: the frequency band this row applies to. Freq: the frequency in MHz used to evaluate this row. R/X: the feed-point resistance/reactance in Ohms used for this row's matching calculation. Active: whether the row is included in the results.",
            "help_ut_freq": "Design frequency in MHz for this band's impedance data, taken from (or overriding) the optimizer's computed feed-point results.",
            "help_ut_rout": "Antenna feed-point resistance (real part of impedance) in Ohms at the output side of the UnUn/transformer, from the optimizer results.",
            "help_ut_xout": "Antenna feed-point reactance (imaginary part of impedance) in Ohms at the output side of the UnUn/transformer.",
            "help_ut_rin": "Desired input-side resistance in Ohms (typically 50 Ω to match standard coax feedline).",
            "help_ut_xin": "Desired input-side reactance in Ohms, typically 0 for a resistive coax match.",
            "help_ut_coil_dia": "Outer diameter of the coil former in millimeters, used for air-core solenoid designs instead of a toroid.",
            "help_ut_space": "Spacing between adjacent turns in millimeters for an air-core solenoid winding.",
            "help_ut_ratio_val": "Fixed impedance transformation ratio (e.g. 4, 9, 16, 49) to build the transformer for, used only in fixed-ratio mode.",
            "help_ut_np": "Number of primary turns wound on the core, used together with the core's inductance factor to compute reactance and saturation.",
            "help_ut_wire": "Diameter of the magnet wire used for the winding, in millimeters. Affects how many turns fit on the chosen core.",
            "help_ut_mb_val": "Component value (inductance in µH or capacitance in pF, depending on the type selected) for the multi-band compensation network.",
            "help_ut_mb_ratio": "Turns ratio used for this particular band when multi-band automatic selection is turned off.",
            "help_ut_mb_z0": "Reference impedance in Ohms used when computing the multi-band compensation component value.",
            "help_ut_tm_z0": "Characteristic/reference impedance in Ohms that the matching network (transmatch) is designed around, typically 50 Ω.",
            "help_ut_tm_wire": "Diameter of the wire used to wind the matching-network coils, in millimeters.",
            "help_ut_tm_space": "Spacing between turns in millimeters for the matching-network coil windings.",
            "help_ut_tm_core": "Diameter in millimeters of the core or coil former used in the matching-network design.",
            "help_ut_tm_tref": "Reference turns value used as a starting point for the matching-network's tapped-coil calculations, when not chosen automatically.",
        },
        "es": {
            "help_bands": "Lista de bandas de radioaficionado separadas por comas, ej. 40m,20m,15m. Los nombres deben coincidir con una banda conocida, o bien debe indicar también --freqs.",
            "help_freqs": "Frecuencias centrales opcionales en MHz, separadas por comas, una por banda, en el mismo orden que la lista de bandas. Obligatorio solo para bandas que no están en la tabla de bandas conocidas.",
            "help_wire_len": "Longitud total del hilo radiante inclinado, en metros. Es el punto de partida que el optimizador varía al buscar la longitud de mejor rendimiento.",
            "help_cp_len": "Longitud del contrapeso (tierra), en metros. Solo se usa si 'Usar contrapeso' está activado; se ignora en configuraciones sin contrapeso.",
            "help_active_bands": "Subconjunto opcional, separado por comas, de la lista de bandas para el que realmente se optimiza (p. ej. restringir un modelo de 3 bandas a solo 40m,20m). Dejar vacío para usar todas las bandas.",
            "help_optlang": "Idioma usado para el texto en pantalla y de los informes que genera el propio optimizador (independiente del idioma de esta interfaz, definido con el botón del globo).",
            "help_margin": "Margen de seguridad añadido a las especificaciones de línea de alimentación/componentes al verificar la calidad del acople, expresado como multiplicador. Valores más altos son más conservadores.",
            "help_wire_range": "Límites inferior y superior (en metros) que el optimizador puede probar para la longitud del radiador durante el barrido de búsqueda.",
            "help_use_cp": "Activar para incluir un hilo de contrapeso/tierra en el modelo. Desactivar para modelar una configuración sin contrapeso (p. ej. solo vertical).",
            "help_nocp_mode": "Cómo se conecta a tierra la antena cuando no se usa hilo de contrapeso: elija el esquema de radiales, estaca de tierra, o basado en stub que corresponda a su instalación.",
            "help_stub_len": "Longitud en metros del stub de acople/carga usado en modo sin contrapeso. Solo se aplica cuando se selecciona una opción de puesta a tierra basada en stub.",
            "help_radiator_height": "Altura sobre el suelo, en metros, de los extremos del hilo radiante. Afecta el modelado de reflexión en tierra y la impedancia en el punto de alimentación.",
            "help_rad_target_toa": "Ángulo de despegue de radiación deseado, en grados. Las geometrías candidatas se puntúan según la ganancia modelada en este ángulo de elevación, no según cuán cerca queda el pico del patrón de este ángulo.",
            "help_rad_gain_weight": "Cuánto influye la ganancia pico (frente al acople de ROE) en el puntaje agregado. Valores más altos favorecen geometrías de alta ganancia aunque el acople sea algo peor.",
            "help_rad_rerank_top": "Cantidad de candidatos mejor clasificados por ROE que luego se reordenan según el puntaje de patrón de radiación antes de producir la clasificación final.",
            "help_cp_range": "Límites inferior y superior (en metros) que el optimizador puede probar para la longitud del contrapeso durante el barrido de búsqueda.",
            "help_geometry_height": "Altura física de instalación en metros para esta parte de la geometría de la antena, usada para construir el modelo de hilos NEC2.",
            "help_height": "Altura del punto de alimentación sobre el suelo, en metros. Tanto el radiador como el contrapeso cuelgan de este mismo punto, por lo que afecta a ambos.",
            "help_wire_slope_end": "Altura en metros del extremo lejano del hilo radiante. Dejar vacío para un hilo horizontal; poner un valor menor que la altura de alimentación para un tendido inclinado (tipo V invertida).",
            "help_cp_end_height": "Altura en metros del extremo lejano del hilo de contrapeso. Dejar vacío para usar la misma altura que el punto de alimentación.",
            "help_retry": "Cantidad de veces que se reintenta automáticamente una corrida de nec2c fallida (p. ej. tras un error transitorio del solver) antes de descartar ese candidato.",
            "help_topn": "Cuántas geometrías candidatas mejor clasificadas se conservan e informan al final de la búsqueda, ordenadas por puntaje agregado.",
            "help_ground_cond": "Conductividad del terreno en Siemens/metro usada por el modelo de tierra de Sommerfeld de NEC2. Un terreno promedio ronda 0.005 S/m.",
            "help_ground_diel": "Constante dieléctrica relativa (permitividad) del terreno, usada junto con la conductividad en el modelo de tierra de NEC2. Un terreno promedio ronda 13.",
            "help_ground_model": "Qué modelo de tierra usa NEC2 para la simulación: perfecto (sin pérdidas, más rápido), tierra real promedio, o un par personalizado de conductividad/permitividad que usted mismo introduce.",
            "help_wire_diam": "Diámetro físico del hilo de la antena en milímetros. Un hilo más grueso amplía levemente el ancho de banda y cambia la longitud de resonancia exacta.",
            "help_wire_material": "Material conductor del hilo de la antena (cobre, copperweld, aluminio, etc.), usado para obtener su conductividad eléctrica en los cálculos de pérdidas.",
            "help_wire_conductivity": "Conductividad eléctrica del material del hilo en Siemens/metro, usada directamente cuando se selecciona el material 'personalizado' en lugar de un preajuste.",
            "help_segs": "Cantidad de segmentos NEC2 por media longitud de onda. Valores bajos sirven para barridos rápidos; la geometría ganadora debe volver a verificarse con un ajuste más fino.",
            "help_segs_custom": "Valor personalizado de segmentos por media onda usado en lugar de los preajustes rápido/normal/fino. Valores muy bajos distorsionan la resistencia y la reactancia.",
            "help_converge": "Al activarlo, reejecuta la geometría ganadora a 2x y 4x la segmentación e informa cuánto siguen cambiando R y X, como verificación de convergencia.",
            "help_outdir": "Carpeta donde se guardarán el informe, el gráfico y el CSV de esta corrida. Se crea automáticamente si no existe.",
            "help_out_filenames": "Nombre de archivo usado para este artefacto de salida en particular (informe, archivo de patrón de radiación o PDF) dentro de la carpeta de salida elegida.",
            "help_quiet": "Suprime el registro detallado de progreso durante la corrida e imprime solo el resumen final y cualquier advertencia o error.",
            "help_no_interact": "Nunca detenerse a hacer preguntas de forma interactiva (p. ej. para localizar nec2c); fallar de inmediato si falta algo requerido.",
            "help_nec2c_path": "Ruta completa al ejecutable nec2c usado para cada simulación. Cambiar solo si la instalación no está en una ubicación estándar.",
            "help_calc_mode": "Qué motor calcula el rendimiento de la antena: automático (prefiere nec2c si está disponible), siempre nec2c, o una aproximación empírica rápida incorporada.",
            "help_script_path": "Ruta a este script optimizador, usada para construir la línea de comandos mostrada en el cuadro de vista previa de abajo. Cambiar solo si movió el script.",
            "help_ut_band": "Banda de radioaficionado para la que se realiza este cálculo de UnUn/Transmatch; selecciona qué impedancia del punto de alimentación de la antena se usa como dato fuente.",
            "help_ut_reload_export": "Recargar vuelve a leer las impedancias del punto de alimentación desde el último CSV generado por el optimizador para la banda seleccionada. Exportar TXT guarda en un archivo de texto los resultados de UnUn/Transmatch mostrados abajo.",
            "help_ut_core_type": "Si el transformador/choke usa un núcleo toroidal de ferrita/polvo (marcado) o un devanado con núcleo de aire (desmarcado).",
            "help_ut_core": "Número de parte/material del núcleo específico a usar para los cálculos de relación de vueltas y saturación.",
            "help_ut_ratio_mode": "Cómo se elige la relación de transformación de impedancia: automáticamente a partir de los datos de la antena, o fijada manualmente por usted.",
            "help_ut_mb_auto": "Elegir automáticamente la cantidad de vueltas por lado de un devanado apto para multibanda según las bandas seleccionadas.",
            "help_ut_mb_kind": "Configuración de devanado usada para operación multibanda (p. ej. con tomas, bifilar, trifilar) cuando la selección automática de vueltas está activada.",
            "help_tm_tref": "Elegir automáticamente una topología/diseño de referencia de la red de acople en lugar de especificar los valores de componentes a mano.",
            "help_tm_table_b": "Banda de frecuencia a la que corresponde esta fila de la tabla de la red de acople.",
            "help_tm_table_f": "Frecuencia en MHz usada para evaluar los valores de componentes de la red de acople de esta fila.",
            "help_tm_table_r": "Resistencia del punto de alimentación (parte real de la impedancia, en Ohms) usada para el cálculo de acople de esta fila.",
            "help_tm_table_x": "Reactancia del punto de alimentación (parte imaginaria de la impedancia, en Ohms) usada para el cálculo de acople de esta fila.",
            "help_tm_table_active": "Si esta fila de banda se incluye al calcular/mostrar los resultados de la red de acople.",
            "help_tm_table": "Banda: la banda de frecuencia a la que corresponde esta fila. Frec: la frecuencia en MHz usada para evaluar esta fila. R/X: la resistencia/reactancia del punto de alimentación en Ohms usada en el cálculo de esta fila. Activa: si la fila se incluye en los resultados.",
            "help_ut_freq": "Frecuencia de diseño en MHz para los datos de impedancia de esta banda, tomada de (o sustituyendo a) los resultados del punto de alimentación calculados por el optimizador.",
            "help_ut_rout": "Resistencia del punto de alimentación de la antena (parte real de la impedancia) en Ohms, en el lado de salida del UnUn/transformador, según los resultados del optimizador.",
            "help_ut_xout": "Reactancia del punto de alimentación de la antena (parte imaginaria de la impedancia) en Ohms, en el lado de salida del UnUn/transformador.",
            "help_ut_rin": "Resistencia deseada en el lado de entrada, en Ohms (típicamente 50 Ω para acoplar con línea coaxial estándar).",
            "help_ut_xin": "Reactancia deseada en el lado de entrada, en Ohms, típicamente 0 para un acople resistivo con coaxial.",
            "help_ut_coil_dia": "Diámetro exterior del soporte de la bobina en milímetros, usado para diseños de solenoide con núcleo de aire en lugar de un toroide.",
            "help_ut_space": "Espaciado entre vueltas adyacentes en milímetros para un devanado de solenoide con núcleo de aire.",
            "help_ut_ratio_val": "Relación de transformación de impedancia fija (p. ej. 4, 9, 16, 49) para la que construir el transformador, usada solo en modo de relación fija.",
            "help_ut_np": "Cantidad de vueltas primarias enrolladas en el núcleo, usada junto con el factor de inductancia del núcleo para calcular reactancia y saturación.",
            "help_ut_wire": "Diámetro del alambre esmaltado usado para el devanado, en milímetros. Afecta cuántas vueltas caben en el núcleo elegido.",
            "help_ut_mb_val": "Valor del componente (inductancia en µH o capacitancia en pF, según el tipo seleccionado) para la red de compensación multibanda.",
            "help_ut_mb_ratio": "Relación de vueltas usada para esta banda en particular cuando la selección automática multibanda está desactivada.",
            "help_ut_mb_z0": "Impedancia de referencia en Ohms usada al calcular el valor del componente de compensación multibanda.",
            "help_ut_tm_z0": "Impedancia característica/de referencia en Ohms alrededor de la cual se diseña la red de acople (transmatch), típicamente 50 Ω.",
            "help_ut_tm_wire": "Diámetro del alambre usado para bobinar las bobinas de la red de acople, en milímetros.",
            "help_ut_tm_space": "Espaciado entre vueltas en milímetros para los devanados de las bobinas de la red de acople.",
            "help_ut_tm_core": "Diámetro en milímetros del núcleo o soporte de bobina usado en el diseño de la red de acople.",
            "help_ut_tm_tref": "Valor de vueltas de referencia usado como punto de partida para los cálculos de la bobina con tomas de la red de acople, cuando no se elige automáticamente.",
        },
        "it": {
            "help_bands": "Elenco separato da virgole delle bande radioamatoriali, es. 40m,20m,15m. I nomi devono corrispondere a una banda nota, oppure occorre indicare anche --freqs.",
            "help_freqs": "Frequenze centrali opzionali in MHz, separate da virgole, una per banda, nello stesso ordine dell'elenco delle bande. Obbligatorio solo per bande non presenti nella tabella delle bande note.",
            "help_wire_len": "Lunghezza totale del filo radiante inclinato, in metri. È il punto di partenza che l'ottimizzatore fa variare cercando la lunghezza dalle prestazioni migliori.",
            "help_cp_len": "Lunghezza del contrappeso (terra), in metri. Usata solo se 'Usa contrappeso' è attivo; ignorata per le configurazioni senza contrappeso.",
            "help_active_bands": "Sottoinsieme opzionale, separato da virgole, dell'elenco delle bande per cui ottimizzare effettivamente (es. limitare un modello a 3 bande solo a 40m,20m). Lasciare vuoto per usare tutte le bande.",
            "help_optlang": "Lingua usata per il testo a schermo e nei report generati dall'ottimizzatore stesso (indipendente dalla lingua di questa interfaccia, impostata con il pulsante del globo).",
            "help_margin": "Margine di sicurezza aggiunto alle specifiche di linea di alimentazione/componenti nel verificare la qualità dell'accoppiamento, espresso come moltiplicatore. Valori più alti sono più prudenti.",
            "help_wire_range": "Limiti inferiore e superiore (in metri) che l'ottimizzatore può provare per la lunghezza del radiatore durante la scansione di ricerca.",
            "help_use_cp": "Attivare per includere un filo di contrappeso/terra nel modello. Disattivare per una configurazione senza contrappeso (es. solo verticale).",
            "help_nocp_mode": "Come viene messa a terra l'antenna quando non si usa un filo di contrappeso: scegliere lo schema a radiali, con picchetto di terra o basato su stub adatto alla propria installazione.",
            "help_stub_len": "Lunghezza in metri dello stub di accoppiamento/carico usato in modalità senza contrappeso. Si applica solo quando è selezionata un'opzione di messa a terra basata su stub.",
            "help_radiator_height": "Altezza da terra, in metri, delle estremità del filo radiante. Influisce sulla modellazione della riflessione a terra e sull'impedenza al punto di alimentazione.",
            "help_rad_target_toa": "Angolo di decollo della radiazione desiderato, in gradi. Le geometrie candidate vengono valutate in base al guadagno modellato a questo angolo di elevazione, non a quanto il picco del diagramma si avvicina a questo angolo.",
            "help_rad_gain_weight": "Quanto influisce il guadagno di picco (rispetto all'accoppiamento ROS) sul punteggio complessivo. Valori più alti favoriscono geometrie ad alto guadagno anche con un accoppiamento leggermente peggiore.",
            "help_rad_rerank_top": "Numero dei migliori candidati classificati per ROS che vengono poi riordinati in base al punteggio del diagramma di radiazione prima di produrre la classifica finale.",
            "help_cp_range": "Limiti inferiore e superiore (in metri) che l'ottimizzatore può provare per la lunghezza del contrappeso durante la scansione di ricerca.",
            "help_geometry_height": "Altezza fisica di installazione in metri per questa parte della geometria dell'antenna, usata per costruire il modello a fili NEC2.",
            "help_height": "Altezza del punto di alimentazione da terra, in metri. Sia il radiatore sia il contrappeso pendono da questo stesso punto, quindi influisce su entrambi.",
            "help_wire_slope_end": "Altezza in metri dell'estremità lontana del filo radiante. Lasciare vuoto per un filo orizzontale; impostare un valore inferiore all'altezza di alimentazione per una posa inclinata (tipo V invertita).",
            "help_cp_end_height": "Altezza in metri dell'estremità lontana del filo di contrappeso. Lasciare vuoto per usare la stessa altezza del punto di alimentazione.",
            "help_retry": "Numero di tentativi automatici di ripetizione di un'esecuzione nec2c fallita (es. dopo un errore transitorio del solver) prima di scartare quel candidato.",
            "help_topn": "Quante geometrie candidate meglio classificate vengono conservate e riportate al termine della ricerca, ordinate per punteggio complessivo.",
            "help_ground_cond": "Conducibilità del terreno in Siemens/metro usata dal modello di terra di Sommerfeld di NEC2. Un terreno medio è circa 0.005 S/m.",
            "help_ground_diel": "Costante dielettrica relativa (permittività) del terreno, usata insieme alla conducibilità nel modello di terra di NEC2. Un terreno medio è circa 13.",
            "help_ground_model": "Quale modello di terra usa NEC2 per la simulazione: perfetto (senza perdite, più veloce), terra reale media, oppure una coppia personalizzata di conducibilità/permittività inserita dall'utente.",
            "help_wire_diam": "Diametro fisico del filo dell'antenna in millimetri. Un filo più spesso allarga leggermente la banda passante e cambia la lunghezza di risonanza esatta.",
            "help_wire_material": "Materiale conduttore del filo dell'antenna (rame, copperweld, alluminio, ecc.), usato per ricavarne la conducibilità elettrica nei calcoli delle perdite.",
            "help_wire_conductivity": "Conducibilità elettrica del materiale del filo in Siemens/metro, usata direttamente quando si seleziona il materiale 'personalizzato' invece di un preset.",
            "help_segs": "Numero di segmenti NEC2 per mezza lunghezza d'onda. Valori bassi vanno bene per scansioni rapide; la geometria vincente va riverificata con un'impostazione più fine.",
            "help_segs_custom": "Valore personalizzato di segmenti per mezza onda usato al posto dei preset rapido/normale/fine. Valori molto bassi distorcono resistenza e reattanza.",
            "help_converge": "Se attivato, riesegue la geometria vincente a 2x e 4x la segmentazione e riporta quanto R e X continuano a cambiare, come verifica di convergenza.",
            "help_outdir": "Cartella in cui verranno scritti report, grafico e CSV di questa esecuzione. Creata automaticamente se non esiste.",
            "help_out_filenames": "Nome file usato per questo particolare artefatto di output (report, file del diagramma di radiazione o PDF) all'interno della cartella di output scelta.",
            "help_quiet": "Sopprime il registro dettagliato di avanzamento durante l'esecuzione e stampa solo il riepilogo finale ed eventuali avvisi o errori.",
            "help_no_interact": "Non fermarsi mai a fare domande in modo interattivo (es. per individuare nec2c); fallire subito se manca qualcosa di necessario.",
            "help_nec2c_path": "Percorso completo dell'eseguibile nec2c usato per ogni simulazione. Cambiare solo se l'installazione non è in una posizione standard.",
            "help_calc_mode": "Quale motore calcola le prestazioni dell'antenna: automatico (preferisce nec2c se disponibile), sempre nec2c, oppure un'approssimazione empirica rapida integrata.",
            "help_script_path": "Percorso di questo script ottimizzatore, usato per costruire la riga di comando mostrata nel riquadro di anteprima sottostante. Cambiare solo se lo script è stato spostato.",
            "help_ut_band": "Banda radioamatoriale per cui viene eseguito questo calcolo UnUn/Transmatch; seleziona quale impedenza del punto di alimentazione dell'antenna viene usata come dato di origine.",
            "help_ut_reload_export": "Ricarica rilegge le impedanze del punto di alimentazione dall'ultimo CSV prodotto dall'ottimizzatore per la banda selezionata. Esporta TXT salva in un file di testo i risultati UnUn/Transmatch mostrati sotto.",
            "help_ut_core_type": "Se il trasformatore/choke usa un nucleo toroidale in ferrite/polvere (selezionato) oppure un avvolgimento a nucleo d'aria (deselezionato).",
            "help_ut_core": "Numero di parte/materiale del nucleo specifico da usare per i calcoli del rapporto spire e della saturazione.",
            "help_ut_ratio_mode": "Come viene scelto il rapporto di trasformazione dell'impedenza: automaticamente dai dati dell'antenna, oppure fissato manualmente dall'utente.",
            "help_ut_mb_auto": "Sceglie automaticamente il numero di spire per lato di un avvolgimento multibanda in base alle bande selezionate.",
            "help_ut_mb_kind": "Configurazione dell'avvolgimento usata per il funzionamento multibanda (es. con prese, bifilare, trifilare) quando la selezione automatica delle spire è attiva.",
            "help_tm_tref": "Sceglie automaticamente una topologia/progetto di riferimento della rete di accoppiamento invece di specificare a mano i valori dei componenti.",
            "help_tm_table_b": "Banda di frequenza a cui si applica questa riga della tabella della rete di accoppiamento.",
            "help_tm_table_f": "Frequenza in MHz usata per calcolare i valori dei componenti della rete di accoppiamento di questa riga.",
            "help_tm_table_r": "Resistenza al punto di alimentazione (parte reale dell'impedenza, in Ohm) usata per il calcolo di accoppiamento di questa riga.",
            "help_tm_table_x": "Reattanza al punto di alimentazione (parte immaginaria dell'impedenza, in Ohm) usata per il calcolo di accoppiamento di questa riga.",
            "help_tm_table_active": "Se questa riga di banda è inclusa nel calcolo/visualizzazione dei risultati della rete di accoppiamento.",
            "help_tm_table": "Banda: la banda di frequenza a cui si applica questa riga. Freq: la frequenza in MHz usata per calcolare questa riga. R/X: la resistenza/reattanza al punto di alimentazione in Ohm usata nel calcolo di questa riga. Attiva: se la riga è inclusa nei risultati.",
            "help_ut_freq": "Frequenza di progetto in MHz per i dati di impedenza di questa banda, presa da (o in sostituzione di) i risultati del punto di alimentazione calcolati dall'ottimizzatore.",
            "help_ut_rout": "Resistenza del punto di alimentazione dell'antenna (parte reale dell'impedenza) in Ohm, sul lato di uscita dell'UnUn/trasformatore, secondo i risultati dell'ottimizzatore.",
            "help_ut_xout": "Reattanza del punto di alimentazione dell'antenna (parte immaginaria dell'impedenza) in Ohm, sul lato di uscita dell'UnUn/trasformatore.",
            "help_ut_rin": "Resistenza desiderata sul lato di ingresso, in Ohm (tipicamente 50 Ω per l'accoppiamento con linea coassiale standard).",
            "help_ut_xin": "Reattanza desiderata sul lato di ingresso, in Ohm, tipicamente 0 per un accoppiamento resistivo con il coassiale.",
            "help_ut_coil_dia": "Diametro esterno del supporto della bobina in millimetri, usato per i progetti a solenoide con nucleo d'aria invece di un toroide.",
            "help_ut_space": "Spaziatura tra spire adiacenti in millimetri per un avvolgimento a solenoide con nucleo d'aria.",
            "help_ut_ratio_val": "Rapporto di trasformazione dell'impedenza fisso (es. 4, 9, 16, 49) per cui costruire il trasformatore, usato solo in modalità a rapporto fisso.",
            "help_ut_np": "Numero di spire primarie avvolte sul nucleo, usato insieme al fattore di induttanza del nucleo per calcolare reattanza e saturazione.",
            "help_ut_wire": "Diametro del filo smaltato usato per l'avvolgimento, in millimetri. Influisce su quante spire entrano nel nucleo scelto.",
            "help_ut_mb_val": "Valore del componente (induttanza in µH o capacità in pF, a seconda del tipo selezionato) per la rete di compensazione multibanda.",
            "help_ut_mb_ratio": "Rapporto di spire usato per questa particolare banda quando la selezione automatica multibanda è disattivata.",
            "help_ut_mb_z0": "Impedenza di riferimento in Ohm usata nel calcolo del valore del componente di compensazione multibanda.",
            "help_ut_tm_z0": "Impedenza caratteristica/di riferimento in Ohm attorno a cui è progettata la rete di accoppiamento (transmatch), tipicamente 50 Ω.",
            "help_ut_tm_wire": "Diametro del filo usato per avvolgere le bobine della rete di accoppiamento, in millimetri.",
            "help_ut_tm_space": "Spaziatura tra le spire in millimetri per gli avvolgimenti delle bobine della rete di accoppiamento.",
            "help_ut_tm_core": "Diametro in millimetri del nucleo o supporto bobina usato nel progetto della rete di accoppiamento.",
            "help_ut_tm_tref": "Valore di spire di riferimento usato come punto di partenza per i calcoli della bobina a prese della rete di accoppiamento, quando non scelto automaticamente.",
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

    _HELP_ORANGE       = "#E8820C"
    _HELP_ORANGE_EDGE  = "#B5620A"
    _HELP_POPUP_BG     = "#FFFFE6"
    _HELP_POPUP_EDGE   = "#B5620A"
    _HELP_MAX_CHARS    = 1024

    # ── Help badge widget ────────────────────────────────────────────────
    #
    # A tiny orange circle with a "?" that any modifiable GUI control can
    # carry next to it.  Hovering shows a short (<=1024 char) description
    # in a borderless popup; moving away (or the widget/app being
    # destroyed) closes it.  Implemented as a Canvas so it needs no image
    # assets and stays crisp at any font/DPI setting.

    class _HelpBadge(tk.Canvas):

        _BASE_SIZE = 16

        def __init__(self, parent, text: str, font=None, bg: str = None,
                     size: int = None):
            resolved_bg = bg
            if resolved_bg is None:
                try:
                    resolved_bg = parent.cget("background")
                except Exception:
                    resolved_bg = None
            resolved_bg = resolved_bg or _BG
            self._size = size or self._BASE_SIZE
            super().__init__(parent, width=self._size, height=self._size,
                              highlightthickness=0, bd=0, bg=resolved_bg,
                              cursor="hand2", takefocus=0)
            self._text  = (text or "")[: _HELP_MAX_CHARS]
            # `font` may be a live tkfont.Font (tracks later rescales on
            # its own) or a static (family, size[, style]) tuple; either
            # is accepted. On a GUI-wide rescale the caller pushes the
            # new font/size in via set_font().
            self._font  = font
            self._popup = None
            self._oval_id = None
            self._mark_id = None
            self._draw()
            self.bind("<Enter>", self._show)
            self.bind("<Leave>", self._hide)
            self.bind("<ButtonPress>", self._hide)
            self.bind("<Destroy>", self._on_destroy)

        def _body_size(self) -> int:
            try:
                if isinstance(self._font, tkfont.Font):
                    sz = self._font.cget("size")
                elif isinstance(self._font, (tuple, list)) and len(self._font) >= 2:
                    sz = self._font[1]
                else:
                    sz = _BASE
                sz = abs(int(sz)) if sz else _BASE
            except Exception:
                sz = _BASE
            return sz

        def _mark_font(self):
            # Derive the "?" glyph size from the popup/body font so it
            # scales in step with the rest of the GUI, rather than a
            # value frozen at construction time.
            return (_FF, max(7, self._body_size() - 3), "bold")

        def _draw(self):
            self.delete("all")
            r = self._size
            self.configure(width=r, height=r)
            self._oval_id = self.create_oval(
                1, 1, r - 1, r - 1,
                fill=_HELP_ORANGE, outline=_HELP_ORANGE_EDGE, width=1)
            self._mark_id = self.create_text(
                r // 2, r // 2, text="?", fill="white", font=self._mark_font())

        def set_text(self, text: str):
            self._text = (text or "")[: _HELP_MAX_CHARS]

        def set_font(self, font, size: int = None):
            """Called on GUI-wide rescale: updates both the tooltip body
            font and the on-badge '?' glyph, and (when `size` is given)
            the badge circle itself, so it tracks the upper font-scale
            value along with the rest of the GUI."""
            self._font = font
            if size is not None:
                self._size = size
            self._draw()

        def _show(self, _evt=None):
            if self._popup is not None or not self._text:
                return
            try:
                x = self.winfo_rootx() + self._size + 6
                y = self.winfo_rooty() - 2
                tw = tk.Toplevel(self)
                tw.wm_overrideredirect(True)
                try:
                    tw.wm_attributes("-topmost", True)
                except Exception:
                    pass
                tw.configure(bg=_HELP_POPUP_EDGE)
                inner = tk.Frame(tw, bg=_HELP_POPUP_BG)
                inner.pack(padx=1, pady=1)
                # wraplength scales with font size too, so the popup box
                # keeps roughly the same proportions instead of getting
                # cramped as text grows.
                wrap = max(280, min(520, 36 * self._body_size()))
                tk.Label(inner, text=self._text, justify="left",
                         background=_HELP_POPUP_BG, foreground="#333333",
                         font=self._font, wraplength=wrap,
                         padx=8, pady=6).pack()
                tw.update_idletasks()
                sw = tw.winfo_screenwidth()
                tw_w = tw.winfo_width()
                if x + tw_w > sw:
                    x = max(0, self.winfo_rootx() - tw_w - 6)
                tw.wm_geometry(f"+{x}+{y}")
                self._popup = tw
            except Exception:
                self._popup = None

        def _hide(self, _evt=None):
            if self._popup is not None:
                try:
                    self._popup.destroy()
                except Exception:
                    pass
                self._popup = None

        def _on_destroy(self, _evt=None):
            self._hide()

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

            self._ui_lang = _detect_locale_lang()
            self._font_sz = _BASE
            self._tw: list = []

            # Drop-down lists created later by ttk::combobox inherit this.
            self.option_add("*TCombobox*Listbox.font", self._font_obj)

            self._build_style()
            self._build_ui()
            self._apply_language()
            self._apply_fonts()          # sync named fonts + edit boxes
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

        # ── Help badges ───────────────────────────────────────────────────
        #
        # `_help(parent, key)` builds one orange "?" badge next to a control.
        # `key` is looked up in _GUI_HELP for the active language (falling
        # back to English, then to the key itself) so badges relocalize the
        # same way ordinary labels do via `_reg`.  Callers place the
        # returned widget with .grid(...) or .pack(...) like any other.
        def _help(self, parent, key: str) -> "_HelpBadge":
            badge_size = max(12, min(28, self._font_sz + 6))
            badge = _HelpBadge(parent, self._help_text(key),
                                font=self._font("label"), size=badge_size)
            self._help_badges = getattr(self, "_help_badges", [])
            self._help_badges.append((badge, key))
            return badge

        def _help_text(self, key: str) -> str:
            table = _GUI_HELP.get(self._ui_lang, _GUI_HELP.get("en", {}))
            if key in table:
                return table[key]
            return _GUI_HELP.get("en", {}).get(key, key)

        def _refresh_help_badges(self):
            for badge, key in getattr(self, "_help_badges", []):
                try:
                    badge.set_text(self._help_text(key))
                except Exception:
                    pass

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
            # The UnUn / Transmatch panels render translated labels, so they
            # have to be rebuilt when the language changes.
            if hasattr(self, "_ut_res_text"):
                try:
                    self._ut_recompute()
                except Exception:
                    pass
            self._refresh_help_badges()

        # Native-script display names for the language picker menu (not run
        # through t(), since each name is always shown in its own language).
        _LANG_NAMES = {"en": "English", "es": "Español", "it": "Italiano"}

        def _set_lang(self, lang: str):
            if lang not in _GUI_STRINGS:
                return
            self._ui_lang = lang
            self._apply_language()

        def _show_lang_menu(self):
            menu = tk.Menu(self, tearoff=0)
            for code in ("en", "es", "it"):
                label = self._LANG_NAMES.get(code, code.upper())
                mark = " \u2713" if code == self._ui_lang else "    "
                menu.add_command(
                    label=f"{mark} {label}",
                    command=lambda c=code: self._set_lang(c))
            try:
                x = self._lang_btn.winfo_rootx()
                y = self._lang_btn.winfo_rooty() + self._lang_btn.winfo_height()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()

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

        # ttk::entry, ttk::combobox and ttk::spinbox do NOT take their -font
        # from the style: their default is hard-wired to the named font
        # "TkTextFont", so `style configure TEntry -font ...` is ignored and
        # the text *inside* the edit boxes stays at its original size.  The
        # two fixes below cover it: rescale the standard named fonts (also
        # fixes menus, dialogs and drop-down lists) and set -font explicitly
        # on every input widget already on screen.
        _NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                        "TkHeadingFont", "TkCaptionFont",
                        "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")

        def _sync_named_fonts(self):
            sz = self._font_sz
            for nm in self._NAMED_FONTS:
                try:
                    tkfont.nametofont(nm).configure(family=_FF, size=sz)
                except Exception:
                    pass
            try:
                tkfont.nametofont("TkFixedFont").configure(family=_FFM, size=sz)
            except Exception:
                pass

        def _rescale_inputs(self, widget=None):
            """Push the current font onto entries, spinboxes, comboboxes and
            the (already created) combobox drop-down listboxes."""
            w = self if widget is None else widget
            try:
                children = w.winfo_children()
            except Exception:
                return
            for ch in children:
                try:
                    cls = ch.winfo_class()
                except Exception:
                    continue
                if cls in ("TEntry", "TCombobox", "TSpinbox",
                           "Entry", "Spinbox", "Listbox"):
                    try:
                        ch.configure(font=self._font_obj)
                    except Exception:
                        pass
                self._rescale_inputs(ch)

        def _apply_fonts(self):
            self._font_obj.configure(family=_FF,  size=self._font_sz)
            self._font_obj_mono.configure(family=_FFM, size=self._font_sz)
            self._sync_named_fonts()
            sz = self._font_sz
            st = ttk.Style(self)
            st.configure(".",                 font=(_FF, sz))
            st.configure("TLabel",            font=(_FF, sz))
            st.configure("Bold.TLabel",       font=(_FF, sz + 2, "bold"))
            st.configure("Muted.TLabel",      font=(_FF, sz))
            st.configure("Footer.TLabel",     font=(_FF, sz))
            st.configure("FooterLink.TLabel", font=(_FF, sz))
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
            st.configure("UT.Treeview",          font=(_FF, sz),
                         rowheight=int(self._font_obj.metrics("linespace") * 1.35))
            st.configure("UT.Treeview.Heading",  font=(_FF, sz))
            self._rescale_inputs()
            mono = (_FFM, sz)
            if hasattr(self, "_cmd_text"):
                self._cmd_text.config(font=mono)
            if hasattr(self, "_console"):
                self._console.config(font=mono)
            if hasattr(self, "_font_sz_lbl"):
                self._font_sz_lbl.config(text=str(self._font_sz))
            self._rescale_help_badges()

        def _rescale_help_badges(self):
            """Keep every help '?' badge (icon size, glyph, and popup
            text) in step with the current GUI font-scale value."""
            badge_size = max(12, min(28, self._font_sz + 6))
            for badge, _key in getattr(self, "_help_badges", []):
                try:
                    badge.set_font(self._font("label"), size=badge_size)
                except Exception:
                    pass

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
            st.configure("Footer.TFrame", background=_BG2)
            st.configure("Footer.TLabel", background=_BG2, foreground=_FG2, font=self._font("label"))
            st.configure("FooterLink.TLabel", background=_BG2, foreground=_ACCENT,
                         font=self._font("label"))
            st.map("FooterLink.TLabel", foreground=[("active", _ACCENT2)])
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

        # ── Footer ────────────────────────────────────────────────────────

        _PROJECT_URL = "https://github.com/hiperiondev/Long_Wire_Antenna"

        def _open_project_url(self, _evt=None):
            try:
                webbrowser.open(self._PROJECT_URL)
            except Exception:
                pass

        def _build_footer(self):
            """Bottom-of-window footer: author, license and project URL.

            Packed with side='bottom' on the root window BEFORE the
            notebook, so it stays pinned to the bottom of the GUI no
            matter how the notebook/console areas resize."""
            footer = ttk.Frame(self, style="Footer.TFrame")
            footer.pack(side="bottom", fill="x")

            ttk.Separator(footer, orient="horizontal").pack(fill="x", side="top")

            inner = ttk.Frame(footer, style="Footer.TFrame")
            inner.pack(fill="x", padx=16, pady=(4, 6))

            self._footer_author_lbl = ttk.Label(inner, style="Footer.TLabel")
            self._footer_author_lbl.pack(side="left")
            self._reg(self._footer_author_lbl, "footer_author")

            ttk.Label(inner, text="   |   ", style="Footer.TLabel").pack(side="left")

            self._footer_license_lbl = ttk.Label(inner, style="Footer.TLabel")
            self._footer_license_lbl.pack(side="left")
            self._reg(self._footer_license_lbl, "footer_license")

            ttk.Label(inner, text="   |   ", style="Footer.TLabel").pack(side="left")

            self._footer_project_lbl = ttk.Label(inner, style="Footer.TLabel")
            self._footer_project_lbl.pack(side="left")
            self._reg(self._footer_project_lbl, "footer_project")

            self._footer_link_lbl = ttk.Label(inner, text=self._PROJECT_URL,
                                               style="FooterLink.TLabel", cursor="hand2")
            self._footer_link_lbl.pack(side="left")
            self._footer_link_lbl.bind("<Button-1>", self._open_project_url)

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

            self._lang_btn = ttk.Button(hdr, style="Lang.TButton", command=self._show_lang_menu)
            self._lang_btn.pack(side="right", padx=(6, 0))
            self._reg_fn(lambda: self._lang_btn.config(
                text=f"\U0001F310 {self._ui_lang.upper()}"))

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
            self._help(spf, "help_script_path").pack(side="left", padx=(6, 0))

            ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=6)

            self._build_footer()

            self._nb = ttk.Notebook(self)
            self._nb.pack(fill="both", expand=True, padx=10, pady=(0, 4))

            self._tab_input   = ttk.Frame(self._nb, padding=10)
            self._tab_search  = ttk.Frame(self._nb, padding=10)
            self._tab_physics = ttk.Frame(self._nb, padding=10)
            self._tab_output  = ttk.Frame(self._nb, padding=10)
            self._tab_run     = ttk.Frame(self._nb, padding=10)
            self._tab_ut      = ttk.Frame(self._nb, padding=0)

            for tab in (self._tab_input, self._tab_search,
                        self._tab_physics, self._tab_output, self._tab_run,
                        self._tab_ut):
                self._nb.add(tab, text="")

            self._tab_keys = [
                (0, "tab_input"), (1, "tab_search"), (2, "tab_physics"),
                (3, "tab_output"), (4, "tab_run"), (5, "tab_ut"),
            ]

            self._build_tab_input()
            self._build_tab_search()
            self._build_tab_physics()
            self._build_tab_output()
            self._build_tab_run()
            self._build_tab_ut()

            # Counterpoise fields follow the "Use counterpoise" checkbox
            # (enabled by default).
            self._toggle_cp_fields()

            # Every setting feeds the command preview, so bind them all now
            # that the widgets (and their variables) exist.
            self._bind_auto_refresh()

        # ── Tab: Band / Source ────────────────────────────────────────────

        def _build_tab_input(self):
            t = self._scrollable(self._tab_input)
            src_lf = ttk.LabelFrame(t, padding=8)
            src_lf.pack(fill="x", pady=(0, 8))
            self._reg(src_lf, "band_source_lf")
            src_lf.columnconfigure(2, weight=1)

            # Bands are always entered here — CSV loading has been removed.
            self._manual_frame = ttk.Frame(src_lf)
            self._manual_frame.grid(row=0, column=0, columnspan=3, sticky="ew")
            # src_lf.columnconfigure(2, weight=1) makes this frame's single
            # spanning cell stretch to the tab's full width. Without giving
            # this frame its own column weight, that stretch was absorbed
            # by column 1 (the Entry widgets, sticky="ew"), which grew wide
            # and pushed the help-text column far from the box. Weighting
            # a dedicated trailing spacer column instead keeps columns 0-2
            # (label / entry / hint) hugging their natural size.
            self._manual_frame.columnconfigure(3, weight=1)

            self._bands_lbl = ttk.Label(self._manual_frame)
            self._bands_lbl.grid(row=0, column=0, sticky="w")
            self._reg(self._bands_lbl, "bands_label")
            self._bands_var = tk.StringVar(value="40m,20m,15m")
            ttk.Entry(self._manual_frame, textvariable=self._bands_var, width=40).grid(
                row=0, column=1, padx=6, sticky="ew")
            self._help(self._manual_frame, "help_bands").grid(row=0, column=2, sticky="w")
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
            self._help(self._manual_frame, "help_freqs").grid(row=2, column=2, sticky="w", pady=(6, 0))
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
            self._help(self._manual_frame, "help_wire_len").grid(
                row=4, column=3, sticky="w", padx=(6, 0), pady=(6, 0))

            self._cp_len_lbl = ttk.Label(self._manual_frame)
            self._cp_len_lbl.grid(row=5, column=0, sticky="w", pady=(4, 0))
            self._reg(self._cp_len_lbl, "cp_len")
            self._cp_widgets = getattr(self, "_cp_widgets", [])
            self._cp_len_var = tk.StringVar(value="5.0")
            _cp_len_ent = ttk.Entry(self._manual_frame, textvariable=self._cp_len_var, width=12)
            _cp_len_ent.grid(row=5, column=1, padx=6, pady=(4, 0), sticky="w")
            self._cp_widgets.append(_cp_len_ent)
            _cl = ttk.Label(self._manual_frame, foreground=_ACCENT)
            _cl.grid(row=5, column=2, sticky="w", padx=(4, 0), pady=(4, 0))
            self._reg(_cl, "hint_cp_len")
            self._help(self._manual_frame, "help_cp_len").grid(
                row=5, column=3, sticky="w", padx=(6, 0), pady=(4, 0))

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
            self._help(abf2, "help_active_bands").pack(side="left", padx=(6, 0))

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
                         values=["auto", "en", "es", "it"], state="readonly").pack(side="left", padx=6)
            self._optlang_hint_lbl = ttk.Label(olf, style="Muted.TLabel")
            self._optlang_hint_lbl.pack(side="left")
            self._reg(self._optlang_hint_lbl, "optlang_hint")
            self._help(olf, "help_optlang").pack(side="left", padx=(6, 0))


        # ── Tab: Search Range ─────────────────────────────────────────────

        def _build_tab_search(self):
            t = self._scrollable(self._tab_search)
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
            self._help(mf, "help_margin").pack(side="left", padx=(6, 0))

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
                self._help(wr_lf, "help_wire_range").grid(
                    row=row_i, column=4, sticky="w", padx=(6, 0))
            self._wire_empty_lbl = ttk.Label(wr_lf, style="Muted.TLabel")
            self._wire_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(self._wire_empty_lbl, "leave_empty_wire")

            # ── Counterpoise on/off ──────────────────────────────────────
            # Unchecking this models an antenna WITHOUT a counterpoise: every
            # counterpoise field below (and the CP length on the Input tab)
            # becomes read-only and --no-counterpoise is added to the command.
            self._cp_widgets = getattr(self, "_cp_widgets", [])
            usecp_f = ttk.Frame(t)
            usecp_f.pack(fill="x", pady=(0, 4))
            self._use_cp_var = tk.BooleanVar(value=True)
            self._use_cp_chk = ttk.Checkbutton(usecp_f, variable=self._use_cp_var,
                                               command=self._toggle_cp_fields)
            self._use_cp_chk.pack(side="left")
            self._reg(self._use_cp_chk, "use_cp_chk")
            self._use_cp_hint_lbl = ttk.Label(usecp_f, foreground=_ACCENT)
            self._use_cp_hint_lbl.pack(side="left", padx=(8, 0))
            self._reg(self._use_cp_hint_lbl, "use_cp_hint")
            self._help(usecp_f, "help_use_cp").pack(side="left", padx=(6, 0))

            # ── Return path when there is NO counterpoise ────────────────
            # Mutually exclusive models, so radio buttons rather than
            # independent check boxes.  Enabled only while "Use counterpoise"
            # is unchecked — with a counterpoise the return path IS the
            # counterpoise.
            self._nocp_widgets = getattr(self, "_nocp_widgets", [])
            nocp_lf = ttk.LabelFrame(t, padding=8)
            nocp_lf.pack(fill="x", pady=(0, 8))
            self._reg(nocp_lf, "no_cp_return_lf")
            _nocp_hint = ttk.Label(nocp_lf, foreground=_ACCENT, wraplength=760,
                                   justify="left")
            _nocp_hint.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
            self._reg(_nocp_hint, "no_cp_return_hint")
            self._help(nocp_lf, "help_nocp_mode").grid(
                row=0, column=3, sticky="w", padx=(6, 0), pady=(0, 4))
            self._no_cp_return_var = tk.StringVar(value=DEFAULT_NO_CP_RETURN)
            for _r, (_val, _key) in enumerate((
                ("ground-rod", "no_cp_rod"),
                ("coax-stub",  "no_cp_stub"),
                ("reject",     "no_cp_reject"),
            ), start=1):
                _rb = ttk.Radiobutton(nocp_lf, value=_val,
                                      variable=self._no_cp_return_var,
                                      command=self._on_setting_changed)
                _rb.grid(row=_r, column=0, columnspan=3, sticky="w", pady=2)
                self._reg(_rb, _key)
                self._nocp_widgets.append(_rb)
            self._cp_stub_len_var = tk.StringVar(value=f"{DEFAULT_CP_STUB_LEN_M:.1f}")
            _stub_lbl = ttk.Label(nocp_lf)
            _stub_lbl.grid(row=4, column=0, sticky="w", pady=(6, 0))
            self._reg(_stub_lbl, "cp_stub_len_lbl")
            _stub_ent = ttk.Entry(nocp_lf, textvariable=self._cp_stub_len_var, width=10)
            _stub_ent.grid(row=4, column=1, padx=6, pady=(6, 0), sticky="w")
            self._nocp_widgets.append(_stub_ent)
            _stub_hint = ttk.Label(nocp_lf, foreground=_ACCENT)
            _stub_hint.grid(row=4, column=2, sticky="w", padx=(8, 0), pady=(6, 0))
            self._reg(_stub_hint, "cp_stub_len_hint")
            self._help(nocp_lf, "help_stub_len").grid(
                row=4, column=3, sticky="w", padx=(6, 0), pady=(6, 0))

            # ── Radiation / take-off angle ───────────────────────────────
            rad_lf = ttk.LabelFrame(t, padding=8)
            rad_lf.pack(fill="x", pady=(0, 8))
            self._reg(rad_lf, "rad_lf")
            self._target_toa_var   = tk.StringVar(value=f"{DEFAULT_TARGET_TOA_DEG:g}")
            self._gain_weight_var  = tk.StringVar(value=f"{DEFAULT_GAIN_WEIGHT:g}")
            self._rerank_top_var   = tk.StringVar(value=str(DEFAULT_RERANK_TOP_N))
            for _r, (_var, _key, _hkey) in enumerate((
                (self._target_toa_var,  "rad_target_toa_lbl",  "help_rad_target_toa"),
                (self._gain_weight_var, "rad_gain_weight_lbl", "help_rad_gain_weight"),
                (self._rerank_top_var,  "rad_rerank_top_lbl",  "help_rad_rerank_top"),
            )):
                _rl = ttk.Label(rad_lf)
                _rl.grid(row=_r, column=0, sticky="w", pady=3)
                self._reg(_rl, _key)
                _re_ent = ttk.Entry(rad_lf, textvariable=_var, width=10)
                _re_ent.grid(row=_r, column=1, padx=6, sticky="w")
                _var.trace_add("write", lambda *_a: self._on_setting_changed())
                self._help(rad_lf, _hkey).grid(
                    row=_r, column=2, sticky="w", padx=(6, 0))
            _rad_hint = ttk.Label(rad_lf, foreground=_ACCENT, wraplength=760,
                                  justify="left")
            _rad_hint.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(_rad_hint, "rad_hint")

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
                _cp_ent = ttk.Entry(cp_lf, textvariable=var, width=10)
                _cp_ent.grid(row=row_i, column=1, padx=6, pady=3, sticky="w")
                self._cp_widgets.append(_cp_ent)
                ttk.Label(cp_lf, text="m", style="Muted.TLabel").grid(row=row_i, column=2, sticky="w")
                _h = ttk.Label(cp_lf, foreground=_ACCENT)
                _h.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
                self._reg(_h, hk)
                self._help(cp_lf, "help_cp_range").grid(
                    row=row_i, column=4, sticky="w", padx=(6, 0))
            self._cp_empty_lbl = ttk.Label(cp_lf, style="Muted.TLabel")
            self._cp_empty_lbl.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(self._cp_empty_lbl, "leave_empty_cp")
            # Live "no cp length in range can reach the requested far-end
            # height" warning — depends on cp-min/cp-max AND on the height /
            # cp-end-height fields below, so it is recomputed by the same
            # _refresh_geom_warnings() that the height frame's label uses.
            self._cp_range_warn_lbl = ttk.Label(
                cp_lf, foreground=_WARN, wraplength=760, justify="left")
            self._cp_range_warn_lbl.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))
            self._cp_range_warn_lbl.grid_remove()

            hgt_lf = ttk.LabelFrame(t, padding=8)
            hgt_lf.pack(fill="x", pady=(0, 8))
            self._reg(hgt_lf, "antenna_geom_lf")
            # One height for the whole antenna: radiator and counterpoise both
            # hang from the feedpoint, so they always share the same value.
            self._height_var           = tk.StringVar(value=f"{DEFAULT_HEIGHT_M:.1f}")
            self._wire_slope_end_var   = tk.StringVar(value="")   # empty = horizontal
            self._cp_end_height_var    = tk.StringVar(value="")   # empty = antenna height
            for row_i, (key_lbl, var, key_hint, help_key) in enumerate([
                ("height_lbl",         self._height_var,         "height_hint",         "help_height"),
                ("wire_slope_end_lbl", self._wire_slope_end_var, "wire_slope_end_hint", "help_wire_slope_end"),
                ("cp_end_height_lbl",  self._cp_end_height_var,  "cp_end_height_hint",  "help_cp_end_height"),
            ]):
                lbl = ttk.Label(hgt_lf)
                lbl.grid(row=row_i, column=0, sticky="w", pady=3)
                self._reg(lbl, key_lbl)
                _geo_ent = ttk.Entry(hgt_lf, textvariable=var, width=10)
                _geo_ent.grid(row=row_i, column=1, padx=6, pady=3, sticky="w")
                if key_lbl == "cp_end_height_lbl":
                    self._cp_widgets.append(_geo_ent)
                ttk.Label(hgt_lf, text="m", style="Muted.TLabel").grid(row=row_i, column=2, sticky="w")
                hl = ttk.Label(hgt_lf, foreground=_ACCENT)
                hl.grid(row=row_i, column=3, sticky="w", padx=(8, 0))
                self._reg(hl, key_hint)
                self._help(hgt_lf, help_key).grid(
                    row=row_i, column=4, sticky="w", padx=(6, 0))

            # Live ground-proximity / unreachable-counterpoise warnings.
            # These mirror the CLI's own validation (build_deck_geometry,
            # validate_feedpoint_height, and the cp-end-height reach check)
            # so a value that would make nec2c emit garbage — or that would
            # silently make --cp-end-height a no-op — is flagged in the GUI
            # BEFORE the run starts, not buried in the console log after.
            self._geom_warn_lbl = ttk.Label(
                hgt_lf, foreground=_WARN, wraplength=760, justify="left")
            self._geom_warn_lbl.grid(
                row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
            self._geom_warn_lbl.grid_remove()   # hidden until there is something to say

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
            self._help(rtf, "help_retry").pack(side="left", padx=(6, 0))

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
            self._help(tnf, "help_topn").pack(side="left", padx=(6, 0))

        # ── Live geometry warnings (ground clearance / cp reach) ────────────

        def _gui_resolve_freqs_mhz(self) -> List[float]:
            """Best-effort frequency list from the current Bands/Freqs fields.

            Mirrors the CLI's own band/--freqs resolution closely enough for
            warning purposes: explicit --freqs wins, otherwise every band
            name that is in the known table is resolved to its centre
            frequency.  Unknown bands and parse errors are skipped silently
            — this is advisory GUI feedback, not the real validation the
            script performs at run time.
            """
            freqs: List[float] = []
            raw_freqs = self._freqs_var.get().strip() if hasattr(self, "_freqs_var") else ""
            if raw_freqs:
                for tok in raw_freqs.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    try:
                        f = float(tok)
                        if f > 0:
                            freqs.append(f)
                    except ValueError:
                        pass
            if not freqs and hasattr(self, "_bands_var"):
                for tok in self._bands_var.get().strip().split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    f = _lookup_band_freq(tok)
                    if f:
                        freqs.append(f)
            return freqs

        def _refresh_geom_warnings(self):
            """Recompute and show/hide the ground-clearance & cp-reach warnings.

            Reuses the script's own physics (ground_clearance_floor_m,
            ground_clearance_hard_min_m) rather than re-deriving the 0.05·λ /
            0.02·λ thresholds here, so the GUI can never drift out of sync
            with what a real run would report.
            """
            global _LANG
            geom_lbl = getattr(self, "_geom_warn_lbl", None)
            cp_lbl = getattr(self, "_cp_range_warn_lbl", None)
            if geom_lbl is None or cp_lbl is None:
                return

            def _hide(lbl):
                lbl.config(text="")
                lbl.grid_remove()

            def _show(lbl, text):
                lbl.config(text=text)
                lbl.grid()

            try:
                freqs = self._gui_resolve_freqs_mhz()
                if not freqs:
                    _hide(geom_lbl)
                    _hide(cp_lbl)
                    return

                # Speak the CLI's own warning strings, in the GUI's current
                # language, so the wording the user sees here is identical to
                # what a real run would print to the console.
                _prev_lang = _LANG
                _LANG = self._ui_lang if self._ui_lang in ("en", "es", "it") else "en"
                try:
                    ground_model = (self._ground_model_var.get().strip()
                                    if hasattr(self, "_ground_model_var") else DEFAULT_GROUND_MODEL)
                    perfect = (ground_model == "perfect")
                    floor_m = ground_clearance_floor_m(freqs)
                    hard_m  = ground_clearance_hard_min_m(freqs)

                    try:
                        height = float(self._height_var.get().strip() or DEFAULT_HEIGHT_M)
                    except ValueError:
                        height = DEFAULT_HEIGHT_M

                    geom_msgs = []

                    # ── Feedpoint height itself (--height) ─────────────────
                    if not perfect and height >= 0.0 and height < hard_m:
                        geom_msgs.append(
                            T("err_feedpoint_too_low").format(
                                height, hard_m, GROUND_CLEAR_FRAC_HARD))
                    elif not perfect and hard_m <= height < floor_m:
                        # Below the safe floor but above the hard singularity:
                        # the CLI raises this to the floor with a warning
                        # rather than rejecting it outright.
                        geom_msgs.append(
                            T("warn_slope_below_floor").format(
                                height, floor_m, GROUND_CLEAR_FRAC_SAFE))

                    # ── Radiator far end (--wire-slope-end-height) ─────────
                    slope_raw = (self._wire_slope_end_var.get().strip()
                                 if hasattr(self, "_wire_slope_end_var") else "")
                    if slope_raw:
                        try:
                            slope_val = float(slope_raw)
                        except ValueError:
                            slope_val = None
                        if slope_val is not None and slope_val >= 0.0:
                            if not perfect and slope_val < hard_m:
                                geom_msgs.append(
                                    T("warn_radiator_far_end_unreliable").format(
                                        slope_val, hard_m, floor_m))
                            elif not perfect and slope_val < floor_m:
                                geom_msgs.append(
                                    T("warn_slope_below_floor").format(
                                        slope_val, floor_m, GROUND_CLEAR_FRAC_SAFE))
                            elif perfect and 0.0 < slope_val <= floor_m:
                                # The CLI's own message here (DeckGeometry._clamp_end)
                                # is English-only, with no ES/IT variant — matched
                                # verbatim rather than inventing a translation.
                                geom_msgs.append(
                                    f"Radiator far end: requested {slope_val:.3f} m over a "
                                    f"perfectly conducting ground \u2014 snapped to z=0.000 m "
                                    f"(galvanic ground connection)."
                                )

                    if geom_msgs:
                        _show(geom_lbl, "\n\n".join(geom_msgs))
                    else:
                        _hide(geom_lbl)

                    # ── Counterpoise far end (--cp-end-height / --cp-min/max) ─
                    use_cp = bool(self._use_cp_var.get()) if hasattr(self, "_use_cp_var") else True
                    cp_msgs = []
                    if use_cp:
                        cp_end_raw = (self._cp_end_height_var.get().strip()
                                      if hasattr(self, "_cp_end_height_var") else "")
                        try:
                            cp_end_height = float(cp_end_raw) if cp_end_raw else height
                        except ValueError:
                            cp_end_height = height
                        try:
                            cp_min = float(self._cp_min_var.get().strip() or 0.0)
                        except ValueError:
                            cp_min = 0.0
                        try:
                            cp_max = float(self._cp_max_var.get().strip() or 0.0)
                        except ValueError:
                            cp_max = 0.0

                        # Counterpoise-far-end ground-clearance warning
                        # (same rule as the radiator far end, just labelled
                        # "Counterpoise far end" to match the CLI wording).
                        if not perfect and cp_end_height >= 0.0 and cp_end_height < hard_m:
                            cp_msgs.append(
                                T("warn_cp_far_end_unreliable").format(cp_end_height, hard_m))

                        # Unreachable-far-end warning, using the CLI's own
                        # translated strings so wording matches exactly.
                        cp_drop_needed = height - cp_end_height
                        if cp_drop_needed > 1e-9 and cp_max > 0.0:
                            if cp_max <= cp_drop_needed:
                                cp_msgs.append(T("cp_end_height_warn_all").format(
                                    cp_min, cp_max, cp_end_height, height, cp_drop_needed))
                            elif cp_min <= cp_drop_needed:
                                cp_msgs.append(T("cp_end_height_warn_some").format(
                                    cp_drop_needed, cp_end_height, height))

                    if cp_msgs:
                        _show(cp_lbl, "\n\n".join(cp_msgs))
                    else:
                        _hide(cp_lbl)
                finally:
                    _LANG = _prev_lang
            except Exception:
                # Advisory-only feature: never let a warning-preview bug
                # interfere with building or running the real command.
                pass

        # ── Tab: Physics ──────────────────────────────────────────────────

        def _toggle_cp_fields(self, *_a):
            """Enable/disable every counterpoise input.

            Called by the "Use counterpoise" checkbox and once at start-up.
            The values are kept (not cleared) so re-enabling the checkbox
            restores exactly what the user had typed.
            """
            state = "normal" if self._use_cp_var.get() else "disabled"
            for w in getattr(self, "_cp_widgets", []):
                try:
                    w.configure(state=state)
                except Exception:
                    pass
            # The return-path selector is the mirror image: it only matters
            # for an antenna built WITHOUT a counterpoise.
            nocp_state = "disabled" if self._use_cp_var.get() else "normal"
            for w in getattr(self, "_nocp_widgets", []):
                try:
                    w.configure(state=nocp_state)
                except Exception:
                    pass
            # The command preview depends on this flag as well.
            try:
                self._on_setting_changed()
            except Exception:
                pass

        def _build_tab_physics(self):
            t = self._scrollable(self._tab_physics)
            nec_lf = ttk.LabelFrame(t, padding=8)
            nec_lf.pack(fill="x", pady=(0, 8))
            self._reg(nec_lf, "nec2_engine_lf")
            mf_lbl_row = ttk.Frame(nec_lf)
            mf_lbl_row.pack(fill="x")
            self._eval_mode_lbl = ttk.Label(mf_lbl_row)
            self._eval_mode_lbl.pack(side="left")
            self._reg(self._eval_mode_lbl, "eval_mode")
            self._help(mf_lbl_row, "help_calc_mode").pack(side="left", padx=(6, 0))
            mf = ttk.Frame(nec_lf)
            mf.pack(fill="x", pady=(4, 0))
            self._mode_var = tk.StringVar(value="auto")
            self._rb_auto = ttk.Radiobutton(mf, variable=self._mode_var, value="auto")
            self._rb_auto.pack(side="left")
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
            self._help(nf, "help_nec2c_path").pack(side="left", padx=(6, 0))
            self._nec2c_hint_lbl = ttk.Label(nec_lf, style="Muted.TLabel")
            self._nec2c_hint_lbl.pack(anchor="w", pady=(2, 0))
            self._reg(self._nec2c_hint_lbl, "nec2c_hint")

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
            self._help(gf, "help_ground_cond").grid(row=0, column=3, sticky="w", padx=(6, 0))
            self._perm_lbl = ttk.Label(gf)
            self._perm_lbl.grid(row=1, column=0, sticky="w", pady=3)
            self._reg(self._perm_lbl, "permittivity")
            self._ground_diel_var = tk.StringVar(value="13.0")
            ttk.Entry(gf, textvariable=self._ground_diel_var, width=10).grid(row=1, column=1, padx=6, pady=3)
            self._perm_hint_lbl = ttk.Label(gf, style="Muted.TLabel")
            self._perm_hint_lbl.grid(row=1, column=2, sticky="w")
            self._reg(self._perm_hint_lbl, "perm_hint")
            self._help(gf, "help_ground_diel").grid(row=1, column=3, sticky="w", padx=(6, 0))

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

            # ── Ground model ─────────────────────────────────────────────
            gm_lf = ttk.LabelFrame(t, padding=8)
            gm_lf.pack(fill="x", pady=(0, 8))
            self._reg(gm_lf, "ground_model_lf")
            self._ground_model_var = tk.StringVar(value=DEFAULT_GROUND_MODEL)
            for _r, (_val, _key) in enumerate((
                ("sommerfeld", "ground_model_som"),
                ("perfect",    "ground_model_per"),
            )):
                _rb = ttk.Radiobutton(gm_lf, value=_val,
                                      variable=self._ground_model_var,
                                      command=self._on_setting_changed)
                _rb.grid(row=_r, column=0, sticky="w", pady=2)
                self._reg(_rb, _key)
            _gm_hint = ttk.Label(gm_lf, foreground=_ACCENT, wraplength=760,
                                 justify="left")
            _gm_hint.grid(row=2, column=0, sticky="w", pady=(4, 0))
            self._reg(_gm_hint, "ground_model_hint")
            self._help(gm_lf, "help_ground_model").grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

            # ── Conductor (wire diameter + material) ────────────────────
            # Previously WIRE_RADIUS_M and WIRE_MATERIALS were only settable
            # from the CLI; the GUI silently sent every run with 2 mm copper
            # regardless of what was selected here, because nothing here was
            # actually wired to a --wire-diameter/--wire-material/
            # --wire-conductivity flag. Now it is.
            wire_lf = ttk.LabelFrame(t, padding=8)
            wire_lf.pack(fill="x", pady=(0, 8))
            self._reg(wire_lf, "wire_conductor_lf")
            wdf = ttk.Frame(wire_lf)
            wdf.pack(anchor="w")
            self._wire_diam_lbl = ttk.Label(wdf)
            self._wire_diam_lbl.grid(row=0, column=0, sticky="w", pady=3)
            self._reg(self._wire_diam_lbl, "wire_diam_lbl")
            self._wire_diameter_var = tk.StringVar(value=f"{WIRE_RADIUS_M * 2000.0:.1f}")
            ttk.Entry(wdf, textvariable=self._wire_diameter_var, width=10).grid(
                row=0, column=1, padx=6, pady=3)
            ttk.Label(wdf, text="mm", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
            self._wire_diam_hint_lbl = ttk.Label(wdf, foreground=_ACCENT)
            self._wire_diam_hint_lbl.grid(row=0, column=3, sticky="w", padx=(8, 0))
            self._reg(self._wire_diam_hint_lbl, "wire_diam_hint")
            self._help(wdf, "help_wire_diam").grid(row=0, column=4, sticky="w", padx=(6, 0))

            self._wire_material_lbl = ttk.Label(wire_lf)
            self._wire_material_lbl.pack(anchor="w", pady=(8, 2))
            self._reg(self._wire_material_lbl, "wire_material_lbl")
            wmf = ttk.Frame(wire_lf)
            wmf.pack(anchor="w")
            # The combobox displays labels localized to self._ui_lang (e.g.
            # "cobre") but the *stored* selection is tracked separately as
            # the canonical English key ("copper") in _wire_material_key,
            # so --wire-material always gets a valid argparse choice
            # regardless of which language the combobox is showing. When
            # the language button is pressed, _apply_language() calls
            # _refresh_wire_material_combo() (registered below via
            # _reg_fn) to relabel the dropdown in place without losing the
            # current selection.
            self._wire_material_keys = sorted(WIRE_MATERIALS)
            self._wire_material_key = DEFAULT_WIRE_MATERIAL
            self._wire_material_var = tk.StringVar(
                value=wire_material_label(DEFAULT_WIRE_MATERIAL, self._ui_lang))
            self._wire_material_cb = ttk.Combobox(
                wmf, textvariable=self._wire_material_var, width=16,
                values=[wire_material_label(k, self._ui_lang)
                        for k in self._wire_material_keys],
                state="readonly")
            self._wire_material_cb.pack(side="left")
            self._help(wmf, "help_wire_material").pack(side="left", padx=(6, 0))

            def _on_wire_material_selected(_evt=None):
                # Combobox gives us the localized label the user clicked;
                # resolve it back to the canonical key immediately so
                # _wire_material_key is always correct even mid-selection.
                self._wire_material_key = wire_material_key_from_label(
                    self._wire_material_var.get().strip(), self._ui_lang)
            self._wire_material_cb.bind("<<ComboboxSelected>>",
                                         _on_wire_material_selected)

            def _refresh_wire_material_combo():
                self._wire_material_cb.config(
                    values=[wire_material_label(k, self._ui_lang)
                            for k in self._wire_material_keys])
                self._wire_material_var.set(
                    wire_material_label(self._wire_material_key, self._ui_lang))
            self._reg_fn(_refresh_wire_material_combo)

            wcf = ttk.Frame(wire_lf)
            wcf.pack(anchor="w", pady=(8, 0))
            self._wire_cond_lbl = ttk.Label(wcf)
            self._wire_cond_lbl.pack(side="left")
            self._reg(self._wire_cond_lbl, "wire_cond_override_lbl")
            self._wire_conductivity_var = tk.StringVar(value="")   # empty = use material
            ttk.Entry(wcf, textvariable=self._wire_conductivity_var, width=12).pack(
                side="left", padx=6)
            ttk.Label(wcf, text="S/m", style="Muted.TLabel").pack(side="left")
            self._help(wcf, "help_wire_conductivity").pack(side="left", padx=(6, 0))
            self._wire_cond_hint_lbl = ttk.Label(wire_lf, foreground=_ACCENT,
                                                 wraplength=760, justify="left")
            self._wire_cond_hint_lbl.pack(anchor="w", pady=(4, 0))
            self._reg(self._wire_cond_hint_lbl, "wire_cond_override_hint")

            # ── Accuracy / segmentation ──────────────────────────────────
            seg_lf = ttk.LabelFrame(t, padding=8)
            seg_lf.pack(fill="x", pady=(0, 8))
            self._reg(seg_lf, "segs_lf")
            self._segs_mode_var = tk.StringVar(value="fine")
            for _r, (_val, _key) in enumerate((
                ("fine",   "segs_mode_fine"),
                ("fast",   "segs_mode_fast"),
                ("custom", "segs_mode_custom"),
            )):
                _rb = ttk.Radiobutton(seg_lf, value=_val,
                                      variable=self._segs_mode_var,
                                      command=self._on_setting_changed)
                _rb.grid(row=_r, column=0, sticky="w", pady=2)
                self._reg(_rb, _key)
            self._segs_custom_var = tk.StringVar(value=str(SEGS_PER_HALF_WAVE_FINE))
            _seg_ent = ttk.Entry(seg_lf, textvariable=self._segs_custom_var, width=8)
            _seg_ent.grid(row=2, column=1, padx=6, sticky="w")
            self._segs_custom_var.trace_add("write", lambda *_a: self._on_setting_changed())
            self._help(seg_lf, "help_segs_custom").grid(row=2, column=2, sticky="w", padx=(6, 0))
            self._converge_var = tk.BooleanVar(value=False)
            _cv_cb = ttk.Checkbutton(seg_lf, variable=self._converge_var,
                                     command=self._on_setting_changed)
            _cv_cb.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self._reg(_cv_cb, "segs_converge_cb")
            self._help(seg_lf, "help_converge").grid(row=3, column=2, sticky="w", padx=(6, 0), pady=(6, 0))
            _seg_hint = ttk.Label(seg_lf, foreground=_ACCENT, wraplength=760,
                                  justify="left")
            _seg_hint.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self._reg(_seg_hint, "segs_hint")
            self._help(seg_lf, "help_segs").grid(row=4, column=3, sticky="w", padx=(6, 0), pady=(4, 0))

        # ── Tab: Output Files ─────────────────────────────────────────────

        def _build_tab_output(self):
            t = self._scrollable(self._tab_output)
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
            self._help(wdf, "help_outdir").pack(side="left", padx=(6, 0))
            self._workdir_hint_lbl = ttk.Label(wd_lf, style="Muted.TLabel")
            self._workdir_hint_lbl.pack(anchor="w", pady=(2, 0))
            self._reg(self._workdir_hint_lbl, "workdir_hint")

            of_lf = ttk.LabelFrame(t, padding=8)
            of_lf.pack(fill="x", pady=(0, 8))
            self._reg(of_lf, "outfiles_lf")
            self._out_txt_var          = tk.StringVar(value="optimizer_report.txt")
            self._out_png_var          = tk.StringVar(value="optimizer_plot.png")
            self._out_csv_var          = tk.StringVar(value="optimizer_best.csv")
            self._out_nec_var          = tk.StringVar(value="best_antenna.nec")
            self._out_rad_var          = tk.StringVar(value="radiation_diagrams.png")
            self._out_construction_var = tk.StringVar(value="antenna_construction.png")
            self._out_pdf_var          = tk.StringVar(value="antenna_brochure.pdf")
            for row_i, (flag, var, hk) in enumerate([
                ("out-txt:",          self._out_txt_var,          "hint_out_txt"),
                ("out-png:",          self._out_png_var,          "hint_out_png"),
                ("out-csv:",          self._out_csv_var,          "hint_out_csv"),
                ("out-nec:",          self._out_nec_var,          "hint_out_nec"),
                ("out-radiation:",    self._out_rad_var,          "hint_out_rad"),
                ("out-construction:", self._out_construction_var, "hint_out_construction"),
                ("out-pdf:",          self._out_pdf_var,          "hint_out_pdf"),
            ]):
                ttk.Label(of_lf, text=flag).grid(row=row_i, column=0, sticky="w", pady=3)
                ttk.Entry(of_lf, textvariable=var, width=30).grid(
                    row=row_i, column=1, padx=6, pady=3, sticky="ew")
                hl = ttk.Label(of_lf, foreground=_ACCENT)
                hl.grid(row=row_i, column=2, sticky="w", padx=(8, 0))
                self._reg(hl, hk)
                self._help(of_lf, "help_out_filenames").grid(
                    row=row_i, column=3, sticky="w", padx=(6, 0))
            of_lf.columnconfigure(1, weight=1)

        # ── Tab: Run ──────────────────────────────────────────────────────

        def _build_tab_run(self):
            t = self._tab_run
            misc_lf = ttk.LabelFrame(t, padding=8)
            misc_lf.pack(fill="x", pady=(0, 8))
            self._reg(misc_lf, "misc_lf")
            self._quiet_var       = tk.BooleanVar(value=True)
            self._no_interact_var = tk.BooleanVar(value=True)
            _q_row = ttk.Frame(misc_lf)
            _q_row.pack(anchor="w", fill="x")
            self._cb_quiet = ttk.Checkbutton(_q_row, variable=self._quiet_var)
            self._cb_quiet.pack(side="left")
            self._reg(self._cb_quiet, "quiet_flag")
            self._help(_q_row, "help_quiet").pack(side="left", padx=(6, 0))
            _ni_row = ttk.Frame(misc_lf)
            _ni_row.pack(anchor="w", fill="x")
            self._cb_no_interact = ttk.Checkbutton(_ni_row, variable=self._no_interact_var)
            self._cb_no_interact.pack(side="left")
            self._reg(self._cb_no_interact, "no_interact")
            self._help(_ni_row, "help_no_interact").pack(side="left", padx=(6, 0))

            cmd_lf = ttk.LabelFrame(t, padding=8)
            cmd_lf.pack(fill="x", expand=False, pady=(0, 8))
            self._reg(cmd_lf, "cmd_preview_lf")
            self._cmd_text = tk.Text(cmd_lf, height=4, wrap="word", state="disabled",
                                     bg=_ENTRY_BG, fg=_FG, font=self._font("mono"),
                                     relief="solid", insertbackground=_FG,
                                     highlightbackground=_BORDER, highlightthickness=1)
            self._cmd_text.pack(fill="x", expand=False)
            # No refresh button: the preview tracks every setting live (see
            # _bind_auto_refresh).

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
            self._show_pdf_btn = ttk.Button(btn_frame, style="InfoBtn.TButton",
                                             command=self._show_pdf, state="disabled")
            self._show_pdf_btn.pack(side="left", padx=(6, 0))
            self._reg(self._show_pdf_btn, "show_pdf_btn")
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

        # ── Tab: UnUn / Transmatch ────────────────────────────────────────

        @staticmethod
        def _ut_num(txt: str, default: float = 0.0) -> float:
            """Tolerant float parser — accepts ',' as decimal separator."""
            try:
                return float(str(txt).strip().replace(",", "."))
            except (TypeError, ValueError):
                return default

        @staticmethod
        def _ut_fmt(value, nd: int = 2, dash: str = "—") -> str:
            if value is None:
                return dash
            try:
                f = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not math.isfinite(f):
                return dash
            return f"{f:,.{nd}f}"

        def _scrollable(self, parent):
            """Return a vertically scrollable frame filling `parent`.

            Generic helper (not UT-specific): wraps `parent` in a Canvas +
            Scrollbar so that any page with more options than fit in the
            window height can always be scrolled, no matter how the window
            is sized. Mouse wheel scrolling is bound only while the pointer
            is over the canvas, so it doesn't hijack scrolling elsewhere.
            """
            canvas = tk.Canvas(parent, bg=_BG, highlightthickness=0)
            vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
            inner = ttk.Frame(canvas, padding=10)
            inner.bind("<Configure>",
                       lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
            win = canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.bind("<Configure>",
                        lambda e, c=canvas, w=win: c.itemconfigure(w, width=e.width))
            canvas.configure(yscrollcommand=vsb.set)
            canvas.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            def _wheel(ev, c=canvas):
                num = getattr(ev, "num", 0)
                if num == 4:
                    step = -1
                elif num == 5:
                    step = 1
                else:
                    step = -1 if getattr(ev, "delta", 0) > 0 else 1
                c.yview_scroll(step, "units")

            def _bind(_e=None, c=canvas):
                for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    c.bind_all(seq, _wheel)

            def _unbind(_e=None, c=canvas):
                for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    c.unbind_all(seq)

            canvas.bind("<Enter>", _bind)
            canvas.bind("<Leave>", _unbind)
            return inner

        def _ut_field(self, parent, row, key, var, width=14, unit="", col=0, help_key=None):
            lbl = ttk.Label(parent)
            lbl.grid(row=row, column=col, sticky="w", pady=2)
            self._reg(lbl, key)
            ent = ttk.Entry(parent, textvariable=var, width=width)
            ent.grid(row=row, column=col + 1, sticky="w", padx=(6, 12), pady=2)
            # Unit label and help badge are packed together into a single
            # narrow side-frame at one fixed column (col+2) instead of each
            # getting their own grid column. Two side-by-side field groups
            # in the same row (col=0 and col=3) previously multiplied any
            # extra column into real width, pushing later badges (e.g.
            # help_ut_core, help_ut_tm_core) out past the visible ~940px
            # of the 980px-wide window, where there is no horizontal
            # scrollbar to reach them — they existed but were effectively
            # invisible/unreachable. Packing keeps each field's total
            # width to "unit text + one badge", regardless of unit length.
            side = ttk.Frame(parent)
            side.grid(row=row, column=col + 2, sticky="w", padx=(0, 12), pady=2)
            if unit:
                ttk.Label(side, text=unit, style="Muted.TLabel").pack(
                    side="left", padx=(0, 4))
            hk = help_key or f"help_{key}"
            if hk in _GUI_HELP.get("en", {}):
                self._help(side, hk).pack(side="left")
            return ent

        def _ut_make_tree(self, parent, keys, widths, height=8):
            cols = [f"c{i}" for i in range(len(keys))]
            tv = ttk.Treeview(parent, columns=cols, show="headings",
                              height=height, style="UT.Treeview")
            for cid, w in zip(cols, widths):
                tv.column(cid, width=w, minwidth=60, anchor="center", stretch=True)

            def _heads(tv=tv, keys=keys, cols=cols):
                for cid, k in zip(cols, keys):
                    tv.heading(cid, text=self.t(k))

            _heads()
            self._reg_fn(_heads)
            xsb = ttk.Scrollbar(parent, orient="horizontal", command=tv.xview)
            tv.configure(xscrollcommand=xsb.set)
            tv.pack(fill="both", expand=True)
            xsb.pack(fill="x")
            return tv

        def _build_tab_ut(self):
            st = ttk.Style(self)
            st.configure("UT.Treeview", background=_ENTRY_BG, fieldbackground=_ENTRY_BG,
                         foreground=_FG, bordercolor=_BORDER, rowheight=22,
                         font=self._font("label"))
            st.configure("UT.Treeview.Heading", background=_BG3, foreground=_FG,
                         relief="solid", bordercolor=_BORDER, font=self._font("label"))
            st.map("UT.Treeview", background=[("selected", _ACCENT)],
                   foreground=[("selected", _BG)])

            # Antenna data cached from the optimizer CSV
            self._ant_bands: list = []
            self._ant_unun_ratio: float = 1.0
            self._ut_busy = False
            self._ut_job = None

            self._ut_nb = ttk.Notebook(self._tab_ut)
            self._ut_nb.pack(fill="both", expand=True)
            un_page = ttk.Frame(self._ut_nb)
            tm_page = ttk.Frame(self._ut_nb)
            self._ut_nb.add(un_page, text="")
            self._ut_nb.add(tm_page, text="")
            self._ut_sub_keys = [(0, "ut_sub_unun"), (1, "ut_sub_tm")]

            def _subtabs():
                for idx, key in self._ut_sub_keys:
                    try:
                        self._ut_nb.tab(idx, text=self.t(key))
                    except Exception:
                        pass

            _subtabs()
            self._reg_fn(_subtabs)

            self._build_ut_unun(self._scrollable(un_page))
            self._build_ut_tm(self._scrollable(tm_page))
            self._ut_bind_vars()
            self._ut_recompute()

        # ── UnUn page ─────────────────────────────────────────────────────

        def _build_ut_unun(self, t):
            ant_lf = ttk.LabelFrame(t, padding=8)
            ant_lf.pack(fill="x", pady=(0, 8))
            self._reg(ant_lf, "ut_ant_lf")

            top = ttk.Frame(ant_lf)
            top.pack(fill="x")
            bl = ttk.Label(top)
            bl.pack(side="left")
            self._reg(bl, "ut_band")
            self._ut_band_var = tk.StringVar(value="")
            self._ut_band_cb = ttk.Combobox(top, textvariable=self._ut_band_var,
                                            width=12, state="readonly", values=[])
            self._ut_band_cb.pack(side="left", padx=6)
            self._ut_band_cb.bind("<<ComboboxSelected>>", self._ut_apply_band)
            self._help(top, "help_ut_band").pack(side="left", padx=(0, 6))
            rb = ttk.Button(top, style="Browse.TButton",
                            command=lambda: self._load_antenna_data(False))
            rb.pack(side="left", padx=(12, 0))
            self._reg(rb, "ut_reload_btn")
            xb = ttk.Button(top, style="Browse.TButton", command=self._ut_export)
            xb.pack(side="left", padx=(6, 0))
            self._reg(xb, "ut_export_btn")
            self._help(top, "help_ut_reload_export").pack(side="left", padx=(6, 0))

            self._ut_status_lbl = ttk.Label(ant_lf, style="Muted.TLabel")
            self._ut_status_lbl.pack(anchor="w", pady=(4, 0))
            self._ut_status_key = "ut_no_data"
            self._ut_status_kw: dict = {}

            def _upd_status():
                if self._ut_status_key:
                    self._ut_status_lbl.config(
                        text=self.t(self._ut_status_key, **self._ut_status_kw))

            self._ut_status_upd = _upd_status
            _upd_status()
            self._reg_fn(_upd_status)

            g = ttk.Frame(ant_lf)
            g.pack(fill="x", pady=(6, 0))
            self._ut_freq_var = tk.StringVar(value="7.100")
            self._ut_rout_var = tk.StringVar(value="450")
            self._ut_xout_var = tk.StringVar(value="150")
            self._ut_rin_var  = tk.StringVar(value="50")
            self._ut_xin_var  = tk.StringVar(value="0")
            self._ut_field(g, 0, "ut_freq", self._ut_freq_var, unit="MHz")
            self._ut_field(g, 1, "ut_rout", self._ut_rout_var, unit="Ω")
            self._ut_field(g, 2, "ut_xout", self._ut_xout_var, unit="Ω")
            self._ut_field(g, 0, "ut_rin",  self._ut_rin_var,  unit="Ω", col=3)
            self._ut_field(g, 1, "ut_xin",  self._ut_xin_var,  unit="Ω", col=3)

            core_lf = ttk.LabelFrame(t, padding=8)
            core_lf.pack(fill="x", pady=(0, 8))
            self._reg(core_lf, "ut_core_lf")
            core_row = ttk.Frame(core_lf)
            core_row.pack(fill="both", expand=True)
            cg = ttk.Frame(core_row)
            cg.pack(side="left", fill="both", expand=True)

            # ── Core / Air ──────────────────────────────────────────────
            # Checked (default) → "Core": build on a ferrite/powdered-iron
            #                     toroid, exactly as before (Toroid core
            #                     dropdown active; magnetics/saturation/
            #                     core-loss results shown).
            # Unchecked         → "Air": build an air-core single-layer
            #                     solenoid instead (Toroid core dropdown
            #                     disabled; Coil former diameter / Space
            #                     between turns enabled in its place;
            #                     toroid-only results hidden).
            ctl = ttk.Label(cg)
            ctl.grid(row=0, column=0, sticky="w", pady=2)
            self._reg(ctl, "ut_core_type")
            self._ut_core_is_core_var = tk.BooleanVar(value=True)
            self._ut_core_type_cb = ttk.Checkbutton(
                cg, variable=self._ut_core_is_core_var,
                command=self._ut_on_core_type_change)
            self._ut_core_type_cb.grid(row=0, column=1, sticky="w", padx=(6, 12))
            # Label + badge share a small side-frame at column 2 instead of
            # each getting their own grid column: column 3's width used to
            # be set by row 1's much longer, dynamic toroid-spec text (see
            # below), which pushed this badge out to the far right of the
            # window, past the visible area with no horizontal scrollbar.
            ct_side = ttk.Frame(cg)
            ct_side.grid(row=0, column=2, sticky="w")
            self._ut_core_type_lbl = ttk.Label(ct_side, style="Muted.TLabel")
            self._ut_core_type_lbl.pack(side="left", padx=(0, 6))
            self._help(ct_side, "help_ut_core_type").pack(side="left")

            def _upd_core_type_lbl():
                self._ut_core_type_lbl.config(
                    text=self.t("ut_core_type_core")
                    if self._ut_core_is_core_var.get()
                    else self.t("ut_core_type_air"))
            self._ut_core_type_lbl_upd = _upd_core_type_lbl
            _upd_core_type_lbl()
            self._reg_fn(_upd_core_type_lbl)

            self._ut_core_var = tk.StringVar(value=DEFAULT_TOROID)
            cl = ttk.Label(cg)
            cl.grid(row=1, column=0, sticky="w", pady=2)
            self._reg(cl, "ut_core")
            self._ut_core_cb = ttk.Combobox(cg, textvariable=self._ut_core_var, width=14,
                         state="readonly",
                         values=list(TOROID_DB.keys()))
            self._ut_core_cb.grid(row=1, column=1, sticky="w", padx=(6, 12))
            # The toroid spec text (e.g. "Ferrite Mix 31 · AL 1800 nH/N² ·
            # OD 61.0 / ID 35.6 / H 12.7 mm · Ae 1.52 cm²") is long and its
            # width varies by core, so it gets a wraplength and its own
            # column, with the badge in a separate fixed column right
            # after — previously the badge's column position was set by
            # this label's full unwrapped width via columnspan, pushing it
            # off the visible edge of the window.
            self._ut_core_info = ttk.Label(cg, style="Muted.TLabel", wraplength=220,
                                           justify="left")
            self._ut_core_info.grid(row=1, column=2, sticky="w", padx=(0, 6))
            self._help(cg, "help_ut_core").grid(row=1, column=3, sticky="w")

            self._ut_coil_dia_var = tk.StringVar(value="50")
            self._ut_space_var    = tk.StringVar(value="1.0")
            self._ut_coil_dia_ent = self._ut_field(
                cg, 2, "ut_coil_dia", self._ut_coil_dia_var, unit="mm")
            self._ut_space_ent = self._ut_field(
                cg, 3, "ut_space", self._ut_space_var, unit="mm")

            self._ut_air_note_lbl = ttk.Label(cg, style="Muted.TLabel",
                                              wraplength=520, justify="left")
            self._ut_air_note_lbl.grid(row=8, column=0, columnspan=5, sticky="w", pady=(6, 0))
            self._reg(self._ut_air_note_lbl, "ut_air_note")

            # ── Compensate / fixed-ratio mode ─────────────────────────
            # Checked (default)  → "Compensate": ratio is auto-calculated
            #                       from R_out / R_in, same as before.
            # Unchecked          → "Ratio": the UnUn is built for a FIXED
            #                       standard ratio (e.g. 9, 49, 64) typed
            #                       into the Ratio box; R_out / R_in no
            #                       longer set the turns ratio (they still
            #                       feed the reactance-compensation and
            #                       multi-band sections further down).
            rl = ttk.Label(cg)
            rl.grid(row=4, column=0, sticky="w", pady=2)
            self._reg(rl, "ut_ratio_mode")
            self._ut_ratio_compensate_var = tk.BooleanVar(value=True)
            self._ut_ratio_cb = ttk.Checkbutton(
                cg, variable=self._ut_ratio_compensate_var,
                command=self._ut_on_ratio_mode_change)
            self._ut_ratio_cb.grid(row=4, column=1, sticky="w", padx=(6, 12))
            rm_side = ttk.Frame(cg)
            rm_side.grid(row=4, column=2, sticky="w")
            self._ut_ratio_mode_lbl = ttk.Label(rm_side, style="Muted.TLabel",
                                                 wraplength=180, justify="left")
            self._ut_ratio_mode_lbl.pack(side="left", padx=(0, 6))
            self._help(rm_side, "help_ut_ratio_mode").pack(side="left")

            def _upd_ratio_mode_lbl():
                self._ut_ratio_mode_lbl.config(
                    text=self.t("ut_ratio_compensate")
                    if self._ut_ratio_compensate_var.get()
                    else self.t("ut_ratio_fixed"))
            self._ut_ratio_mode_lbl_upd = _upd_ratio_mode_lbl
            _upd_ratio_mode_lbl()
            self._reg_fn(_upd_ratio_mode_lbl)

            self._ut_ratio_val_var = tk.StringVar(value="9")
            self._ut_ratio_val_ent = self._ut_field(
                cg, 5, "ut_ratio_val", self._ut_ratio_val_var, unit="")

            self._ut_np_var   = tk.StringVar(value="15")
            self._ut_wire_var = tk.StringVar(value="2.0")
            self._ut_field(cg, 6, "ut_np",   self._ut_np_var,   unit="")
            self._ut_field(cg, 7, "ut_wire", self._ut_wire_var, unit="mm")
            self._build_ut_diagram(core_row)
            self._ut_apply_ratio_mode_state()
            self._ut_apply_core_type_state()

            res_lf = ttk.LabelFrame(t, padding=6)
            res_lf.pack(fill="both", expand=True, pady=(0, 8))
            self._reg(res_lf, "ut_res_lf")
            self._ut_res_text = tk.Text(res_lf, height=30, wrap="none", state="disabled",
                                        bg=_ENTRY_BG, fg=_FG, font=self._font("mono"),
                                        relief="solid", highlightbackground=_BORDER,
                                        highlightthickness=1)
            self._ut_res_text.pack(fill="both", expand=True)
            self._ut_res_text.tag_config("head", foreground=_TAG_HEAD)
            self._ut_res_text.tag_config("ok",   foreground=_TAG_OK)
            self._ut_res_text.tag_config("warn", foreground=_TAG_WARN)
            self._ut_res_text.tag_config("err",  foreground=_TAG_ERR)

            mb_lf = ttk.LabelFrame(t, padding=8)
            mb_lf.pack(fill="both", expand=True)
            self._reg(mb_lf, "ut_mb_lf")
            note = ttk.Label(mb_lf, style="Muted.TLabel", wraplength=880, justify="left")
            note.pack(anchor="w")
            self._reg(note, "ut_mb_note")

            mg = ttk.Frame(mb_lf)
            mg.pack(fill="x", pady=(6, 6))
            self._ut_mb_auto_var  = tk.BooleanVar(value=True)
            self._ut_mb_kind_var  = tk.StringVar(value="C")
            self._ut_mb_val_var   = tk.StringVar(value="")
            self._ut_mb_ratio_var = tk.StringVar(value="")
            self._ut_mb_z0_var    = tk.StringVar(value="50")
            self._ut_mb_auto_cb = ttk.Checkbutton(mg, variable=self._ut_mb_auto_var)
            self._ut_mb_auto_cb.grid(row=0, column=0, columnspan=2, sticky="w")
            self._reg(self._ut_mb_auto_cb, "ut_mb_auto")
            self._help(mg, "help_ut_mb_auto").grid(row=0, column=2, sticky="w")
            tl = ttk.Label(mg)
            tl.grid(row=1, column=0, sticky="w", pady=2)
            self._reg(tl, "ut_mb_type")
            self._ut_mb_kind_cb = ttk.Combobox(mg, textvariable=self._ut_mb_kind_var,
                                               width=8, state="readonly",
                                               values=["L", "C", "none"])
            self._ut_mb_kind_cb.grid(row=1, column=1, sticky="w", padx=(6, 12))
            self._help(mg, "help_ut_mb_kind").grid(row=1, column=2, sticky="w")
            # ut_mb_val's unit (µH/pF) depends on the L/C choice at
            # runtime, so it can't be passed as _ut_field's static unit=
            # kwarg. Building label+entry+dynamic-unit+badge by hand here
            # (all packed together, left to right) keeps the badge from
            # colliding with the unit text regardless of its width.
            ut_mb_val_row = ttk.Frame(mg)
            ut_mb_val_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
            _mb_val_lbl = ttk.Label(ut_mb_val_row)
            _mb_val_lbl.pack(side="left")
            self._reg(_mb_val_lbl, "ut_mb_val")
            self._ut_mb_val_ent = ttk.Entry(ut_mb_val_row, textvariable=self._ut_mb_val_var, width=14)
            self._ut_mb_val_ent.pack(side="left", padx=(6, 6))
            self._ut_mb_unit_lbl = ttk.Label(ut_mb_val_row, style="Muted.TLabel")
            self._ut_mb_unit_lbl.pack(side="left", padx=(0, 6))
            self._help(ut_mb_val_row, "help_ut_mb_val").pack(side="left")
            self._ut_mb_ratio_ent = self._ut_field(mg, 1, "ut_mb_ratio", self._ut_mb_ratio_var, col=3)
            self._ut_field(mg, 2, "ut_mb_z0", self._ut_mb_z0_var, col=3)

            self._ut_mb_tree = self._ut_make_tree(
                mb_lf,
                ["utc_band", "utc_freq", "utc_r", "utc_x", "utc_xcomp",
                 "utc_zin", "utc_vswr_plain", "utc_vswr_comp", "utc_delta"],
                [70, 80, 90, 90, 100, 150, 120, 120, 90], height=9)

            note2 = ttk.Label(t, style="Muted.TLabel", wraplength=880, justify="left")
            note2.pack(anchor="w", pady=(6, 0))
            self._reg(note2, "ut_note_unun")

        # ── UnUn toroid construction drawing (PNG) ───────────────────────

        def _build_ut_diagram(self, parent):
            """Constructional PNG of the toroid, shown right of the core settings."""
            box = ttk.LabelFrame(parent, padding=6)
            # expand=True let this box claim all leftover horizontal space
            # in the scrollable page (which has no real width ceiling),
            # stretching it far past the window — fill="y" keeps it sized
            # to its own content (the wrapped label) instead.
            box.pack(side="left", fill="y", padx=(12, 0))
            self._reg(box, "ut_dia_lf")

            self._ut_dia_path = None          # last PNG written on disk
            self._ut_dia_img = None           # keep a reference alive for Tk
            self._ut_dia_sig = None           # avoid useless re-renders

            self._ut_dia_lbl = tk.Label(box, bg=_ENTRY_BG, bd=1, relief="solid",
                                        cursor="hand2", justify="center",
                                        fg=_FG, wraplength=260, padx=10, pady=40,
                                        text=self.t("ut_dia_empty"))
            self._ut_dia_lbl.pack(fill="both", expand=True)
            self._ut_dia_lbl.bind("<Button-1>", lambda _e: self._ut_dia_zoom())

            bar = ttk.Frame(box)
            bar.pack(fill="x", pady=(6, 0))
            self._ut_dia_upd_btn = ttk.Button(bar, style="Accent.TButton",
                                              command=self._ut_dia_update)
            self._ut_dia_upd_btn.pack(side="left")
            self._reg(self._ut_dia_upd_btn, "ut_dia_upd")
            self._ut_dia_btn = ttk.Button(bar, style="Browse.TButton",
                                          command=self._ut_dia_save_as)
            self._ut_dia_btn.pack(side="left", padx=(6, 0))
            self._reg(self._ut_dia_btn, "ut_dia_save")
            self._ut_dia_hint = ttk.Label(box, style="Muted.TLabel",
                                          wraplength=430, justify="left")
            self._ut_dia_hint.pack(anchor="w", pady=(4, 0))
            self._reg(self._ut_dia_hint, "ut_dia_click")

            self._ut_dia_file = ttk.Label(box, style="Muted.TLabel",
                                          wraplength=430, justify="left")
            self._ut_dia_file.pack(anchor="w", pady=(2, 0))

        def _ut_dia_outpath(self) -> str:
            """Where the PNG lives: the optimizer output directory if usable."""
            outdir = ""
            try:
                outdir = self._outdir_var.get().strip()
            except Exception:
                outdir = ""
            outdir = outdir or os.getcwd()
            if not (os.path.isdir(outdir) and os.access(outdir, os.W_OK)):
                outdir = tempfile.gettempdir()
            return os.path.join(outdir, "unun_toroid.png")

        def _ut_dia_mark_stale(self):
            """The page changed: flag the drawing, but never redraw on its own."""
            if not hasattr(self, "_ut_dia_lbl"):
                return
            if self._ut_dia_path and self._ut_dia_sig != self._ut_dia_signature():
                self._ut_dia_hint.config(text=self.t("ut_dia_stale"))

        def _ut_dia_signature(self):
            """Fingerprint of everything the drawing depends on."""
            d = getattr(self, "_ut_design", None) or {}
            return (self._ui_lang, d.get("core_type"), d.get("core"), d.get("n_total"),
                    d.get("n_tap"), d.get("wire_dia_mm"), d.get("r_out"),
                    d.get("coil_dia_mm"), d.get("space_mm"))

        def _ut_dia_update(self):
            """UPDATE DRAWING button — rebuild the PNG from the page data."""
            if not HAS_MPL:
                self._ut_dia_lbl.config(image="", text=self.t("ut_dia_none"),
                                        wraplength=400, padx=10, pady=40)
                return
            if getattr(self, "_ut_job", None) is not None:
                try:                                     # apply pending edits
                    self.after_cancel(self._ut_job)
                except Exception:
                    pass
                self._ut_job = None
                self._ut_recompute()
            self._ut_dia_render()

        def _ut_dia_render(self):
            d = getattr(self, "_ut_design", None)
            if not d or not HAS_MPL:
                return
            path = self._ut_dia_outpath()
            draw_fn = unun_solenoid_png if d.get("core_type") == "air" else unun_toroid_png
            try:
                out = draw_fn(d, path, lang=self._ui_lang, dpi=150)
            except Exception as e:                      # never kill the GUI
                self._ut_dia_lbl.config(image="", text=self.t("ut_dia_err", e=e),
                                        wraplength=400, padx=10, pady=30)
                return
            if not out:
                return
            self._ut_dia_path = out
            self._ut_dia_sig = self._ut_dia_signature()
            self._ut_dia_show(out)
            self._ut_dia_hint.config(text=self.t("ut_dia_click"))
            self._ut_dia_file.config(text=self.t("ut_dia_file", file=out))

        def _ut_dia_show(self, path: str, max_w: int = 440, max_h: int = 300):
            """Load the PNG and fit it into the preview label."""
            try:
                img = tk.PhotoImage(file=path)
            except Exception:                            # Tk < 8.6: no PNG
                self._ut_dia_lbl.config(image="", padx=10, pady=30,
                                        wraplength=400,
                                        text=self.t("ut_dia_file", file=path))
                return
            k = max(1, -(-img.width() // max_w), -(-img.height() // max_h))
            if k > 1:
                img = img.subsample(k, k)
            self._ut_dia_img = img                       # keep the reference
            self._ut_dia_lbl.config(image=img, text="", padx=0, pady=0)

        def _ut_dia_zoom(self):
            """Open the PNG at full size in its own scrollable window."""
            path = getattr(self, "_ut_dia_path", None)
            if not path or not os.path.isfile(path):
                return
            try:
                img = tk.PhotoImage(file=path)
            except Exception:
                return
            top = tk.Toplevel(self)
            top.title(self.t("ut_dia_title"))
            top.configure(bg=_BG)
            cv = tk.Canvas(top, bg=_BG, highlightthickness=0,
                           width=min(img.width(), self.winfo_screenwidth() - 120),
                           height=min(img.height(), self.winfo_screenheight() - 160))
            hsb = ttk.Scrollbar(top, orient="horizontal", command=cv.xview)
            vsb = ttk.Scrollbar(top, orient="vertical", command=cv.yview)
            cv.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set,
                         scrollregion=(0, 0, img.width(), img.height()))
            cv.create_image(0, 0, image=img, anchor="nw")
            cv._img_ref = img                            # keep the reference
            cv.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            top.rowconfigure(0, weight=1)
            top.columnconfigure(0, weight=1)
            top.bind("<Escape>", lambda _e: top.destroy())

        def _ut_dia_save_as(self):
            d = getattr(self, "_ut_design", None)
            title = self.t("ut_dia_lf")
            if not HAS_MPL:
                messagebox.showinfo(title, self.t("ut_dia_none"))
                return
            if not d:
                return
            is_air = d.get("core_type") == "air"
            draw_fn = unun_solenoid_png if is_air else unun_toroid_png
            default_name = "unun_solenoid.png" if is_air else "unun_toroid.png"
            path = filedialog.asksaveasfilename(
                title=title, defaultextension=".png",
                initialdir=self._outdir_var.get().strip() or os.getcwd(),
                initialfile=default_name,
                filetypes=[("PNG image", "*.png"), ("All files", "*")])
            if not path:
                return
            try:
                out = draw_fn(d, path, lang=self._ui_lang, dpi=200)
            except Exception as e:
                messagebox.showerror(title, str(e))
                return
            if not out:
                messagebox.showerror(title, self.t("ut_dia_err", e=self.t("ut_dia_none")))
                return
            messagebox.showinfo(title, self.t("ut_dia_saved", file=out))

        # ── Transmatch page ───────────────────────────────────────────────

        def _build_ut_tm(self, t):
            gl = ttk.LabelFrame(t, padding=8)
            gl.pack(fill="x", pady=(0, 8))
            self._reg(gl, "ut_tm_glob_lf")
            g = ttk.Frame(gl)
            g.pack(fill="x")
            self._tm_z0_var    = tk.StringVar(value="50")
            self._tm_wire_var  = tk.StringVar(value="1.0")
            self._tm_core_var  = tk.StringVar(value="50")
            self._tm_space_var = tk.StringVar(value="1.0")
            self._tm_tref_var  = tk.StringVar(value="")
            self._tm_tref_auto_var = tk.BooleanVar(value=True)
            self._ut_field(g, 0, "ut_tm_z0",    self._tm_z0_var,    unit="Ω")
            self._ut_field(g, 1, "ut_tm_wire",  self._tm_wire_var,  unit="mm")
            self._ut_field(g, 2, "ut_tm_space", self._tm_space_var, unit="mm")
            self._ut_field(g, 0, "ut_tm_core",  self._tm_core_var,  unit="mm", col=3)
            self._tm_tref_ent = self._ut_field(g, 1, "ut_tm_tref", self._tm_tref_var, col=3)
            self._tm_tref_cb = ttk.Checkbutton(g, variable=self._tm_tref_auto_var)
            self._tm_tref_cb.grid(row=2, column=4, sticky="w")
            self._reg(self._tm_tref_cb, "ut_tm_tref_auto")
            self._help(g, "help_tm_tref").grid(row=2, column=5, sticky="w", padx=(6, 0))
            # ut_tm_tref (row=1, col=3) already places its own help badge
            # in a side-frame at column 5 via _ut_field — this hint label
            # used to be grid-placed at that same row/column, overlapping
            # the badge. Column 6 is free at row 1.
            self._tm_tref_hint = ttk.Label(g, style="Muted.TLabel")
            self._tm_tref_hint.grid(row=1, column=6, sticky="w", padx=(6, 0))

            tap_lf = ttk.LabelFrame(t, padding=8)
            tap_lf.pack(fill="x", pady=(0, 8))
            self._reg(tap_lf, "ut_tm_taps_lf")
            tap_hdr_row = ttk.Frame(tap_lf)
            tap_hdr_row.pack(fill="x")
            self._tm_tap_hdr_lbl = ttk.Label(tap_hdr_row, style="Muted.TLabel")
            self._tm_tap_hdr_lbl.pack(side="left")
            self._reg(self._tm_tap_hdr_lbl, "ut_tm_columns_lbl")
            self._help(tap_hdr_row, "help_tm_table").pack(side="left", padx=(6, 0))
            tap_row = ttk.Frame(tap_lf)
            tap_row.pack(fill="both", expand=True)
            tg = ttk.Frame(tap_row)
            tg.pack(side="left", anchor="n")
            self._build_tm_diagram(tap_row)
            hdrs = [("ut_tm_tap", 0), ("utc_band", 1), ("utc_freq", 2),
                    ("utc_r", 3), ("utc_x", 4), ("ut_tm_active", 5)]
            for key, col in hdrs:
                hl = ttk.Label(tg, style="Muted.TLabel")
                hl.grid(row=0, column=col, sticky="w", padx=4, pady=(0, 3))
                self._reg(hl, key)

            self._tm_band_vars, self._tm_f_vars = [], []
            self._tm_r_vars, self._tm_x_vars, self._tm_act_vars = [], [], []
            for i in range(11):
                ttk.Label(tg, text=str(i + 1)).grid(row=i + 1, column=0, padx=4)
                bv = tk.StringVar(value="")
                fv = tk.StringVar(value="")
                rv = tk.StringVar(value="")
                xv = tk.StringVar(value="")
                av = tk.BooleanVar(value=False)
                ttk.Entry(tg, textvariable=bv, width=8).grid(row=i + 1, column=1, padx=4, pady=1)
                ttk.Entry(tg, textvariable=fv, width=12).grid(row=i + 1, column=2, padx=4, pady=1)
                ttk.Entry(tg, textvariable=rv, width=12).grid(row=i + 1, column=3, padx=4, pady=1)
                ttk.Entry(tg, textvariable=xv, width=12).grid(row=i + 1, column=4, padx=4, pady=1)
                ttk.Checkbutton(tg, variable=av).grid(row=i + 1, column=5, padx=4)
                self._tm_band_vars.append(bv)
                self._tm_f_vars.append(fv)
                self._tm_r_vars.append(rv)
                self._tm_x_vars.append(xv)
                self._tm_act_vars.append(av)
            # Workbook defaults so the page is usable before any optimizer run
            for i, (b, f, r, x) in enumerate((("40m", "7.150", "75", "-12"),
                                              ("20m", "14.170", "67", "23"),
                                              ("10m", "28.000", "45", "10"))):
                self._tm_band_vars[i].set(b)
                self._tm_f_vars[i].set(f)
                self._tm_r_vars[i].set(r)
                self._tm_x_vars[i].set(x)
                self._tm_act_vars[i].set(True)

            win_lf = ttk.LabelFrame(t, padding=6)
            win_lf.pack(fill="both", expand=True, pady=(0, 8))
            self._reg(win_lf, "ut_tm_win_lf")
            self._tm_tree = self._ut_make_tree(
                win_lf,
                ["utc_band", "utc_freq", "utc_r", "utt_rreal", "utt_rerr",
                 "utt_n", "utt_turns", "utt_dturns",
                 "utt_wire", "utt_rdc", "utt_cum", "utt_z", "utt_phase",
                 "utt_swr", "utt_rl", "utt_ml", "utt_refl"],
                [70, 80, 90, 110, 80, 90, 70, 80, 90, 90, 110, 80, 80,
                 70, 80, 80, 80], height=8)

            comp_lf = ttk.LabelFrame(t, padding=6)
            comp_lf.pack(fill="both", expand=True, pady=(0, 8))
            self._reg(comp_lf, "ut_tm_comp_lf")
            self._tm_ctree = self._ut_make_tree(
                comp_lf,
                ["utc_band", "utc_freq", "utc_r", "utc_x", "utt_xp",
                 "utt_serl", "utt_serc", "utt_shl", "utt_shc", "utt_swr5"],
                [70, 80, 90, 90, 90, 110, 120, 110, 120, 110], height=8)

            coil_lf = ttk.LabelFrame(t, padding=6)
            coil_lf.pack(fill="x", pady=(0, 8))
            self._reg(coil_lf, "ut_tm_coil_lf")
            self._tm_coil_text = tk.Text(coil_lf, height=12, wrap="none", state="disabled",
                                         bg=_ENTRY_BG, fg=_FG, font=self._font("mono"),
                                         relief="solid", highlightbackground=_BORDER,
                                         highlightthickness=1)
            self._tm_coil_text.pack(fill="both", expand=True)
            self._tm_coil_text.tag_config("ok",   foreground=_TAG_OK)
            self._tm_coil_text.tag_config("warn", foreground=_TAG_WARN)

            guide = ttk.Label(t, style="Muted.TLabel", wraplength=880, justify="left")
            guide.pack(anchor="w")
            self._reg(guide, "ut_tm_guide")

        # ── Transmatch construction drawing (PNG) ─────────────────────────

        def _build_tm_diagram(self, parent):
            """Constructional PNG of the coil, shown right of the tap table."""
            box = ttk.LabelFrame(parent, padding=6)
            # Same fix as _build_ut_diagram: expand=True made this box
            # claim all leftover width in the scrollable page instead of
            # sizing to its own (wrapped) content.
            box.pack(side="left", fill="y", padx=(12, 0))
            self._reg(box, "ut_tm_dia_lf")

            self._tm_dia_path = None          # last PNG written on disk
            self._tm_dia_img = None           # keep a reference alive for Tk
            self._tm_dia_sig = None           # avoid useless re-renders

            self._tm_dia_lbl = tk.Label(box, bg=_ENTRY_BG, bd=1, relief="solid",
                                        cursor="hand2", justify="center",
                                        fg=_FG, wraplength=260, padx=10, pady=40,
                                        text=self.t("ut_tm_dia_empty"))
            self._tm_dia_lbl.pack(fill="both", expand=True)
            self._tm_dia_lbl.bind("<Button-1>", lambda _e: self._tm_dia_zoom())

            bar = ttk.Frame(box)
            bar.pack(fill="x", pady=(6, 0))
            self._tm_dia_upd_btn = ttk.Button(bar, style="Accent.TButton",
                                              command=self._tm_dia_update)
            self._tm_dia_upd_btn.pack(side="left")
            self._reg(self._tm_dia_upd_btn, "ut_tm_dia_upd")
            self._tm_dia_btn = ttk.Button(bar, style="Browse.TButton",
                                          command=self._tm_dia_save_as)
            self._tm_dia_btn.pack(side="left", padx=(6, 0))
            self._reg(self._tm_dia_btn, "ut_tm_dia_save")
            self._tm_dia_hint = ttk.Label(box, style="Muted.TLabel",
                                          wraplength=280, justify="left")
            self._tm_dia_hint.pack(anchor="w", pady=(4, 0))
            self._reg(self._tm_dia_hint, "ut_tm_dia_click")

            self._tm_dia_file = ttk.Label(box, style="Muted.TLabel",
                                          wraplength=430, justify="left")
            self._tm_dia_file.pack(anchor="w", pady=(2, 0))

        def _tm_dia_outpath(self) -> str:
            """Where the PNG lives: the optimizer output directory if usable."""
            outdir = ""
            try:
                outdir = self._outdir_var.get().strip()
            except Exception:
                outdir = ""
            outdir = outdir or os.getcwd()
            if not (os.path.isdir(outdir) and os.access(outdir, os.W_OK)):
                outdir = tempfile.gettempdir()
            return os.path.join(outdir, "transmatch_coil.png")

        def _tm_dia_mark_stale(self):
            """The page changed: flag the drawing, but never redraw on its own."""
            if not hasattr(self, "_tm_dia_lbl"):
                return
            if self._tm_dia_path and self._tm_dia_sig != self._tm_dia_signature():
                self._tm_dia_hint.config(text=self.t("ut_tm_dia_stale"))

        def _tm_dia_signature(self):
            """Fingerprint of everything the drawing depends on."""
            res = getattr(self, "_tm_result", None) or {}
            coil, tot = res.get("coil") or {}, res.get("totals") or {}
            return (self._ui_lang, tot.get("t_ref"), coil.get("n_total"),
                    coil.get("former_dia_mm"), coil.get("wire_dia_mm"),
                    coil.get("pitch_mm"), coil.get("z0"),
                    tuple((r.get("band"), r.get("turns"),
                           round(float(r.get("R") or 0), 2))
                          for r in res.get("taps") or []))

        def _tm_dia_update(self):
            """UPDATE DRAWING button — rebuild the PNG from the page data."""
            if not HAS_MPL:
                self._tm_dia_lbl.config(image="", text=self.t("ut_tm_dia_none"),
                                        wraplength=400, padx=10, pady=40)
                return
            if getattr(self, "_ut_job", None) is not None:
                try:                                     # apply pending edits
                    self.after_cancel(self._ut_job)
                except Exception:
                    pass
                self._ut_job = None
                self._ut_recompute()
            self._tm_dia_render()

        def _tm_dia_render(self):
            res = getattr(self, "_tm_result", None)
            if not res or not HAS_MPL:
                return
            path = self._tm_dia_outpath()
            try:
                out = transmatch_coil_png(res, path, lang=self._ui_lang, dpi=150)
            except Exception as e:                      # never kill the GUI
                self._tm_dia_lbl.config(image="", text=self.t("ut_tm_dia_err", e=e),
                                        wraplength=400, padx=10, pady=30)
                return
            if not out:
                return
            self._tm_dia_path = out
            self._tm_dia_sig = self._tm_dia_signature()
            self._tm_dia_show(out)
            self._tm_dia_hint.config(text=self.t("ut_tm_dia_click"))
            self._tm_dia_file.config(text=self.t("ut_tm_dia_file", file=out))

        def _tm_dia_show(self, path: str, max_w: int = 440, max_h: int = 300):
            """Load the PNG and fit it into the preview label."""
            try:
                img = tk.PhotoImage(file=path)
            except Exception:                            # Tk < 8.6: no PNG
                self._tm_dia_lbl.config(image="", padx=10, pady=30,
                                        wraplength=400,
                                        text=self.t("ut_tm_dia_file", file=path))
                return
            k = max(1, -(-img.width() // max_w), -(-img.height() // max_h))
            if k > 1:
                img = img.subsample(k, k)
            self._tm_dia_img = img                       # keep the reference
            self._tm_dia_lbl.config(image=img, text="", padx=0, pady=0)

        def _tm_dia_zoom(self):
            """Open the PNG at full size in its own scrollable window."""
            path = getattr(self, "_tm_dia_path", None)
            if not path or not os.path.isfile(path):
                return
            try:
                img = tk.PhotoImage(file=path)
            except Exception:
                return
            top = tk.Toplevel(self)
            top.title(self.t("ut_tm_dia_title"))
            top.configure(bg=_BG)
            cv = tk.Canvas(top, bg=_BG, highlightthickness=0,
                           width=min(img.width(), self.winfo_screenwidth() - 120),
                           height=min(img.height(), self.winfo_screenheight() - 160))
            hsb = ttk.Scrollbar(top, orient="horizontal", command=cv.xview)
            vsb = ttk.Scrollbar(top, orient="vertical", command=cv.yview)
            cv.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set,
                         scrollregion=(0, 0, img.width(), img.height()))
            cv.create_image(0, 0, image=img, anchor="nw")
            cv._img_ref = img                            # keep the reference
            cv.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            top.rowconfigure(0, weight=1)
            top.columnconfigure(0, weight=1)
            top.bind("<Escape>", lambda _e: top.destroy())

        def _tm_dia_save_as(self):
            res = getattr(self, "_tm_result", None)
            title = self.t("ut_tm_dia_lf")
            if not HAS_MPL:
                messagebox.showinfo(title, self.t("ut_tm_dia_none"))
                return
            if not res:
                return
            path = filedialog.asksaveasfilename(
                title=title, defaultextension=".png",
                initialdir=self._outdir_var.get().strip() or os.getcwd(),
                initialfile="transmatch_coil.png",
                filetypes=[("PNG image", "*.png"), ("All files", "*")])
            if not path:
                return
            try:
                transmatch_coil_png(res, path, lang=self._ui_lang, dpi=200)
                messagebox.showinfo(title, self.t("ut_tm_dia_saved", file=path))
            except Exception as e:
                messagebox.showerror(title, self.t("ut_tm_dia_err", e=e))

        # ── Recompute plumbing ────────────────────────────────────────────

        def _ut_apply_ratio_mode_state(self):
            """Enable/disable the Ratio box to match the Compensate/Ratio
            checkbox. Compensate (checked) needs no manual ratio, so the
            Ratio box is disabled; Ratio mode (unchecked) needs it, so it
            is enabled. Nothing else is disabled: R_out/X_out/R_in still
            feed the reactance-compensation and multi-band sections in
            both modes."""
            compensate = bool(self._ut_ratio_compensate_var.get())
            self._ut_ratio_val_ent.config(state="disabled" if compensate else "normal")
            if hasattr(self, "_ut_ratio_mode_lbl_upd"):
                self._ut_ratio_mode_lbl_upd()

        def _ut_on_ratio_mode_change(self):
            self._ut_apply_ratio_mode_state()
            self._ut_on_change()

        def _ut_apply_core_type_state(self):
            """Enable/disable the Toroid-core vs Air-core input boxes to
            match the Core/Air checkbox. Core (checked) uses the toroid
            dropdown, exactly as before, and disables the air-only Coil
            former diameter / Space between turns boxes. Air (unchecked)
            is the reverse: the toroid dropdown is disabled and the coil-
            geometry boxes are enabled. Everything else (frequency,
            impedances, primary turns, wire diameter, ratio mode) is used
            by both modes and is never touched here."""
            is_core = bool(self._ut_core_is_core_var.get())
            self._ut_core_cb.config(state="readonly" if is_core else "disabled")
            self._ut_coil_dia_ent.config(state="disabled" if is_core else "normal")
            self._ut_space_ent.config(state="disabled" if is_core else "normal")
            self._ut_core_info.config(text="" if not is_core else self._ut_core_info.cget("text"))
            if is_core:
                self._ut_air_note_lbl.grid_remove()
            else:
                self._ut_air_note_lbl.grid()
            if hasattr(self, "_ut_core_type_lbl_upd"):
                self._ut_core_type_lbl_upd()

        def _ut_on_core_type_change(self):
            self._ut_apply_core_type_state()
            self._ut_on_change()

        def _ut_bind_vars(self):
            """Recalculate whenever any UnUn / Transmatch input changes."""
            watched = [self._ut_freq_var, self._ut_rout_var, self._ut_xout_var,
                       self._ut_rin_var, self._ut_xin_var, self._ut_core_var,
                       self._ut_np_var, self._ut_wire_var,
                       self._ut_core_is_core_var, self._ut_coil_dia_var, self._ut_space_var,
                       self._ut_ratio_compensate_var, self._ut_ratio_val_var,
                       self._ut_mb_auto_var, self._ut_mb_kind_var,
                       self._ut_mb_val_var, self._ut_mb_ratio_var, self._ut_mb_z0_var,
                       self._tm_z0_var, self._tm_wire_var, self._tm_core_var,
                       self._tm_space_var, self._tm_tref_var, self._tm_tref_auto_var]
            watched += self._tm_band_vars + self._tm_f_vars + self._tm_r_vars
            watched += self._tm_x_vars + self._tm_act_vars
            for v in watched:
                try:
                    v.trace_add("write", self._ut_on_change)
                except AttributeError:
                    v.trace("w", lambda *_a: self._ut_on_change())

        def _ut_on_change(self, *_args):
            if self._ut_busy:
                return
            if self._ut_job is not None:
                try:
                    self.after_cancel(self._ut_job)
                except Exception:
                    pass
            self._ut_job = self.after(150, self._ut_recompute)

        def _ut_recompute(self):
            self._ut_job = None
            if not hasattr(self, "_ut_res_text") or self._ut_busy:
                return
            self._ut_busy = True
            try:
                self._ut_calc_unun()
                self._ut_calc_tm()
            except Exception as e:                       # keep the GUI alive
                self._ut_write(self._ut_res_text, f"⛔  {e}\n", "err")
            finally:
                self._ut_busy = False

        @staticmethod
        def _ut_write(widget, text: str, tag: str = ""):
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", text, tag)
            widget.config(state="disabled")

        def _ut_line(self, key: str, value: str, **kw) -> str:
            return f"  {self.t(key, **kw):<46}{value}\n"

        # ── UnUn computation ──────────────────────────────────────────────

        def _ut_calc_unun(self):
            core = self._ut_core_var.get() or DEFAULT_TOROID
            is_core = bool(self._ut_core_is_core_var.get())
            core_type = "core" if is_core else "air"
            compensate = bool(self._ut_ratio_compensate_var.get())
            fixed_ratio = (None if compensate
                           else self._ut_num(self._ut_ratio_val_var.get(), 0.0) or None)
            d = unun_design(
                freq_mhz=self._ut_num(self._ut_freq_var.get(), 7.1),
                r_in=self._ut_num(self._ut_rin_var.get(), 50.0) or 50.0,
                x_in=self._ut_num(self._ut_xin_var.get(), 0.0),
                r_out=self._ut_num(self._ut_rout_var.get(), 450.0),
                x_out=self._ut_num(self._ut_xout_var.get(), 0.0),
                core=core,
                np_turns=int(self._ut_num(self._ut_np_var.get(), 15) or 15),
                wire_dia_mm=self._ut_num(self._ut_wire_var.get(), 2.0) or 2.0,
                fixed_ratio=fixed_ratio,
                core_type=core_type,
                coil_dia_mm=self._ut_num(self._ut_coil_dia_var.get(), 50.0) or 50.0,
                space_mm=self._ut_num(self._ut_space_var.get(), 1.0),
            )
            self._ut_design = d
            if is_core:
                cd = TOROID_DB.get(core, {})
                self._ut_core_info.config(
                    text=f"{cd.get('material', '')} · AL {cd.get('AL', 0):.0f} nH/N² · "
                         f"OD {cd.get('OD', 0)} / ID {cd.get('ID', 0)} / H {cd.get('H', 0)} mm · "
                         f"Ae {cd.get('Ae', 0)} cm²")
            else:
                self._ut_core_info.config(text="")

            f = self._ut_fmt
            comp_name = {"L": "ut_r_ind", "C": "ut_r_cap"}.get(d["comp_kind"], "ut_r_none")
            lines = []
            lines.append(f"  {self.t('ut_r_sec2')}\n")
            ratio_label = "ut_r_ratio_fixed" if d.get("ratio_mode") == "fixed" else "ut_r_ratio"
            lines.append(self._ut_line(ratio_label,      f"{f(d['ratio'], 2)} : 1"))
            lines.append(self._ut_line("ut_r_tratio",   f(d["turns_ratio"], 3)))
            lines.append(self._ut_line("ut_r_nscalc",   f(d["ns_calc"], 2)))
            lines.append(self._ut_line("ut_r_ns",       f"{d['ns']}"))
            if d.get("max_turns") is None:
                lines.append(self._ut_line("ut_r_maxturns", self.t("ut_st_na")))
            else:
                lines.append(self._ut_line("ut_r_maxturns",
                                           f"{d['max_turns']}    "
                                           f"{self.t('ut_st_ns_ok') if d['turns_ok'] else self.t('ut_st_ns_err')}"))
            lines.append(self._ut_line("ut_r_ratioact", f"{f(d['ratio_actual'], 2)} : 1"))
            lines.append(self._ut_line("ut_r_xtrans",   f"{f(d['x_transformed'], 2)} Ω"))
            lines.append("\n")
            lines.append(f"  {self.t('ut_r_sec21')}\n")
            lines.append(self._ut_line("ut_r_nt",       f"{d['n_total']}"))
            lines.append(self._ut_line("ut_r_ntap",     f"{d['n_tap']}"))
            # A negative n_above only ever occurs when winding_code == "warn"
            # (r_out <= r_in: the autotransformer tap would have to sit above
            # the total winding, which is not buildable). Showing "-3 turns"
            # in that case reads as a usable spec; show the warning instead.
            if d.get("winding_code") == "warn":
                lines.append(self._ut_line("ut_r_nabove", self.t("ut_st_wind_warn")))
            else:
                lines.append(self._ut_line("ut_r_nabove", f"{d['n_above']}"))
            lines.append(self._ut_line("ut_r_ratiochk", f"{f(d['ratio_check'], 2)} : 1"))
            lines.append(self._ut_line("ut_r_wpt",      f"{f(d['wire_per_turn_m'], 3)} m"))
            lines.append(self._ut_line("ut_r_wtot",     f"{f(d['wire_total_m'], 2)} m"))
            lines.append("\n")
            lines.append(f"  {self.t('ut_r_sec3')}\n")
            lines.append(self._ut_line("ut_r_xcomp",    f"{f(d['x_comp'], 2)} Ω"))
            lines.append(self._ut_line("ut_r_ctype",    self.t(comp_name)))
            lines.append(self._ut_line("ut_r_cval",     f"{f(d['comp_value'], 2)} {d['comp_unit']}"))
            lines.append(self._ut_line("ut_r_cstd",     f"{f(d['comp_std'], 1)} {d['comp_unit']}"))
            lines.append("\n")
            lines.append(f"  {self.t('ut_r_sec4')}\n")
            if is_core:
                lines.append(self._ut_line("ut_r_al",       f"{f(d['al'], 1)} nH/N²"))
            lines.append(self._ut_line("ut_r_lp",       f"{f(d['lp_uh'], 2)} µH"))
            lines.append(self._ut_line("ut_r_xlp",      f"{f(d['xlp'], 1)} Ω"))
            lines.append(self._ut_line("ut_r_check",
                                       self.t("ut_st_mag_ok") if d["mag_ok"]
                                       else self.t("ut_st_mag_warn")))
            lines.append("\n")
            if is_core:
                lines.append(f"  {self.t('ut_r_sec5')}\n")
                lines.append(self._ut_line("ut_r_ae",       f"{f(d['ae_cm2'], 2)} cm²"))
                lines.append(self._ut_line("ut_r_bmax",     f"{f(d['b_max_mt'], 0)} mT"))
                lines.append(self._ut_line("ut_r_vpeak",    f"{f(d['v_peak'], 1)} V pico"))
                lines.append(self._ut_line("ut_r_pavg",     f"{f(d['p_sat'], 0)} W"))
                if d.get("p_thermal") is not None:
                    lines.append(self._ut_line(
                        "ut_r_mu", f"{f(d['mu_prime'], 1)} / {f(d['mu_dprime'], 1)}"))
                    lines.append(self._ut_line("ut_r_qcore", f(d["q_core"], 2)))
                    lines.append(self._ut_line("ut_r_rp",    f"{f(d['rp_core'], 0)} Ω"))
                    lines.append(self._ut_line("ut_r_loss",  f"{f(d['loss_pct'], 2)} %"))
                    lines.append(self._ut_line("ut_r_surf",  f"{f(d['a_surf_cm2'], 1)} cm²"))
                    lines.append(self._ut_line("ut_r_pdiss",
                                               f"{f(d['p_diss_w'], 2)} W",
                                               dt=d["delta_t_c"]))
                    lines.append(self._ut_line("ut_r_pther", f"{f(d['p_thermal'], 0)} W"))
                else:
                    lines.append(self._ut_line("ut_r_mu", self.t("ut_st_mu_na")))
                lim_key = ("ut_st_lim_flux" if d["p_limited_by"] == "flux"
                           else "ut_st_lim_heat")
                lines.append(self._ut_line(
                    "ut_r_pmax", f"{f(d['p_max'], 0)} W    ({self.t(lim_key)})"))
                sat_key = {"high": "ut_st_sat_high", "ok": "ut_st_sat_ok",
                           "limited": "ut_st_sat_lim",
                           "unknown": "ut_st_sat_unk"}.get(d["power_code"], "ut_st_sat_ins")
                lines.append(self._ut_line("ut_r_sat", self.t(sat_key)))
            else:
                lines.append(f"  {self.t('ut_r_sec5')}\n")
                lines.append(f"  {self.t('ut_st_sec5_na')}\n")
            self._ut_unun_txt = "".join(lines)
            self._ut_write(self._ut_res_text, self._ut_unun_txt)

            # ── Section 6: multi-band compensation ─────────────────────
            auto = bool(self._ut_mb_auto_var.get())
            state = "disabled" if auto else "normal"
            self._ut_mb_kind_cb.config(state="disabled" if auto else "readonly")
            self._ut_mb_val_ent.config(state=state)
            self._ut_mb_ratio_ent.config(state=state)
            if auto:
                self._ut_mb_kind_var.set(d["comp_kind"] if d["comp_kind"] != "none" else "none")
                self._ut_mb_val_var.set(f"{d['comp_std']:g}" if d["comp_std"] else "0")
                self._ut_mb_ratio_var.set(f"{d['ratio_actual']:.2f}")
            kind = self._ut_mb_kind_var.get()
            self._ut_mb_unit_lbl.config(text={"L": "µH", "C": "pF"}.get(kind, "—"))

            bands = self._ant_bands or [{
                "band": self._ut_band_var.get() or "—",
                "freq_mhz": d["freq_mhz"], "R": d["r_out"], "X": d["x_out"],
                "active": True}]
            rows = unun_multiband(
                bands, kind,
                self._ut_num(self._ut_mb_val_var.get(), 0.0),
                self._ut_num(self._ut_mb_ratio_var.get(), d["ratio_actual"]) or 1.0,
                self._ut_num(self._ut_mb_z0_var.get(), 50.0) or 50.0)
            self._ut_mb_rows = rows
            self._ut_mb_tree.delete(*self._ut_mb_tree.get_children())
            for r in rows:
                self._ut_mb_tree.insert("", "end", values=(
                    r["band"], f(r["freq_mhz"], 3), f(r["R"], 1), f(r["X"], 1),
                    f(r["x_comp"], 1),
                    f"{f(r['z_in_r'], 1)} {'+' if r['z_in_x'] >= 0 else '−'}j{f(abs(r['z_in_x']), 1)}",
                    f(r["vswr_plain"], 2), f(r["vswr_comp"], 2), f(r["delta"], 2)))
            self._ut_dia_mark_stale()

        # ── Transmatch computation ────────────────────────────────────────

        def _ut_calc_tm(self):
            taps = []
            for i in range(11):
                taps.append({
                    "band": self._tm_band_vars[i].get().strip() or f"#{i + 1}",
                    "freq_mhz": self._ut_num(self._tm_f_vars[i].get(), 0.0),
                    "R": self._ut_num(self._tm_r_vars[i].get(), 0.0),
                    "X": self._ut_num(self._tm_x_vars[i].get(), 0.0),
                    "active": bool(self._tm_act_vars[i].get()),
                })
            auto = bool(self._tm_tref_auto_var.get())
            self._tm_tref_ent.config(state="disabled" if auto else "normal")
            tref = None if auto else int(self._ut_num(self._tm_tref_var.get(), 0) or 0)
            res = transmatch_design(
                taps,
                z0=self._ut_num(self._tm_z0_var.get(), 50.0) or 50.0,
                wire_dia_mm=self._ut_num(self._tm_wire_var.get(), 1.0) or 1.0,
                core_dia_mm=self._ut_num(self._tm_core_var.get(), 50.0) or 50.0,
                space_mm=self._ut_num(self._tm_space_var.get(), 1.0),
                t_ref=tref)
            self._tm_result = res
            tot, coil = res["totals"], res["coil"]
            self._tm_tref_hint.config(text=self.t("ut_tm_tref_hint", n=tot["t_ref_auto"]))
            if auto:
                self._tm_tref_var.set(str(tot["t_ref"]))

            f = self._ut_fmt
            self._tm_tree.delete(*self._tm_tree.get_children())
            for r in res["taps"]:
                self._tm_tree.insert("", "end", values=(
                    r["band"], f(r["freq_mhz"], 3),
                    f(r["R"], 1), f(r["r_real"], 1), f(r["r_err_pct"], 2),
                    f(r["turns_ratio"], 3),
                    r["turns"], r["d_turns"], f(r["sec_wire_mm"], 1),
                    f(r["sec_rdc_mohm"], 2), f(r["cum_wire_mm"], 1),
                    f(r["z_mag"], 1), f(r["phase_deg"], 2), f(r["swr"], 3),
                    f(r["return_loss_db"], 2), f(r["mismatch_db"], 3),
                    f(r["refl_pct"], 2)))
            self._tm_ctree.delete(*self._tm_ctree.get_children())
            for r in res["taps"]:
                self._tm_ctree.insert("", "end", values=(
                    r["band"], f(r["freq_mhz"], 3), f(r["R"], 1), f(r["X"], 1),
                    f(r["x_transformed"], 2),
                    f(r["ser_l_nh"], 0), f(r["ser_c_e24"], 0),
                    f(r["sh_l_nh"], 0), f(r["sh_c_e24"], 0),
                    f(r["swr_5pct"], 3)))

            lines = [
                self._ut_line("utk_pitch", f(coil["pitch_mm"], 2)),
                self._ut_line("utk_n",     f"{coil['n_total']}"),
                self._ut_line("utk_len",   f"{f(coil['win_len_mm'], 1)} mm  "
                                           f"({f(coil['win_len_in'], 3)} in)"),
                self._ut_line("utk_rad",   f"{f(coil['radius_mm'], 2)} mm  "
                                           f"({f(coil['radius_in'], 3)} in)"),
                self._ut_line("utk_l",     f"{f(coil['l_uh'], 3)} µH"),
                self._ut_line("utk_xl",    f"{f(coil['x_l'], 1)} Ω  @ "
                                           f"{f(coil['f_min_mhz'], 3)} MHz"),
                self._ut_line("utk_lmin",  f"{f(coil['l_min_uh'], 3)} µH"),
                self._ut_line("utk_lok",   self.t("utk_yes") if coil["l_ok"]
                                           else self.t("utk_no")),
                "\n",
                # Self-resonance: the winding only works as an autotransformer
                # below its own SRF, so it is reported next to the inductance.
                self._ut_line("utk_cself", f"{f(coil['c_self_pf'], 2)} pF"),
                self._ut_line("utk_srf",   f"{f(coil['srf_mhz'], 3)} MHz"),
                self._ut_line("utk_srfneed",
                              f"{f(coil['srf_needed_mhz'], 3)} MHz",
                              m=f"{coil['srf_margin']:g}",
                              f=f(coil["f_max_mhz"], 3)),
                self._ut_line("utk_nsrf",  f"{coil['n_srf_max']}"),
                self._ut_line("utk_srfok", self.t("utk_yes") if coil["srf_ok"]
                                           else self.t("utk_srf_no")),
                self._ut_line("utk_xwind", f"{f(coil['x_wind_total_ohm'], 0)} Ω  @ "
                                           f"{f(coil['f_max_mhz'], 3)} MHz"),
                "\n",
                self._ut_line("utk_wire",  f"{f(tot['total_wire_mm'], 1)} mm"),
                self._ut_line("utk_rdc",   f"{f(tot['total_rdc_mohm'], 2)} mΩ"),
            ]
            if tot.get("srf_cap_applied"):
                lines.append("\n  " + self.t("utk_srf_cap", n=tot["t_ref"]) + "\n")
            if not coil["srf_ok"]:
                lines.append("\n  " + self.t(
                    "utk_srf_bad",
                    srf=f(coil["srf_mhz"], 3),
                    need=f(coil["srf_needed_mhz"], 3),
                    b=", ".join(coil["bands_above_srf"]) or "—") + "\n")
                if coil["n_srf_max"] and tot.get("t_ref_floor", 0) \
                        and coil["n_total"] > coil["n_srf_max"]:
                    lines.append("  " + self.t("utk_srf_floor",
                                               n=tot["t_ref_floor"]) + "\n")
            if coil["shunt_warn_bands"]:
                lines.append("\n  " + self.t(
                    "utk_shunt_bad",
                    r=f"{coil['shunt_ratio_min']:g}",
                    b=", ".join(coil["shunt_warn_bands"])) + "\n")
            # The SMALLEST n_above belongs to the highest tap: that is how much
            # winding is left hanging open above every tap.
            _n_above_top = min((int(r.get("n_above") or 0) for r in res["taps"]),
                               default=0)
            if _n_above_top > 0:
                lines.append("\n  " + self.t("utk_above", n=_n_above_top) + "\n")
            self._tm_coil_txt = "".join(lines)
            self._ut_write(self._tm_coil_text, self._tm_coil_txt,
                           "ok" if coil["coil_ok"] else "warn")
            self._tm_dia_mark_stale()

        # ── Antenna data plumbing ─────────────────────────────────────────

        def _ut_set_band_fields(self, band: dict):
            self._ut_freq_var.set(f"{float(band['freq_mhz']):.3f}")
            self._ut_rout_var.set(f"{float(band['R']):.2f}")
            self._ut_xout_var.set(f"{float(band['X']):.2f}")

        def _ut_apply_band(self, _event=None):
            name = self._ut_band_var.get()
            band = next((b for b in self._ant_bands if b["band"] == name), None)
            if not band:
                return
            self._ut_busy = True
            try:
                self._ut_set_band_fields(band)
            finally:
                self._ut_busy = False
            self._ut_recompute()

        def _load_antenna_data(self, silent: bool = True):
            """Fill the UnUn / Transmatch inputs from the optimizer CSV."""
            if not hasattr(self, "_ut_band_cb"):
                return
            outdir = self._outdir_var.get().strip() or os.getcwd()
            name = self._out_csv_var.get().strip() or "optimizer_best.csv"
            path = os.path.join(outdir, name)
            title = self.t("tab_ut").strip()
            if not os.path.isfile(path):
                if not silent:
                    messagebox.showinfo(title, self.t("ut_csv_missing", file=path))
                return
            try:
                bands, ratio = load_band_impedances_csv(path)
            except Exception as e:
                if not silent:
                    messagebox.showerror(title, self.t("ut_load_err", e=e))
                return
            if not bands:
                return
            self._ant_bands = bands
            self._ant_unun_ratio = ratio
            self._ut_band_cb.config(values=[b["band"] for b in bands])
            first = next((b for b in bands if b["active"]), bands[0])
            actives = [b for b in bands if b["active"]] or bands

            self._ut_busy = True
            try:
                self._ut_band_var.set(first["band"])
                self._ut_set_band_fields(first)
                for i in range(11):
                    if i < len(actives):
                        b = actives[i]
                        self._tm_band_vars[i].set(str(b["band"]))
                        self._tm_f_vars[i].set(f"{float(b['freq_mhz']):.3f}")
                        self._tm_r_vars[i].set(f"{float(b['R']):.2f}")
                        self._tm_x_vars[i].set(f"{float(b['X']):.2f}")
                        self._tm_act_vars[i].set(True)
                    else:
                        self._tm_band_vars[i].set("")
                        self._tm_f_vars[i].set("")
                        self._tm_r_vars[i].set("")
                        self._tm_x_vars[i].set("")
                        self._tm_act_vars[i].set(False)
                self._ut_status_key = "ut_loaded"
                self._ut_status_kw = {"n": len(bands), "file": os.path.basename(path)}
                self._ut_status_upd()
            finally:
                self._ut_busy = False
            self._ut_recompute()

        def _ut_export(self):
            path = filedialog.asksaveasfilename(
                title=self.t("ut_export_btn").strip(),
                defaultextension=".txt",
                initialdir=self._outdir_var.get().strip() or os.getcwd(),
                initialfile="unun_transmatch.txt",
                filetypes=[("Text file", "*.txt"), ("All files", "*")])
            if not path:
                return
            f = self._ut_fmt
            out = ["=" * 78, "  UNUN / TRANSMATCH", "=" * 78, "",
                   getattr(self, "_ut_unun_txt", ""), "",
                   f"  {self.t('ut_mb_lf')}", "-" * 78]
            for r in getattr(self, "_ut_mb_rows", []):
                out.append(f"  {r['band']:<8}{f(r['freq_mhz'], 3):>10} MHz   "
                           f"R={f(r['R'], 1):>8}  X={f(r['X'], 1):>8}  "
                           f"Xc={f(r['x_comp'], 1):>8}   "
                           f"VSWR {f(r['vswr_plain'], 2)} → {f(r['vswr_comp'], 2)}")
            out += ["", f"  {self.t('ut_sub_tm').strip()}", "-" * 78]
            for r in (getattr(self, "_tm_result", {}) or {}).get("taps", []):
                out.append(f"  {r['band']:<8}{f(r['freq_mhz'], 3):>10} MHz   "
                           f"R={f(r['R'], 1):>8} → {f(r['r_real'], 1):>8} Ω "
                           f"({f(r['r_err_pct'], 2)} %)  "
                           f"n={f(r['turns_ratio'], 3)}  N={r['turns']:>3}  "
                           f"SWR={f(r['swr'], 3)}  RL={f(r['return_loss_db'], 2)} dB  "
                           f"L={f(r['ser_l_nh'], 0)} nH  C={f(r['ser_c_e24'], 0)} pF")
            out += ["", getattr(self, "_tm_coil_txt", "")]
            png = os.path.splitext(path)[0] + "_transmatch.png"
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(out))
                if HAS_MPL and getattr(self, "_tm_result", None):
                    try:
                        transmatch_coil_png(self._tm_result, png,
                                            lang=self._ui_lang, dpi=200)
                    except Exception:
                        pass
                messagebox.showinfo(self.t("tab_ut").strip(),
                                    self.t("ut_export_done", file=path))
            except Exception as e:
                messagebox.showerror(self.t("tab_ut").strip(), str(e))

        # ── Browse helpers ────────────────────────────────────────────────

        def _browse_script(self):
            p = filedialog.askopenfilename(
                title="Select nec2_length_optimizer.py",
                filetypes=[("Python script", "*.py"), ("All files", "*")])
            if p:
                self._script_var.set(p)

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
            bands = self._bands_var.get().strip()
            if bands:
                cmd += ["--bands", bands]
            freqs = self._freqs_var.get().strip()
            if freqs:
                cmd += ["--freqs", freqs]
            wl = self._wire_len_var.get().strip()
            if wl:
                cmd += ["--wire-len", wl]
            use_cp = bool(self._use_cp_var.get())
            if not use_cp:
                cmd += ["--no-counterpoise"]
                _ret = self._no_cp_return_var.get().strip() or DEFAULT_NO_CP_RETURN
                cmd += ["--no-cp-return", _ret]
                if _ret == "coax-stub":
                    _stub = self._cp_stub_len_var.get().strip()
                    if _stub:
                        cmd += ["--cp-stub-len", _stub]
            else:
                cp = self._cp_len_var.get().strip()
                if cp:
                    cmd += ["--cp-len", cp]
            ab = self._active_bands_var.get().strip()
            if ab:
                cmd += ["--active-bands", ab]
            cmd += ["--mode", self._mode_var.get()]
            nec2c = self._nec2c_var.get().strip()
            if nec2c:
                cmd += ["--nec2c", nec2c]
            margin = self._margin_var.get().strip()
            if margin:
                cmd += ["--margin", margin]
            _range_flags = [
                ("--wire-min",  self._wire_min_var),
                ("--wire-max",  self._wire_max_var),
                ("--wire-step", self._wire_step_var),
            ]
            if use_cp:
                _range_flags += [
                    ("--cp-min",    self._cp_min_var),
                    ("--cp-max",    self._cp_max_var),
                    ("--cp-step",   self._cp_step_var),
                ]
            for flag, var in _range_flags:
                v = var.get().strip()
                if v:
                    cmd += [flag, v]
            retry = self._retry_var.get().strip()
            if retry and retry != "0":
                cmd += ["--retry", retry]
            topn = self._topn_var.get().strip()
            if topn:
                cmd += ["--top-n", topn]
            h = self._height_var.get().strip()
            if h:
                cmd += ["--height", h]
            slope = self._wire_slope_end_var.get().strip()
            if slope:
                cmd += ["--wire-slope-end-height", slope]
            cp_end = self._cp_end_height_var.get().strip()
            if use_cp and cp_end:
                cmd += ["--cp-end-height", cp_end]
            _gm = self._ground_model_var.get().strip()
            if _gm and _gm != DEFAULT_GROUND_MODEL:
                cmd += ["--ground-model", _gm]
            _sm = self._segs_mode_var.get().strip()
            if _sm == "fast":
                cmd += ["--fast"]
            elif _sm == "custom":
                _sv = self._segs_custom_var.get().strip()
                if _sv:
                    cmd += ["--segs-per-half-wave", _sv]
            if self._converge_var.get():
                cmd += ["--converge"]
            _tt = self._target_toa_var.get().strip()
            if _tt and _tt != f"{DEFAULT_TARGET_TOA_DEG:g}":
                cmd += ["--target-toa", _tt]
            _gw = self._gain_weight_var.get().strip()
            if _gw and _gw != f"{DEFAULT_GAIN_WEIGHT:g}":
                cmd += ["--gain-weight", _gw]
            _rt = self._rerank_top_var.get().strip()
            if _rt and _rt != str(DEFAULT_RERANK_TOP_N):
                cmd += ["--rerank-top", _rt]
            gc = self._ground_cond_var.get().strip()
            if gc:
                cmd += ["--ground-cond", gc]
            gd = self._ground_diel_var.get().strip()
            if gd:
                cmd += ["--ground-diel", gd]
            wd = self._wire_diameter_var.get().strip()
            if wd:
                cmd += ["--wire-diameter", wd]
            wm = getattr(self, "_wire_material_key", DEFAULT_WIRE_MATERIAL)
            if wm and wm != DEFAULT_WIRE_MATERIAL:
                cmd += ["--wire-material", wm]
            wc = self._wire_conductivity_var.get().strip()
            if wc:
                cmd += ["--wire-conductivity", wc]
            for flag, var in (
                ("--out-txt",          self._out_txt_var),
                ("--out-png",          self._out_png_var),
                ("--out-csv",          self._out_csv_var),
                ("--out-nec",          self._out_nec_var),
                ("--out-radiation",    self._out_rad_var),
                ("--out-construction", self._out_construction_var),
                ("--out-pdf",          self._out_pdf_var),
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

        def _bind_auto_refresh(self):
            """Make the command preview follow every setting automatically.

            Each tk variable created by the tab builders gets a write trace, so
            typing in an entry or toggling a checkbox updates the preview with
            no button to press.  The redraw is debounced by a short timer so a
            burst of keystrokes costs one rebuild instead of one per character.
            """
            self._refresh_job = None
            self._traced_vars = getattr(self, "_traced_vars", [])
            for _attr, _val in list(vars(self).items()):
                if isinstance(_val, tk.Variable) and _val not in self._traced_vars:
                    try:
                        _val.trace_add("write", self._on_setting_changed)
                    except AttributeError:            # very old tkinter
                        _val.trace("w", lambda *_a: self._on_setting_changed())
                    self._traced_vars.append(_val)
            self._refresh_cmd()

        def _on_setting_changed(self, *_args):
            """Debounced trigger — coalesces rapid edits into one refresh."""
            if getattr(self, "_refresh_job", None) is not None:
                try:
                    self.after_cancel(self._refresh_job)
                except Exception:
                    pass
            self._refresh_job = self.after(120, self._refresh_cmd)

        def _refresh_cmd(self):
            self._refresh_job = None
            self._refresh_geom_warnings()
            if not hasattr(self, "_cmd_text"):
                return                    # preview not built yet
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
            self._show_pdf_btn.config(state="disabled")
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
                pdf_name = self._out_pdf_var.get().strip()
                report  = os.path.join(outdir, txt_name) if txt_name else None
                radfile = os.path.join(outdir, rad_name) if rad_name else None
                pdffile = os.path.join(outdir, pdf_name) if pdf_name else None
                if report and os.path.isfile(report):
                    self._show_report_btn.config(state="normal")
                if radfile and os.path.isfile(radfile):
                    self._show_radiation_btn.config(state="normal")
                if pdffile and os.path.isfile(pdffile):
                    self._show_pdf_btn.config(state="normal")
                # Feed the UnUn / Transmatch page with the freshly computed
                # antenna impedances (still editable by hand afterwards).
                self._load_antenna_data(silent=True)

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

        def _show_pdf(self):
            outdir   = self._outdir_var.get().strip() or os.getcwd()
            pdf_name = self._out_pdf_var.get().strip()
            pdffile  = os.path.join(outdir, pdf_name) if pdf_name else None
            if pdffile and os.path.isfile(pdffile):
                self._open_file(pdffile)

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
