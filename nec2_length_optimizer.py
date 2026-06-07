#!/usr/bin/env python3
"""
=============================================================================
  NEC2 Antenna Length Optimizer
  Author: based on nec2_vs_calc_analyzer.py (LU3VEA, CC0 v1.0)

  Searches for the optimal antenna wire length AND counterpoise length
  that minimise aggregate VSWR across all active bands defined in a CSV
  (same format used by nec2_vs_calc_analyzer).

  For each candidate (wire_len, cp_len) pair the script:
    1. Writes a NEC2 .nec input deck  (horizontal CP + vertical CP)
    2. Runs nec2c to produce a .out file
    3. Parses the .out with the same parser from nec2_vs_calc_analyzer
    4. Computes the aggregate score  (penalised VSWR, avoidance, CP delta)
    5. Tracks the Pareto-optimal candidates

  At the end it writes:
    • A ranked text report     (optimizer_report.txt)
    • A scatter plot PNG       (optimizer_plot.png)
    • A ready-to-use CSV       (optimizer_best.csv)  in nec2_vs_calc_analyzer format

  Usage (with CSV):
    python nec2_length_optimizer.py --csv my_bands.csv [options]

  Usage (without CSV):
    # Known bands — --freqs is optional (centre frequency auto-resolved):
    python nec2_length_optimizer.py --bands 40m,20m,15m \
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

# ── import the upstream analyser's core routines ──────────────────────────
# We import calc_empirical, load_csv, CalcRow, NEC2Run, FreqPoint and the
# parser from nec2_vs_calc_analyzer.  The file is expected beside this
# script (or on PYTHONPATH).
try:
    import importlib.util, pathlib

    def _find_analyzer():
        candidates = [
            pathlib.Path(__file__).parent / "nec2_vs_calc_analyzer.py",
            pathlib.Path.cwd() / "nec2_vs_calc_analyzer.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        # also check PYTHONPATH entries
        for p in sys.path:
            c = pathlib.Path(p) / "nec2_vs_calc_analyzer.py"
            if c.exists():
                return c
        return None

    _analyzer_path = _find_analyzer()
    if _analyzer_path is None:
        raise ImportError("nec2_vs_calc_analyzer.py not found")

    _spec = importlib.util.spec_from_file_location("nec2_vs_calc_analyzer",
                                                     str(_analyzer_path))
    _mod  = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    calc_empirical   = _mod.calc_empirical
    load_csv         = _mod.load_csv
    parse_nec2_output= _mod.parse_nec2_output
    CalcRow          = _mod.CalcRow
    NEC2Run          = _mod.NEC2Run
    FreqPoint        = _mod.FreqPoint
    # NOTE: _avoidance_score is intentionally NOT imported — this optimizer
    # computes avoidance inline in score_candidate using the corrected formula
    # (distance to nearest λ/4 multiple, max = 0.125).  The upstream function
    # uses a different formula and different thresholds.
    _avoidance_rating= _mod._avoidance_rating
    VSWR_THRESHOLDS  = _mod.VSWR_THRESHOLDS
    ANALYZER_PATH    = str(_analyzer_path)

except ImportError as _e:
    print(f"\n{Fore.RED}ERROR: cannot import nec2_vs_calc_analyzer: {_e}")
    print("       Place nec2_vs_calc_analyzer.py in the same directory as this script")
    print(f"       or add its directory to PYTHONPATH.{Style.RESET_ALL}")
    sys.exit(1)


# Override the imported _avoidance_rating with thresholds calibrated for the
# corrected avoidance formula (max achievable = 0.125, midway between two λ/4
# resonances).  The upstream analyzer uses the old formula (max ≈ 0.25–0.50)
# so its thresholds (≥0.20 = EXCELLENT) are unreachable here and must be
# replaced.  New thresholds:
#   ≥ 0.10  → ★★★ EXCELLENT   (≥ 80 % of max)
#   ≥ 0.06  → ★★  GOOD
#   ≥ 0.03  → ★   MARGINAL
#   < 0.03  → ✗   RESONANCE RISK
def _avoidance_rating(score: float) -> str:
    if score >= 0.10:
        return "★★★ EXCELLENT"
    elif score >= 0.06:
        return "★★  GOOD"
    elif score >= 0.03:
        return "★   MARGINAL"
    else:
        return "✗   RESONANCE RISK"


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
# Used when --bands is given without --freqs.
# Keys are accepted case-insensitively and with or without the trailing 'm'.
# Covers all ITU amateur HF bands plus the most common VHF/UHF bands.
# Each value is the band's nominal centre frequency used by the optimizer;
# the user can always override any individual frequency with --freqs.
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
    # VHF / UHF (less common for long-wire, included for completeness)
    "4m":   70.200,
    "2m":  144.200,
    "70cm": 432.100,
    "23cm": 1296.200,
}

def _lookup_band_freq(name: str) -> Optional[float]:
    """
    Return the centre frequency in MHz for a named amateur band.

    Accepts the band name case-insensitively and with or without the
    trailing 'm' (e.g. '40m', '40M', '40', '2200m' all work).
    Returns None when the name is not in the table.
    """
    key = name.strip().lower()
    if key in BAND_CENTRE_FREQ_MHZ:
        return BAND_CENTRE_FREQ_MHZ[key]
    # Try appending 'm' if the user omitted it (e.g. '40' → '40m')
    if key + "m" in BAND_CENTRE_FREQ_MHZ:
        return BAND_CENTRE_FREQ_MHZ[key + "m"]
    return None


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

    # 1. Explicit
    if explicit:
        r = _check(explicit)
        if r:
            return r
        print(f"{Fore.RED}  --nec2c path not found or not executable: {explicit}{Style.RESET_ALL}")

    # 2. Environment variable
    env_path = os.environ.get("NEC2C", "")
    r = _check(env_path)
    if r:
        print(f"  {Fore.CYAN}nec2c found via $NEC2C → {r}{Style.RESET_ALL}")
        return r

    # 3. PATH
    for name in NEC2C_NAMES:
        r = shutil.which(name)
        if r:
            print(f"  {Fore.CYAN}nec2c found on PATH → {r}{Style.RESET_ALL}")
            return r

    # 4. Hard-coded paths
    for p in NEC2C_SEARCH_PATHS:
        r = _check(p)
        if r:
            print(f"  {Fore.CYAN}nec2c found → {r}{Style.RESET_ALL}")
            return r

    # 5. Interactive prompt
    if interactive:
        print(f"\n{Fore.YELLOW}  nec2c binary not found automatically.{Style.RESET_ALL}")
        print("  Options:")
        print("    • Install:  sudo apt install nec2c   (Debian/Ubuntu)")
        print("    •           brew install nec2c        (macOS / Homebrew)")
        print("    • Re-run with:  --nec2c /full/path/to/nec2c")
        print("    • Set env var:  export NEC2C=/full/path/to/nec2c")
        ans = input(f"\n{Fore.CYAN}  Enter path to nec2c binary (or press Enter to skip NEC2 runs): {Style.RESET_ALL}").strip()
        if ans:
            r = _check(ans)
            if r:
                return r
            print(f"{Fore.RED}  Path not found or not executable: {ans}{Style.RESET_ALL}")
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
    return n if n % 2 == 1 else n + 1   # keep odd for numerical stability


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
    junction where Wire 1 meets the counterpoise).  This is correct for an
    end-fed long-wire: the feed/UnUn sits at x=0 where the CP connects,
    and the wire extends away from it to x = wire_len_m.
    """
    highest_f = max(freqs_mhz)
    segs_ant = _segs(wire_len_m, highest_f)
    segs_cp  = max(5, _segs(cp_len_m, highest_f))

    with open(nec_path, "w") as fh:
        fh.write(f"CM NEC2 Long Wire Optimizer Deck\n")
        fh.write(f"CM Wire length: {wire_len_m:.3f} m\n")
        fh.write(f"CM Counterpoise ({cp_type}): {cp_len_m:.3f} m  height: {cp_height_m:.2f} m\n")
        fh.write("CE\n")

        # Wire 1: antenna  (source at seg 1 = near end at x=0)
        fh.write(f"GW 1 {segs_ant} "
                 f"0.0 0.0 {wire_height_m:.3f} "
                 f"{wire_len_m:.3f} 0.0 {wire_height_m:.3f} "
                 f"{wire_radius_m:.5f}\n")

        # Wire 2: counterpoise
        if cp_type == "horizontal":
            drop_len = wire_height_m - cp_height_m
            if drop_len > 0.01:
                segs_drop = max(5, _segs(drop_len, highest_f))
                # GW 2: vertical drop — connects feedpoint to CP height
                fh.write(f"GW 2 {segs_drop} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
                # GW 3: horizontal CP wire at cp_height_m
                fh.write(f"GW 3 {segs_cp} "
                         f"0.0 0.0 {cp_height_m:.3f} "
                         f"{-cp_len_m:.3f} 0.0 {cp_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
            else:
                # Feedpoint already at (or below) cp_height_m — no drop needed,
                # just extend the CP horizontally from the feedpoint.
                fh.write(f"GW 2 {segs_cp} "
                         f"0.0 0.0 {wire_height_m:.3f} "
                         f"{-cp_len_m:.3f} 0.0 {wire_height_m:.3f} "
                         f"{wire_radius_m:.5f}\n")
        else:  # vertical
            # Drop cp_len_m from the feed point downward, but never go below
            # cp_height_m (minimum ground clearance).  When cp_len_m is longer
            # than the available drop (wire_height_m - cp_height_m) the wire
            # bends horizontally at cp_height_m to use the remaining length —
            # i.e. it becomes an L-shaped wire in the NEC2 deck.
            cp_bottom_z = max(cp_height_m, wire_height_m - cp_len_m)
            vert_len    = wire_height_m - cp_bottom_z        # actual vertical drop
            horiz_rem   = cp_len_m - vert_len                # remainder, if any
            # Segment count for the vertical drop must be sized for vert_len,
            # NOT for the full cp_len_m.  Using cp_len_m over-segments the
            # vertical portion when the CP bends into an L-shape, producing
            # an incorrect segment density that can degrade NEC2 accuracy.
            segs_cp_v = max(5, _segs(vert_len, highest_f))
            if segs_cp_v % 2 == 0:
                segs_cp_v += 1
            fh.write(f"GW 2 {segs_cp_v} "
                     f"0.0 0.0 {wire_height_m:.3f} "
                     f"0.0 0.0 {cp_bottom_z:.3f} "
                     f"{wire_radius_m:.5f}\n")
            # If cp_len > available vertical drop, add horizontal extension (wire 3)
            if horiz_rem > 0.01:
                segs_cp_h = max(3, _segs(horiz_rem, highest_f))
                if segs_cp_h % 2 == 0:
                    segs_cp_h += 1
                fh.write(f"GW 3 {segs_cp_h} "
                         f"0.0 0.0 {cp_bottom_z:.3f} "
                         f"{-horiz_rem:.3f} 0.0 {cp_bottom_z:.3f} "
                         f"{wire_radius_m:.5f}\n")

        fh.write("GE 0\n")           # no image ground plane; Sommerfeld-Norton via GN 2

        # Ground (Sommerfeld-Norton)
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")

        # Excitation: segment 1 of Wire 1 — the near-end segment at x=0, which is
        # the feedpoint junction where the antenna wire meets the counterpoise.
        # Wire 1 runs from x=0 (seg 1) to x=wire_len_m (seg segs_ant).
        # Placing EX at seg 1 puts the voltage source in the middle of that
        # segment, which is the standard NEC2 end-feed modeling approach.
        fh.write("EX 0 1 1 0 1.0 0.0\n")

        # Frequency sweep — FR + XQ + minimal RP idiom per frequency.
        #
        # Root cause of NEC2-MISS: sequential FR cards alone do NOT guarantee
        # a per-frequency "ANTENNA INPUT PARAMETERS" block in .out.  Many
        # nec2c builds only print the impedance block at program end (= last
        # frequency only), so all earlier bands are silently missed.
        #
        # Two-card fix applied after every FR:
        #   XQ  — "execute": tells NEC2 to print ANTENNA INPUT PARAMETERS for
        #          the current frequency RIGHT NOW, before the next FR.  Zero
        #          radiation-pattern overhead.  The correct NEC2 idiom for
        #          per-frequency impedance flushing.
        #   RP 0 1 1 0 90.0 0.0 0.0 0.0
        #       — single elevation point (90°) pattern card used as a
        #          belt-and-suspenders fallback for parsers that only
        #          recognise RP-triggered output blocks.  Costs one pattern
        #          point per frequency (~negligible vs. 37-point RP).
        #
        # Together these two cards make impedance output universal across
        # all nec2c versions and all downstream parsers.
        for f in freqs_mhz:
            fh.write(f"FR 0 1 0 0 {f:.4f} 0\n")
            fh.write("XQ\n")                          # flush impedance output
            fh.write("RP 0 1 1 0 90.0 0.0 0.0 0.0\n") # 1-point RP fallback
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
    score_vswr:      float = 999.0   # weighted mean VSWR penalty across active bands (mean only, for reporting)
    score_vswr_raw:  float = 999.0   # mean + 1.5*worst VSWR penalty (no avoidance bonuses) — used for Pareto
    score_avoidance: float = 0.0     # mean avoidance score over ALL bands (higher = better; used in score_combined)
    score_avoidance_active: float = 0.0  # mean avoidance score over ACTIVE bands only (used for Pareto axis)
    score_combined:  float = 999.0   # final combined score

    nec2_ok:    bool = True          # False = NEC2 run failed → empirical only
    note:       str  = ""


def _vswr_score_single(vswr: float) -> float:
    """
    Map a VSWR value to a penalty score:
      ≤1.5 → 0, ≤3.0 → linear 0-1, ≤6.0 → linear 1-3, >6 → 3 + log
    """
    if vswr <= 1.5:
        return 0.0
    elif vswr <= 3.0:
        return (vswr - 1.5) / 1.5           # 0 … 1
    elif vswr <= 6.0:
        return 1.0 + (vswr - 3.0) / 1.5     # 1 … 3
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
      A wire that sits at resonance on an inactive band is still penalised,
      because the geometry affects the whole spectrum even if the operator
      does not transmit on that band.

    If NEC2 run results are provided they are used; otherwise the empirical
    formulas from nec2_vs_calc_analyzer are used as a fast fallback —
    UNLESS nec2_strict=True, in which case any band whose frequency is not
    found in the NEC2 output is marked as failed (VSWR=999, nec2_ok=False)
    rather than silently falling back to the empirical model.
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

        # ── VSWR: prefer NEC2 H-CP, then V-CP ──────────────────────────
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
            # Adaptive tolerance: 4% of target frequency, clamped to [0.15, 0.75] MHz.
            # This avoids cross-band contamination when many bands are active while
            # still accommodating minor NEC2 output rounding on any band.
            _tol = max(0.15, min(0.75, 0.04 * freq))
            if abs(key - freq) > _tol:
                continue
            fp = fmap[key]
            R_ant, X_ant = fp.R_ohm, fp.X_ohm
            # Always compute VSWR through the UnUn via the reflection-coefficient
            # formula so that R_tx/X_tx and VSWR are always mutually consistent.
            if unun_ratio > 1.0:
                R_in = R_ant / unun_ratio
                X_in = X_ant / unun_ratio
            else:
                R_in, X_in = R_ant, X_ant
            g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
            v = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
            if best_vswr is None or v < best_vswr:
                best_vswr = v
                best_R, best_X = R_ant, X_ant
                imp_src = src_tag

        # ── Fallback: empirical model (only when nec2_strict is False) ──
        if best_vswr is None:
            if nec2_strict:
                # NEC2 data missing for this band — mark as failed, do NOT
                # substitute empirical values.  Use math.nan as the R/X sentinel
                # so that find_best_unun can reliably distinguish a genuine
                # NEC2-MISS from a real near-zero-R impedance (which R=0,X=0
                # would ambiguously represent, leading to incorrect UnUn analysis).
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
                best_R = max(1.0, 50.0 * (80.0 ** cos2))   # clamp R ≥ 1 Ω
                best_X = 1500.0 * math.sin(2.0 * arg)
                # Re-derive VSWR from the same R/X so it is consistent with
                # best_R / best_X rather than calling calc_empirical separately.
                if unun_ratio > 1.0:
                    R_in_emp = best_R / unun_ratio
                    X_in_emp = best_X / unun_ratio
                else:
                    R_in_emp, X_in_emp = best_R, best_X
                _g = math.hypot(R_in_emp - 50, X_in_emp) / math.hypot(R_in_emp + 50, X_in_emp)
                best_vswr = (1 + _g) / (1 - _g) if _g < 1 else 999.0
                res.nec2_ok = False
                imp_src = "empirical"

        # Store antenna-side and Tx-side impedance, plus which CP orientation won
        res.band_R_ant[cr.band]   = round(best_R, 2)
        res.band_X_ant[cr.band]   = round(best_X, 2)
        res.band_imp_src[cr.band] = imp_src
        # Record the winning CP orientation key so find_best_unun can reuse it
        # without re-running NEC2 or re-introducing a ratio-dependent bias.
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

    # ── Store NEC2 (or empirical) impedances for INACTIVE bands ────────
    # Now that nec2_sweep passes ALL frequencies to the NEC2 deck, the run
    # objects contain impedance data for every band.  Storing it here means
    # export_best_csv can fill Z_eff_ohm for all rows and the UnUn analysis
    # has a richer dataset to work with.  Inactive bands are NOT added to
    # vswr_penalties (they do not affect the score), but their impedances
    # are captured for inspection.
    #
    # Orientation selection: use the SAME CP orientation that won for the active
    # bands rather than independently re-optimising per band.  The physical
    # antenna has ONE CP orientation; picking the best orientation per inactive
    # band would store impedances from a geometry that does not actually exist,
    # making the exported Z_eff_ohm values inconsistent with the rest of the report.
    #
    # Dominant orientation = the CP source that appears most often across the
    # active bands (ties broken in favour of H-CP).  When no active-band data
    # exists (should not happen — guarded above), fall back to H then V.
    _src_votes = list(res.band_cp_src.values())
    _dominant_cp = ("H" if _src_votes.count("H") >= _src_votes.count("V")
                    else "V") if _src_votes else "H"
    # Build ordered list: dominant orientation first, then the other as fallback.
    _inactive_run_order = (
        [(run_h, "NEC2-H"), (run_v, "NEC2-V")] if _dominant_cp == "H"
        else [(run_v, "NEC2-V"), (run_h, "NEC2-H")]
    )
    inactive = [r for r in calc_rows if not r.active]
    for cr in inactive:
        if cr.band in res.band_R_ant:
            continue   # already stored (should not happen, but guard anyway)
        freq = cr.freq_mhz
        found_R: Optional[float] = None
        found_X: Optional[float] = None
        found_src = "empirical"
        # Try dominant orientation first; fall back to the other only if NEC2
        # data is absent for this frequency in the dominant run.
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
            break   # use first (dominant) orientation that has data
        if found_R is None and not nec2_strict:
            # Empirical fallback for inactive bands (non-strict mode only)
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
    for cr in calc_rows:       # ALL bands, not just active
        freq = cr.freq_mhz
        lambda_half = C_MHZ / (2.0 * freq)
        ratio = wire_len_m / lambda_half
        frac = ratio % 1.0
        # Resonances occur at EVERY multiple of λ/4, i.e. whenever
        # frac ∈ {0.0, 0.25, 0.50, 0.75} (and wrapping at 1.0).
        # In frac-space (units of λ/2) these are multiples of 0.25.
        # The correct avoidance is the distance to the nearest such resonance:
        #   d = frac mod 0.25    →  distance below the nearest 0.25 step
        #   avoidance = min(d, 0.25 - d)   →  distance to NEAREST multiple
        # Max achievable value = 0.125 (midway between two resonances).
        d = frac % 0.25
        avoidance = min(d, 0.25 - d)
        res.band_avoidance[cr.band] = round(avoidance, 4)
        avoidances.append(avoidance)

    # Counterpoise λ/4 proximity bonus: reward CP lengths near an ODD multiple
    # of λ/4 (i.e. λ/4, 3λ/4, 5λ/4 …) which provide a low-Z return path.
    # Only active bands are used here: the CP return path matters at the
    # OPERATING frequencies.  An inactive-band λ/4 coincidence is physically
    # irrelevant (and could mislead the optimizer into preferring a CP length
    # that is resonant only on bands the operator never uses).
    cp_lambda_quarter_scores = []
    for cr in active:          # ACTIVE bands only (operating frequencies)
        lq = C_MHZ / (4.0 * cr.freq_mhz)
        cp_ratio = cp_len_m / lq
        # Reward CP lengths at ODD multiples of λ/4 (λ/4, 3λ/4, 5λ/4 …) which
        # provide a low-impedance return path.  Even multiples (λ/2, λ, 3λ/2 …)
        # give a high-impedance path and score 0.
        cp_score = 0.25 * math.cos(math.pi * (cp_ratio - 1) / 2) ** 2
        cp_lambda_quarter_scores.append(cp_score)

    # Aggregate
    n = len(vswr_penalties)
    mean_vswr_penalty   = sum(vswr_penalties) / n if n else 999.0
    worst_vswr_penalty  = max(vswr_penalties) if vswr_penalties else 999.0
    res.score_vswr      = mean_vswr_penalty          # kept for report / readability
    # score_vswr_raw is the VSWR-only objective (no avoidance bonuses).
    # The Pareto front must use this as its primary axis — NOT score_combined —
    # because score_combined already includes avoidance bonuses.  Using
    # score_combined as a Pareto axis alongside score_avoidance would double-count
    # avoidance: once in score_combined, and again as the second axis.  The correct
    # Pareto trade-off is between VSWR quality and resonance avoidance, independently.
    res.score_vswr_raw  = mean_vswr_penalty + 1.5 * worst_vswr_penalty
    res.score_avoidance = sum(avoidances) / len(avoidances) if avoidances else 0.0

    # Active-band-only avoidance: mean of avoidance only for bands the operator
    # uses.  This is the correct second axis for the Pareto front AND the correct
    # term to use in score_combined.
    #
    # Using score_avoidance_active ensures the avoidance bonus in score_combined
    # is earned only from the bands the operator is actually transmitting on,
    # so score_combined and the per-band avoidance ratings remain consistent.
    #
    # score_avoidance (all-band mean) is still stored and shown in the report
    # (avoidance column, Pareto avoid_all) for full-spectrum inspection, but it
    # no longer feeds directly into the ranking objective.
    active_avoidances = [res.band_avoidance[cr.band] for cr in active
                         if cr.band in res.band_avoidance]
    res.score_avoidance_active = (sum(active_avoidances) / len(active_avoidances)
                                  if active_avoidances else 0.0)

    cp_avoid_mean       = sum(cp_lambda_quarter_scores) / len(cp_lambda_quarter_scores) \
                          if cp_lambda_quarter_scores else 0.0

    # Combined score: mean VSWR penalty + worst-band VSWR penalty (minimax term).
    #
    # The minimax term (weight 1.5) ensures that a single band with a very high
    # VSWR cannot be hidden by a good mean — every band must be acceptable for
    # a candidate to rank well.  Together, mean + 1.5×worst gives:
    #   • both bands good  (pen ≤ 1): combined VSWR term ≤ 2.5   → excellent
    #   • one band bad     (pen = 5): combined VSWR term ≥ 7.5+mean → punished
    #
    # Avoidance bonuses are strictly limited relative to the VSWR terms:
    #   max avoidance bonus  = 0.5 × 0.125 = 0.0625  (avoidance max = 0.125,
    #                          frac midway between any two λ/4 resonances)
    #   max CP bonus         = 0.1 × 0.25  = 0.025   (cp_score max  = 0.25,
    #                          i.e. cos²(0) × 0.25 at an exact λ/4 hit)
    # Bonus ceiling ≈ 0.088, so avoidance can never overcome even a modest
    # VSWR penalty and the ranking is truly VSWR-dominated.
    #
    # Note: score_avoidance_active (active bands only) is used here so that
    # the bonus genuinely reflects resonance avoidance on the operating bands,
    # not diluted by however many inactive bands happen to avoid resonances.
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

    Uses index-based generation (lo + i*step) instead of repeated addition.
    Repeated floating-point addition accumulates rounding error: after many
    steps the running total can drift enough that the final intended point
    barely exceeds (max + 1e-9) and is silently dropped, or an extra
    out-of-range point sneaks in.  Multiplying from the base value avoids
    that drift because each point is computed independently.
    """
    n_w = round((wire_max - wire_min) / wire_step)
    wires = [round(wire_min + i * wire_step, 3) for i in range(n_w + 1)]

    n_c = round((cp_max - cp_min) / cp_step)
    cps = [round(cp_min + i * cp_step, 3) for i in range(n_c + 1)]

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
            print(f"  Empirical sweep {pct:3d}% ({i}/{total})  w={w:.2f} m  cp={c:.2f} m",
                  end="\r")
        r = score_candidate(w, c, calc_rows, unun_ratio, cp_type_hint=cp_type)
        results.append(r)
    if verbose:
        print(f"  Empirical sweep 100% ({total}/{total}) — done.         ")
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
    cp_types: List[str],        # e.g. ["horizontal", "vertical"]
    verbose: bool = True,
) -> List[CandidateResult]:
    """
    Full NEC2 sweep.  For each (wire, cp) pair we run nec2c for each
    cp_type requested, then score with NEC2 impedance data.
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        raise ValueError("No active bands in CSV")
    # Simulate ALL band frequencies in the NEC2 deck so that impedance data is
    # available for every band — including inactive ones used for avoidance scoring
    # and for the UnUn analysis / export CSV.  VSWR scoring in score_candidate
    # still only touches bands where active=YES; simulating extra frequencies adds
    # negligible runtime while enabling full-spectrum inspection.
    freqs  = [cr.freq_mhz for cr in calc_rows]   # ALL bands, not just active

    results: List[CandidateResult] = []
    total = len(grid) * len(cp_types)
    done  = 0

    with tempfile.TemporaryDirectory(prefix="nec2opt_") as tmpdir:
        for w, c in grid:
            runs_by_type: Dict[str, Optional[NEC2Run]] = {}

            for cpt in cp_types:
                done += 1
                if verbose:
                    print(f"  NEC2 {done:4d}/{total}  wire={w:.2f} m  cp={c:.2f} m  ({cpt})",
                          end="\r")

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
                        # Guard: if the run object has an empty freq_map it
                        # means nec2c ran but the parser found no impedance
                        # blocks — treat as a failed run so score_candidate
                        # uses the empirical fallback rather than producing
                        # NEC2-MISS (VSWR=999) for every band.
                        if run is not None and not run.freq_map():
                            run = None
                        runs_by_type[cpt] = run
                    except Exception:
                        runs_by_type[cpt] = None
                else:
                    runs_by_type[cpt] = None

            # Score each CP orientation separately — a real antenna has ONE physical
            # CP orientation.  Mixing H-CP for band A and V-CP for band B produces
            # an impossible hybrid geometry whose simulated VSWR cannot be reproduced
            # on the bench.  We therefore score H and V independently and keep
            # whichever orientation yields the lower combined score overall.
            run_h = runs_by_type.get("horizontal")
            run_v = runs_by_type.get("vertical")

            # Determine the actual geometry label for a "vertical" CP: when
            # cp_len_m exceeds the available vertical drop the NEC2 deck adds
            # a horizontal extension, making the CP L-shaped rather than purely
            # vertical.  Report this accurately so users aren't surprised when
            # they look at the .nec file or try to build the antenna.
            def _cp_actual_label(cpt: str, w_h: float, c_h: float, c_len: float) -> str:
                if cpt != "vertical":
                    return cpt
                avail_drop = w_h - c_h
                return "vertical" if c_len <= avail_drop + 0.01 else "L-shaped"

            if len(cp_types) == 1:
                # Only one orientation simulated — no ambiguity.
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
                # Both orientations simulated: score each one with ONLY its own run,
                # then keep the better candidate.  This guarantees every stored VSWR
                # value corresponds to a single physical geometry.
                candidates_this = []
                for cpt, r_h, r_v in [
                    ("horizontal", run_h, None),
                    ("vertical",   None,  run_v),
                ]:
                    if runs_by_type.get(cpt) is None:
                        # NEC2 failed for this orientation.  Warn when the sibling
                        # orientation succeeded so the user knows the comparison is
                        # one-sided rather than assuming both ran cleanly.
                        sibling = "vertical" if cpt == "horizontal" else "horizontal"
                        if runs_by_type.get(sibling) is not None:
                            print(f"\n  ⚠  NEC2 failed for {cpt} CP at"
                                  f" wire={w:.3f} m / cp={c:.3f} m —"
                                  f" only {sibling} orientation scored.",
                                  flush=True)
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
                    # Both NEC2 runs failed.  In strict mode we do NOT substitute
                    # empirical scores — that would silently mix two different models
                    # and could let a failed-NEC2 pair outrank a valid NEC2 candidate.
                    # Instead, record a sentinel candidate with score=999 so the pair
                    # appears in the output (marked nec2_ok=False) but always ranks last.
                    cand = CandidateResult(
                        wire_len_m=w, cp_len_m=c, cp_type="both",
                        score_combined=999.0, score_vswr_raw=999.0,
                        score_vswr=999.0, score_avoidance=0.0,
                        nec2_ok=False, note="NEC2 failed (both orientations)",
                    )
                    results.append(cand)
                else:
                    # Keep the orientation with the lower combined score.
                    best_cand = min(candidates_this, key=lambda r: r.score_combined)
                    results.append(best_cand)

    if verbose:
        print(f"  NEC2 sweep complete. {total} runs processed.           ")

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
    higher active-band avoidance = better.  A candidate is dominated if
    another beats it on BOTH axes.

    We use score_vswr_raw = mean_vswr_penalty + 1.5*worst_vswr_penalty
    (the pure VSWR objective, without avoidance bonuses) rather than
    score_combined as the first axis.  This is critical because
    score_combined already subtracts 0.5*avoidance, so using it alongside
    score_avoidance as a second axis would double-count avoidance.

    We use score_avoidance_active (active bands only) as the second Pareto
    axis rather than score_avoidance (all bands).  The all-band mean can be
    inflated by inactive bands that happen to avoid resonances well, masking
    the fact that the operating bands themselves are near-resonant.  Using
    only active-band avoidance on the Pareto axis ensures the trade-off
    surface reflects the actual operating situation.  score_avoidance (all
    bands) is still used in score_combined to penalise wire positions that
    are resonant anywhere in the spectrum.

    The correct Pareto trade-off is:
      Axis 1: how well the wire matches the transmitter (VSWR quality — lower = better)
      Axis 2: how far the wire is from resonance on ACTIVE bands (higher = better)
    """
    dominated = set()
    for i, a in enumerate(results):
        for j, b in enumerate(results):
            if i == j:
                continue
            # b dominates a if b is at least as good on every axis AND strictly better on one.
            # Lower score_vswr_raw is better; higher score_avoidance_active is better.
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

# Standard commercially available UnUn impedance ratios.
# 27:1 is included because it is widely sold for end-fed long-wire antennas.
# 36:1, 49:1 and 64:1 are widely used for end-fed long-wire and EFHW antennas
# whose high antenna-side impedance (often 1000–5000 Ω) demands a large step-down.
STANDARD_UNUN_RATIOS: List[float] = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 12.0, 16.0, 25.0, 27.0, 36.0, 49.0, 64.0]

@dataclass
class UnUnResult:
    """Outcome of the UnUn sweep for one antenna geometry."""
    # Per-ratio: ratio → {band: vswr}
    ratio_band_vswr: Dict[float, Dict[str, float]] = field(default_factory=dict)
    # Per-ratio aggregate VSWR penalty score (lower = better)
    ratio_score: Dict[float, float] = field(default_factory=dict)

    best_standard_ratio: float = 9.0
    best_standard_score: float = 999.0
    best_continuous_ratio: float = 9.0
    best_continuous_score: float = 999.0

    # Per-band: what ratio is optimal for that band alone
    per_band_best_ratio: Dict[str, float] = field(default_factory=dict)
    per_band_best_vswr:  Dict[str, float] = field(default_factory=dict)

    # Raw antenna-side impedances collected during analysis
    # list of (band, R_ant, X_ant)
    band_impedances: List[Tuple[str, float, float]] = field(default_factory=list)


def _vswr_for_ratio(R_ant: float, X_ant: float, n: float,
                    z0: float = 50.0) -> float:
    """
    Compute VSWR at the transmitter (Z0=50Ω) through an n:1 impedance
    transformer (ideal UnUn / balun).

    The transformer scales impedance by 1/n so:
        Z_in = (R_ant + jX_ant) / n
    Then VSWR referenced to Z0:
        Γ = (Z_in − Z0) / (Z_in + Z0)
        VSWR = (1 + |Γ|) / (1 − |Γ|)

    A math.nan R_ant or X_ant is the NEC2-MISS sentinel set by score_candidate
    in nec2_strict mode.  Return 999.0 explicitly so callers never propagate nan.
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
                             n: float) -> float:
    """
    Compute the aggregate VSWR penalty for a given UnUn ratio n.
    band_impedances: list of (band_name, R_ant, X_ant).

    Uses the same objective as score_candidate: mean + 1.5 * worst.
    This ensures the UnUn optimiser is consistent with the antenna sweep
    and recommends the ratio that truly minimises the combined score.

    (The previous implementation used mean-only, which diverges from
    score_candidate's minimax term and systematically over-favours ratios
    that improve the better band at the expense of the worse one.)
    """
    if not band_impedances:
        return 999.0
    penalties = []
    for _band, R, X in band_impedances:
        v = _vswr_for_ratio(R, X, n)
        penalties.append(_vswr_score_single(v))
    mean_pen  = sum(penalties) / len(penalties)
    worst_pen = max(penalties)
    return mean_pen + 1.5 * worst_pen


def _golden_section_min(f, lo: float, hi: float,
                         tol: float = 1e-4) -> Tuple[float, float]:
    """
    Find the minimum of scalar function f on [lo, hi].

    Because the aggregate VSWR penalty across multiple bands is multimodal,
    we first do a coarse 200-point grid scan to find the best sub-interval,
    then refine with golden-section search within that interval.
    Returns (argmin, f(argmin)).
    """
    # Coarse scan
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

    # Golden-section refinement in the best sub-interval
    phi = (math.sqrt(5) - 1) / 2   # ≈ 0.618
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

    Impedance source priority:
      1. Impedances already stored in `best.band_R_ant` / `best.band_X_ant`
         (produced by score_candidate during the sweep, using the per-band
         optimal H/V CP choice).  Reusing these guarantees that the UnUn
         analysis and the best-candidate breakdown section of the report are
         always consistent with each other.
      2. Fresh NEC2 runs (run_h, run_v) — used only for bands not already
         present in best.band_R_ant (e.g. if the geometry was partially re-run).
      3. Empirical model  (only when nec2_strict=False)

    When nec2_strict=True and a band has no NEC2 data, that band is skipped
    from the sweep rather than substituted with empirical values.

    Returns an UnUnResult with:
      • Per-standard-ratio VSWR table
      • Best standard ratio
      • Best continuous ratio (golden-section search, range 1:1 … 100:1)
      • Per-band optimal ratio
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        return UnUnResult()

    # ── Collect per-band antenna impedance ────────────────────────────────
    # Priority: sweep-stored values (consistent with report breakdown) →
    #           fresh NEC2 re-run → empirical fallback.
    band_impedances: List[Tuple[str, float, float]] = []  # (band, R, X)

    for cr in active:
        freq = cr.freq_mhz
        R_ant: Optional[float] = None
        X_ant: Optional[float] = None

        # 1. Reuse sweep-stored impedance (best per-band H/V already chosen)
        if cr.band in best.band_R_ant and cr.band in best.band_X_ant:
            R_ant = best.band_R_ant[cr.band]
            X_ant = best.band_X_ant[cr.band]
            # NaN sentinel: score_candidate stores math.nan for a NEC2-MISS band
            # in nec2_strict mode.  Treat this as "no data" so we don't carry a
            # nan-impedance into _vswr_for_ratio, which would silently return nan.
            if math.isnan(R_ant) or math.isnan(X_ant):
                R_ant = None
                X_ant = None

        # 2. Fresh NEC2 run (fallback if band not in stored data)
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
                # Use the same adaptive tolerance as score_candidate to stay consistent.
                # Hardcoding 0.75 MHz is 5× too loose at 160 m / 80 m and could
                # accidentally accept a neighbour-band impedance value.
                _tol = max(0.15, min(0.75, 0.04 * freq))
                if abs(key - freq) > _tol:
                    continue
                fp = fmap[key]
                # Use VSWR (not |Z|) as the selection criterion — consistent with
                # how score_candidate picks the best CP orientation during the sweep.
                # Minimising |Z| is NOT the same as minimising VSWR: the optimal
                # impedance is the one closest to Z0 after the UnUn transformation.
                cand_vswr = _vswr_for_ratio(fp.R_ohm, fp.X_ohm, current_unun)
                if best_R_local is None or cand_vswr < best_vswr_local:
                    best_vswr_local = cand_vswr
                    best_R_local = fp.R_ohm
                    best_X_local = fp.X_ohm
            R_ant = best_R_local
            X_ant = best_X_local

        if R_ant is None:
            if nec2_strict:
                # No NEC2 data for this band — use VSWR=999 penalty, consistent
                # with score_candidate's nec2_strict behaviour.  Silently skipping
                # the band (old behaviour) would optimise the UnUn ratio over a
                # different band subset than the antenna sweep used, making the
                # recommended ratio inconsistent with the sweep ranking.
                # Use math.nan as sentinel (same as score_candidate) so that
                # _aggregate_vswr_penalty can detect and handle it as VSWR=999
                # without confusing it with a genuine R≈0 short-circuit impedance.
                band_impedances.append((cr.band, math.nan, math.nan))
                continue
            # Empirical fallback (only in non-strict mode)
            lhalf = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio = best.wire_len_m / lhalf if lhalf else 0.0
            arg = math.pi * ratio
            cos2 = math.cos(arg) ** 2
            R_ant = max(1.0, 50.0 * (80.0 ** cos2))   # clamp R ≥ 1 Ω
            X_ant = 1500.0 * math.sin(2.0 * arg)

        band_impedances.append((cr.band, R_ant, X_ant))

    if not band_impedances:
        return UnUnResult()

    result = UnUnResult()
    result.band_impedances = band_impedances

    # ── Sweep standard ratios ─────────────────────────────────────────────
    # Build the set of ratios to evaluate: always include the user-supplied
    # current_unun even when it is not in STANDARD_UNUN_RATIOS (e.g. a custom
    # homebrew ratio like 18:1).  Without this, ratio_score.get(current_unun)
    # returns None, breaking the improvement comparison in write_report and the
    # export logic in main().
    ratios_to_sweep: List[float] = list(STANDARD_UNUN_RATIOS)
    if current_unun not in ratios_to_sweep:
        ratios_to_sweep = sorted(ratios_to_sweep + [current_unun])

    for n in ratios_to_sweep:
        bv: Dict[str, float] = {}
        for band, R, X in band_impedances:
            bv[band] = round(_vswr_for_ratio(R, X, n, z0), 3)
        result.ratio_band_vswr[n] = bv
        result.ratio_score[n] = _aggregate_vswr_penalty(band_impedances, n)

    # best_standard_ratio must only consider STANDARD_UNUN_RATIOS so that a
    # non-standard current_unun cannot be returned as the "best standard" choice.
    best_std = min(STANDARD_UNUN_RATIOS, key=lambda n: result.ratio_score[n])
    result.best_standard_ratio = best_std
    result.best_standard_score = result.ratio_score[best_std]

    # ── Continuous golden-section search (ratio 1.0 … 36.0) ──────────────
    def _obj(n: float) -> float:
        return _aggregate_vswr_penalty(band_impedances, n)

    cont_n, cont_score = _golden_section_min(_obj, 1.0, 100.0)
    result.best_continuous_ratio = round(cont_n, 2)
    result.best_continuous_score = round(cont_score, 4)

    # Warn when the optimum lands on (or very near) a search boundary,
    # which means the true minimum may lie beyond the search range.
    _BOUNDARY_TOL = 0.5   # flag if within 0.5 of either end
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

    # ── Per-band best ratio (independent search per band) ─────────────────
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

    h1("NEC2 ANTENNA LENGTH OPTIMIZER REPORT")
    ln(f"Analyzer module : {ANALYZER_PATH}")
    ln(f"Evaluation mode : {mode.upper()}")
    ln(f"UnUn ratio      : {unun_ratio:.1f}:1")
    ln(f"Wire range      : {wire_range[0]:.2f} m … {wire_range[1]:.2f} m  step {wire_range[2]:.3f} m")
    ln(f"CP range        : {cp_range[0]:.2f} m … {cp_range[1]:.2f} m  step {cp_range[2]:.3f} m")
    all_bands_list  = [cr.band for cr in calc_rows]
    active_band_set = set(cr.band for cr in active)
    band_labels = [f"{b}(*)" if b in active_band_set else b for b in all_bands_list]
    ln(f"Active bands    : {len(active)} of {len(calc_rows)}"
       f"  ({', '.join(band_labels)})  (* = scored for VSWR)")

    display_total = total_candidates if total_candidates > 0 else len(ranked)
    ln(f"Total candidates: {display_total}")
    lines.append("")

    # ── TOP 20 RANKING ───────────────────────────────────────────────────
    top_n = len(ranked)
    h1(f"TOP {top_n} CANDIDATES  (lower combined score = better)")
    # Column layout:  Score = mVSWRpen + 1.5xWPen - 0.5xAvoid(act) - 0.1xCPbon
    # All four score components are shown as explicit columns.
    #   mVSWRpen      = mean VSWR penalty across active bands (from rounded band_vswr)
    #   1.5xWPen      = 1.5 × worst-band VSWR penalty (from rounded band_vswr)
    #   0.5xAvoid(act)= 0.5 × mean avoidance score across ACTIVE bands only
    #   0.1xCPbon     = 0.1 × mean CP λ/4 bonus (back-derived; absorbs any float residual)
    # Score is computed internally from unrounded VSWRs; columns from rounded values
    # so Score == mVSWRpen + 1.5xWPen - 0.5xAvoid(act) - 0.1xCPbon holds exactly.
    header = (f"  {'#':>3}  {'Wire(m)':>8}  {'CP(m)':>7}  {'CP type':>10}  "
              f"{'Score':>7}  {'mVSWRpen':>9}  {'1.5xWPen':>9}  {'0.5xAv(a)':>9}  {'0.1xCPbon':>10}  "
              + "  ".join(f"{b:>7}" for b in bands)
              + "  NEC2")
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))

    for rank, r in enumerate(ranked[:top_n], 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        nec_flag = "✓" if r.nec2_ok else "emp"
        # Recompute penalties from the ROUNDED band_vswr values stored in the result.
        # score_combined was produced from UNrounded VSWRs inside score_candidate;
        # to make the table columns self-consistent (Score = mVSWRpen + 1.5xWPen
        # - 0.5xAvoid - 0.1xCPbon) we must derive ALL visible columns from the same
        # source (rounded band_vswr).  The residual is absorbed by _cp_bonus_deduction.
        _pens = [_vswr_score_single(r.band_vswr.get(b, 999.0)) for b in bands]
        _mean_vswr_pen      = sum(_pens) / len(_pens) if _pens else 0.0
        worst_pen_weighted  = 1.5 * max(_pens) if _pens else 0.0
        # CP λ/4 bonus deduction (0.1 × cp_avoid_mean) — back-derived so that
        # Score == mVSWRpen + 1.5xWPen - 0.5xAvoid(active) - 0.1xCPbon exactly.
        # Note: 0.5xAvoid column now shows active-band avoidance (score_avoidance_active)
        # to match the updated score_combined formula.
        _cp_bonus_deduction = (_mean_vswr_pen + worst_pen_weighted
                               - 0.5 * r.score_avoidance_active - r.score_combined)
        lines.append(
            f"  {rank:3d}  {r.wire_len_m:8.3f}  {r.cp_len_m:7.3f}  {r.cp_type:>10}  "
            f"{r.score_combined:7.3f}  {_mean_vswr_pen:9.3f}  {worst_pen_weighted:9.3f}  "
            f"{0.5*r.score_avoidance_active:9.4f}  {_cp_bonus_deduction:10.4f}  "
            f"{band_cols}  {nec_flag}"
        )

    # ── PARETO FRONT ─────────────────────────────────────────────────────
    h1(f"PARETO-OPTIMAL FRONT  ({len(pareto)} candidates)")
    ln("Candidates not dominated on both VSWR-penalty and avoidance score.")
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
        h1("BEST CANDIDATE — DETAILED BREAKDOWN")
        ln(f"Wire length   : {best.wire_len_m:.3f} m")
        ln(f"CP length     : {best.cp_len_m:.3f} m   ({best.cp_type} orientation)")
        ln(f"Combined score: {best.score_combined:.4f}")
        ln(f"VSWR penalty  : {best.score_vswr:.4f}  (mean VSWR penalty across active bands; score_combined = mean + 1.5×worst − bonuses)")
        ln(f"Avoidance(act): {best.score_avoidance_active:.4f}  (mean across ACTIVE bands — used in score_combined)")
        ln(f"Avoidance(all): {best.score_avoidance:.4f}  (mean across ALL bands in CSV — shown for reference)")
        ln(f"NEC2 data used: {'YES' if best.nec2_ok else 'NO — empirical model only'}")

        # ── Boundary warnings ──────────────────────────────────────────
        # Warn when the best candidate lands exactly on a search boundary,
        # which means the true optimum may lie beyond the current range.
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

        ln("Per-band results:")
        ln(f"  {'Band':>8}  {'Active':>6}  {'VSWR(Tx)':>9}  {'Avoid':>8}  {'Rating':>22}  {'VSWR label'}")
        ln("  " + "─" * 80)

        for cr in calc_rows:
            b = cr.band
            a = best.band_avoidance.get(b, 0.0)
            rating = _avoidance_rating(a)
            act_flag = "YES" if cr.active else "no"
            if cr.active:
                v = best.band_vswr.get(b, 999.0)
                if v <= 1.5:
                    vlabel = "EXCELLENT"
                elif v <= 3.0:
                    vlabel = "GOOD"
                elif v <= 6.0:
                    vlabel = "MARGINAL"
                else:
                    vlabel = "POOR"
                ln(f"  {b:>8}  {act_flag:>6}  {v:9.2f}  {a:8.4f}  {rating:>22}  {vlabel}")
            else:
                ln(f"  {b:>8}  {act_flag:>6}  {'—':>9}  {a:8.4f}  {rating:>22}  —")

        # ── Per-band impedance table ──────────────────────────────────
        lines.append("")
        ln("Per-band impedance (antenna side and transmitter side):")
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
        ln(f"  (UnUn {unun_ratio:.0f}:1 — antenna-side Z divided by {unun_ratio:.0f} to give Tx-side Z)")

    # ── UnUn OPTIMISATION ────────────────────────────────────────────────
    if unun_result is not None:
        h1("UnUn RATIO ANALYSIS  (for best antenna geometry)")
        ln(f"Used UnUn ratio (this run) : {unun_ratio:.1f}:1")

        # Continuous optimum
        cont_n = unun_result.best_continuous_ratio
        boundary_note = ""
        if cont_n >= 99.5:
            boundary_note = "  ⚠ HIT UPPER BOUND — true optimum may be >100:1"
        elif cont_n <= 1.5:
            boundary_note = "  ⚠ HIT LOWER BOUND — try no transformer"
        ln(f"Continuous optimum         : {cont_n:.2f}:1"
           f"  (aggregate VSWR penalty {unun_result.best_continuous_score:.4f}){boundary_note}")

        # Nearest standard ratio
        std_n = unun_result.best_standard_ratio
        std_score = unun_result.best_standard_score
        ln(f"Best standard ratio        : {std_n:.0f}:1"
           f"  (aggregate VSWR penalty {std_score:.4f})")

        # Improvement vs current ratio.
        # ratio_score always contains unun_ratio (injected by find_best_unun
        # even for non-standard values like 27:1), so a direct lookup is safe.
        cur_score = unun_result.ratio_score[unun_ratio]
        if cur_score > 0:
            delta = cur_score - std_score
            pct = 100.0 * delta / cur_score
            if delta > 0.001:
                ln(f"  → Switching to {std_n:.0f}:1 improves aggregate VSWR penalty"
                   f" by {delta:.4f}  ({pct:.1f} %)")
                if abs(std_n - unun_ratio) > 0.5:
                    ln(f"  ⚠  Rankings in this report were computed with {unun_ratio:.0f}:1.")
                    ln(f"     Re-run with --unun {std_n:.0f} to rank candidates under"
                       f" the recommended ratio.")
            else:
                ln(f"  → Current ratio {unun_ratio:.0f}:1 is already optimal"
                   f" among standard values.")

        lines.append("")

        # Standard ratio sweep table
        ln("Standard ratio sweep:")
        # Label each band column as "VSWR@<band>" so the reader knows the values
        # are Tx-side VSWR (post-UnUn, referenced to 50 Ω), not impedance or score.
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

        # Antenna-side impedance table (independent of ratio)
        if unun_result.band_impedances:
            lines.append("")
            ln("Antenna-side impedance (independent of UnUn ratio):")
            ln(f"  {'Band':>8}  {'R_ant Ω':>9}  {'X_ant Ω':>9}  {'|Z_ant| Ω':>10}  {'θ °':>7}")
            ln("  " + "─" * 52)
            for bname, R_a, X_a in unun_result.band_impedances:
                Z_a   = math.hypot(R_a, X_a)
                theta = math.degrees(math.atan2(X_a, R_a))
                ln(f"  {bname:>8}  {R_a:9.1f}  {X_a:+9.1f}  {Z_a:10.1f}  {theta:+7.1f}")

        lines.append("")

        # Per-band optimal ratios
        ln("Per-band optimal ratio (independent, continuous):")
        ln(f"  {'Band':>8}  {'Best ratio':>12}  {'VSWR':>7}")
        ln("  " + "─" * 34)
        for b in bands:
            opt_n = unun_result.per_band_best_ratio.get(b, None)
            opt_v = unun_result.per_band_best_vswr.get(b, None)
            opt_n_str = f"{opt_n:10.2f}:1" if opt_n is not None else f"{'N/A (no NEC2)':>11}"
            opt_v_str = f"{opt_v:7.3f}"    if opt_v is not None else f"{'---':>7}"
            ln(f"  {b:>8}  {opt_n_str}  {opt_v_str}")

        lines.append("")
        ln("Note: per-band ratios optimise each band independently and may")
        ln("      conflict with each other.  The aggregate score above is the")
        ln("      correct metric for a single multi-band UnUn.")

    # ── PHYSICAL INTERPRETATION ──────────────────────────────────────────
    h1("PHYSICAL INTERPRETATION")
    notes = [
        ("Wire length selection",
         "The optimal wire avoids landing on ANY multiple of λ/4 on ALL bands in the CSV"
         " simultaneously — including those marked inactive for VSWR scoring.  Resonances"
         " occur at every λ/4 step: λ/4 (low Z / current max), λ/2 (high Z / voltage max),"
         " 3λ/4 (low Z again), λ (high Z), etc.  The avoidance score is the fractional"
         " distance to the NEAREST λ/4 multiple across all bands;"
         " maximum achievable = 0.125 (midway between resonances) = ★★★ EXCELLENT."
         " Values below 0.03 flag RESONANCE RISK."),

        ("Counterpoise length selection",
         "The counterpoise acts as the missing half of the antenna system.  A length near"
         " λ/4 at the operating frequency (or an odd multiple thereof: 3λ/4, 5λ/4 …)"
         " provides a low-impedance return path and is actively rewarded by the optimizer."
         " Lengths near an even multiple of λ/4 (i.e. λ/2, λ, 3λ/2 …) produce a"
         " high-impedance return path and receive no reward.  This bonus is intentionally"
         " small relative to the VSWR term so that CP resonance can nudge a close pair of"
         " candidates but cannot override a poor VSWR match."),

        ("VSWR after UnUn",
         f"All VSWR values shown are referred to the TRANSMITTER side (50 Ω coaxial)"
         f" AFTER the {unun_ratio:.0f}:1 UnUn.  The antenna-side impedance is divided"
         f" by {unun_ratio:.0f} before computing VSWR.  A well-chosen UnUn ratio can"
         f" improve or worsen match: if VSWR is poor on every band consider trying"
         f" 4:1 or 16:1 instead of {unun_ratio:.0f}:1."),

        ("NEC2 vs empirical",
         "When nec2c is available, the optimizer runs a full Sommerfeld-Norton ground"
         " simulation for each candidate.  Without NEC2, the empirical formulas"
         " R = 50·80^cos²(π·L/λ½) and X = 1500·sin(2π·L/λ½) are used.  The empirical"
         " model overestimates impedance accuracy near resonances; NEC2 results are"
         " always preferred.  Cross-validate with nec2_vs_calc_analyzer.py."),

        ("Next steps",
         "1. Take the top-3 wire/CP pairs and feed them into nec2_vs_calc_analyzer.py"
         "   for the full 8-section report with H-CP vs. V-CP comparison."
         "2. Validate with a VNA before cutting the final wire."
         "3. If VSWR > 3 on any priority band, try a different UnUn ratio or add"
         "   a second CP radial cut to λ/4 for that specific band."),
    ]
    for i, (title, body) in enumerate(notes, 1):
        ln(f"{i}. {title}")
        for line in textwrap.wrap(body, width=74):
            ln(f"   {line}")
        lines.append("")

    h1("END OF OPTIMIZER REPORT")

    report_text = "\n".join(lines)

    import re as _re
    clean = _re.sub(r'\x1b\[[0-9;]*m', '', report_text)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(clean)

    return report_text


# ═══════════════════════════════════════════════════════════════════════════
# CSV EXPORT  (nec2_vs_calc_analyzer format)
# ═══════════════════════════════════════════════════════════════════════════

def _recompute_vswr(R_ant: float, X_ant: float, unun_ratio: float,
                    z0: float = 50.0) -> float:
    """
    Recompute Tx-side VSWR for given antenna impedance and UnUn ratio.
    Used by export_best_csv to ensure exported VSWR values are always
    consistent with the unun_ratio column (the sweep may have used a
    different ratio).

    Returns 999.0 when R_ant or X_ant is math.nan — the NEC2-MISS sentinel
    set by score_candidate in nec2_strict mode.  Without this guard, nan/ratio
    propagates silently through all arithmetic and writes 'nan' to the CSV.
    """
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
    Write a CSV in nec2_vs_calc_analyzer format pre-filled with the best
    wire/CP lengths so the user can feed it straight back into the analyser.

    NOTE: vswr_with_cp is recomputed here using the supplied unun_ratio so
    that the exported VSWR values are always consistent with the unun_ratio
    column.  The sweep may have used a different (e.g. original) ratio; we
    must not copy band_vswr[] verbatim when export_unun differs from the
    sweep ratio.
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

            # Use stored antenna-side impedances when available for this specific
            # band, regardless of the global nec2_ok flag.  nec2_ok=False means
            # *at least one* band fell back to empirical; other bands may still
            # have valid NEC2 data stored in band_R_ant / band_X_ant.
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
                R = max(1.0, 50 * (80 ** cos2))   # clamp R ≥ 1 Ω
                X = 1500 * math.sin(2 * arg)

            # vswr_no_cp: Tx-side VSWR through the UnUn computed WITHOUT the
            # counterpoise — i.e. using the empirical single-wire impedance.
            # This matches the convention used by nec2_vs_calc_analyzer where
            # vswr_no_cp and vswr_with_cp are different columns (e.g. antenna.csv
            # shows 21.89 vs 14.46 for 40 m).  The NEC2-derived R,X stored in
            # best.band_R_ant already includes CP interaction, so we must use the
            # empirical formula here to recover the no-CP reference value.
            lhalf_emp = C_MHZ / (2.0 * freq) if freq else 1.0
            ratio_emp = w / lhalf_emp if lhalf_emp else 0.0
            arg_emp = math.pi * ratio_emp
            cos2_emp = math.cos(arg_emp) ** 2
            R_no_cp = max(1.0, 50.0 * (80.0 ** cos2_emp))
            X_no_cp = 1500.0 * math.sin(2.0 * arg_emp)
            vswr_no = _recompute_vswr(R_no_cp, X_no_cp, unun_ratio)

            ratio = w / lhalf if lhalf else 0.0
            frac = ratio % 1.0
            # Use the same corrected avoidance formula as score_candidate:
            # distance to nearest multiple of 0.25 (every λ/4 resonance).
            d = frac % 0.25
            avoid = min(d, 0.25 - d)
            rating = _avoidance_rating(avoid)

            writer.writerow({
                "band":           cr.band,
                "freq_mhz":       freq,
                "active":         "YES" if cr.active else "NO",
                "lambda_half_m":  round(lhalf, 4),
                "lambda_qtr_m":   round(lhalf / 2, 4),
                "wire_len_m":     w,
                "L_over_lhalf":   round(ratio, 4),
                "R_wire_ohm":     round(R, 2),
                "X_wire_ohm":     round(X, 2),
                "vswr_no_cp":     round(vswr_no, 3),
                # vswr_with_cp: Tx-side VSWR after the UnUn, recomputed here using
                # the *export* unun_ratio (which may differ from the sweep ratio).
                # We must NOT copy best.band_vswr[] verbatim: those values were
                # computed during the sweep at a potentially different ratio and
                # would be inconsistent with the unun_ratio column in the CSV.
                "vswr_with_cp":   _recompute_vswr(R, X, unun_ratio)
                                  if cr.active else "",
                # Z_eff_ohm: magnitude of the antenna-side impedance |Z_ant|.
                # Populated whenever R/X data is available (NEC2 or empirical).
                "Z_eff_ohm":      round(math.hypot(R, X), 2),
                # Zcp_ohm: counterpoise impedance is not separately simulated
                # in this optimizer run; left blank for nec2_vs_calc_analyzer
                # to fill in if desired.
                "Zcp_ohm":        "",
                "unun_ratio":     unun_ratio,
                "avoidance_score":round(avoid, 4),
                "quality_rating": rating,
                "cp_len_m":       best.cp_len_m,
                "cp_height_m":    cr.cp_height_m if cr.cp_height_m is not None else 0.5,
                "num_radials":    cr.num_radials if cr.num_radials is not None else 1,
            })


# ═══════════════════════════════════════════════════════════════════════════
# MATPLOTLIB PLOT
# ═══════════════════════════════════════════════════════════════════════════

def plot_results(
    results: List[CandidateResult],
    pareto: List[CandidateResult],
    ranked: List[CandidateResult],
    calc_rows: List[CalcRow],
    unun_ratio: float,
    out_png: str,
) -> None:
    if not HAS_MPL:
        print("  matplotlib not available — skipping plot.")
        return

    active = [r for r in calc_rows if r.active]
    bands = [cr.band for cr in active]

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle("NEC2 Antenna Length Optimizer Results", fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.55, wspace=0.4)

    # ── Panel 1: Score scatter (wire vs cp) ────────────────────────────
    ax1 = fig.add_subplot(gs[0, :2])
    ws = [r.wire_len_m for r in results]
    cs = [r.cp_len_m   for r in results]
    sc = [r.score_combined for r in results]
    sc_clipped = [min(s, 5.0) for s in sc]
    scatter = ax1.scatter(ws, cs, c=sc_clipped, cmap="RdYlGn_r",
                          s=20, alpha=0.6, vmin=min(sc_clipped), vmax=5.0)
    fig.colorbar(scatter, ax=ax1, label="Combined score (lower=better)")

    # Pareto overlay
    pw = [r.wire_len_m for r in pareto]
    pc = [r.cp_len_m   for r in pareto]
    ax1.scatter(pw, pc, marker="*", s=120, c="blue", zorder=5, label="Pareto front")

    # Top-1
    if ranked:
        ax1.scatter(ranked[0].wire_len_m, ranked[0].cp_len_m,
                    marker="D", s=160, c="black", zorder=6, label="Best")
        ax1.annotate(f"Best\n{ranked[0].wire_len_m:.2f}m / {ranked[0].cp_len_m:.2f}m",
                     xy=(ranked[0].wire_len_m, ranked[0].cp_len_m),
                     xytext=(10, 10), textcoords="offset points", fontsize=8)
    ax1.set_xlabel("Wire length (m)")
    ax1.set_ylabel("Counterpoise length (m)")
    ax1.set_title("Combined Score Heat Map")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: VSWR penalty vs avoidance (Pareto space) ──────────────
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
    ax2.set_xlabel("VSWR penalty mean+1.5×worst (lower=better)")
    ax2.set_ylabel("Active-band avoidance (higher=better)")
    ax2.set_title("Pareto Space (active bands)")
    ax2.legend(fontsize=7)
    ax2.grid(True, alpha=0.3)

    # ── Panels 3+: Per-band VSWR for top-10 candidates ─────────────────
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
        ax.set_ylabel("VSWR (Tx side)")
        ax.set_ylim(0.9, min(20, max(vswrs) * 1.15 + 0.5))
        ax.grid(True, alpha=0.3, axis="y")

    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  📊  Optimizer plot saved → {out_png}")


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
              optimizer_best.csv    — best candidate in nec2_vs_calc_analyzer format
        """),
    )
    p.add_argument("--csv", metavar="FILE", default=None,
                   help="Band CSV in nec2_vs_calc_analyzer format (optional). "
                        "If omitted, supply --bands, --freqs, --wire-len, and --cp-len.")
    # No-CSV mode: manual band definition
    p.add_argument("--bands", metavar="NAMES", default=None,
                   help="Comma-separated band names, e.g. '40m,20m,15m'. "
                        "Required when --csv is not supplied.")
    p.add_argument("--freqs", metavar="MHZ", default=None,
                   help="Comma-separated centre frequencies in MHz, one per band, "
                        "e.g. '7.1,14.2,21.2'. Optional when all --bands names are "
                        "recognised amateur-radio bands (40m, 20m, 15m, …) — the "
                        "standard ITU centre frequency is used automatically. "
                        "Required only for unrecognised band names.")
    p.add_argument("--wire-len", metavar="M", type=float, default=None,
                   help="Starting wire length in metres for the search window centre. "
                        "Required when --csv is not supplied.")
    p.add_argument("--cp-len", metavar="M", type=float, default=None,
                   help="Starting counterpoise length in metres for the search window centre. "
                        "Required when --csv is not supplied.")
    p.add_argument("--active-bands", metavar="BANDS", default=None,
                   help="Comma-separated list of band names to mark as active for VSWR scoring, "
                        "e.g. '40m,20m'. Overrides the 'active' column in the CSV. "
                        "All other bands are treated as inactive (avoidance-only). "
                        "When --csv is not used, all --bands are active by default "
                        "unless this flag restricts them.")
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
                        "--cp-min/max.  Increase when the CSV value may be near a "
                        "resonance and you want to explore further.")
    p.add_argument("--wire-min", metavar="M", type=float, default=None,
                   help="Minimum wire length to search (metres). "
                        "Default: CSV wire length minus --margin.")
    p.add_argument("--wire-max", metavar="M", type=float, default=None,
                   help="Maximum wire length to search (metres). "
                        "Default: CSV wire length plus --margin.")
    p.add_argument("--wire-step", metavar="M", type=float, default=0.25,
                   help="Wire length step size (metres, default 0.25).")
    p.add_argument("--cp-min", metavar="M", type=float, default=None,
                   help="Minimum counterpoise length (metres). "
                        "Default: CSV CP length minus --margin.")
    p.add_argument("--cp-max", metavar="M", type=float, default=None,
                   help="Maximum counterpoise length (metres). "
                        "Default: CSV CP length plus --margin.")
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
    p.add_argument("--no-interactive", action="store_true",
                   help="Do not prompt interactively for missing inputs; exit with error instead.")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress progress output.")
    return p


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print(f"{Fore.CYAN}{'═'*70}")
    print("  NEC2 Antenna Length Optimizer")
    print("  Uses nec2_vs_calc_analyzer core — LU3VEA (CC0 v1.0)")
    print(f"{'═'*70}{Style.RESET_ALL}")
    print()

    parser = _build_parser()
    args, _unknown = parser.parse_known_args()
    verbose = not args.quiet

    # ── Load bands — CSV or manual ───────────────────────────────────────
    calc_rows: List[CalcRow]

    if args.csv is not None:
        # ── CSV path ──────────────────────────────────────────────────────
        if not os.path.isfile(args.csv):
            print(f"{Fore.RED}  CSV not found: {args.csv}{Style.RESET_ALL}")
            sys.exit(1)

        # Normalise European-locale CSVs (semicolon separator, comma decimal)
        # to standard CSV (comma separator, dot decimal) before passing to load_csv.
        _csv_to_load = args.csv
        try:
            with open(args.csv, "r", encoding="utf-8-sig") as _fh:
                _raw = _fh.read()
            _first_line = _raw.split("\n")[0]
            if ";" in _first_line and "," not in _first_line.split(";", 1)[1]:
                # Semicolon-separated file (European locale)
                import re as _re
                # Step 1: replace decimal commas inside numeric tokens
                #   e.g. "13,3" → "13.3"  but NOT "YES,NO" → keep as is
                def _fix_decimal(m):
                    s = m.group(0)
                    # Only replace if it looks like a number: digits on both sides of comma
                    return _re.sub(r'(\d),(\d)', r'\1.\2', s)
                _norm = _re.sub(r'[^;\n]+', _fix_decimal, _raw)
                # Step 2: replace semicolon separators with commas
                _norm = _norm.replace(";", ",")
                _tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".csv", prefix="nec2opt_norm_")
                with os.fdopen(_tmp_fd, "w", encoding="utf-8") as _fh:
                    _fh.write(_norm)
                _csv_to_load = _tmp_path
                print(f"  CSV format    : European locale (';' sep, ',' decimal) — normalised")
            else:
                print(f"  CSV format    : standard (',' sep, '.' decimal)")
        except Exception as _e:
            print(f"{Fore.YELLOW}  CSV locale detection failed ({_e}); trying direct load.{Style.RESET_ALL}")

        print(f"  Loading CSV: {args.csv}")
        try:
            calc_rows = load_csv(_csv_to_load)
        except Exception as e:
            print(f"{Fore.RED}  Failed to load CSV: {e}{Style.RESET_ALL}")
            sys.exit(1)
        finally:
            # Clean up temp file if we created one
            if _csv_to_load != args.csv and os.path.isfile(_csv_to_load):
                try:
                    os.unlink(_csv_to_load)
                except OSError:
                    pass

    else:
        # ── No-CSV path: build CalcRow list from CLI arguments ────────────
        # Validate that all required parameters are present; exit with a clear
        # error message for each missing one rather than crashing with an obscure
        # AttributeError later.
        _missing = []
        if not args.bands:
            _missing.append("--bands  (e.g. --bands 40m,20m,15m)")
        if args.wire_len is None:
            _missing.append("--wire-len  (starting wire length in metres)")
        if args.cp_len is None:
            _missing.append("--cp-len  (starting counterpoise length in metres)")
        if _missing:
            print(f"{Fore.RED}  ERROR: --csv was not provided."
                  f"  The following arguments are required:{Style.RESET_ALL}")
            for m in _missing:
                print(f"{Fore.RED}    {m}{Style.RESET_ALL}")
            print(f"{Fore.RED}  Supply --csv OR all of the arguments above.{Style.RESET_ALL}")
            sys.exit(1)

        _band_names = [b.strip() for b in args.bands.split(",") if b.strip()]

        # ── Resolve frequencies ───────────────────────────────────────────
        # If --freqs is given, parse it directly (must match band count).
        # If --freqs is omitted, look up each band name in BAND_CENTRE_FREQ_MHZ.
        # Any unrecognised name that has no --freqs entry is a hard error.
        if args.freqs:
            try:
                _freqs_explicit = [float(f.strip()) for f in args.freqs.split(",") if f.strip()]
            except ValueError as _ve:
                print(f"{Fore.RED}  ERROR: --freqs contains a non-numeric value: {_ve}{Style.RESET_ALL}")
                sys.exit(1)
            if len(_band_names) != len(_freqs_explicit):
                print(f"{Fore.RED}  ERROR: --bands has {len(_band_names)} entries"
                      f" but --freqs has {len(_freqs_explicit)} entries."
                      f"  They must match one-to-one.{Style.RESET_ALL}")
                sys.exit(1)
            _freqs_mhz = _freqs_explicit
            print(f"  Frequencies   : explicit via --freqs")
        else:
            # Auto-resolve from band name table; collect any failures first
            # so we can print them all at once rather than one at a time.
            _freqs_mhz = []
            _unknown_bands = []
            for _bn in _band_names:
                _f = _lookup_band_freq(_bn)
                if _f is None:
                    _unknown_bands.append(_bn)
                else:
                    _freqs_mhz.append(_f)
            if _unknown_bands:
                print(f"{Fore.RED}  ERROR: --freqs was not supplied and the following band"
                      f" name(s) are not in the built-in frequency table:{Style.RESET_ALL}")
                for _ub in _unknown_bands:
                    print(f"{Fore.RED}    '{_ub}'{Style.RESET_ALL}")
                _known = sorted(BAND_CENTRE_FREQ_MHZ.keys())
                print(f"{Fore.RED}  Known bands: {', '.join(_known)}{Style.RESET_ALL}")
                print(f"{Fore.RED}  Supply --freqs with one frequency per band to use"
                      f" custom names.{Style.RESET_ALL}")
                sys.exit(1)
            print(f"  Frequencies   : auto-resolved from band names (use --freqs to override)")
            for _bn, _f in zip(_band_names, _freqs_mhz):
                print(f"    {_bn:>8} → {_f} MHz")


        # Determine active set (all bands by default; restricted by --active-bands)
        if args.active_bands:
            _active_set = {b.strip() for b in args.active_bands.split(",") if b.strip()}
            _unknown_active = _active_set - set(_band_names)
            if _unknown_active:
                print(f"{Fore.YELLOW}  ⚠  --active-bands contains names not in --bands: "
                      f"{sorted(_unknown_active)}.  They will be ignored.{Style.RESET_ALL}")
        else:
            _active_set = set(_band_names)   # all active when no filter given

        # Resolve UnUn ratio early so we can embed it in CalcRow
        # (need it before building rows; CSV path resolves it below)
        _nocsv_unun = args.unun if args.unun is not None else None

        # Build synthetic CalcRow objects.
        # CalcRow is a dataclass from nec2_vs_calc_analyzer; we set only the
        # fields the optimizer actually reads.  Defaults mirror what load_csv
        # would produce for a standard row.
        _wire_len_init = args.wire_len
        _cp_len_init   = args.cp_len
        _cp_height_val = args.cp_height if args.cp_height is not None else 0.5
        _wire_h_val    = args.wire_height if args.wire_height is not None else DEFAULT_HEIGHT_M

        calc_rows = []
        for _bn, _fmhz in zip(_band_names, _freqs_mhz):
            _row = CalcRow.__new__(CalcRow)
            # Mandatory fields
            _row.band       = _bn
            _row.freq_mhz   = _fmhz
            _row.active     = (_bn in _active_set)
            # Geometry — used for search-window defaults and CSV export
            _row.wire_len_m = _wire_len_init
            _row.cp_len_m   = _cp_len_init
            _row.cp_height_m   = _cp_height_val
            _row.wire_height_m = _wire_h_val
            # Fields that may be read by export_best_csv or the CSV mean helper
            _row.num_radials   = 1
            _row.unun_ratio    = _nocsv_unun if _nocsv_unun is not None else 9.0
            # Fields expected by CalcRow but not relevant in no-CSV mode
            for _attr in ("lambda_half_m", "lambda_qtr_m", "L_over_lhalf",
                          "R_wire_ohm", "X_wire_ohm", "vswr_no_cp", "vswr_with_cp",
                          "Z_eff_ohm", "Zcp_ohm", "avoidance_score", "quality_rating"):
                if hasattr(CalcRow, _attr) and not hasattr(_row, _attr):
                    setattr(_row, _attr, None)
            calc_rows.append(_row)

        print(f"  Band source   : command-line (no CSV)")
        print(f"  Bands defined : {len(calc_rows)}  ({', '.join(_band_names)})")

    # ── Apply --active-bands override (CSV path) ──────────────────────────
    # When --csv was used, --active-bands overrides the CSV 'active' column.
    if args.csv is not None and args.active_bands is not None:
        _active_set = {b.strip() for b in args.active_bands.split(",") if b.strip()}
        _all_names  = {r.band for r in calc_rows}
        _unknown_ab = _active_set - _all_names
        if _unknown_ab:
            print(f"{Fore.YELLOW}  ⚠  --active-bands contains names not in CSV: "
                  f"{sorted(_unknown_ab)}.  They will be ignored.{Style.RESET_ALL}")
        for _row in calc_rows:
            _row.active = (_row.band in _active_set)
        print(f"  Active bands  : overridden by --active-bands → "
              f"{sorted(_active_set & _all_names)}")

    active = [r for r in calc_rows if r.active]
    if not active:
        print(f"{Fore.RED}  No active bands found."
              f"  Set the 'active' column to YES in the CSV, or use --active-bands,"
              f"  or omit --active-bands to activate all --bands.{Style.RESET_ALL}")
        sys.exit(1)

    print(f"  Active bands  : {len(active)}  ({', '.join(r.band for r in active)})")
    print(f"  Frequencies   : {[r.freq_mhz for r in active]}")

    # ── UnUn ratio ────────────────────────────────────────────────────────
    if args.unun is not None:
        unun_ratio = args.unun
    elif args.csv is None:
        # No-CSV mode without explicit --unun
        if args.no_interactive:
            print(f"{Fore.RED}  No --unun supplied and no CSV to read it from."
                  f"  Use --unun RATIO (e.g. --unun 9).{Style.RESET_ALL}")
            sys.exit(1)
        val = input(f"{Fore.CYAN}  UnUn ratio (e.g. 9 for 9:1) [9]: {Style.RESET_ALL}").strip()
        unun_ratio = float(val) if val else 9.0
    else:
        csv_ununs = {r.unun_ratio for r in calc_rows if r.unun_ratio > 0}
        if len(csv_ununs) == 1:
            unun_ratio = list(csv_ununs)[0]
            print(f"  UnUn ratio    : {unun_ratio:.1f}:1  (from CSV)")
        elif len(csv_ununs) == 0:
            if args.no_interactive:
                print(f"{Fore.RED}  No unun_ratio in CSV; supply --unun.{Style.RESET_ALL}")
                sys.exit(1)
            val = input(f"{Fore.CYAN}  UnUn ratio (e.g. 9 for 9:1) [9]: {Style.RESET_ALL}").strip()
            unun_ratio = float(val) if val else 9.0
        else:
            if args.no_interactive:
                print(f"{Fore.RED}  Multiple unun_ratio values in CSV ({sorted(csv_ununs)}). "
                      f"Supply --unun explicitly.{Style.RESET_ALL}")
                sys.exit(1)
            val = input(f"{Fore.CYAN}  Multiple UnUn values in CSV {sorted(csv_ununs)}."
                        f"  Which to use? [{list(csv_ununs)[0]}]: {Style.RESET_ALL}").strip()
            unun_ratio = float(val) if val else list(csv_ununs)[0]


    print(f"  UnUn ratio    : {unun_ratio:.1f}:1")

    # ── Resolve range / height defaults ──────────────────────────────────
    # Default margin: search ±args.margin metres around the reference lengths.
    # This keeps the optimizer close to the physically intended design.
    # Use --margin to widen deliberately when you want to explore further.
    _MARGIN = args.margin

    # Helper: extract a mean value for an attribute across rows that have it.
    def _csv_mean(attr: str, rows, fallback: float) -> float:
        vals = [getattr(r, attr) for r in rows
                if hasattr(r, attr) and getattr(r, attr) is not None]
        return (sum(vals) / len(vals)) if vals else fallback

    # Wire length range — when no CSV, args.wire_len is the explicit centre.
    if args.wire_min is None or args.wire_max is None:
        if args.wire_len is not None:
            ref_wire = args.wire_len
            src_wire = "--wire-len"
        else:
            ref_wire = _csv_mean("wire_len_m", active,
                                 fallback=_csv_mean("wire_len_m", calc_rows, 10.0))
            src_wire = "CSV"
        print(f"  Search margin : ±{_MARGIN} m around {src_wire} wire {ref_wire:.3f} m  "
              f"(use --margin to change)")
        if args.wire_min is None:
            args.wire_min = max(1.0, round(ref_wire - _MARGIN, 3))
            print(f"  --wire-min    : {args.wire_min} m")
        if args.wire_max is None:
            args.wire_max = round(ref_wire + _MARGIN, 3)
            print(f"  --wire-max    : {args.wire_max} m")

    # Counterpoise length range
    if args.cp_min is None or args.cp_max is None:
        if args.cp_len is not None:
            ref_cp = args.cp_len
            src_cp = "--cp-len"
        else:
            ref_cp = _csv_mean("cp_len_m", active,
                               fallback=_csv_mean("cp_len_m", calc_rows, 4.0))
            src_cp = "CSV"
        print(f"  CP margin     : ±{_MARGIN} m around {src_cp} CP {ref_cp:.3f} m  "
              f"(use --margin to change)")
        if args.cp_min is None:
            args.cp_min = max(1.0, round(ref_cp - _MARGIN, 3))
            print(f"  --cp-min      : {args.cp_min} m")
        if args.cp_max is None:
            args.cp_max = round(ref_cp + _MARGIN, 3)
            print(f"  --cp-max      : {args.cp_max} m")

    # Heights
    if args.wire_height is None:
        csv_wh = _csv_mean("wire_height_m", active,
                           fallback=_csv_mean("wire_height_m", calc_rows,
                                              DEFAULT_HEIGHT_M))
        # Use is-not-None so that a legitimate height of 0.0 m is kept
        # (rather than being falsely overridden to DEFAULT_HEIGHT_M).
        args.wire_height = csv_wh if csv_wh is not None else DEFAULT_HEIGHT_M
        src_note = ("(from CSV)" if args.csv is not None
                    else f"(default; use --wire-height to override)")
        print(f"  --wire-height : {args.wire_height} m  {src_note}")

    if args.cp_height is None:
        csv_cph = _csv_mean("cp_height_m", active,
                            fallback=_csv_mean("cp_height_m", calc_rows, 0.5))
        args.cp_height = csv_cph if csv_cph is not None else 0.5
        src_note = "(from CSV)" if args.csv is not None else "(default; use --cp-height to override)"
        print(f"  --cp-height   : {args.cp_height} m  {src_note}")

    # ── Build search grid ────────────────────────────────────────────────
    wire_range = (args.wire_min, args.wire_max, args.wire_step)
    cp_range   = (args.cp_min,  args.cp_max,  args.cp_step)
    grid = build_search_grid(*wire_range, *cp_range)
    print(f"  Grid size     : {len(grid)} (wire) × (cp) pairs")

    cp_types = (["horizontal", "vertical"] if args.cp_type == "both"
                else [args.cp_type])
    print(f"  CP types      : {cp_types}")

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
                print(f"{Fore.RED}  --mode nec2 requires nec2c binary."
                      f"  Use --nec2c PATH or install nec2c.{Style.RESET_ALL}")
                sys.exit(1)
            print(f"  {Fore.YELLOW}nec2c not found — falling back to empirical mode.{Style.RESET_ALL}")
            mode = "empirical"
        else:
            mode = "nec2"

    # ── Run sweep ────────────────────────────────────────────────────────
    print()
    print(f"  Starting {mode.upper()} sweep …")
    print()

    if mode == "nec2":
        results = nec2_sweep(
            grid=grid,
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
            print(f"  {Fore.YELLOW}Note: empirical model ignores CP geometry for VSWR;"
                  f" cp_type forced to 'horizontal' for the cp-avoidance label"
                  f" (CP length avoidance is still evaluated for all bands).{Style.RESET_ALL}")
        results = empirical_sweep(
            grid=grid,
            calc_rows=calc_rows,
            unun_ratio=unun_ratio,
            cp_type=_emp_cp,
            verbose=verbose,
        )

    print(f"\n  Sweep complete.  {len(results)} candidates evaluated.")

    # ── Rank & Pareto ────────────────────────────────────────────────────
    ranked = rank_results(results)
    pareto = pareto_front(results)
    pareto_ranked = sorted(pareto, key=lambda r: r.score_combined)

    print(f"  Pareto-optimal candidates: {len(pareto)}")

    if ranked:
        best = ranked[0]
        print(f"\n  {Fore.GREEN}★ BEST CANDIDATE:{Style.RESET_ALL}"
              f"  wire = {best.wire_len_m:.3f} m   cp = {best.cp_len_m:.3f} m"
              f"   ({best.cp_type})")
        print(f"    Combined score  = {best.score_combined:.4f}")
        print(f"    VSWR penalty    = {best.score_vswr:.4f}")
        print(f"    Avoidance mean  = {best.score_avoidance:.4f}")

        # ── Boundary warnings ─────────────────────────────────────────
        # Count how many of the top-5 candidates sit at a search boundary.
        # When the best (or several top candidates) land exactly at wire_min,
        # wire_max, cp_min, or cp_max it is a strong signal that the search
        # space is truncating the true optimum.  Warn the user so they can
        # re-run with a wider margin or explicit --wire-min/max flags.
        _tol = 1e-6
        _boundary_hits_wire = sum(
            1 for r in ranked[:5]
            if abs(r.wire_len_m - args.wire_min) < _tol
            or abs(r.wire_len_m - args.wire_max) < _tol
        )
        _boundary_hits_cp = sum(
            1 for r in ranked[:5]
            if abs(r.cp_len_m - args.cp_min) < _tol
            or abs(r.cp_len_m - args.cp_max) < _tol
        )
        if abs(best.wire_len_m - args.wire_max) < _tol:
            print(f"\n  {Fore.YELLOW}⚠  WIRE LENGTH at search maximum ({args.wire_max:.3f} m)."
                  f"  {_boundary_hits_wire}/5 top candidates hit this boundary."
                  f"\n     The true optimum may be longer. Re-run with a larger"
                  f" --wire-max or increase --margin.{Style.RESET_ALL}")
        elif abs(best.wire_len_m - args.wire_min) < _tol:
            print(f"\n  {Fore.YELLOW}⚠  WIRE LENGTH at search minimum ({args.wire_min:.3f} m)."
                  f"  {_boundary_hits_wire}/5 top candidates hit this boundary."
                  f"\n     The true optimum may be shorter. Re-run with a smaller"
                  f" --wire-min or increase --margin.{Style.RESET_ALL}")
        if abs(best.cp_len_m - args.cp_max) < _tol:
            print(f"\n  {Fore.YELLOW}⚠  CP LENGTH at search maximum ({args.cp_max:.3f} m)."
                  f"  {_boundary_hits_cp}/5 top candidates hit this boundary."
                  f"\n     The true optimum may be longer. Re-run with a larger"
                  f" --cp-max or increase --margin.{Style.RESET_ALL}")
        elif abs(best.cp_len_m - args.cp_min) < _tol:
            print(f"\n  {Fore.YELLOW}⚠  CP LENGTH at search minimum ({args.cp_min:.3f} m)."
                  f"  {_boundary_hits_cp}/5 top candidates hit this boundary."
                  f"\n     The true optimum may be shorter. Re-run with a smaller"
                  f" --cp-min or increase --margin.{Style.RESET_ALL}")
        print()

        # ── Impedance table ───────────────────────────────────────────
        active_rows = [cr for cr in calc_rows if cr.active]
        print(f"  {Fore.CYAN}Impedance — antenna side & transmitter side "
              f"(UnUn {unun_ratio:.0f}:1):{Style.RESET_ALL}")
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

        # For NEC2 mode: re-run the best geometry to get fresh impedance data
        if mode == "nec2" and nec2c_bin:
            # Re-run the best geometry for ALL band frequencies — including inactive
            # bands — so that the UnUn analysis has NEC2 impedances for the full
            # spectrum.  This is consistent with the nec2_sweep fix above.
            all_freqs = [cr.freq_mhz for cr in calc_rows]  # ALL bands, not just active
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
                            # Treat runs with empty freq_map as failed
                            if _run is not None and not _run.freq_map():
                                _run = None
                            if cpt == "horizontal":
                                best_run_h = _run
                            else:
                                best_run_v = _run
                        except Exception:
                            pass

        print("  Optimising UnUn ratio for best geometry …")
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
        # ratio_score always contains unun_ratio (injected by find_best_unun
        # even for non-standard values), so direct lookup is safe here.
        cur_score = unun_result.ratio_score[unun_ratio]
        std_score = unun_result.best_standard_score

        print(f"\n  {Fore.CYAN}UnUn Analysis (best geometry: "
              f"{best.wire_len_m:.3f} m / {best.cp_len_m:.3f} m):{Style.RESET_ALL}")
        print(f"    Current ratio    : {unun_ratio:.0f}:1"
              f"  (aggregate VSWR penalty {cur_score:.4f})")
        print(f"    Best standard    : {std_n:.0f}:1"
              f"  (aggregate VSWR penalty {std_score:.4f})")
        print(f"    Continuous opt.  : {cont_n:.2f}:1"
              f"  (aggregate VSWR penalty {unun_result.best_continuous_score:.4f})")

        if abs(std_n - unun_ratio) > 0.5 and (cur_score - std_score) > 0.001:
            print(f"    {Fore.YELLOW}→ Consider switching to {std_n:.0f}:1 UnUn for better match.{Style.RESET_ALL}")
        else:
            print(f"    {Fore.GREEN}→ Current {unun_ratio:.0f}:1 is optimal among standard ratios.{Style.RESET_ALL}")

        # Per-band summary
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
    print("  Writing outputs …")

    # Use the recommended UnUn ratio for the CSV export if it's better.
    # NOTE: write_report is called with the original unun_ratio (the one used
    # during the sweep and shown in the per-band impedance tables) so the report
    # and the CSV both document their respective ratio clearly.  If the recommended
    # ratio differs, a note is printed here and the CSV header carries export_unun.
    #
    # IMPORTANT: the ranking in the report was produced at unun_ratio, not at
    # export_unun.  The best wire/CP pair at one ratio is not necessarily best at
    # another — impedance matching shifts non-linearly across the grid.  Re-run
    # the optimizer with --unun <export_unun> to obtain rankings that are truly
    # optimal for the recommended transformer.
    export_unun = unun_ratio
    if unun_result is not None:
        std_n = unun_result.best_standard_ratio
        cur_score = unun_result.ratio_score[unun_ratio]
        if (unun_result.best_standard_score < cur_score - 0.001
                and abs(std_n - unun_ratio) > 0.5):
            export_unun = std_n
            print(f"  ℹ  CSV export uses recommended UnUn {export_unun:.0f}:1"
                  f" (instead of {unun_ratio:.0f}:1)")
            print(f"  ⚠  Rankings above were computed with {unun_ratio:.0f}:1 UnUn.")
            print(f"     Re-run with --unun {export_unun:.0f} to rank candidates"
                  f" under the recommended ratio.")

    report = write_report(
        ranked=ranked[:args.top_n],
        pareto=pareto_ranked,
        calc_rows=calc_rows,
        unun_ratio=unun_ratio,
        wire_range=wire_range,
        cp_range=cp_range,
        mode=mode,
        out_path=args.out_txt,
        unun_result=unun_result,
        total_candidates=len(results),
    )
    print(f"  📄  Report saved → {args.out_txt}")

    if ranked:
        export_best_csv(ranked[0], calc_rows, export_unun, args.out_csv)
        print(f"  📋  Best-candidate CSV → {args.out_csv}"
              f"  (UnUn {export_unun:.0f}:1)")

    plot_results(results, pareto, ranked, calc_rows, unun_ratio, args.out_png)

    # ── Print abbreviated report to terminal ─────────────────────────────
    print()
    if verbose:
        import re as _re
        clean = _re.sub(r'\x1b\[[0-9;]*m', '', report)
        print(clean)

    print(f"\n{Fore.CYAN}  Done.  Feed {args.out_csv} back into nec2_vs_calc_analyzer.py")
    print(f"  for a full 8-section comparison report.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    main()
