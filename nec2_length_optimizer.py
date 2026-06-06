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

  Usage:
    python nec2_length_optimizer.py --csv my_bands.csv [options]
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
    _avoidance_score = _mod._avoidance_score
    _avoidance_rating= _mod._avoidance_rating
    VSWR_THRESHOLDS  = _mod.VSWR_THRESHOLDS
    ANALYZER_PATH    = str(_analyzer_path)

except ImportError as _e:
    print(f"\n{Fore.RED}ERROR: cannot import nec2_vs_calc_analyzer: {_e}")
    print("       Place nec2_vs_calc_analyzer.py in the same directory as this script")
    print(f"       or add its directory to PYTHONPATH.{Style.RESET_ALL}")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS & DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════

C_MHZ = 299.792458          # speed of light / 1e6
WIRE_RADIUS_M = 0.001       # 1 mm copper wire
DEFAULT_HEIGHT_M = 8.0      # antenna wire height above ground
DEFAULT_GROUND_COND = 0.005 # S/m  (average ground)
DEFAULT_GROUND_DIEL = 13.0  # relative permittivity
SEGS_PER_HALF_WAVE = 21     # NEC2 segments per half wavelength (odd, centred source)

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
    """Return an odd number of segments appropriate for the wire length."""
    lambda_half = C_MHZ / (2.0 * highest_freq_mhz) if highest_freq_mhz else 10.0
    n = max(7, int(length_m / lambda_half * SEGS_PER_HALF_WAVE))
    return n if n % 2 == 1 else n + 1   # keep odd for centred source


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

    Source (EX): last segment of Wire 1 (the far end → end-fed).
    The feedpoint is the junction of Wire 1 end / Wire 2 start.
    """
    highest_f = max(freqs_mhz)
    segs_ant = _segs(wire_len_m, highest_f)
    segs_cp  = max(5, _segs(cp_len_m, highest_f))
    if segs_cp % 2 == 0:
        segs_cp += 1

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
            # BUG FIX: the horizontal CP must be connected to the feedpoint
            # at (0, 0, wire_height_m).  The previous code placed GW 2 starting
            # at (0, 0, cp_height_m), which is spatially disconnected from the
            # antenna feedpoint, so NEC2 treated the CP as a floating wire.
            #
            # Correct model: a vertical drop wire (GW 2) descends from the
            # feedpoint to cp_height_m, then the horizontal CP wire (GW 3)
            # extends outward at that height.  cp_len_m is the horizontal
            # wire length; the vertical drop is always added as a connecting
            # section (it represents the physical feedline / lead-in).
            drop_len = wire_height_m - cp_height_m
            if drop_len > 0.01:
                segs_drop = max(5, _segs(drop_len, highest_f))
                if segs_drop % 2 == 0:
                    segs_drop += 1
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
            # Recompute segment count for the actual vertical length actually used
            segs_cp_v = max(5, _segs(cp_len_m, highest_f))
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

        fh.write("GE 1\n")           # ground plane present

        # Ground (Sommerfeld-Norton)
        fh.write(f"GN 2 0 0 0 {ground_diel:.1f} {ground_cond:.4f}\n")

        # Excitation: middle segment of wire 1 (nearest to the feed junction).
        # Wire 1 runs from x=0 (seg 1) to x=wire_len_m (seg segs_ant).
        # The CP connects at x=0, so segment 1 is the correct feedpoint.
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

    # Aggregate scores (lower = better)
    score_vswr:      float = 999.0   # weighted mean VSWR across active bands
    score_avoidance: float = 0.0     # mean avoidance score (higher = better)
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
            if abs(key - freq) > 0.75:
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
                # substitute empirical values.
                best_vswr = 999.0
                best_R    = 0.0
                best_X    = 0.0
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

        # Store antenna-side and Tx-side impedance
        res.band_R_ant[cr.band]   = round(best_R, 2)
        res.band_X_ant[cr.band]   = round(best_X, 2)
        res.band_imp_src[cr.band] = imp_src
        if unun_ratio > 1.0:
            res.band_R_tx[cr.band] = round(best_R / unun_ratio, 3)
            res.band_X_tx[cr.band] = round(best_X / unun_ratio, 3)
        else:
            res.band_R_tx[cr.band] = round(best_R, 3)
            res.band_X_tx[cr.band] = round(best_X, 3)

        res.band_vswr[cr.band] = round(best_vswr, 3)
        vswr_penalties.append(_vswr_score_single(best_vswr))

    # ── Avoidance score: computed over ALL bands in the CSV ─────────────
    # BUG FIX: previously avoidance was computed only for active bands.
    # This meant a wire could sit right at resonance on inactive bands
    # (e.g. 30m, 60m) with zero penalty.  Since avoidance is a property
    # of the wire geometry against the spectrum — independent of whether
    # the operator transmits on that band — ALL bands in the CSV are
    # included.  VSWR scoring is still restricted to active bands only.
    #
    # BUG FIX (retained from earlier version): penalise proximity to BOTH
    # bad zones:
    #   d_half    = distance to nearest λ/2 multiple  (frac ∈ {0, 1})
    #   d_quarter = distance to nearest λ/4 multiple  (frac = 0.5)
    #   avoidance = min(d_half, d_quarter)
    # Maximum = 0.25 at frac = 0.25 or 0.75 (3λ/8, 7λ/8 — ideal mid-points).
    for cr in calc_rows:       # ALL bands, not just active
        freq = cr.freq_mhz
        lambda_half = C_MHZ / (2.0 * freq)
        ratio = wire_len_m / lambda_half
        frac = ratio % 1.0
        d_half    = min(frac, 1.0 - frac)   # distance from λ/2 (high Z)
        d_quarter = abs(frac - 0.5)          # distance from λ/4 (low Z)
        avoidance = min(d_half, d_quarter)   # avoid BOTH resonant extremes
        res.band_avoidance[cr.band] = round(avoidance, 4)
        avoidances.append(avoidance)

    # Counterpoise λ/4 proximity bonus: reward CP lengths near an ODD multiple
    # of λ/4 (i.e. λ/4, 3λ/4, 5λ/4 …) which provide a low-Z return path.
    # BUG FIX: the previous formula  0.5 - abs(cp_frac - 0.5)  was inverted —
    # it gave ZERO bonus when cp_len was at λ/4 (the ideal CP length) and the
    # MAXIMUM bonus at 3λ/8 (a non-resonant mid-point).
    #
    # Correct formula: cosine that peaks at every odd multiple of λ/4.
    #   score = 0.25 * (1 − cos(π * cp_ratio))
    #   • cp_ratio=0   → 0.0  (zero length — no path)
    #   • cp_ratio=1   → 0.5  (λ/4   — ideal, low Z)  ← maximum = 0.5
    #   • cp_ratio=2   → 0.0  (λ/2   — high Z, bad)
    #   • cp_ratio=3   → 0.5  (3λ/4  — ideal, low Z)  ← maximum = 0.5
    # CP bonus also covers ALL bands (same reasoning as avoidance above).
    cp_lambda_quarter_scores = []
    for cr in calc_rows:       # ALL bands
        lq = C_MHZ / (4.0 * cr.freq_mhz)
        cp_ratio = cp_len_m / lq
        cp_score = 0.25 * (1.0 - math.cos(math.pi * cp_ratio))
        cp_lambda_quarter_scores.append(cp_score)

    # Aggregate
    n = len(vswr_penalties)
    mean_vswr_penalty   = sum(vswr_penalties) / n if n else 999.0
    worst_vswr_penalty  = max(vswr_penalties) if vswr_penalties else 999.0
    res.score_vswr      = mean_vswr_penalty          # kept for report / Pareto
    res.score_avoidance = sum(avoidances) / len(avoidances) if avoidances else 0.0
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
    #   max avoidance bonus  = 0.5 × 0.25 = 0.125  (avoidance max = 0.25)
    #   max CP bonus         = 0.1 × 0.5  = 0.05   (cp_score max  = 0.5)
    # Bonus ceiling ≈ 0.175, so avoidance can never overcome even a modest
    # VSWR penalty and the ranking is truly VSWR-dominated.
    res.score_combined = (mean_vswr_penalty
                          + 1.5 * worst_vswr_penalty
                          - 0.5 * res.score_avoidance
                          - 0.1 * cp_avoid_mean)

    return res


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH GRID BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_search_grid(
    calc_rows: List[CalcRow],
    wire_min: float,
    wire_max: float,
    wire_step: float,
    cp_min: float,
    cp_max: float,
    cp_step: float,
) -> List[Tuple[float, float]]:
    """Return all (wire_len, cp_len) grid combinations to evaluate."""
    wires = []
    w = wire_min
    while w <= wire_max + 1e-9:
        wires.append(round(w, 3))
        w += wire_step

    cps = []
    c = cp_min
    while c <= cp_max + 1e-9:
        cps.append(round(c, 3))
        c += cp_step

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
    freqs  = [cr.freq_mhz for cr in active]
    if not freqs:
        raise ValueError("No active bands in CSV")

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

            # Score with all available runs
            run_h = runs_by_type.get("horizontal")
            run_v = runs_by_type.get("vertical")

            if len(cp_types) == 1:
                cpt_label = cp_types[0]
            else:
                cpt_label = "both"

            cand = score_candidate(
                wire_len_m=w,
                cp_len_m=c,
                calc_rows=calc_rows,
                unun_ratio=unun_ratio,
                run_h=run_h,
                run_v=run_v,
                cp_type_hint=cpt_label,
                nec2_strict=True,
            )
            results.append(cand)

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
    (score_vswr, score_avoidance).  Lower vswr_score AND higher avoidance
    = better.  A candidate is dominated if another beats it on BOTH axes.
    """
    dominated = set()
    for i, a in enumerate(results):
        for j, b in enumerate(results):
            if i == j:
                continue
            # b dominates a if b is at least as good on every axis AND strictly better on one
            if (b.score_vswr <= a.score_vswr and
                    b.score_avoidance >= a.score_avoidance and
                    (b.score_vswr < a.score_vswr or b.score_avoidance > a.score_avoidance)):
                dominated.add(i)
                break
    return [r for i, r in enumerate(results) if i not in dominated]


