#!/usr/bin/env python3
"""
=============================================================================
  NEC2 vs. Long Wire Antenna Calculator — Exhaustive Comparison Analyzer
  Author: based on LU3VEA LongWire_Antenna_Calculator.xlsx (CC0 v1.0)
  Usage:  python nec2_vs_calc_analyzer.py [options]

  All arguments are optional; any omitted value is requested interactively.
  Run with --help for the full argument reference.
=============================================================================

This script:
  1. Reads one or two NEC2 output files (.out / .nec):
       • Horizontal counterpoise  (antenna H + counterpoise H)
       • Vertical   counterpoise  (antenna H + counterpoise V)
  2. Reads a CSV with the spreadsheet-calculated reference values.
  3. Computes every comparison metric and produces an exhaustive report:
       • Feedpoint impedance (R, X, |Z|, phase) per frequency
       • VSWR (simulated vs. empirical model)
       • Gain (dBi), take-off angle, front-to-back
       • Counterpoise effect: Δ-impedance, Δ-VSWR between the two NEC2 runs
       • Per-band summary table with green/yellow/red flags
       • Detailed physical interpretation of each discrepancy

CSV FORMAT  — see the section "CSV COLUMN GUIDE" at the bottom of this file.
"""

import os
import re
import sys
import csv
import math
import argparse
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional pretty-printing / colour support
# ---------------------------------------------------------------------------
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    class _C:                            # no-op colour stub
        RED = YELLOW = GREEN = CYAN = MAGENTA = BLUE = WHITE = ""
        BRIGHT = RESET_ALL = ""
    Fore = Style = _C()
    HAS_COLOR = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
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
        # FIX #4: always round to `decimals` places so that identical MHz
        # values written with different trailing digits in the two .out files
        # still produce matching keys when the two maps are intersected.
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
    num_radials:    int   = 1


# ═══════════════════════════════════════════════════════════════════════════
# NEC2 OUTPUT PARSER
# ═══════════════════════════════════════════════════════════════════════════

# Compiled patterns
# ---------------------------------------------------------------------------
# FIX #1 — Extended regex patterns covering all common NEC2 output variants:
#   nec2c, 4nec2, xnec2c, EZNEC export.
#   Previous patterns missed bare "*** FREQUENCY" star-bordered headers and
#   "Z = R +j X" tabular impedance blocks used by nec2c standard output.
# ---------------------------------------------------------------------------

# Frequency markers — covers all known NEC2 front-end formats
_RE_FREQ    = re.compile(r'FREQUENCY\s*=\s*([\d.E+\-]+)\s*MHZ',       re.IGNORECASE)
_RE_FREQ2   = re.compile(r'FREQ\s*=\s*([\d.E+\-]+)\s*MHZ',            re.IGNORECASE)
# nec2c standard output: "  ***** FREQUENCY = 7.150000  MHZ  *****"
_RE_FREQ3   = re.compile(r'\*+\s*FREQUENCY\s*=\s*([\d.E+\-]+)\s*MHZ', re.IGNORECASE)
# 4nec2 / EZNEC: "Frequency =  7.150 MHz"  (already covered by _RE_FREQ but
# some exports use lower-case MHz — adding as explicit fallback)
_RE_FREQ4   = re.compile(r'Frequency\s*=\s*([\d.E+\-]+)\s*MHz',       re.IGNORECASE)
# xnec2c and some FORTRAN outputs: bare float before "MHZ" on its own line
_RE_FREQ5   = re.compile(r'^\s*([\d.]{3,})\s+MHZ\b', re.IGNORECASE | re.MULTILINE)
# FIX-B1: nec2c standard output uses a colon separator:
#   "                                FREQUENCY : 7.0000E+00 MHz"
# None of the patterns above match this; add an explicit colon variant.
_RE_FREQ6   = re.compile(r'FREQUENCY\s*:\s*([\d.E+\-]+)\s*MHz', re.IGNORECASE)

# All frequency patterns collected for the multi-pass scan
_ALL_FREQ_RES = [_RE_FREQ, _RE_FREQ2, _RE_FREQ3, _RE_FREQ4, _RE_FREQ5, _RE_FREQ6]

# Impedance — IMPEDANCE = (R, X) inline style
_RE_IMPEDANCE = re.compile(
    r'IMPEDANCE\s*=\s*\(\s*([\-\d.E+]+)\s*,\s*([\-\d.E+]+)\s*\)', re.IGNORECASE)

# nec2c ANTENNA INPUT PARAMETERS table:
# Columns: TAG  SEG  V_REAL  V_IMAG  I_REAL  I_IMAG  Z_REAL  Z_IMAG  Y_REAL  Y_IMAG
# Bug G fix: gate the data row match to the ANTENNA INPUT PARAMETERS section header
# so we never accidentally match the CURRENTS AND LOCATION table rows, which share
# the same column structure but carry I and phase in groups 1/2 instead of Z_R/Z_I.
_RE_ANTINPUT_SECTION = re.compile(
    r'ANTENNA INPUT PARAMETERS', re.IGNORECASE)
_RE_ANTINPUT = re.compile(
    r'^\s*\d+\s+\d+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+[\-\d.E+]+\s+'
    r'([\-\d.E+]+)\s+([\-\d.E+]+)',
    re.IGNORECASE | re.MULTILINE)

# ZIN label style (EZNEC / MMANA exports): "ZIN  R  X" or "INPUT IMPEDANCE: R X"
_RE_ZIN_ROW = re.compile(
    r'(?:INPUT\s+IMPEDANCE|ZIN)\s*[\s\-:=]+([\-\d.Ee+]+)\s*[+j]?\s*([\-\d.Ee+]+)',
    re.IGNORECASE)

# xnec2c / 4nec2 tabular impedance: "Z =  R +j X"  or  "Z =  R -j X"
_RE_Z_TABLE = re.compile(
    r'Z\s*=\s*([\-\d.E+]+)\s*([+\-])\s*j\s*([\d.E+]+)', re.IGNORECASE)

_RE_GAIN_DB  = re.compile(r'POWER\s+GAIN\s*=\s*([\-\d.E+]+)\s*DB',   re.IGNORECASE)
_RE_GAIN_MAX = re.compile(r'MAXIMUM\s+GAIN\s*=\s*([\-\d.E+]+)\s*DB', re.IGNORECASE)
_RE_EFF = re.compile(
    r'(?:RADIATION\s+EFFICIENCY|EFFICIENCY)\s*=\s*([\d.E+\-]+)', re.IGNORECASE)

# FIX-B3: nec2c writes metadata inside a plain COMMENTS block, not as NEC2
# "CM" card lines.  The actual text is:
#   "Wire length: 13.3 m  |  Counterpoise: 10.0 m  |  Height: 5.0 m"
# Drop the leading "CM\s+" requirement so both formats are matched.
_RE_WIRE_CM = re.compile(r'Wire\s+length:\s*([\d.]+)\s*m',             re.IGNORECASE)
_RE_CP_CM   = re.compile(
    r'Counterpoise(?:\s*\(vertical\))?\s*:\s*([\d.]+)\s*m',            re.IGNORECASE)
_RE_CP_VERT = re.compile(r'counterpoise\s*\(vertical\)',                re.IGNORECASE)

# RP (radiation pattern) table row: THETA  PHI  VERTC  HORIZ  TOTAL  ...
# BUG 2 FIX: The original pattern matched ANY 5-column numeric line, which
# includes the CURRENTS AND LOCATION table rows (seg# tag# x y z ...).
# Those rows begin with small positive integers (seg/tag) and z-values like
# 0.1167 (height in wavelengths), producing fake gain = 0.1167 and fake
# TOA = 1, 2, 3 ... (segment numbers).
#
# Fix strategy: only search for RP rows within RADIATION PATTERNS sub-blocks.
# _RE_RP_SECTION marks where each RP section starts inside a frequency block;
# _RE_RP_ROW is then applied only to the text after that marker.
# Additionally constrain THETA to [0, 90] (NEC2 ground-reflection RP uses
# elevation 0–90°) so stray numeric lines outside the section still can't
# match: the current-table SEG numbers go 1..18, which satisfies that range,
# so the section-gating is the primary guard.
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


# ---------------------------------------------------------------------------
# FIX #2 — Parse counterpoise geometry from the .nec INPUT deck (GW cards).
#   The .out file never contains geometry; the old code always read 0.000 m.
#   This function reads the sibling .nec file (same basename, .nec extension)
#   and extracts wire lengths from GW cards to identify the CP wire.
# ---------------------------------------------------------------------------

def _parse_cp_from_nec_deck(out_filepath: str, run: NEC2Run,
                             explicit_nec_path: Optional[str] = None):
    """
    Try to find a companion .nec input deck and parse CP length from GW cards.
    Wire 1 is assumed to be the antenna; Wire 2 (if present) is the CP.
    Also detects CP type (horizontal vs vertical) from z-coordinates.

    BUG 4 FIX: accepts an explicit_nec_path so the caller can supply a companion
    file whose basename differs from the .out file (e.g. antenna_horizontal.nec
    paired with antenna_counterpoise_horizontal.out).  If explicit_nec_path is
    given and the file exists it is used directly; otherwise the old same-basename
    search is attempted as a fallback.
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
        return  # no input deck found — leave cp_len_m as parsed from CM comments

    wires = []
    try:
        with open(nec_path, 'r', errors='replace') as fh:
            for line in fh:
                # GW  tag  segs  x1  y1  z1  x2  y2  z2  radius
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
                # Pre-flight check for RP card
                if re.match(r'^RP\b', line, re.IGNORECASE):
                    run._has_rp_card = True
    except OSError:
        return

    if not wires:
        return

    # Wire 1 = antenna; wire 2+ = counterpoise (pick longest non-antenna wire)
    cp_wires = [w for w in wires if w['tag'] != 1]
    if not cp_wires:
        return

    cp = max(cp_wires, key=lambda w: w['length'])
    run.cp_len_m = round(cp['length'], 3)

    # Classify orientation: if dz > 60% of length → vertical, else horizontal
    if cp['length'] > 0 and cp['dz'] / cp['length'] > 0.6:
        run.cp_type = 'vertical'
    else:
        run.cp_type = 'horizontal'

    # Bug E fix: mark that cp_len_m came from actual GW geometry, not CM comment
    run._cp_from_deck = True


def parse_nec2_output(filepath: str, debug: bool = False,
                      explicit_nec_path: Optional[str] = None) -> NEC2Run:
    """
    Parse a NEC2 .out file produced by nec2c, 4nec2, xnec2c, or EZNEC export.

    FIX #1: Uses five frequency-marker patterns in priority order so that
            nec2c star-bordered headers, 4nec2 "Frequency =" lines, and
            xnec2c bare-number lines are all recognised.
    FIX #1: Adds a fourth impedance-extraction method: "Z = R +j X" table.
    FIX #1: debug=True prints the first 60 lines of the file so you can see
            which tokens the parser is looking for vs what is actually there.
    FIX #2: After parsing, calls _parse_cp_from_nec_deck() to get accurate
            CP length and type from the companion .nec geometry file.
    FIX #8: Warns if no RP card was found in the .nec deck.
    """
    run = NEC2Run(filepath=filepath)
    run._has_rp_card = False  # updated below once .out text is loaded
    run._cp_from_deck = False  # Bug E fix: set True only when .nec GW geometry is found

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"NEC2 file not found: {filepath}")

    with open(filepath, 'r', errors='replace') as fh:
        text = fh.read()

    # Detect RP card from the .out file itself (reproduced as "DATA CARD No: N RP …").
    # _parse_cp_from_nec_deck also sets this flag when a .nec sibling exists, but
    # the .out file is always present so it is the primary detection path.
    # Two patterns cover all nec2c output styles:
    #   "  DATA CARD No:   6 RP   0 …"  (standard nec2c echo)
    #   "RP 0 …"                         (bare card, some front-ends)
    run._has_rp_card = bool(
        re.search(r'DATA\s+CARD[^\n]*\bRP\b', text, re.IGNORECASE) or
        re.search(r'^\s*RP\b',                text, re.IGNORECASE | re.MULTILINE)
    )

    # ── FIX #1: diagnostic dump ─────────────────────────────────────────────
    if debug:
        print(f"\n{'─'*60}")
        print(f"  DEBUG: first 60 lines of {filepath}")
        print(f"{'─'*60}")
        for i, line in enumerate(text.splitlines()[:60], 1):
            print(f"  {i:3d}: {repr(line)}")
        print(f"{'─'*60}\n")

    # --- meta from CM comments ---
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

    # ── FIX #2: override CP geometry from companion .nec deck ───────────────
    # BUG 4 FIX: forward the explicit_nec_path so a user-supplied filename
    # that differs from the .out basename is honoured without guessing.
    _parse_cp_from_nec_deck(filepath, run, explicit_nec_path=explicit_nec_path)

    # --- split into per-frequency blocks ---
    # FIX #1: try all five frequency patterns; use the one that finds the most hits
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

    # Append sentinel
    freq_positions.append((len(text), 0.0))

    for idx, (pos, freq_mhz) in enumerate(freq_positions[:-1]):
        block = text[pos: freq_positions[idx + 1][0]]
        fp = FreqPoint(freq_mhz=round(freq_mhz, 4))

        # --- impedance (four methods, first match wins) ---
        # Method 1: IMPEDANCE = (R, X)
        m = _RE_IMPEDANCE.search(block)
        if m:
            fp.R_ohm = _safe_float(m.group(1))
            fp.X_ohm = _safe_float(m.group(2))

        # Method 2: ANTENNA INPUT PARAMETERS table
        # Bug G fix: search only within the text after the section header AND
        # before the CURRENTS AND LOCATION section, which shares the exact same
        # column structure.  Without the upper bound the regex matches the first
        # CURRENTS row (not the impedance row) whenever CURRENTS precedes the
        # impedance line — a layout that is possible in non-standard NEC2 outputs.
        if fp.R_ohm == 0.0:
            sec_m = _RE_ANTINPUT_SECTION.search(block)
            antinput_text = block[sec_m.start():] if sec_m else ""
            # Slice off everything from CURRENTS AND LOCATION onwards so that
            # _RE_ANTINPUT can never accidentally match a current-table row.
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

        # FIX #1 — Method 4: "Z = R +j X"  or  "Z = R -j X" table
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
                fp.efficiency /= 100.0  # was percentage

        # --- RP table: find max gain and take-off angle ---
        # BUG 2 FIX: Only search for RP rows within the RADIATION PATTERNS
        # sub-section of this frequency block.  Searching the whole block
        # matched CURRENTS AND LOCATION table rows (seg# tag# x y z ...),
        # which have the same column count, producing fake gain values equal
        # to the segment z-height in wavelengths and fake TOA = seg numbers.
        rp_gains: List[Tuple[float, float, float]] = []  # (theta, phi, dBi)
        rp_sec_m = _RE_RP_SECTION.search(block)
        rp_search_text = block[rp_sec_m.start():] if rp_sec_m else ""
        for rm in _RE_RP_ROW.finditer(rp_search_text):
            theta = _safe_float(rm.group(1))
            phi   = _safe_float(rm.group(2))
            gain  = _safe_float(rm.group(4))  # group 4 = TOTAL column
            # FIX-B5: NEC2 outputs -999.99 dB as a sentinel for below-ground
            # or invalid radiation pattern points (theta = 90° ground plane).
            # Accepting the sentinel causes the reported max gain to read
            # ~-999 dBi on every band.  Skip any value ≤ -200 dB.
            if gain <= -200.0:
                continue
            rp_gains.append((theta, phi, gain))

        if rp_gains:
            best = max(rp_gains, key=lambda t: t[2])
            fp.gain_dbi = best[2]
            # BUG 3 FIX: NEC2 RP THETA is measured FROM THE ZENITH
            # (0° = straight up, 90° = horizon), which is the OPPOSITE of the
            # ham-radio take-off angle convention (0° = horizon = DX, 90° =
            # zenith = NVIS).  Storing NEC2 THETA directly made the report
            # show "take-off = 0°" for a pure NVIS antenna, which reads as
            # excellent DX to anyone not aware of the convention inversion.
            # Fix: convert here so that all downstream code, labels, and the
            # NVIS flag all use the correct elevation-from-horizon angle.
            fp.toa_deg = 90.0 - best[0]  # ham TOA = 90° − NEC2_THETA

        fp.vswr50 = fp.compute_vswr50()
        run.freqs.append(fp)

    return run


def _parse_nec2_fallback(text: str, run: NEC2Run):
    """
    Fallback when no FREQUENCY= markers found with any pattern.
    FIX #1: Tries all impedance extraction methods (including Z= table),
            and uses all five frequency patterns to locate the best candidates.
    """
    imp_matches = list(_RE_IMPEDANCE.finditer(text))

    # Also try Z = R +j X style if no IMPEDANCE= matches
    if not imp_matches:
        imp_matches = list(_RE_Z_TABLE.finditer(text))
        use_z_table = True
    else:
        use_z_table = False

    # Collect all frequency candidates from all patterns
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


# ═══════════════════════════════════════════════════════════════════════════
# CSV READER
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
    "cp_len_m", "cp_height_m", "num_radials",
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
    # DATA fix: only convert a leading-comma decimal separator (European locale)
    # when the entire string is numeric — digits, commas, dots, and an optional
    # leading minus.  A broad s.replace(',', '.') would corrupt string columns
    # that legitimately contain commas (e.g. quality_rating "Good, excellent")
    # and would misparse thousands-separator notation (1,234 → 1.234 ≠ 1234).
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
    # FIX-B2: CSV files exported from European-locale spreadsheets use a
    # comma as the decimal separator AND as the column separator, which makes
    # standard comma-delimited parsing impossible ("7,15" splits into two
    # fields instead of one).  The fix is to export / save the CSV with a
    # semicolon column delimiter (common in European Excel / LibreOffice
    # locales).  We auto-detect the delimiter here so that both the semicolon
    # format (locale commas for decimals) and the standard comma format
    # (period decimals) work without any manual change to this script.
    with open(filepath, newline='', encoding='utf-8-sig') as probe:
        first_line = probe.readline()
    delimiter = ';' if ';' in first_line else ','

    with open(filepath, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        cols_lower = {c.strip().lower() for c in (reader.fieldnames or [])}
        missing = REQUIRED_CSV_COLS - cols_lower
        if missing:
            print(f"\n{Fore.YELLOW}⚠  CSV is missing recommended columns: {missing}")
            print(f"   Script will continue but some comparisons may be limited.{Style.RESET_ALL}\n")
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
            cr.num_radials     = int(_flt(raw, "num_radials", default=1))

            # BUG 1 + BUG 3 COMBINED FIX:
            # The CSV L_over_lhalf was computed against a single fixed reference
            # wavelength (the 160m band), so every row carries the same wrong
            # fraction (e.g. 0.178 for all bands).
            #
            # Naively recomputing from the CSV lambda_half_m column still
            # produces a slightly different ratio than calc_empirical uses,
            # because lambda_half_m is rounded (e.g. 19.93 m vs the exact
            # c/(2f) = 20.965 m at 7.15 MHz). That rounding discrepancy makes
            # Section 2 (which reads cr.R_wire_ohm) disagree with Section 4
            # (which calls calc_empirical directly) — Bug 3.
            #
            # Fix: always derive L_over_lhalf from the exact c/(2f) formula,
            # matching what calc_empirical computes internally.  This makes
            # cr.R_wire_ohm / cr.X_wire_ohm identical to calc_empirical's
            # output and eliminates the cross-section inconsistency.
            if cr.freq_mhz > 0:
                c_mhz = 299.792458
                lambda_half_exact = (c_mhz / cr.freq_mhz) * 0.5
                cr.L_over_lhalf = cr.wire_len_m / lambda_half_exact

            # BUG 1 FIX: Always recompute R_wire / X_wire from the corrected
            # L_over_lhalf (now derived from the correct per-band lambda_half_m).
            # The CSV values were computed from the wrong (160m-reference)
            # L_over_lhalf, so we must override them unconditionally.
            # BUG 5 FIX: also recompute vswr_no_cp from the new R/X so that
            # the three values printed in Section 2 are mutually consistent.
            if cr.L_over_lhalf > 0:
                arg = math.pi * cr.L_over_lhalf
                cr.R_wire_ohm = 50 * (80 ** (math.cos(arg) ** 2))
                cr.X_wire_ohm = 1500 * math.sin(2 * arg)
                # BUG 5 FIX: keep vswr_no_cp consistent with the recomputed R/X
                # (antenna side, ref 50 Ω, no UnUn — matches what Section 2 displays).
                _g5 = math.hypot(cr.R_wire_ohm - 50, cr.X_wire_ohm) / \
                      math.hypot(cr.R_wire_ohm + 50, cr.X_wire_ohm)
                cr.vswr_no_cp = (1 + _g5) / (1 - _g5) if _g5 < 1 else 999.0

            # FIX #7 — Recompute avoidance_score per band from actual L/λ½.
            # The CSV stores a single wire-length score from the Length Sweep
            # sheet, which is identical for every row and therefore wrong for
            # multi-band comparisons.  The correct score measures how far this
            # specific wire is from resonance at THIS band's frequency.
            if cr.L_over_lhalf > 0:
                frac = cr.L_over_lhalf % 1.0   # fractional part of L/(λ/2)
                computed_score = min(frac, 1.0 - frac)  # 0=resonance, 0.5=best
                # Only override the CSV value if it looks like a copy-paste
                # artifact (all rows identical) — keep user-supplied per-band
                # values if they actually differ between rows.
                cr._computed_avoidance = computed_score
            else:
                cr._computed_avoidance = cr.avoidance_score

            rows.append(cr)

    # FIX #7 — Decide whether to use CSV avoidance scores or computed ones.
    # The comment in the per-row block above promises "only override when all
    # rows are identical (copy-paste artifact)", but the old code set
    # _computed_avoidance unconditionally and _avoidance_score() always returned
    # it, silently discarding meaningful per-band CSV values.
    #
    # Correct implementation:
    #   • Collect all non-zero CSV avoidance scores across all rows.
    #   • If every row has the same value (single unique score) — that is the
    #     classic copy-paste artifact from the Length Sweep sheet where one
    #     wire-level score is pasted into every band cell.  In that case use the
    #     per-band computed scores.
    #   • If the scores differ between rows the user supplied genuine per-band
    #     values; keep them and set _computed_avoidance = csv value so
    #     _avoidance_score() returns the original.
    all_csv_scores = [r.avoidance_score for r in rows if r.avoidance_score > 0]
    use_computed = (len(set(all_csv_scores)) <= 1)  # True = uniform/absent → override

    for r in rows:
        if use_computed:
            # Keep _computed_avoidance as already set per-row above (from L/λ½).
            pass
        else:
            # Distinct per-band CSV values — honour them when present (> 0).
            # FIX A: when csv_score == 0 the cell was blank in the spreadsheet
            # (not a genuine "zero avoidance" value).  In that case keep the
            # per-row L/λ½ derived value that was computed in the loop above
            # rather than overwriting it with 0.0.
            if r.avoidance_score > 0:
                r._computed_avoidance = r.avoidance_score
            # else: leave _computed_avoidance as set from L/λ½ in the per-row block

    return rows


def _avoidance_score(cr: 'CalcRow') -> float:
    """
    FIX #7: Return the per-band avoidance score, preferring the value
    computed from L/λ½ over the potentially-uniform CSV value.
    """
    return getattr(cr, '_computed_avoidance', cr.avoidance_score)


def _avoidance_rating(score: float) -> str:
    """Map avoidance score to a star rating string."""
    if score >= 0.20:
        return "★★★ EXCELLENT"
    elif score >= 0.12:
        return "★★  GOOD"
    elif score >= 0.06:
        return "★   MARGINAL"
    else:
        return "✗   RESONANCE RISK"


# ═══════════════════════════════════════════════════════════════════════════
# EMPIRICAL MODEL RE-CALCULATION  (same formulas as spreadsheet)
# ═══════════════════════════════════════════════════════════════════════════

def calc_empirical(wire_len_m: float, freq_mhz: float,
                   unun_ratio: float = 1.0) -> Tuple[float, float, float]:
    """
    Returns (R_wire_ohm, X_wire_ohm, vswr50) using the spreadsheet empirical model:
      R = 50 * 80^cos²(π * L/λ½)
      X = 1500 * sin(2π * L/λ½)

    FIX #6: The UnUn is an impedance transformer, not a power divider.
    A N:1 UnUn presents Z_feed / N to the coax, so we divide R and X by N
    (not N²).  The VSWR returned is what the transmitter actually sees through
    the balun — which is the quantity that matters for matching assessment.
    The raw wire impedance (R_wire, X_wire) is returned unchanged so the
    report can still show both the antenna-side and coax-side values.
    """
    c_mhz = 299.792458   # speed of light / 1e6 → MHz·m/s
    lambda_half = (c_mhz / freq_mhz) * 0.5
    if lambda_half <= 0:
        return 0.0, 0.0, 99.0
    ratio = wire_len_m / lambda_half
    arg = math.pi * ratio
    R = 50 * (80 ** (math.cos(arg) ** 2))
    X = 1500 * math.sin(2 * arg)
    # FIX #6: correct UnUn impedance transformation — divide by N, not N²
    # (an ideal N:1 UnUn transforms Z by factor N, so Z_coax = Z_antenna / N)
    R_in = R / unun_ratio if unun_ratio > 0 else R
    X_in = X / unun_ratio if unun_ratio > 0 else X
    Z0 = 50.0
    g = math.hypot(R_in - Z0, X_in) / math.hypot(R_in + Z0, X_in)
    vswr = (1 + g) / (1 - g) if g < 1 else 999.0
    return R, X, vswr


# ═══════════════════════════════════════════════════════════════════════════
# COMPARISON ENGINE
# ═══════════════════════════════════════════════════════════════════════════

VSWR_THRESHOLDS = {"excellent": 1.5, "good": 3.0, "marginal": 6.0}

def _vswr_label(v: float) -> str:
    if v <= 1.5:
        return f"{Fore.GREEN}EXCELLENT{Style.RESET_ALL}"
    elif v <= 3.0:
        return f"{Fore.CYAN}GOOD     {Style.RESET_ALL}"
    elif v <= 6.0:
        return f"{Fore.YELLOW}MARGINAL {Style.RESET_ALL}"
    else:
        return f"{Fore.RED}POOR     {Style.RESET_ALL}"


def _delta_arrow(delta: float, threshold: float = 1.0) -> str:
    if abs(delta) < threshold:
        return "≈"
    return ("▲ +" if delta > 0 else "▼ ") + f"{delta:+.1f}"


def _impedance_region(R: float, X: float) -> str:
    """Physical interpretation of impedance region."""
    Z = math.hypot(R, X)
    if Z < 30:
        return "Near λ/4 (very low Z – current maximum)"
    elif Z > 1500:
        return "Near λ/2 (very high Z – voltage maximum)"
    elif abs(X) < 0.15 * R:
        return "Predominantly resistive (good match region)"
    elif X > 0:
        return "Inductive reactance dominant"
    else:
        return "Capacitive reactance dominant"


def analyse_model_vs_nec(
    run_h: Optional[NEC2Run],
    run_v: Optional[NEC2Run],
    calc_rows: List[CalcRow],
    wire_len_m: float,
    unun_ratio: float = 1.0,
) -> str:
    """
    Core analysis function.  Returns a multi-section text report.
    """
    lines: List[str] = []
    SEP  = "═" * 80
    SEP2 = "─" * 80

    def h1(title):
        lines.append("")
        lines.append(SEP)
        lines.append(f"  {title}")
        lines.append(SEP)

    def h2(title):
        lines.append("")
        lines.append(f"  ── {title} " + "─" * max(2, 75 - len(title)))

    def info(msg):
        lines.append(f"  {msg}")

    def warn(msg):
        lines.append(f"  {Fore.YELLOW}⚠  {msg}{Style.RESET_ALL}")

    def good(msg):
        lines.append(f"  {Fore.GREEN}✔  {msg}{Style.RESET_ALL}")

    def bad(msg):
        lines.append(f"  {Fore.RED}✖  {msg}{Style.RESET_ALL}")

    def blank():
        lines.append("")

    # -----------------------------------------------------------------------
    # HEADER
    # -----------------------------------------------------------------------
    h1("NEC2 SIMULATION vs. EMPIRICAL MODEL — EXHAUSTIVE COMPARISON REPORT")
    info(f"Antenna wire length  : {wire_len_m:.3f} m")
    info(f"UnUn ratio applied   : {unun_ratio:.2f}:1")
    if run_h:
        info(f"NEC2 file (horiz. CP): {run_h.filepath}")
        cp_src_h = "GW geometry" if getattr(run_h, '_cp_from_deck', False) else "CM comment — co-locate .nec with .out for exact value"
        info(f"   CP length          : {run_h.cp_len_m:.3f} m  |  type: {run_h.cp_type}  |  source: {cp_src_h}")
    if run_v:
        info(f"NEC2 file (vert.  CP): {run_v.filepath}")
        cp_src_v = "GW geometry" if getattr(run_v, '_cp_from_deck', False) else "CM comment — co-locate .nec with .out for exact value"
        info(f"   CP length          : {run_v.cp_len_m:.3f} m  |  type: {run_v.cp_type}  |  source: {cp_src_v}")
    info(f"Spreadsheet CSV rows : {len(calc_rows)}")
    active_rows = [r for r in calc_rows if r.active]
    info(f"Active bands in CSV  : {len(active_rows)} "
         f"({', '.join(r.band for r in active_rows)})")

    # -----------------------------------------------------------------------
    # BUG 1 FIX: Warn when the CSV unun_ratio differs from the user-entered
    # value so the mismatch is never silent.  All VSWR calculations in this
    # report use the user-entered unun_ratio; the CSV column is informational.
    _csv_ununs_in_report = {r.unun_ratio for r in calc_rows if r.unun_ratio > 0}
    for _csv_u in _csv_ununs_in_report:
        if abs(_csv_u - unun_ratio) > 0.1:
            warn(f"CSV unun_ratio={_csv_u:.0f} differs from user-entered "
                 f"{unun_ratio:.0f}. Spreadsheet VSWR values were computed with "
                 f"{_csv_u:.0f}:1. Re-run and enter {_csv_u:.0f} at the UnUn "
                 f"prompt for a consistent comparison.")

    # SECTION 1 — NEC2 Frequency Sweep Summary
    # -----------------------------------------------------------------------
    for run, label in [(run_h, "HORIZONTAL CP"), (run_v, "VERTICAL CP")]:
        if run is None:
            continue
        h1(f"SECTION 1 — NEC2 IMPEDANCE SWEEP  [{label}]")
        info(f"  {'Freq':>8}  {'R (Ω)':>10}  {'X (Ω)':>10}  {'|Z| (Ω)':>10}  "
             f"{'∠ (°)':>7}  {'VSWR':>7}  {'Gain':>7}  Region")
        info(SEP2)
        for fp in sorted(run.freqs, key=lambda p: p.freq_mhz):
            vswr_str = f"{fp.vswr50:7.2f}"
            region   = _impedance_region(fp.R_ohm, fp.X_ohm)
            gain_str = f"{fp.gain_dbi:+.2f} dBi" if fp.gain_dbi != 0.0 else "  n/a  "
            info(f"  {fp.freq_mhz:8.3f}  {fp.R_ohm:10.1f}  {fp.X_ohm:+10.1f}  "
                 f"{fp.Z_mag:10.1f}  {fp.Z_phase_deg:+7.1f}  "
                 f"{vswr_str}  {gain_str}  {region}")

    # -----------------------------------------------------------------------
    # SECTION 2 — Per-Band: NEC2 vs. Empirical Model
    # -----------------------------------------------------------------------
    h1("SECTION 2 — PER-BAND: NEC2 vs. EMPIRICAL MODEL (VSWR/IMPEDANCE)")
    blank()
    # Build index: for each active calc_row, find nearest NEC2 freq point
    active = [r for r in calc_rows if r.active]
    if not active:
        warn("No active bands found in CSV — skipping per-band comparison.")
    else:
        for cr in active:
            h2(f"Band {cr.band}  —  f_center = {cr.freq_mhz:.4f} MHz")
            info(f"  Wire L = {cr.wire_len_m:.3f} m  →  L/λ½ = {cr.L_over_lhalf:.4f}  "
                 f"({cr.L_over_lhalf:.3f}×λ/2)")

            # ---- Empirical model recap ----
            # FIX #6: show both raw-wire VSWR and post-UnUn VSWR
            # Bug A fix: always use the global unun_ratio passed by the caller.
            # The CSV column cr.unun_ratio may differ from the user-entered value
            # (e.g. CSV has 27, user entered 9), causing silent inconsistencies
            # across sections.  The global parameter is the single source of truth.
            # FIX B: use cr.wire_len_m (from the CSV row) instead of the global
            # wire_len_m for the empirical model calls in this section so that
            # cr.R_wire_ohm / cr.X_wire_ohm (which were derived from cr.wire_len_m
            # in load_csv) and calc_empirical are always computed from the same
            # reference length.  If the user typed a different length at the prompt
            # the two values would be inconsistent; using cr.wire_len_m avoids that.
            unun = unun_ratio
            sec2_wire = cr.wire_len_m if cr.wire_len_m > 0 else wire_len_m
            _, _, vswr_unun_no_cp = calc_empirical(sec2_wire, cr.freq_mhz, unun)
            R_cp_coax = (cr.R_wire_ohm / unun) if unun else cr.R_wire_ohm
            X_cp_coax = (cr.X_wire_ohm / unun) if unun else cr.X_wire_ohm

            info(f"  ┌─ EMPIRICAL MODEL (spreadsheet formulas)")
            info(f"  │  R_wire   = {cr.R_wire_ohm:8.1f} Ω  (antenna side)")
            info(f"  │  X_wire   = {cr.X_wire_ohm:+8.1f} Ω   ({_impedance_region(cr.R_wire_ohm, cr.X_wire_ohm)})")
            # BUG 2 FIX: cr.vswr_no_cp in the CSV is computed THROUGH the
            # UnUn (it is the post-transformer VSWR without CP correction),
            # NOT the raw antenna-side VSWR.  The old label "[antenna side,
            # no UnUn]" was factually wrong and confused callers comparing it
            # to NEC2 results.  We now recompute the true antenna-side VSWR
            # from R_wire_ohm / X_wire_ohm (which are always in sync after
            # the BUG 5 fix in load_csv) and show both values with correct
            # labels so the report is internally consistent.
            # True antenna-side VSWR (ref 50 Ω, no UnUn)
            _g_raw = math.hypot(cr.R_wire_ohm - 50, cr.X_wire_ohm) / \
                     math.hypot(cr.R_wire_ohm + 50, cr.X_wire_ohm)
            _vswr_raw = (1 + _g_raw) / (1 - _g_raw) if _g_raw < 1 else 999.0
            info(f"  │  VSWR(antenna side, ref 50Ω, no UnUn) = {_vswr_raw:.2f}"
                 f"  → {_vswr_label(_vswr_raw)}")
            # Also show the CSV vswr_no_cp with a corrected label for traceability
            # FIX #5: note that the CSV vswr_with_cp uses a series CP model
            # which is physically incorrect for end-fed antennas; flag it
            if cr.vswr_no_cp:
                info(f"  │  VSWR(no CP correction, ref 50Ω)  = {cr.vswr_no_cp:.2f}"
                     f"  → {_vswr_label(cr.vswr_no_cp)}"
                     f"  [CSV value — recomputed from R/X above]")
            info(f"  │  VSWR(post-{unun:.0f}:1 UnUn)  = {vswr_unun_no_cp:.2f}  → {_vswr_label(vswr_unun_no_cp)}"
                 f"  [← transmitter sees this]")
            if cr.vswr_with_cp:
                info(f"  │  VSWR(w/ CP, model)    = {cr.vswr_with_cp:.2f}  → {_vswr_label(cr.vswr_with_cp)}"
                     f"  [⚠ series-CP model — may be inaccurate."
                     f" NEC2 result (VSWR_H / VSWR_V) supersedes both model columns.]")
            if cr.Zcp_ohm:
                info(f"  │  Zcp (counterpoise)  = {cr.Zcp_ohm:.1f} Ω  "
                     f"(CP length {cr.cp_len_m:.2f} m, height {cr.cp_height_m:.1f} m, "
                     f"{cr.num_radials} radial(s))")
            # FIX #7: use per-band computed avoidance score
            avoid = _avoidance_score(cr)
            rating = _avoidance_rating(avoid)
            info(f"  │  Avoidance score      = {avoid:.4f}  [{rating}]  (per-band, computed)")

            # ---- NEC2 result lookup ----
            # BUG 5 FIX: The delta comparison must use the SAME reference system
            # for both sides.  NEC2 VSWR is antenna-side (ref 50Ω, no UnUn).
            # The old code compared that against cr.vswr_with_cp which is the
            # model's post-UnUn, post-CP-correction value — apples vs oranges.
            # Correct comparison: NEC2 post-UnUn VSWR  vs  model post-UnUn VSWR
            # (what the transmitter actually sees through the same UnUn).
            for run, rlabel in [
                (run_h, "NEC2 – HORIZ. CP"),
                (run_v, "NEC2 – VERT.  CP"),
            ]:
                if run is None:
                    continue
                fmap = run.freq_map()
                # FIX #3: nearest-neighbor with generous tolerance + report
                # the closest available frequency even when no match is found
                best_key = min(fmap.keys(), key=lambda k: abs(k - cr.freq_mhz)) \
                    if fmap else None
                if best_key is None:
                    warn(f"  No NEC2 data at all in {rlabel} — check parser output above.")
                    continue
                delta_f = best_key - cr.freq_mhz
                # FIX #3: raised tolerance from 0.3 to 0.75 MHz and report
                # the nearest point even when outside tolerance
                if abs(delta_f) > 0.75:
                    warn(f"  No NEC2 data near {cr.freq_mhz:.3f} MHz for {rlabel}"
                         f" (closest: {best_key:.3f} MHz, Δf={delta_f:+.3f} MHz)."
                         f" Add a sweep point at {cr.freq_mhz:.3f} MHz to your NEC2 deck.")
                    continue
                # MEDIUM fix: if the closest NEC2 point is more than ~100 kHz away,
                # quantify the empirical model's impedance change over that frequency
                # offset so the user can judge the interpolation error magnitude.
                if abs(delta_f) > 0.1:
                    R_at_nec, X_at_nec, _ = calc_empirical(wire_len_m, best_key, 1.0)
                    R_at_band, X_at_band, _ = calc_empirical(wire_len_m, cr.freq_mhz, 1.0)
                    dR_interp = R_at_band - R_at_nec
                    dX_interp = X_at_band - X_at_nec
                    warn(f"  Frequency offset {delta_f:+.3f} MHz for {rlabel}: empirical"
                         f" model predicts ΔR≈{dR_interp:+.0f} Ω, ΔX≈{dX_interp:+.0f} Ω"
                         f" across this gap — actual NEC2 shift may differ."
                         f" Consider adding {cr.freq_mhz:.3f} MHz as an explicit FR"
                         f" sweep point for a reliable comparison.")
                fp = fmap[best_key]
                info(f"  ├─ {rlabel}  (NEC2 freq={best_key:.3f} MHz, Δf={delta_f:+.3f} MHz)")
                if cr.R_wire_ohm:
                    info(f"  │  R_sim    = {fp.R_ohm:8.1f} Ω   Δ vs model = {fp.R_ohm - cr.R_wire_ohm:+.1f} Ω  "
                         f"({(fp.R_ohm/cr.R_wire_ohm - 1)*100:+.1f}%)")
                else:
                    info(f"  │  R_sim    = {fp.R_ohm:8.1f} Ω")
                if cr.X_wire_ohm:
                    info(f"  │  X_sim    = {fp.X_ohm:+8.1f} Ω   Δ vs model = {fp.X_ohm - cr.X_wire_ohm:+.1f} Ω")
                else:
                    info(f"  │  X_sim    = {fp.X_ohm:+8.1f} Ω")
                info(f"  │  |Z|_sim  = {fp.Z_mag:8.1f} Ω   phase = {fp.Z_phase_deg:+.1f}°")
                info(f"  │  VSWR_sim = {fp.vswr50:8.2f}  → {_vswr_label(fp.vswr50)}"
                     f"  [antenna side, ref 50Ω]")
                # BUG 5 FIX: compute NEC2 post-UnUn VSWR for apples-to-apples delta.
                # Model post-UnUn VSWR comes from calc_empirical(unun=unun) which
                # divides both R and X by the UnUn ratio before computing VSWR.
                if unun > 1.0:
                    R_in = fp.R_ohm / unun
                    X_in = fp.X_ohm / unun
                    g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
                    vswr_nec2_unun = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
                    info(f"  │  VSWR(post-{unun:.0f}:1 UnUn)= {vswr_nec2_unun:7.2f}  → {_vswr_label(vswr_nec2_unun)}"
                         f"  [← transmitter sees this]")
                else:
                    vswr_nec2_unun = fp.vswr50

                # BUG 5 FIX: compare post-UnUn NEC2 vs post-UnUn model (same reference).
                # FIX B: use cr.wire_len_m here as well so the model reference is
                # always derived from the same wire length as cr.R_wire_ohm.
                _, _, vswr_model_unun = calc_empirical(sec2_wire, cr.freq_mhz, unun)
                delta_vswr = vswr_nec2_unun - vswr_model_unun
                arrow = _delta_arrow(delta_vswr, 0.5)
                info(f"  │  ΔVSWR(post-UnUn) NEC2 vs model = {delta_vswr:+.2f}  {arrow}"
                     f"  [NEC2={vswr_nec2_unun:.2f}  model={vswr_model_unun:.2f}  — same ref]")

                # Interpretation
                if abs(delta_vswr) < 0.5:
                    good(f"   VSWR matches model within ±0.5 → model is reliable for {cr.band}")
                elif delta_vswr > 0:
                    warn(f"   NEC2 VSWR is HIGHER than model by {delta_vswr:.1f}."
                         " Ground loss, near-field coupling, or wire height are likely"
                         " increasing the effective feedpoint impedance beyond the"
                         " infinite-ground assumption in the empirical formula.")
                else:
                    warn(f"   NEC2 VSWR is LOWER than model by {abs(delta_vswr):.1f}."
                         " The antenna may be seeing a more favourable ground or a"
                         " resonance effect not captured by the sinusoidal empirical model.")

                # Gain & efficiency
                if fp.gain_dbi != 0.0:
                    info(f"  │  Gain     = {fp.gain_dbi:+.2f} dBi   take-off = {fp.toa_deg:.1f}°"
                         f"   efficiency = {fp.efficiency*100:.1f}%")
                    if fp.efficiency < 0.5:
                        warn(f"   Radiation efficiency < 50% on {cr.band}. High ground loss,"
                             " short wire, or reactive mismatch absorbing power.")

            blank()

    # -----------------------------------------------------------------------
    # SECTION 3 — Horizontal CP vs. Vertical CP Delta Analysis
    # -----------------------------------------------------------------------
    # Bug F fix: initialize outside the if-block so Section 8 never sees NameError
    # when only one NEC2 file is supplied.
    delta_R_list:    List[float] = []
    delta_X_list:    List[float] = []
    delta_vswr_list: List[float] = []

    if run_h and run_v:
        h1("SECTION 3 — COUNTERPOISE ORIENTATION COMPARISON  (H-CP vs. V-CP)")
        info("  This section quantifies the effect of mounting the counterpoise")
        info("  horizontally (in-line with antenna) versus vertically (drooping")
        info("  down from the feedpoint).  Differences reveal mutual coupling,")
        info("  ground proximity, and current distribution effects.")
        blank()
        info(f"  {'Freq':>8}  {'R_H':>8}  {'R_V':>8}  {'ΔR':>7}  "
             f"{'X_H':>8}  {'X_V':>8}  {'ΔX':>7}  "
             f"{'VSWR_H':>7}  {'VSWR_V':>7}  {'ΔVSWR':>7}")
        info(SEP2)

        fmap_h = run_h.freq_map()
        fmap_v = run_v.freq_map()
        common_freqs = sorted(set(fmap_h.keys()) & set(fmap_v.keys()))

        for freq in common_freqs:
            fh = fmap_h[freq]
            fv = fmap_v[freq]
            dR    = fv.R_ohm - fh.R_ohm
            dX    = fv.X_ohm - fh.X_ohm
            dVSWR = fv.vswr50 - fh.vswr50
            delta_R_list.append(dR)
            delta_X_list.append(dX)
            delta_vswr_list.append(dVSWR)
            info(f"  {freq:8.3f}  {fh.R_ohm:8.1f}  {fv.R_ohm:8.1f}  {dR:+7.1f}  "
                 f"{fh.X_ohm:+8.1f}  {fv.X_ohm:+8.1f}  {dX:+7.1f}  "
                 f"{fh.vswr50:7.2f}  {fv.vswr50:7.2f}  {dVSWR:+7.2f}")

        blank()
        h2("Statistical Summary of H-CP vs. V-CP Differences")

        def stats(data: List[float], label: str):
            if not data:
                return
            mn = sum(data) / len(data)
            rms = math.sqrt(sum(x**2 for x in data) / len(data))
            mx = max(data, key=abs)
            info(f"  {label:30s}: mean={mn:+.2f}  RMS={rms:.2f}  max={mx:+.2f}")

        stats(delta_R_list,    "ΔR_feed  (V-CP minus H-CP) Ω")
        stats(delta_X_list,    "ΔX_feed  (V-CP minus H-CP) Ω")
        stats(delta_vswr_list, "ΔVSWR    (V-CP minus H-CP)  ")

        blank()
        h2("Physical Interpretation")

        mean_dR = sum(delta_R_list) / len(delta_R_list) if delta_R_list else 0.0
        mean_dV = sum(delta_vswr_list) / len(delta_vswr_list) if delta_vswr_list else 0.0

        if abs(mean_dR) < 20:
            good("  ΔR is small: counterpoise orientation has minor effect on"
                 " feedpoint resistance. Both configurations are electrically equivalent.")
        elif mean_dR > 0:
            warn("  Vertical CP raises feedpoint R slightly more than horizontal CP."
                 " This is expected: a vertical drop brings the wire closer to the"
                 " soil surface, increasing capacitive loading and ground-return loss.")
        else:
            warn("  Horizontal CP raises feedpoint R more. Mutual coupling between the"
                 " in-line CP and the antenna wire is adding series resistance.")

        if abs(mean_dV) < 0.5:
            good("  VSWR difference < 0.5: orientation choice does not significantly"
                 " change matching. Select the mechanically easier installation.")
        elif mean_dV > 0:
            warn("  Vertical CP worsens VSWR on average. Consider horizontal CP"
                 " or multiple radials to reduce the counterpoise impedance.")
        else:
            good("  Vertical CP improves VSWR on average versus horizontal CP.")

    # -----------------------------------------------------------------------
    # SECTION 4 — Impedance Model Accuracy Assessment
    # -----------------------------------------------------------------------
    h1("SECTION 4 — EMPIRICAL MODEL ACCURACY vs. NEC2  (Systematic Error)")
    info("  The spreadsheet uses empirical formulas:")
    info("    R = 50 · 80^cos²(π·L/λ½)   [Ω]")
    info("    X = 1500 · sin(2π·L/λ½)     [Ω]")
    info("  These are curve-fit approximations. This section quantifies the error.")
    blank()

    for run, rlabel in [(run_h, "HORIZ. CP"), (run_v, "VERT.  CP")]:
        if run is None:
            continue
        h2(f"Error statistics — {rlabel}")

        if not run.freqs:
            warn(f"  No NEC2 frequency points parsed — error statistics unavailable.")
            warn(f"  Run with --debug to diagnose the parser (see FIX #1 notes).")
            continue

        err_R:    List[float] = []
        err_X:    List[float] = []
        err_vswr: List[float] = []

        # FIX #9: per-frequency table header
        info(f"  {'Freq':>8}  {'R_sim':>8}  {'R_mod':>8}  {'ΔR%':>7}  "
             f"{'X_sim':>8}  {'X_mod':>8}  {'ΔX(Ω)':>8}  {'VSWR_sim':>9}  {'VSWR_mod':>9}")
        info("  " + "─" * 88)

        for fp in sorted(run.freqs, key=lambda p: p.freq_mhz):
            f = fp.freq_mhz
            # FIX #9: match to nearest calc_row; always recompute empirical
            # values from formula so we aren't dependent on CSV completeness
            cr_match = None
            best_df = 999.0
            for cr in calc_rows:
                df = abs(cr.freq_mhz - f)
                if df < best_df:
                    best_df = df
                    cr_match = cr

            unun_row = unun_ratio   # Bug A fix: always use the global unun_ratio
            # Always recompute empirical to avoid stale/missing CSV values
            R_ref, X_ref, vswr_emp = calc_empirical(wire_len_m, f, unun_row)

            if R_ref and fp.R_ohm:
                eR_pct = (fp.R_ohm - R_ref) / R_ref * 100
                eX     = fp.X_ohm - X_ref
                eV     = fp.vswr50 - vswr_emp
                err_R.append(eR_pct)
                err_X.append(eX)
                err_vswr.append(eV)
                info(f"  {f:8.3f}  {fp.R_ohm:8.1f}  {R_ref:8.1f}  {eR_pct:+7.1f}%  "
                     f"{fp.X_ohm:+8.1f}  {X_ref:+8.1f}  {eX:+8.1f}  "
                     f"{fp.vswr50:9.2f}  {vswr_emp:9.2f}")
            else:
                info(f"  {f:8.3f}  (no valid R/X data)")

        blank()
        # FIX #9: summary statistics
        if err_R:
            n = len(err_R)
            mean_eR = sum(err_R) / n
            rms_eR  = math.sqrt(sum(e**2 for e in err_R) / n)
            info(f"  R error  : n={n}  mean={mean_eR:+.1f}%  RMS={rms_eR:.1f}%"
                 f"  range=[{min(err_R):+.1f}%, {max(err_R):+.1f}%]")
            if rms_eR < 30:
                good(f"  R model accuracy is reasonable (RMS < 30%).")
            elif rms_eR < 60:
                warn(f"  R model has moderate error (RMS {rms_eR:.0f}%)."
                     " Ground type, wire height, and end effects cause deviation.")
            else:
                bad(f"  R model error is large (RMS {rms_eR:.0f}%)."
                    " The empirical formula should NOT be used for matching design"
                    " without NEC2 confirmation.")
        else:
            warn("  No paired NEC2/model R data — check NEC2 parser output (Section 1).")

        if err_X:
            n = len(err_X)
            mean_eX = sum(err_X) / n
            rms_eX  = math.sqrt(sum(e**2 for e in err_X) / n)
            info(f"  X error  : n={n}  mean={mean_eX:+.1f} Ω  RMS={rms_eX:.1f} Ω"
                 f"  range=[{min(err_X):+.1f}, {max(err_X):+.1f}] Ω")
            if rms_eX < 200:
                good(f"  Reactance model is reasonable (RMS < 200 Ω).")
            else:
                warn(f"  Reactance model has large error (RMS {rms_eX:.0f} Ω)."
                     " The sinusoidal X formula ignores end-loading and ground proximity.")

        if err_vswr:
            n = len(err_vswr)
            mean_ev  = sum(err_vswr) / n
            rms_ev   = math.sqrt(sum(e**2 for e in err_vswr) / n)
            info(f"  VSWR error: n={n}  mean={mean_ev:+.2f}  RMS={rms_ev:.2f}"
                 f"  range=[{min(err_vswr):+.2f}, {max(err_vswr):+.2f}]")
            info(f"  (VSWR computed post-{unun_ratio:.0f}:1 UnUn — transmitter-side reference)")

    # -----------------------------------------------------------------------
    # SECTION 5 — Band-by-Band Matching Verdict
    # -----------------------------------------------------------------------
    h1("SECTION 5 — BAND-BY-BAND MATCHING VERDICT")
    info("  Combined verdict using NEC2 simulated values.")
    blank()

    col_w = [8, 10, 9, 9, 12, 12, 35]
    header = (f"  {'Band':<8}  {'f(MHz)':<10}  "
              f"{'VSWR_H':<9}  {'VSWR_V':<9}  "
              f"{'Model(nCP)':<12}  {'Model(wCP)':<12}  "
              f"{'Verdict':<35}")
    info(header)
    info("  " + "─" * 93)

    for cr in calc_rows:
        if not cr.active:
            continue
        freq = cr.freq_mhz
        # Bug A fix: always use the global unun_ratio, not cr.unun_ratio from CSV.
        unun = unun_ratio

        # FIX #3: raised tolerance to 0.75 MHz; FIX #6: compute post-UnUn VSWR
        def nec_vswr(run):
            if run is None:
                return None, None
            fmap = run.freq_map()
            if not fmap:
                return None, None
            key = min(fmap.keys(), key=lambda k: abs(k - freq))
            if abs(key - freq) > 0.75:   # FIX #3: was 0.3
                return None, None
            fp_ = fmap[key]
            # FIX #6: VSWR through UnUn
            if unun > 1.0:
                R_in = fp_.R_ohm / unun
                X_in = fp_.X_ohm / unun
                g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
                vswr_in = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
            else:
                vswr_in = fp_.vswr50
            return fp_.vswr50, vswr_in

        vswr_h_raw, vswr_h_unun = nec_vswr(run_h)
        vswr_v_raw, vswr_v_unun = nec_vswr(run_v)
        vswr_h_s = f"{vswr_h_unun:8.2f}" if vswr_h_unun else "   n/a  "
        vswr_v_s = f"{vswr_v_unun:8.2f}" if vswr_v_unun else "   n/a  "
        # BUG 4 FIX: The two calc_empirical calls were identical — the second
        # never incorporated Zcp, so vswr_wcp_unun was the same as vswr_no_unun.
        # Correct fix: the with-CP column derives its VSWR from the CP-corrected
        # impedance: Z_eff = R_wire + (R_cp + jX_cp) with Zcp from the CSV.
        # We then divide by the UnUn ratio for the transmitter-side reference.
        _, _, vswr_no_unun = calc_empirical(wire_len_m, freq, unun)
        m_no = f"{vswr_no_unun:8.2f}"
        if cr.Zcp_ohm and cr.Zcp_ohm != 0.0:
            # Zcp is stored as a magnitude in the CSV; model it as purely
            # resistive series correction (the spreadsheet's own assumption).
            R_eff = cr.R_wire_ohm + cr.Zcp_ohm
            X_eff = cr.X_wire_ohm
            R_eff_in = R_eff / unun if unun > 0 else R_eff
            X_eff_in = X_eff / unun if unun > 0 else X_eff
            g_cp = math.hypot(R_eff_in - 50, X_eff_in) / math.hypot(R_eff_in + 50, X_eff_in)
            vswr_wcp_unun = (1 + g_cp) / (1 - g_cp) if g_cp < 1 else 999.0
            m_wcp = f"{vswr_wcp_unun:8.2f}"
        else:
            # No Zcp available — fall back to the CSV's pre-computed value if present
            m_wcp = f"{cr.vswr_with_cp:8.2f}" if cr.vswr_with_cp else "   n/a  "

        # Build verdict — FIX #6: judge against post-UnUn VSWR
        sims = [v for v in [vswr_h_unun, vswr_v_unun] if v is not None]
        if not sims:
            verdict = "No NEC2 data"
        else:
            best_sim = min(sims)
            if best_sim <= 1.5:
                verdict = f"{Fore.GREEN}Excellent — no tuner needed{Style.RESET_ALL}"
            elif best_sim <= 3.0:
                verdict = f"{Fore.CYAN}Good — tuner helpful{Style.RESET_ALL}"
            elif best_sim <= 6.0:
                verdict = f"{Fore.YELLOW}Marginal — tuner required{Style.RESET_ALL}"
            else:
                verdict = f"{Fore.RED}Poor — high mismatch loss{Style.RESET_ALL}"

            # FIX #7: use per-band avoidance score
            avoid = _avoidance_score(cr)
            if avoid > 0.12:
                model_ok = f"{Fore.GREEN}✓{Style.RESET_ALL}"
            else:
                model_ok = f"{Fore.RED}✗ resonance risk{Style.RESET_ALL}"
            verdict += f"  [score={avoid:.3f}: {model_ok}]"

        info(f"  {cr.band:<8}  {freq:<10.4f}  "
             f"{vswr_h_s}  {vswr_v_s}  "
             f"{m_no}  {m_wcp}  "
             f"{verdict}")

    blank()

    # -----------------------------------------------------------------------
    # SECTION 6 — Gain & Radiation Pattern Notes
    # -----------------------------------------------------------------------
    h1("SECTION 6 — GAIN & RADIATION PATTERN (if available)")

    any_gain = False
    for run, rlabel in [(run_h, "HORIZ. CP"), (run_v, "VERT.  CP")]:
        if run is None:
            continue
        freqs_with_gain = [fp for fp in run.freqs if fp.gain_dbi != 0.0]
        if not freqs_with_gain:
            info(f"  {rlabel}: No gain data found in output file.")
            continue
        any_gain = True
        h2(f"Gain summary — {rlabel}")
        info(f"  {'Freq':>8}  {'MaxGain':>9}  {'TOA(°)':>8}  {'Efficiency':>11}  Note")
        info("  " + "─" * 65)
        for fp in sorted(freqs_with_gain, key=lambda p: p.freq_mhz):
            note = ""
            if fp.gain_dbi > 0:
                note = "Above isotropic — good radiation"
            elif fp.gain_dbi > -3:
                note = "Slight loss vs isotropic — acceptable"
            else:
                note = f"{Fore.YELLOW}Significant loss — check ground, mismatch{Style.RESET_ALL}"
            if fp.efficiency < 0.5:
                note += f"  {Fore.RED}[low η={fp.efficiency*100:.0f}%]{Style.RESET_ALL}"
            # Bug H fix + BUG 3 FIX: flag NVIS operating mode so users expecting DX
            # are not misled.  After the BUG 3 convention fix, toa_deg is elevation
            # from horizon (0° = horizon = DX, 90° = zenith = NVIS).  NVIS therefore
            # corresponds to toa_deg > 85° (near-zenith).  The old threshold of
            # < 5° was accidentally correct when toa_deg stored NEC2 THETA (zenith
            # = 0), but would now flag DX angles instead of NVIS angles.
            if fp.toa_deg > 85.0:
                note += f"  {Fore.CYAN}[NVIS — regional 0-600 km, not DX]{Style.RESET_ALL}"
            info(f"  {fp.freq_mhz:8.3f}  {fp.gain_dbi:+9.2f}  {fp.toa_deg:8.1f}  "
                 f"{fp.efficiency*100:10.1f}%  {note}")

    if not any_gain:
        info("  No gain or RP data available in NEC2 files.")
        # FIX #8: check if RP card was missing from the .nec deck
        missing_rp = []
        for run, rlabel in [(run_h, "H-CP"), (run_v, "V-CP")]:
            if run is not None and not getattr(run, '_has_rp_card', True):
                missing_rp.append(rlabel)
        if missing_rp:
            warn(f"  No RP card found in .nec input deck for: {', '.join(missing_rp)}")
        info("  To get gain data, add the following card to your .nec deck")
        info("  BEFORE the EN card and re-run the simulation:")
        info("    RP 0 37 73 1000 0 0 1.0 5.0")
        info("  (37 elevation steps × 73 azimuth steps, dBi, 1° and 5° increments)")

    # -----------------------------------------------------------------------
    # SECTION 7 — Physical Root-Cause Analysis
    # -----------------------------------------------------------------------
    h1("SECTION 7 — ROOT-CAUSE ANALYSIS OF MODEL vs. NEC2 DISCREPANCIES")

    reasons = [
        ("Ground model",
         "NEC2 uses Sommerfeld-Norton real ground (finite conductivity/permittivity)."
         " The empirical spreadsheet formula assumes an 'infinite perfect ground' equivalent."
         " Real ground increases ground-return loss, raising R_feed and lowering efficiency."
         " Expect NEC2 R values to be 20–100% higher on low bands."),

        ("Wire height above ground",
         "The empirical model has no height term.  NEC2 correctly accounts for the image"
         " wire effect: as height decreases, mutual coupling with the image lowers radiation"
         " resistance and shifts reactance.  A wire at 5 m (≈λ/8 at 7 MHz) sees significant"
         " height-dependent changes versus free-space."),

        ("End effects & velocity factor",
         "The empirical X formula ignores end-loading at the wire termination and the VF"
         " of the insulated wire.  NEC2 models the physical geometry; the actual resonant"
         " length is slightly shorter than the VF-corrected formula predicts.  This shifts"
         " X by tens to hundreds of ohms near resonances."),

        ("Counterpoise coupling",
         "The horizontal counterpoise is electrically in-line with the antenna wire and"
         " forms a T-shaped element.  This mutual coupling modifies the feedpoint impedance"
         " in a way the simple series Zcp model does not capture.  The vertical CP avoids"
         " this coupling at the cost of stronger near-ground interaction."),

        ("Sinusoidal approximation limits",
         "R = 50·80^cos²(πL/λ½) and X = 1500·sin(2πL/λ½) are valid approximations only"
         " when L is not too close to a resonance and the antenna is isolated.  Near λ/2"
         " or λ/4, the actual Z diverges far faster than the smooth curves predict."
         " NEC2 captures the sharp resonance peak; the formula does not."),

        ("Segment count & wire radius",
         "NEC2 accuracy depends on segment density (≥10–20/λ at highest frequency) and"
         " the thin-wire approximation (radius ≪ segment length).  Check your .nec deck:"
         " too few segments produce an inaccurate current distribution and wrong impedance."),

        ("Feed model (EX card)",
         "The spreadsheet assumes end-fed excitation.  Verify the EX card in your .nec file"
         " places the source on segment 1 of wire 1 (the antenna wire end), not a centre"
         " feed.  A misplaced source is the most common cause of large NEC2 discrepancies."),
    ]

    for i, (title, body) in enumerate(reasons, 1):
        info(f"  {i}. {Fore.CYAN}{title}{Style.RESET_ALL}")
        for line in textwrap.wrap(body, width=74):
            info(f"     {line}")
        blank()

    # -----------------------------------------------------------------------
    # SECTION 8 — Recommendations
    # -----------------------------------------------------------------------
    h1("SECTION 8 — RECOMMENDATIONS")

    recs = []

    # VSWR-based
    # Bug B fix: compute post-UnUn VSWR (what the transmitter sees) instead of
    #   raw antenna-side fp.vswr50, which is always huge for end-fed wires and
    #   caused every band to be flagged as "very poor match" even when the UnUn
    #   brings the mismatch to an acceptable level.
    # Bug C fix: raised tolerance from 0.3 MHz to 0.75 MHz to match Sections 2/5.
    for cr in active:
        sims = []
        for run in [run_h, run_v]:
            if run is None:
                continue
            fmap = run.freq_map()
            key  = min(fmap.keys(), key=lambda k: abs(k - cr.freq_mhz)) if fmap else None
            if key and abs(key - cr.freq_mhz) <= 0.75:   # Bug C fix: was 0.3
                fp_ = fmap[key]
                # Bug B fix: apply UnUn transformation before comparing thresholds
                if unun_ratio > 1.0:
                    R_in = fp_.R_ohm / unun_ratio
                    X_in = fp_.X_ohm / unun_ratio
                    g_in = math.hypot(R_in - 50, X_in) / math.hypot(R_in + 50, X_in)
                    vswr_unun = (1 + g_in) / (1 - g_in) if g_in < 1 else 999.0
                else:
                    vswr_unun = fp_.vswr50
                sims.append(vswr_unun)
        if sims:
            worst = max(sims)
            if worst > 6.0:
                recs.append(
                    f"[{cr.band}] NEC2 VSWR = {worst:.1f} (post-{unun_ratio:.0f}:1 UnUn)"
                    " → very poor match."
                    " Adjust wire length (±0.2 m steps) or add more radials."
                    " Consider a tuner (ATU) for this band.")
            elif worst > 3.0:
                recs.append(
                    f"[{cr.band}] NEC2 VSWR = {worst:.1f} (post-{unun_ratio:.0f}:1 UnUn)"
                    " → marginal."
                    " A tuner is recommended.  Verify UnUn ratio is correct.")

    # CP-based
    if run_h and run_v and delta_vswr_list:
        avg_dv = sum(delta_vswr_list) / len(delta_vswr_list)
        if avg_dv > 0.5:
            recs.append("Horizontal CP gives lower average VSWR; prefer this orientation"
                        " if mechanical constraints allow.")
        elif avg_dv < -0.5:
            recs.append("Vertical CP gives lower average VSWR; drop the counterpoise"
                        " vertically from the feedpoint.")
        else:
            recs.append("Both CP orientations are nearly equivalent; choose for mechanical ease.")

    # General
    recs.append("Always verify feedpoint impedance with a vector network analyser (VNA)"
                " before connecting the final coaxial run.  NEC2 is more accurate than"
                " the spreadsheet, but physical installations still differ from the model.")
    recs.append("If ground conductivity is unknown, run NEC2 with σ = 0.001, 0.005, and"
                " 0.030 S/m to bound the expected VSWR variation due to soil type.")
    recs.append("For multi-band use, prioritise wire lengths with avoidance score ≥ 0.12"
                " (★★ GOOD or better) as identified by the spreadsheet Length Sweep sheet.")

    for i, rec in enumerate(recs, 1):
        for j, line in enumerate(textwrap.wrap(rec, 76)):
            prefix = f"  {i}. " if j == 0 else "     "
            info(prefix + line)

    # -----------------------------------------------------------------------
    # FOOTER
    # -----------------------------------------------------------------------
    h1("END OF REPORT")
    info("  Generated by nec2_vs_calc_analyzer.py — LU3VEA LongWire Calculator")
    info("  Empirical model: CC0 v1.0  |  NEC2 data: your simulation output")
    blank()

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# MATPLOTLIB PLOTS
# ═══════════════════════════════════════════════════════════════════════════

def plot_comparison(
    run_h: Optional[NEC2Run],
    run_v: Optional[NEC2Run],
    calc_rows: List[CalcRow],
    wire_len_m: float,
    out_png: str,
):
    """Generate a multi-panel comparison figure."""
    if not HAS_MPL:
        print("matplotlib not available — skipping plot.")
        return

    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(
        f"NEC2 vs. Empirical Model — Long Wire {wire_len_m:.1f} m",
        fontsize=14, fontweight="bold")
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.35)

    # --- Frequency axis from NEC2 ---
    all_runs = [r for r in [run_h, run_v] if r is not None]
    if not all_runs:
        print("No NEC2 runs to plot.")
        return

    ref_freqs = sorted(all_runs[0].freq_map().keys())
    freq_arr  = ref_freqs

    def run_arr(run, attr):
        if run is None:
            return [None] * len(freq_arr)
        fmap = run.freq_map()
        return [getattr(fmap[f], attr) if f in fmap else None for f in freq_arr]

    # Empirical curves
    R_emp = [calc_empirical(wire_len_m, f)[0] for f in freq_arr]
    X_emp = [calc_empirical(wire_len_m, f)[1] for f in freq_arr]

    R_h = run_arr(run_h, "R_ohm")
    X_h = run_arr(run_h, "X_ohm")
    R_v = run_arr(run_v, "R_ohm")
    X_v = run_arr(run_v, "X_ohm")

    VSWR_h = run_arr(run_h, "vswr50")
    VSWR_v = run_arr(run_v, "vswr50")
    VSWR_emp = [calc_empirical(wire_len_m, f)[2] for f in freq_arr]

    GAIN_h = run_arr(run_h, "gain_dbi")
    GAIN_v = run_arr(run_v, "gain_dbi")

    def clean(lst):
        x = [f for f, v in zip(freq_arr, lst) if v is not None]
        y = [v for v in lst if v is not None]
        return x, y

    colors = {"emp": "#888888", "H": "#1f77b4", "V": "#d62728"}

    # ── Plot 1: R ──
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(freq_arr, R_emp, "--", color=colors["emp"], label="Empirical model")
    if any(v is not None for v in R_h):
        fx, fy = clean(R_h); ax1.plot(fx, fy, "o-", color=colors["H"], label="NEC2 H-CP")
    if any(v is not None for v in R_v):
        fx, fy = clean(R_v); ax1.plot(fx, fy, "s-", color=colors["V"], label="NEC2 V-CP")
    ax1.set_title("Feedpoint Resistance R (Ω)")
    ax1.set_xlabel("Frequency (MHz)"); ax1.set_ylabel("R (Ω)")
    ax1.set_yscale("log")
    if ax1.get_legend_handles_labels()[0]:
        ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # ── Plot 2: X ──
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(freq_arr, X_emp, "--", color=colors["emp"], label="Empirical model")
    if any(v is not None for v in X_h):
        fx, fy = clean(X_h); ax2.plot(fx, fy, "o-", color=colors["H"], label="NEC2 H-CP")
    if any(v is not None for v in X_v):
        fx, fy = clean(X_v); ax2.plot(fx, fy, "s-", color=colors["V"], label="NEC2 V-CP")
    ax2.axhline(0, color="black", linewidth=0.7, linestyle=":")
    ax2.set_title("Feedpoint Reactance X (Ω)")
    ax2.set_xlabel("Frequency (MHz)"); ax2.set_ylabel("X (Ω)")
    if ax2.get_legend_handles_labels()[0]:
        ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # ── Plot 3: VSWR ──
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(freq_arr, VSWR_emp, "--", color=colors["emp"], label="Empirical model")
    if any(v is not None for v in VSWR_h):
        fx, fy = clean(VSWR_h); ax3.plot(fx, fy, "o-", color=colors["H"], label="NEC2 H-CP")
    if any(v is not None for v in VSWR_v):
        fx, fy = clean(VSWR_v); ax3.plot(fx, fy, "s-", color=colors["V"], label="NEC2 V-CP")
    ax3.axhline(1.5, color="green",  linestyle="--", linewidth=0.8, label="VSWR 1.5")
    ax3.axhline(3.0, color="orange", linestyle="--", linewidth=0.8, label="VSWR 3.0")
    ax3.axhline(6.0, color="red",    linestyle="--", linewidth=0.8, label="VSWR 6.0")
    ax3.set_title("VSWR (ref 50 Ω)")
    ax3.set_xlabel("Frequency (MHz)"); ax3.set_ylabel("VSWR")
    ax3.set_ylim(0.9, min(30, max(
        [v for v in VSWR_emp + VSWR_h + VSWR_v if v is not None and v < 999] or [10]
    ) * 1.1))
    if ax3.get_legend_handles_labels()[0]:
        ax3.legend(fontsize=7)
    ax3.grid(True, alpha=0.3)

    # ── Plot 4: Gain ──
    ax4 = fig.add_subplot(gs[1, 1])
    has_gain = False
    if any(v is not None and v != 0 for v in GAIN_h):
        fx, fy = clean(GAIN_h); ax4.plot(fx, fy, "o-", color=colors["H"], label="NEC2 H-CP")
        has_gain = True
    if any(v is not None and v != 0 for v in GAIN_v):
        fx, fy = clean(GAIN_v); ax4.plot(fx, fy, "s-", color=colors["V"], label="NEC2 V-CP")
        has_gain = True
    if not has_gain:
        ax4.text(0.5, 0.5, "No gain data\nin NEC2 files",
                 ha='center', va='center', transform=ax4.transAxes, color='gray')
    ax4.set_title("Max Gain (dBi)")
    ax4.set_xlabel("Frequency (MHz)"); ax4.set_ylabel("Gain (dBi)")
    if ax4.get_legend_handles_labels()[0]:
        ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3)

    # ── Plot 5: VSWR delta (H-CP vs V-CP) ──
    ax5 = fig.add_subplot(gs[2, 0])
    if run_h and run_v:
        fmap_h = run_h.freq_map()
        fmap_v = run_v.freq_map()
        common = sorted(set(fmap_h.keys()) & set(fmap_v.keys()))
        dVSWR  = [fmap_v[f].vswr50 - fmap_h[f].vswr50 for f in common]
        # FIX C: dR was computed but never used in the original code (dead variable).
        # Now plotted as a secondary axis so the resistance shift is also visible.
        dR     = [fmap_v[f].R_ohm  - fmap_h[f].R_ohm  for f in common]
        ax5.bar(common, dVSWR, width=0.08, color=[
            "green" if d < 0 else "red" for d in dVSWR], label="ΔVSWR")
        ax5.axhline(0, color="black", linewidth=0.8)
        ax5.set_title("ΔVSWR & ΔR  (V-CP minus H-CP)")
        ax5.set_xlabel("Frequency (MHz)"); ax5.set_ylabel("ΔVSWR")
        ax5_r = ax5.twinx()
        ax5_r.plot(common, dR, "D--", color="purple", markersize=4, label="ΔR (Ω)")
        ax5_r.set_ylabel("ΔR (Ω)", color="purple")
        ax5_r.tick_params(axis='y', labelcolor='purple')
        lines1, labels1 = ax5.get_legend_handles_labels()
        lines2, labels2 = ax5_r.get_legend_handles_labels()
        ax5.legend(lines1 + lines2, labels1 + labels2, fontsize=7)
        ax5.grid(True, alpha=0.3, axis='y')

    # ── Plot 6: R/X error (NEC2 vs model) ──
    ax6 = fig.add_subplot(gs[2, 1])
    if run_h:
        err_R_pct = []
        fmap = run_h.freq_map()
        for f in sorted(fmap.keys()):
            R_m, _, _ = calc_empirical(wire_len_m, f)
            if R_m:
                err_R_pct.append((f, (fmap[f].R_ohm - R_m) / R_m * 100))
        if err_R_pct:
            fx = [e[0] for e in err_R_pct]
            fy = [e[1] for e in err_R_pct]
            ax6.bar(fx, fy, width=0.08,
                    color=["green" if abs(e) < 30 else "orange" if abs(e) < 60 else "red"
                           for e in fy])
            ax6.axhline(0, color="black", linewidth=0.8)
            ax6.set_title("R Error: (NEC2 H-CP − Model) / Model  [%]")
            ax6.set_xlabel("Frequency (MHz)"); ax6.set_ylabel("Error %")
            ax6.grid(True, alpha=0.3, axis='y')

    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n  📊  Comparison chart saved → {out_png}")


# ═══════════════════════════════════════════════════════════════════════════
# USER INTERFACE  (interactive prompts)
# ═══════════════════════════════════════════════════════════════════════════

def ask(prompt: str, default: str = "") -> str:
    full = f"{Fore.CYAN}{prompt}{Style.RESET_ALL}"
    if default:
        full += f" [{default}]"
    full += ": "
    val = input(full).strip()
    return val if val else default


def ask_file(prompt: str, required: bool = True) -> Optional[str]:
    while True:
        path = ask(prompt)
        if not path:
            if not required:
                return None
            print(f"  {Fore.RED}Path is required.{Style.RESET_ALL}")
            continue
        if not os.path.isfile(path):
            print(f"  {Fore.RED}File not found: {path}{Style.RESET_ALL}")
            if not required:
                ans = ask("  Skip this file? (yes/no)", "yes")
                if ans.lower().startswith("y"):
                    return None
        else:
            return path


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    p = argparse.ArgumentParser(
        prog="nec2_vs_calc_analyzer.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            NEC2 vs. Long Wire Antenna Calculator — Exhaustive Comparison Analyzer
            Author: based on LU3VEA LongWire_Antenna_Calculator.xlsx (CC0 v1.0)

            WHAT THIS SCRIPT DOES
            ─────────────────────
            Reads one or two NEC2 output files (.out) — one for a horizontal
            counterpoise (H-CP) run and one for a vertical counterpoise (V-CP) run
            — together with a spreadsheet-exported CSV of empirical reference values,
            then produces an 8-section comparison report and an optional multi-panel
            matplotlib chart.

            The report covers:
              Section 1  NEC2 impedance sweep (R, X, |Z|, phase, VSWR, gain)
              Section 2  Per-band: NEC2 vs. empirical model (VSWR, R, X, gain)
              Section 3  H-CP vs. V-CP delta analysis (ΔR, ΔX, ΔVSWR)
              Section 4  Systematic error statistics of the empirical formulas
              Section 5  Band-by-band matching verdict table
              Section 6  Gain & radiation pattern notes (if RP data present)
              Section 7  Root-cause analysis of model vs. NEC2 discrepancies
              Section 8  Actionable recommendations

            INTERACTIVE vs. BATCH MODE
            ──────────────────────────
            All arguments are optional.  Any argument NOT supplied on the command
            line is requested interactively at run-time (legacy behaviour).
            Supplying ALL arguments — or using --no-interactive — enables fully
            non-interactive/batch use (e.g. from a shell script or CI pipeline).

            'default' SHORTHAND FOR --wire AND --unun
            ──────────────────────────────────────────
            Pass the literal string 'default' to --wire or --unun to instruct the
            script to read that value directly from the CSV without asking:

              --wire default   Uses the wire_len_m column value from the CSV.
                               All active rows must agree on a single length;
                               if they differ the script exits with an error.

              --unun default   Uses the unun_ratio column value from the CSV.
                               All rows must agree on a single ratio;
                               if they differ the script exits with an error.

            This is useful when the CSV already encodes the correct values and you
            want a zero-prompt run without hard-coding the numbers on the CLI.

            CSV FORMAT
            ──────────
            See the CSV COLUMN GUIDE section at the bottom of this script for the
            full column list, required vs. optional columns, and an example.
            The script auto-detects comma (standard) vs. semicolon (European locale)
            CSV delimiters, and accepts UTF-8 or UTF-8-BOM encoded files.

            NEC2 FILE COMPATIBILITY
            ───────────────────────
            Supports output from: nec2c, 4nec2, xnec2c, EZNEC export.
            The parser recognises six different FREQUENCY= header styles and four
            impedance extraction methods (IMPEDANCE=(R,X), ANTENNA INPUT PARAMETERS
            table, ZIN label, and Z = R ±j X table).
            Companion .nec input decks (--hcp-nec / --vcp-nec) are used to read
            exact GW-card geometry for counterpoise length; without them the parser
            falls back to CM-comment metadata.

            OPTIONAL DEPENDENCIES
            ─────────────────────
              tabulate    — prettier ASCII tables (pip install tabulate)
              colorama    — ANSI colour output on Windows (pip install colorama)
              matplotlib  — comparison chart PNG (pip install matplotlib)
        """),
        epilog=textwrap.dedent("""\
            FLAG REFERENCE
            ──────────────
            --hcp FILE        NEC2 .out for the horizontal-CP run (optional; prompted if omitted)
            --hcp-nec FILE    Companion .nec input deck for H-CP (optional; improves CP geometry)
            --vcp FILE        NEC2 .out for the vertical-CP run   (optional; prompted if omitted)
            --vcp-nec FILE    Companion .nec input deck for V-CP  (optional)
            --csv FILE        Spreadsheet reference CSV           (prompted if omitted)
            --wire METRES     Wire length in metres, or 'default' to read from CSV
            --unun RATIO      UnUn ratio N for N:1 transformer, or 'default' to read from CSV
            --out-txt FILE    Output report filename  (default: nec2_comparison_report.txt)
            --out-png FILE    Output chart filename   (default: nec2_comparison_chart.png)
            --debug / -d      Dump first 60 lines of each .out file (parser diagnostics)
            --no-interactive  Abort instead of prompting for any missing argument

            EXAMPLES
            ────────
            # Fully interactive (original behaviour — prompts for every input):
              python nec2_vs_calc_analyzer.py

            # Provide H-CP file only; everything else is still prompted:
              python nec2_vs_calc_analyzer.py --hcp antenna_h.out

            # Use CSV values for wire length and UnUn without typing them:
              python nec2_vs_calc_analyzer.py \\
                --hcp antenna_h.out --csv reference.csv \\
                --wire default --unun default

            # Fully non-interactive batch run (no prompts at all):
              python nec2_vs_calc_analyzer.py \\
                --hcp     antenna_h.out  --hcp-nec antenna_h.nec \\
                --vcp     antenna_v.out  --vcp-nec antenna_v.nec \\
                --csv     reference.csv  \\
                --wire    13.3           \\
                --unun    9              \\
                --out-txt report.txt     \\
                --out-png chart.png

            # Batch run, derive wire+UnUn from CSV, debug parser, no-prompt guard:
              python nec2_vs_calc_analyzer.py \\
                --hcp     antenna_h.out  \\
                --csv     reference.csv  \\
                --wire    default        \\
                --unun    default        \\
                --no-interactive         \\
                --debug
        """),
    )

    # ── NEC2 output files ──────────────────────────────────────────────────
    p.add_argument(
        "--hcp", metavar="FILE",
        help="NEC2 .out file for the HORIZONTAL counterpoise run. "
             "Leave unset to be prompted interactively.",
    )
    p.add_argument(
        "--hcp-nec", metavar="FILE",
        help="Companion NEC2 .nec input deck for the H-CP run (optional). "
             "Used to read exact GW-card geometry instead of CM-comment values.",
    )
    p.add_argument(
        "--vcp", metavar="FILE",
        help="NEC2 .out file for the VERTICAL counterpoise run. "
             "Leave unset to be prompted interactively.",
    )
    p.add_argument(
        "--vcp-nec", metavar="FILE",
        help="Companion NEC2 .nec input deck for the V-CP run (optional).",
    )

    # ── Reference CSV ──────────────────────────────────────────────────────
    p.add_argument(
        "--csv", metavar="FILE",
        help="Spreadsheet-calculated reference CSV file. "
             "See the CSV COLUMN GUIDE at the bottom of this script.",
    )

    # ── Antenna parameters ─────────────────────────────────────────────────
    p.add_argument(
        "--wire", metavar="METRES",
        help=(
            "Antenna wire length in metres (e.g. 13.3).  "
            "Pass 'default' to use the wire_len_m value found in the CSV "
            "without prompting (all active rows must agree on a single length; "
            "if they differ the script exits with an error).  "
            "Leave unset to be prompted interactively."
        ),
    )
    p.add_argument(
        "--unun", metavar="RATIO",
        help=(
            "UnUn impedance ratio N for an N:1 transformer (e.g. 9 for a 9:1 "
            "UnUn, 1 for direct 50 Ω feed, 4 for a 4:1 balun).  "
            "Pass 'default' to use the unun_ratio value found in the CSV "
            "without prompting (all rows must agree on a single value; if they "
            "differ the script exits with an error).  "
            "When omitted entirely the value is read from the CSV unun_ratio "
            "column if all rows agree, otherwise 9 is used as the interactive "
            "default."
        ),
    )

    # ── Output files ───────────────────────────────────────────────────────
    p.add_argument(
        "--out-txt", metavar="FILE", default=None,
        help="Output text report filename (default: nec2_comparison_report.txt).",
    )
    p.add_argument(
        "--out-png", metavar="FILE", default=None,
        help="Output chart filename (default: nec2_comparison_chart.png).",
    )

    # ── Flags ──────────────────────────────────────────────────────────────
    p.add_argument(
        "--debug", "-d", action="store_true",
        help="Print the first 60 lines of each .out file for parser diagnostics.",
    )
    p.add_argument(
        "--no-interactive", action="store_true",
        help="Exit with an error instead of prompting for any missing argument. "
             "Useful in batch/CI contexts where stdin is not a terminal.",
    )

    return p