# ═══════════════════════════════════════════════════════════════════════════
# UnUn OPTIMISER
# ═══════════════════════════════════════════════════════════════════════════

# Standard commercially available UnUn impedance ratios
STANDARD_UNUN_RATIOS: List[float] = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 12.0, 16.0, 25.0]

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
    """
    if n <= 0:
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
    Compute mean VSWR penalty across all bands for a given UnUn ratio n.
    band_impedances: list of (band_name, R_ant, X_ant).
    """
    if not band_impedances:
        return 999.0
    penalties = []
    for _band, R, X in band_impedances:
        v = _vswr_for_ratio(R, X, n)
        penalties.append(_vswr_score_single(v))
    return sum(penalties) / len(penalties)


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

    Impedance source priority (same as score_candidate):
      1. NEC2 horizontal CP run
      2. NEC2 vertical CP run
      3. Empirical model  (only when nec2_strict=False)

    When nec2_strict=True and a band has no NEC2 data, that band is skipped
    from the sweep rather than substituted with empirical values.

    Returns an UnUnResult with:
      • Per-standard-ratio VSWR table
      • Best standard ratio
      • Best continuous ratio (golden-section search)
      • Per-band optimal ratio
    """
    active = [r for r in calc_rows if r.active]
    if not active:
        return UnUnResult()

    # ── Collect per-band antenna impedance ────────────────────────────────
    band_impedances: List[Tuple[str, float, float]] = []  # (band, R, X)

    for cr in active:
        freq = cr.freq_mhz
        R_ant, X_ant = None, None

        # BUG FIX: the previous code always preferred run_h over run_v
        # ('break' after first hit), but score_candidate selects whichever
        # source yields the lower VSWR.  Using run_h unconditionally means
        # the UnUn analysis can end up with completely different (and much
        # worse) impedance values than those that ranked the best candidate.
        # Fix: iterate both runs and pick the one that gives lower VSWR at
        # the current UnUn ratio — matching the logic in score_candidate.
        best_R_local: Optional[float] = None
        best_X_local: Optional[float] = None
        best_v_local: Optional[float] = None

        for run in [run_h, run_v]:
            if run is None:
                continue
            fmap = run.freq_map()
            if not fmap:
                continue
            key = min(fmap.keys(), key=lambda k: abs(k - freq))
            if abs(key - freq) > 0.75:
                continue
            fp = fmap[key]
            v_here = _vswr_for_ratio(fp.R_ohm, fp.X_ohm, current_unun, z0)
            if best_v_local is None or v_here < best_v_local:
                best_v_local = v_here
                best_R_local = fp.R_ohm
                best_X_local = fp.X_ohm

        R_ant = best_R_local
        X_ant = best_X_local

        if R_ant is None:
            if nec2_strict:
                # Skip this band — no NEC2 data and empirical is forbidden
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
    for n in STANDARD_UNUN_RATIOS:
        bv: Dict[str, float] = {}
        for band, R, X in band_impedances:
            bv[band] = round(_vswr_for_ratio(R, X, n, z0), 3)
        result.ratio_band_vswr[n] = bv
        result.ratio_score[n] = _aggregate_vswr_penalty(band_impedances, n)

    best_std = min(result.ratio_score, key=result.ratio_score.get)
    result.best_standard_ratio = best_std
    result.best_standard_score = result.ratio_score[best_std]

    # ── Continuous golden-section search (ratio 1.0 … 36.0) ──────────────
    def _obj(n: float) -> float:
        return _aggregate_vswr_penalty(band_impedances, n)

    cont_n, cont_score = _golden_section_min(_obj, 1.0, 36.0)
    result.best_continuous_ratio = round(cont_n, 2)
    result.best_continuous_score = round(cont_score, 4)

    # ── Per-band best ratio (independent search per band) ─────────────────
    for band, R, X in band_impedances:
        def _band_obj(n: float, _R=R, _X=X) -> float:
            return _vswr_for_ratio(_R, _X, n, z0)
        n_opt, _ = _golden_section_min(_band_obj, 1.0, 36.0)
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
    # BUG FIX: ranked passed in is already sliced to top_n, so len(ranked)
    # always printed the top-N limit (e.g. 20), not the real grid size.
    # total_candidates is now passed explicitly from main().
    display_total = total_candidates if total_candidates > 0 else len(ranked)
    ln(f"Total candidates: {display_total}")
    lines.append("")

    # ── TOP 20 RANKING ───────────────────────────────────────────────────
    h1("TOP 20 CANDIDATES  (lower combined score = better)")
    header = (f"  {'#':>3}  {'Wire(m)':>8}  {'CP(m)':>7}  {'CP type':>10}  "
              f"{'Score':>7}  {'mVSWRpen':>9}  {'Avoid':>7}  "
              + "  ".join(f"{b:>7}" for b in bands)
              + "  NEC2")
    lines.append(header)
    lines.append("  " + "─" * (len(header) - 2))

    for rank, r in enumerate(ranked[:20], 1):
        band_cols = "  ".join(
            f"{r.band_vswr.get(b, 999):7.2f}" for b in bands
        )
        nec_flag = "✓" if r.nec2_ok else "emp"
        lines.append(
            f"  {rank:3d}  {r.wire_len_m:8.3f}  {r.cp_len_m:7.3f}  {r.cp_type:>10}  "
            f"{r.score_combined:7.3f}  {r.score_vswr:9.3f}  {r.score_avoidance:7.4f}  "
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
            f"  VSWR=[{band_cols}]  avoid={r.score_avoidance:.4f}"
        )

    # ── BEST CANDIDATE DETAIL ────────────────────────────────────────────
    if ranked:
        best = ranked[0]
        h1("BEST CANDIDATE — DETAILED BREAKDOWN")
        ln(f"Wire length   : {best.wire_len_m:.3f} m")
        ln(f"CP length     : {best.cp_len_m:.3f} m   ({best.cp_type} orientation)")
        ln(f"Combined score: {best.score_combined:.4f}")
        ln(f"VSWR penalty  : {best.score_vswr:.4f}  (mean across active bands; combined uses mean+1.5×worst)")
        ln(f"Avoidance     : {best.score_avoidance:.4f}  (mean across ALL bands in CSV)")
        ln(f"NEC2 data used: {'YES' if best.nec2_ok else 'NO — empirical model only'}")
        lines.append("")

        ln("Per-band results:")
        ln(f"  {'Band':>8}  {'Active':>6}  {'VSWR(Tx)':>9}  {'Avoid':>8}  {'Rating':>22}  {'VSWR label'}")
        ln("  " + "─" * 80)
        # BUG FIX: show avoidance for ALL bands, VSWR only for active bands.
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
        ln(f"Continuous optimum         : {unun_result.best_continuous_ratio:.2f}:1"
           f"  (mean VSWR penalty {unun_result.best_continuous_score:.4f})")

        # Nearest standard ratio
        std_n = unun_result.best_standard_ratio
        std_score = unun_result.best_standard_score
        ln(f"Best standard ratio        : {std_n:.0f}:1"
           f"  (mean VSWR penalty {std_score:.4f})")

        # Improvement vs current ratio
        cur_score = unun_result.ratio_score.get(unun_ratio)
        if cur_score is not None and cur_score > 0:
            delta = cur_score - std_score
            pct = 100.0 * delta / cur_score if cur_score else 0.0
            if delta > 0.001:
                ln(f"  → Switching to {std_n:.0f}:1 improves mean VSWR penalty"
                   f" by {delta:.4f}  ({pct:.1f} %)")
            else:
                ln(f"  → Current ratio {unun_ratio:.0f}:1 is already optimal"
                   f" among standard values.")

        lines.append("")

        # Standard ratio sweep table
        ln("Standard ratio sweep:")
        hdr_bands = "  ".join(f"{b:>7}" for b in bands)
        ln(f"  {'Ratio':>6}  {'Score':>7}  {hdr_bands}")
        ln("  " + "─" * (6 + 2 + 7 + 2 + max(0, 9 * len(bands))))
        for n in sorted(unun_result.ratio_score.keys()):
            score = unun_result.ratio_score[n]
            bv_cols = "  ".join(
                f"{unun_result.ratio_band_vswr[n].get(b, 999):7.2f}" for b in bands
            )
            marker = " ◄ BEST" if n == std_n else (
                     " ← CURRENT" if n == unun_ratio else "")
            # BUG FIX: {n:5.0f} rounds 1.5 → "2", causing two "2:1" rows.
            # Use {n:.4g} which prints "1.5" for 1.5 and "2" for 2.0.
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
         "The optimal wire avoids being a multiple of λ/2 (voltage maximum: very high Z)"
         " and λ/4 (current maximum: very low Z) on ALL bands in the CSV simultaneously —"
         " including those marked inactive for VSWR scoring.  The avoidance score"
         " quantifies this across all bands: ≥0.20 = ★★★ EXCELLENT."),

        ("Counterpoise length selection",
         "The counterpoise acts as the missing half of the antenna system.  A length near"
         " λ/4 at the operating frequency provides a low-impedance return path.  The"
         " optimizer penalises CP lengths that are resonant (λ/2 or λ/4) on multiple"
         " bands simultaneously — the same logic as for the antenna wire."),

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

def export_best_csv(
    best: CandidateResult,
    calc_rows: List[CalcRow],
    unun_ratio: float,
    out_path: str,
) -> None:
    """
    Write a CSV in nec2_vs_calc_analyzer format pre-filled with the best
    wire/CP lengths so the user can feed it straight back into the analyser.
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

            # BUG FIX: always used the empirical formula for R/X even when
            # NEC2-computed impedances are available in the best candidate.
            # Use NEC2 data first; fall back to empirical only when absent.
            if (cr.band in best.band_R_ant and
                    cr.band in best.band_X_ant and
                    best.nec2_ok):
                R = best.band_R_ant[cr.band]
                X = best.band_X_ant[cr.band]
            else:
                ratio_emp = w / lhalf if lhalf else 0.0
                arg = math.pi * ratio_emp
                cos2 = math.cos(arg) ** 2
                R = max(1.0, 50 * (80 ** cos2))   # clamp R ≥ 1 Ω
                X = 1500 * math.sin(2 * arg)

            g = math.hypot(R - 50, X) / math.hypot(R + 50, X)
            vswr_no = (1 + g) / (1 - g) if g < 1 else 999.0

            ratio = w / lhalf if lhalf else 0.0
            frac = ratio % 1.0
            # Use the same corrected avoidance formula as score_candidate
            d_half    = min(frac, 1.0 - frac)
            d_quarter = abs(frac - 0.5)
            avoid = min(d_half, d_quarter)

            if avoid >= 0.20:
                rating = "★★★ EXCELLENT"
            elif avoid >= 0.12:
                rating = "★★  GOOD"
            elif avoid >= 0.06:
                rating = "★   MARGINAL"
            else:
                rating = "✗   RESONANCE RISK"

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
                "vswr_with_cp":   "",
                "Z_eff_ohm":      "",
                "Zcp_ohm":        "",
                "unun_ratio":     unun_ratio,
                "avoidance_score":round(avoid, 4),
                "quality_rating": rating,
                "cp_len_m":       best.cp_len_m,
                "cp_height_m":    cr.cp_height_m if cr.cp_height_m else 0.5,
                "num_radials":    cr.num_radials if cr.num_radials else 1,
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
    ax2.scatter([r.score_vswr for r in results],
                [r.score_avoidance for r in results],
                s=10, alpha=0.4, color="gray", label="All")
    ax2.scatter([r.score_vswr for r in pareto],
                [r.score_avoidance for r in pareto],
                s=60, marker="*", color="blue", label="Pareto")
    if ranked:
        ax2.scatter(ranked[0].score_vswr, ranked[0].score_avoidance,
                    s=100, marker="D", color="black", label="Best")
    ax2.set_xlabel("VSWR penalty (lower=better)")
    ax2.set_ylabel("Avoidance score (higher=better)")
    ax2.set_title("Pareto Space")
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
            VSWR across all active bands defined in a nec2_vs_calc_analyzer CSV.

            By default the search window is ±2 m around the wire and CP lengths
            in the CSV.  Use --margin to widen it, or --wire-min/max and
            --cp-min/max to set explicit bounds.

            Two evaluation modes:
              empirical  — fast, uses the same R/X formulas as the spreadsheet
              nec2       — accurate, runs nec2c for each candidate geometry

            The optimizer calls nec2_vs_calc_analyzer.py's core routines directly,
            so the CSV format is identical to that tool.

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
    p.add_argument("--csv", metavar="FILE", required=True,
                   help="Band CSV in nec2_vs_calc_analyzer format (required).")
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

    # ── Load CSV ──────────────────────────────────────────────────────────
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
        if ";" in _first_line and "," not in _first_line.split(";")[1:]:
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

    active = [r for r in calc_rows if r.active]
    if not active:
        print(f"{Fore.RED}  No active bands found in CSV."
              f"  Set the 'active' column to YES for at least one band.{Style.RESET_ALL}")
        sys.exit(1)

    print(f"  Active bands  : {len(active)}  ({', '.join(r.band for r in active)})")
    print(f"  Frequencies   : {[r.freq_mhz for r in active]}")

    # ── UnUn ratio ────────────────────────────────────────────────────────
    if args.unun is not None:
        unun_ratio = args.unun
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

    # ── Resolve range / height defaults from CSV ─────────────────────────
    # Default margin: search ±args.margin metres around the CSV lengths.
    # This keeps the optimizer close to the physically intended design.
    # Use --margin to widen deliberately when you want to explore further.
    _MARGIN = args.margin

    # Helper: extract a mean value for an attribute across rows that have it.
    def _csv_mean(attr: str, rows, fallback: float) -> float:
        vals = [getattr(r, attr) for r in rows
                if hasattr(r, attr) and getattr(r, attr) not in (None, 0)]
        return (sum(vals) / len(vals)) if vals else fallback

    # Wire length range
    if args.wire_min is None or args.wire_max is None:
        csv_wire = _csv_mean("wire_len_m", active,
                             fallback=_csv_mean("wire_len_m", calc_rows, 10.0))
        print(f"  Search margin : ±{_MARGIN} m around CSV wire {csv_wire:.3f} m  "
              f"(use --margin to change)")
        if args.wire_min is None:
            args.wire_min = max(1.0, round(csv_wire - _MARGIN, 3))
            print(f"  --wire-min    : {args.wire_min} m")
        if args.wire_max is None:
            args.wire_max = round(csv_wire + _MARGIN, 3)
            print(f"  --wire-max    : {args.wire_max} m")

    # Counterpoise length range
    if args.cp_min is None or args.cp_max is None:
        csv_cp = _csv_mean("cp_len_m", active,
                           fallback=_csv_mean("cp_len_m", calc_rows, 4.0))
        print(f"  CP margin     : ±{_MARGIN} m around CSV CP {csv_cp:.3f} m  "
              f"(use --margin to change)")
        if args.cp_min is None:
            args.cp_min = max(1.0, round(csv_cp - _MARGIN, 3))
            print(f"  --cp-min      : {args.cp_min} m")
        if args.cp_max is None:
            args.cp_max = round(csv_cp + _MARGIN, 3)
            print(f"  --cp-max      : {args.cp_max} m")

    # Heights
    if args.wire_height is None:
        csv_wh = _csv_mean("wire_height_m", active,
                           fallback=_csv_mean("wire_height_m", calc_rows,
                                              DEFAULT_HEIGHT_M))
        args.wire_height = csv_wh if csv_wh else DEFAULT_HEIGHT_M
        print(f"  --wire-height : {args.wire_height} m  (from CSV)")

    if args.cp_height is None:
        csv_cph = _csv_mean("cp_height_m", active,
                            fallback=_csv_mean("cp_height_m", calc_rows, 0.5))
        args.cp_height = csv_cph if csv_cph else 0.5
        print(f"  --cp-height   : {args.cp_height} m  (from CSV)")

    # ── Build search grid ────────────────────────────────────────────────
    wire_range = (args.wire_min, args.wire_max, args.wire_step)
    cp_range   = (args.cp_min,  args.cp_max,  args.cp_step)
    grid = build_search_grid(calc_rows, *wire_range, *cp_range)
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
        results = empirical_sweep(
            grid=grid,
            calc_rows=calc_rows,
            unun_ratio=unun_ratio,
            cp_type=args.cp_type if args.cp_type != "both" else "horizontal",
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
            active_freqs = [cr.freq_mhz for cr in calc_rows if cr.active]
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
                        freqs_mhz=active_freqs,
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
        cur_score = unun_result.ratio_score.get(unun_ratio, 999.0)
        std_score = unun_result.best_standard_score

        print(f"\n  {Fore.CYAN}UnUn Analysis (best geometry: "
              f"{best.wire_len_m:.3f} m / {best.cp_len_m:.3f} m):{Style.RESET_ALL}")
        print(f"    Current ratio    : {unun_ratio:.0f}:1"
              f"  (VSWR penalty {cur_score:.4f})")
        print(f"    Best standard    : {std_n:.0f}:1"
              f"  (VSWR penalty {std_score:.4f})")
        print(f"    Continuous opt.  : {cont_n:.2f}:1"
              f"  (VSWR penalty {unun_result.best_continuous_score:.4f})")

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

    # Use the recommended UnUn ratio for the CSV export if it's better
    export_unun = unun_ratio
    if unun_result is not None:
        std_n = unun_result.best_standard_ratio
        cur_score = unun_result.ratio_score.get(unun_ratio, 999.0)
        if (unun_result.best_standard_score < cur_score - 0.001
                and abs(std_n - unun_ratio) > 0.5):
            export_unun = std_n
            print(f"  ℹ  CSV export uses recommended UnUn {export_unun:.0f}:1"
                  f" (instead of {unun_ratio:.0f}:1)")

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