def main():
    print()
    print(f"{Fore.CYAN}{'═'*70}")
    print("  NEC2 vs. Long Wire Antenna Calculator — Comparison Analyzer")
    print(f"  Author: based on LU3VEA spreadsheet (CC0 v1.0)")
    print(f"{'═'*70}{Style.RESET_ALL}")
    print()

    # ── Parse CLI arguments ────────────────────────────────────────────────
    parser = _build_arg_parser()
    # Use parse_known_args so that unrecognised tokens (e.g. stray filenames
    # passed by old callers) don't cause an immediate hard failure.
    args, _unknown = parser.parse_known_args()

    # Keep the legacy bare --debug / -d detection for callers that still pass
    # those flags without going through argparse (harmless duplication).
    debug_mode = args.debug

    if debug_mode:
        print(f"  {Fore.YELLOW}DEBUG MODE ON — first 60 lines of each .out file will be printed.{Style.RESET_ALL}")
        print()

    # Helper: if --no-interactive was requested, abort instead of prompting.
    def _require(name: str):
        if args.no_interactive:
            print(f"\n{Fore.RED}  Error: --{name} is required in non-interactive mode.{Style.RESET_ALL}")
            sys.exit(1)

    # ── [1] H-CP NEC2 .out file ───────────────────────────────────────────
    if args.hcp is not None:
        # Provided on CLI — validate immediately.
        if not os.path.isfile(args.hcp):
            print(f"  {Fore.RED}H-CP file not found: {args.hcp}{Style.RESET_ALL}")
            sys.exit(1)
        path_h = args.hcp
    else:
        _require("hcp")
        print("  Provide the NEC2 OUTPUT file(s) (.out) from your simulation runs.")
        print("  You can supply one or both counterpoise orientations.")
        print()
        print(f"  {Fore.WHITE}[1] NEC2 output — HORIZONTAL counterpoise{Style.RESET_ALL}")
        print("      (antenna horizontal + counterpoise wire in-line/horizontal)")
        path_h = ask_file("  Path to H-CP NEC2 .out file (press Enter to skip)", required=False)

    # ── [1b] H-CP companion .nec deck ────────────────────────────────────
    if args.hcp_nec is not None:
        if not os.path.isfile(args.hcp_nec):
            print(f"  {Fore.YELLOW}  Warning: H-CP .nec file not found: {args.hcp_nec} — skipping.{Style.RESET_ALL}")
            path_h_nec = None
        else:
            path_h_nec = args.hcp_nec
    else:
        path_h_nec = None
        if path_h and not args.no_interactive:
            print("      To read exact CP geometry from GW cards, supply the corresponding")
            print("      NEC2 INPUT deck (.nec/.inp).  Press Enter to skip (falls back to")
            print("      the CM comment in the .out file, which may differ by a few mm).")
            path_h_nec = ask_file(
                "  Path to H-CP NEC2 .nec input file (press Enter to skip)", required=False)

    # ── [2] V-CP NEC2 .out file ───────────────────────────────────────────
    if args.vcp is not None:
        if not os.path.isfile(args.vcp):
            print(f"  {Fore.RED}V-CP file not found: {args.vcp}{Style.RESET_ALL}")
            sys.exit(1)
        path_v = args.vcp
    else:
        _require("vcp")
        print()
        print(f"  {Fore.WHITE}[2] NEC2 output — VERTICAL counterpoise{Style.RESET_ALL}")
        print("      (antenna horizontal + counterpoise drooping vertically)")
        path_v = ask_file("  Path to V-CP NEC2 .out file (press Enter to skip)", required=False)

    # ── [2b] V-CP companion .nec deck ────────────────────────────────────
    if args.vcp_nec is not None:
        if not os.path.isfile(args.vcp_nec):
            print(f"  {Fore.YELLOW}  Warning: V-CP .nec file not found: {args.vcp_nec} — skipping.{Style.RESET_ALL}")
            path_v_nec = None
        else:
            path_v_nec = args.vcp_nec
    else:
        path_v_nec = None
        if path_v and not args.no_interactive:
            print("      Optional: companion NEC2 input deck for exact V-CP geometry.")
            path_v_nec = ask_file(
                "  Path to V-CP NEC2 .nec input file (press Enter to skip)", required=False)

    if path_h is None and path_v is None:
        print(f"\n{Fore.RED}  At least one NEC2 file must be provided.{Style.RESET_ALL}")
        sys.exit(1)

    # ── [3] Reference CSV ─────────────────────────────────────────────────
    if args.csv is not None:
        if not os.path.isfile(args.csv):
            print(f"  {Fore.RED}CSV file not found: {args.csv}{Style.RESET_ALL}")
            sys.exit(1)
        path_csv = args.csv
    else:
        _require("csv")
        print()
        print(f"  {Fore.WHITE}[3] Spreadsheet-calculated reference CSV{Style.RESET_ALL}")
        print("      (see CSV column guide at end of this script)")
        path_csv = ask_file("  Path to reference CSV file")

    # ── [4] Wire length ───────────────────────────────────────────────────
    # Probe CSV for both unun and wire defaults regardless of interactive mode.
    _csv_unun_default = "9"
    _csv_wire_default = "13.3"
    try:
        _probe_rows = load_csv(path_csv)
        # ── unun default from CSV ──
        _csv_ununs = {r.unun_ratio for r in _probe_rows if r.unun_ratio > 0}
        if len(_csv_ununs) == 1:
            _u = list(_csv_ununs)[0]
            _csv_unun_default = str(int(_u)) if _u == int(_u) else str(_u)
            if args.unun is None:
                print(f"  {Fore.CYAN}ℹ  CSV unun_ratio column = {_csv_unun_default}"
                      f" (all rows agree — using as default){Style.RESET_ALL}")
        # ── wire default from CSV ──
        _csv_wires = {r.wire_len_m for r in _probe_rows if r.wire_len_m > 0}
        if len(_csv_wires) == 1:
            _w = list(_csv_wires)[0]
            _csv_wire_default = str(int(_w)) if _w == int(_w) else str(_w)
    except Exception:
        pass

    if args.wire is not None:
        wire_str = str(args.wire).strip().lower()
        if wire_str == "default":
            # Resolve from CSV
            _csv_wires_active = {r.wire_len_m for r in _probe_rows
                                  if r.wire_len_m > 0 and r.active}
            _csv_wires_all = {r.wire_len_m for r in _probe_rows if r.wire_len_m > 0}
            _resolve_set = _csv_wires_active if _csv_wires_active else _csv_wires_all
            if len(_resolve_set) == 0:
                print(f"\n{Fore.RED}  --wire default: no wire_len_m values found in CSV."
                      f"  Supply an explicit value in metres.{Style.RESET_ALL}")
                sys.exit(1)
            if len(_resolve_set) > 1:
                print(f"\n{Fore.RED}  --wire default: CSV wire_len_m values are not uniform "
                      f"({sorted(_resolve_set)}).  Supply an explicit value with --wire METRES."
                      f"{Style.RESET_ALL}")
                sys.exit(1)
            wire_len_m = list(_resolve_set)[0]
            print(f"  {Fore.CYAN}ℹ  --wire default → {wire_len_m} m (from CSV){Style.RESET_ALL}")
        else:
            try:
                wire_len_m = float(wire_str)
            except ValueError:
                print(f"\n{Fore.RED}  --wire: invalid value '{args.wire}'."
                      f"  Use a number in metres (e.g. 13.3) or the word 'default'."
                      f"{Style.RESET_ALL}")
                sys.exit(1)
    else:
        _require("wire")
        print()
        wire_len_str = ask("  Antenna wire length (m)", _csv_wire_default)
        wire_len_m   = float(wire_len_str)

    # ── [5] UnUn ratio ────────────────────────────────────────────────────
    if args.unun is not None:
        unun_str = str(args.unun).strip().lower()
        if unun_str == "default":
            # Resolve from CSV
            _csv_ununs_check = {r.unun_ratio for r in _probe_rows if r.unun_ratio > 0}
            if len(_csv_ununs_check) == 0:
                print(f"\n{Fore.RED}  --unun default: no unun_ratio values found in CSV."
                      f"  Supply an explicit ratio with --unun N.{Style.RESET_ALL}")
                sys.exit(1)
            if len(_csv_ununs_check) > 1:
                print(f"\n{Fore.RED}  --unun default: CSV unun_ratio values are not uniform "
                      f"({sorted(_csv_ununs_check)}).  Supply an explicit value with --unun N."
                      f"{Style.RESET_ALL}")
                sys.exit(1)
            unun_ratio = list(_csv_ununs_check)[0]
            print(f"  {Fore.CYAN}ℹ  --unun default → {unun_ratio}:1 (from CSV){Style.RESET_ALL}")
        else:
            try:
                unun_ratio = float(unun_str)
            except ValueError:
                print(f"\n{Fore.RED}  --unun: invalid value '{args.unun}'."
                      f"  Use a number (e.g. 9) or the word 'default'."
                      f"{Style.RESET_ALL}")
                sys.exit(1)
    else:
        _require("unun")
        unun_str   = ask("  UnUn ratio (e.g. 9 for 9:1, 1 for direct)", _csv_unun_default)
        unun_ratio = float(unun_str)

    # ── [6] Output filenames ──────────────────────────────────────────────
    if args.out_txt is not None:
        out_txt = args.out_txt
    else:
        _require("out-txt")
        print()
        out_txt = ask("  Output report filename (.txt)", "nec2_comparison_report.txt")

    if args.out_png is not None:
        out_png = args.out_png
    else:
        _require("out-png")
        # Only ask if matplotlib is available; otherwise silently skip.
        if HAS_MPL:
            out_png = ask("  Output chart filename (.png)", "nec2_comparison_chart.png")
        else:
            out_png = "nec2_comparison_chart.png"

    # ── Parse ─────────────────────────────────────────────────────────────
    print()
    print("  Parsing files…")

    run_h, run_v = None, None
    if path_h:
        run_h = parse_nec2_output(path_h, debug=debug_mode,
                                    explicit_nec_path=path_h_nec)
        run_h.label = "Horizontal CP"
        n = len(run_h.freqs)
        if n == 0:
            print(f"  {Fore.RED}H-CP: 0 frequency points loaded — parser found nothing."
                  f" Re-run with --debug to diagnose.{Style.RESET_ALL}")
        else:
            print(f"  H-CP: {n} frequency points loaded."
                  f"  CP={run_h.cp_len_m:.2f} m, type={run_h.cp_type}")
    if path_v:
        run_v = parse_nec2_output(path_v, debug=debug_mode,
                                    explicit_nec_path=path_v_nec)
        run_v.label = "Vertical CP"
        n = len(run_v.freqs)
        if n == 0:
            print(f"  {Fore.RED}V-CP: 0 frequency points loaded — parser found nothing."
                  f" Re-run with --debug to diagnose.{Style.RESET_ALL}")
        else:
            print(f"  V-CP: {n} frequency points loaded."
                  f"  CP={run_v.cp_len_m:.2f} m, type={run_v.cp_type}")

    calc_rows = load_csv(path_csv)
    print(f"  CSV : {len(calc_rows)} rows loaded"
          f" ({sum(1 for r in calc_rows if r.active)} active bands).")

    # ── Analyse ───────────────────────────────────────────────────────────
    print()
    print("  Running analysis…")
    report = analyse_model_vs_nec(run_h, run_v, calc_rows, wire_len_m, unun_ratio)

    # ── Write report ──────────────────────────────────────────────────────
    ansi_esc = re.compile(r'\x1b\[[0-9;]*m')
    clean_report = ansi_esc.sub('', report)
    with open(out_txt, 'w', encoding='utf-8') as fh:
        fh.write(clean_report)
    print(report)
    print(f"\n  📄  Full report saved → {out_txt}")

    # ── Plot ──────────────────────────────────────────────────────────────
    plot_comparison(run_h, run_v, calc_rows, wire_len_m, out_png)


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════════════════════
# CSV COLUMN GUIDE
# ═══════════════════════════════════════════════════════════════════════════
"""
CSV COLUMN GUIDE
════════════════

Copy the table below as a CSV header line.  All column names are case-insensitive.
Use a comma (,) as separator and UTF-8 encoding.  Empty cells are accepted for
optional columns; the script will compute them from the empirical formulas.

REQUIRED COLUMNS
────────────────
  band            Ham radio band name, e.g. "40m", "20m"
  freq_mhz        Band centre frequency in MHz (e.g. 7.15, 14.175)
  active          YES or NO — whether this band is selected in the Calculator sheet
  lambda_half_m   λ/2 in metres at the centre frequency  (from Calculator sheet)
  wire_len_m      Chosen antenna wire length in metres (same for all rows)
  R_wire_ohm      Empirical R = 50·80^cos²(π·L/λ½)  from VSWR Calculator sheet
  X_wire_ohm      Empirical X = 1500·sin(2π·L/λ½)   from VSWR Calculator sheet
  vswr_no_cp      VSWR without counterpoise (ref 50 Ω) from VSWR Calculator sheet

OPTIONAL but STRONGLY RECOMMENDED
───────────────────────────────────
  lambda_qtr_m    λ/4 in metres (= lambda_half_m / 2)
  L_over_lhalf    L / (λ/2) fraction (= wire_len_m / lambda_half_m)
  vswr_with_cp    VSWR with counterpoise correction from VSWR Calculator sheet
  Z_eff_ohm       Corrected feedpoint Z (R_wire + Zcp) from VSWR Calculator sheet
  Zcp_ohm         Counterpoise impedance Zcp (Ω) from VSWR Calculator sheet
  unun_ratio      UnUn impedance ratio N (e.g. 9 for 9:1 UnUn)
  avoidance_score Resonance avoidance score (0.00–0.25) from Length Sweep sheet
  quality_rating  Text rating, e.g. "★★★ EXCELLENT" from Length Sweep / Calculator
  cp_len_m        Counterpoise length in metres (from Calculator sheet)
  cp_height_m     Counterpoise height above ground in metres (UnUn Calculator)
  num_radials     Number of counterpoise radials (UnUn Calculator)

EXAMPLE  (40m + 20m active, 13.3 m wire, 9:1 UnUn, 1 radial at λ/4)
─────────────────────────────────────────────────────────────────────
band,freq_mhz,active,lambda_half_m,lambda_qtr_m,wire_len_m,L_over_lhalf,R_wire_ohm,X_wire_ohm,vswr_no_cp,vswr_with_cp,Z_eff_ohm,Zcp_ohm,unun_ratio,avoidance_score,quality_rating,cp_len_m,cp_height_m,num_radials
160m,1.9,NO,75.0,37.5,13.3,0.177,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
80m,3.65,NO,39.041,19.52,13.3,0.341,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
60m,5.359,NO,26.591,13.295,13.3,0.500,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
40m,7.15,YES,19.930,9.965,13.3,0.667,175.0,-1354.7,16.25,11.46,1201.0,30.0,9,0.153,★★★ EXCELLENT,9.965,5.0,1
30m,10.125,NO,14.074,7.037,13.3,0.945,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
20m,14.175,YES,10.053,5.026,13.3,1.323,195.0,1388.0,15.08,25.70,237.0,55.0,9,0.153,★★★ EXCELLENT,9.965,5.0,1
17m,18.118,NO,7.865,3.933,13.3,1.691,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
15m,21.225,NO,6.714,3.357,13.3,1.981,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
12m,24.940,NO,5.714,2.857,13.3,2.328,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
10m,28.850,NO,4.939,2.470,13.3,2.694,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1
6m,52.000,NO,2.740,1.370,13.3,4.854,,,,,,,9,0.153,★★★ EXCELLENT,9.965,5.0,1

HOW TO EXPORT THE CSV FROM THE SPREADSHEET
────────────────────────────────────────────
1. Open the VSWR Calculator sheet and UnUn Calculator sheet.
2. Copy the values (NOT formulas) for each band row into a new spreadsheet.
3. Add the column names from the REQUIRED list above as the first row.
4. Save as CSV (UTF-8).
5. Optionally add avoidance_score and quality_rating from the Length Sweep sheet
   for the chosen wire length.

NOTE: The script works with ACTIVE bands only for the comparison.  Inactive bands
are still loaded and appear in the report for reference.
"""
