# NEC2 Antenna Length Optimizer

> **Author:** LU3VEA &nbsp;·&nbsp; **License:** CC0 1.0 Universal (public domain)

A command-line tool that searches for the optimal **wire length** and **counterpoise length** of an end-fed long-wire antenna, minimising aggregate VSWR across all active amateur-radio bands. It drives the open-source `nec2c` electromagnetic simulator directly, or falls back to fast empirical formulas when `nec2c` is not available.

---

## Table of Contents

1. [Theory](#1-theory)
   - 1.1 [End-Fed Long-Wire Antennas](#11-end-fed-long-wire-antennas)
   - 1.2 [The UnUn Impedance Transformer](#12-the-unun-impedance-transformer)
   - 1.3 [The Counterpoise](#13-the-counterpoise)
   - 1.4 [Resonance Avoidance](#14-resonance-avoidance)
   - 1.5 [Scoring Function](#15-scoring-function)
   - 1.6 [Pareto Optimality](#16-pareto-optimality)
   - 1.7 [NEC2 vs Empirical Mode](#17-nec2-vs-empirical-mode)
   - 1.8 [The Retry Mechanism](#18-the-retry-mechanism)
2. [Requirements & Installation](#2-requirements--installation)
   - 2.1 [Python Dependencies](#21-python-dependencies)
   - 2.2 [Installing nec2c](#22-installing-nec2c)
3. [Quick Start](#3-quick-start)
4. [Input: The Band CSV](#4-input-the-band-csv)
   - 4.1 [Required Columns](#41-required-columns)
   - 4.2 [Optional Columns](#42-optional-columns)
   - 4.3 [Example CSV](#43-example-csv)
   - 4.4 [European Locale CSVs](#44-european-locale-csvs)
5. [All Command-Line Options](#5-all-command-line-options)
   - 5.1 [Band / Frequency Source](#51-band--frequency-source)
   - 5.2 [Search Window](#52-search-window)
   - 5.3 [Geometry](#53-geometry)
   - 5.4 [Simulation Control](#54-simulation-control)
   - 5.5 [Retry & Boundary Expansion](#55-retry--boundary-expansion)
   - 5.6 [Output Files](#56-output-files)
   - 5.7 [Misc](#57-misc)
6. [Usage Examples](#6-usage-examples)
   - 6.1 [Minimal: known bands, no CSV](#61-minimal-known-bands-no-csv)
   - 6.2 [With a band CSV](#62-with-a-band-csv)
   - 6.3 [Active-band override](#63-active-band-override)
   - 6.4 [Custom / unknown bands](#64-custom--unknown-bands)
   - 6.5 [Fine-tuning around a known good length](#65-fine-tuning-around-a-known-good-length)
   - 6.6 [Pure empirical mode (no nec2c)](#66-pure-empirical-mode-no-nec2c)
   - 6.7 [Force NEC2 mode, explicit binary](#67-force-nec2-mode-explicit-binary)
   - 6.8 [Automatic boundary expansion with --retry](#68-automatic-boundary-expansion-with---retry)
   - 6.9 [Non-interactive / scripted use](#69-non-interactive--scripted-use)
   - 6.10 [Spanish interface](#610-spanish-interface)
7. [Output Files](#7-output-files)
   - 7.1 [optimizer\_report.txt](#71-optimizer_reporttxt)
   - 7.2 [optimizer\_plot.png](#72-optimizer_plotpng)
   - 7.3 [optimizer\_best.csv](#73-optimizer_bestcsv)
   - 7.4 [best\_antenna.nec](#74-best_antennanec)
   - 7.5 [radiation\_diagrams.png](#75-radiation_diagramspng)
8. [Understanding the Console Output](#8-understanding-the-console-output)
   - 8.1 [Boundary Warnings](#81-boundary-warnings)
   - 8.2 [Retry Messages](#82-retry-messages)
   - 8.3 [Impedance Table](#83-impedance-table)
   - 8.4 [UnUn Analysis](#84-unun-analysis)
9. [Antenna Geometry in NEC2](#9-antenna-geometry-in-nec2)
10. [Known-Band Frequency Table](#10-known-band-frequency-table)
11. [Workflow Recommendations](#11-workflow-recommendations)
12. [Troubleshooting](#12-troubleshooting)
13. [License](#13-license)

---

## 1. Theory

### 1.1 End-Fed Long-Wire Antennas

An end-fed long-wire (EFLW) antenna is a single conductor driven at one end. Its feedpoint impedance varies strongly with frequency because the electrical length relative to the operating wavelength (λ) changes. Resonances — points where the impedance is very low (current maximum, λ/4 multiples with odd parity) or very high (voltage maximum, λ/4 multiples with even parity) — make the impedance difficult to predict analytically.

The feedpoint impedance of a long wire over real ground is approximately:

```
R ≈ 50 · 80^cos²(π·L/λ½)     (empirical, Ω)
X ≈ 1500 · sin(2π·L/λ½)       (empirical, Ω)
```

where `L` is the wire length in metres and `λ½ = c / (2f)` is the half-wavelength. These formulas are the fast-path fallback; the real simulation uses NEC2 with a Sommerfeld-Norton ground model.

### 1.2 The UnUn Impedance Transformer

Because end-fed antennas are unbalanced and their feedpoint impedance is rarely near 50 Ω, a transformer called a **UnUn** (unbalanced-to-unbalanced) is inserted between the feedline and the antenna. A winding ratio of n:1 transforms the antenna-side impedance `Z_ant = R_ant + jX_ant` to the transmitter side as:

```
Z_tx = Z_ant / n     →     R_tx = R_ant/n,  X_tx = X_ant/n
```

Both the resistive and reactive parts are divided by the same factor `n`. The resulting VSWR with respect to a 50 Ω coaxial line is:

```
Γ = |Z_tx - 50| / |Z_tx + 50|
VSWR = (1 + Γ) / (1 - Γ)
```

The optimizer sweeps all standard UnUn ratios (1:1, 1.5:1, 2:1, 3:1, 4:1, 6:1, 9:1, 12:1, 16:1, 25:1, 27:1, 36:1, 49:1, 64:1) plus a continuous golden-section search over 1…100 to find the transformer that minimises aggregate VSWR after the wire and counterpoise lengths are fixed.

Common practical ratios in amateur radio are **4:1** (moderate impedance step), **9:1** (the most popular — suitable for ~450 Ω loads), and **16:1** (suitable for ~800 Ω loads).

### 1.3 The Counterpoise

A counterpoise (CP) is a short wire connected to the ground side of the feedpoint. It acts as the missing half of the dipole system and provides a return current path that would otherwise flow through the feedline braid, causing RF on the coax jacket and unpredictable behaviour.

The optimizer supports two CP orientations:

| Orientation | Description |
|---|---|
| `horizontal` | CP runs horizontally at `--cp-height` metres above ground, away from the antenna in the −x direction. A short vertical drop wire connects it to the feedpoint if needed. |
| `vertical` | CP drops vertically from the feedpoint. If it is longer than the available vertical drop (wire height − CP height), the remainder folds out horizontally, forming an L-shape. |
| `both` (default) | Both orientations are simulated for every candidate pair; the one giving the lower combined score is kept. |

A CP length close to an **odd multiple of λ/4** (1×, 3×, 5× …) presents a low impedance at the feedpoint, which is ideal. Even multiples (λ/2, λ, …) present high impedance and are avoided. The optimizer assigns a small CP-resonance bonus to reward odd multiples, but this bonus cannot override poor VSWR.

### 1.4 Resonance Avoidance

For a multi-band antenna, a resonance on any single band causes the impedance to shoot up or down and the VSWR to spike. The **avoidance score** measures how far the wire length is from the nearest λ/4 resonance on each band:

```
λ/4_n  =  n × c / (4f),  n = 1, 2, 3, …

avoidance(band) = min(frac, 1 − frac)  where frac = (L / λ/4) mod 1
                  clamped to [0, 0.25]
```

A value of **0.25** (maximum possible) means the wire is exactly midway between two adjacent λ/4 resonances on that band — ideal. Values below **0.06** indicate a resonance risk. The optimizer computes this over **all** bands in the CSV (including inactive ones) so that even bands not being scored for VSWR still influence the avoidance term.

| Score | Rating |
|---|---|
| ≥ 0.20 | ★★★ EXCELLENT |
| ≥ 0.12 | ★★  GOOD |
| ≥ 0.06 | ★   MARGINAL |
| < 0.06 | ✗   RESONANCE RISK |

### 1.5 Scoring Function

Each candidate `(wire_len, cp_len)` pair receives a **combined score** (lower = better):

```
score_combined = mean_vswr_penalty
               + 1.5 × worst_vswr_penalty
               − 0.5 × mean_avoidance_active
               − 0.1 × mean_cp_quarter_bonus
```

The VSWR penalty for a single band is a piecewise-linear/logarithmic function:

```
vswr_penalty(v) =
    0                         if v ≤ 1.5   (excellent)
    (v − 1.5) / 1.5           if 1.5 < v ≤ 3.0  (linear ramp)
    1 + (v − 3.0) / 1.5       if 3.0 < v ≤ 6.0  (steeper ramp)
    3 + log10(v/6) × 5        if v > 6.0   (logarithmic)
```

The `1.5 × worst_vswr_penalty` term penalises candidates that are perfect on every band but terrible on one — encouraging balanced performance. The avoidance and CP bonus terms are intentionally small (0.5× and 0.1×) so they only break ties between otherwise similar candidates rather than overriding a genuinely poor VSWR match.

### 1.6 Pareto Optimality

Because two objectives are in play — minimising VSWR penalty (`score_vswr_raw`) and maximising resonance avoidance (`score_avoidance_active`) — a single best point may not exist. A candidate A **dominates** candidate B if A is at least as good as B on both objectives and strictly better on at least one. The **Pareto front** is the set of candidates not dominated by any other.

The report shows both the combined-score ranking (for a definitive single recommendation) and the full Pareto front (for users who want to trade off VSWR slightly for better resonance avoidance, or vice versa).

### 1.7 NEC2 vs Empirical Mode

| Feature | NEC2 mode | Empirical mode |
|---|---|---|
| **Accuracy** | Full electromagnetic simulation via Sommerfeld-Norton ground | Closed-form formulas (± 20–40% near resonances) |
| **Speed** | ~0.5–5 s per candidate × grid size | < 1 ms per candidate |
| **Ground model** | Conductivity + permittivity (configurable) | None |
| **Radiation pattern** | Full RP sweep, elevation and azimuth diagrams | Not available |
| **CP type** | Both orientations simulated, best selected | Fixed single orientation |
| **Requirement** | `nec2c` binary | None |

The tool automatically selects NEC2 mode if `nec2c` is found, and falls back to empirical otherwise (mode `auto`). Use `--mode nec2` to require NEC2 and abort if the binary is missing; use `--mode empirical` to force empirical even when `nec2c` is present.

**Empirical formula reference:**
```
R = 50 × 80^cos²(π × L/λ½)
X = 1500 × sin(2π × L/λ½)
```

### 1.8 The Retry Mechanism

When the best candidate sits at the edge of the search window, the true optimum likely lies outside it. The optimizer detects this automatically and, if `--retry N` is set, re-runs the sweep up to N times:

- **Best at maximum** → window shifts **upward**: new range = `[best, best + margin]`
- **Best at minimum** → window shifts **downward**: new range = `[best − margin, best]`

Wire and counterpoise boundaries are checked and shifted independently in the same retry. The loop stops early if:
- No boundary is hit (converged), or
- The new sweep yields no improvement over the current best.

---

## 2. Requirements & Installation

### 2.1 Python Dependencies

Python 3.8+ is required. The script uses only the standard library for its core function. Optional packages enable richer output:

```bash
pip install colorama tabulate matplotlib
```

| Package | Effect if missing |
|---|---|
| `colorama` | Console output has no colour (works on all platforms) |
| `tabulate` | Report table uses plain ASCII instead of Unicode box-drawing |
| `matplotlib` | No PNG plots are generated |

Install everything at once:
```bash
pip install colorama tabulate matplotlib
```

Or install only the packages you need. The script degrades gracefully in all cases.

### 2.2 Installing nec2c

`nec2c` is the C port of the original NEC-2 Fortran code.

**Debian / Ubuntu:**
```bash
sudo apt update && sudo apt install nec2c
```

**macOS (Homebrew):**
```bash
brew install nec2c
```

**From source:**
```bash
git clone https://github.com/KJ4IPS/nec2c.git
cd nec2c && ./configure && make && sudo make install
```

**Verification:**
```bash
nec2c --version
# or simply:
which nec2c
```

**Binary discovery order** (the script tries these in sequence):
1. `--nec2c /explicit/path` CLI flag
2. `$NEC2C` environment variable
3. `nec2c` and `nec2c-mpich` on `$PATH`
4. Hard-coded paths: `/usr/bin/nec2c`, `/usr/local/bin/nec2c`, `/opt/nec2c/bin/nec2c`, `/opt/homebrew/bin/nec2c`, etc.
5. Interactive prompt (unless `--no-interactive` is set)

If none of the above succeed, the script falls back to empirical mode (or exits if `--mode nec2` was specified).

---

## 3. Quick Start

```bash
# Clone or download
git clone https://example.com/nec2_length_optimizer.git
cd nec2_length_optimizer

# Install optional dependencies
pip install colorama tabulate matplotlib

# Run with known amateur bands, no CSV needed
python nec2_length_optimizer.py \
    --bands 40m,20m,15m,10m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9

# Run with a band CSV for full control
python nec2_length_optimizer.py --csv my_bands.csv
```

Within seconds (empirical) or minutes (NEC2, depending on grid size), you will see:

```
★ BEST CANDIDATE:  wire = 21.250 m   cp = 5.500 m   (horizontal)
    Combined score  = 0.4821
    VSWR penalty    = 0.3104
    Avoidance mean  = 0.1823

  Impedance — antenna side & transmitter side (UnUn 9:1):
      Band      MHz    R_ant    X_ant   |Z_ant|    R_tx    X_tx   |Z_tx|   VSWR       Src
      ────────────────────────────────────────────────────────────────────────────────────
        40m    7.100    312.4   +154.8    349.1   34.71  +17.20   38.79   1.64   NEC2-H
        20m   14.175    891.2   −230.5    921.5   99.02  −25.61  102.27   2.14   NEC2-H
        15m   21.225    124.8   −315.6    339.3   13.87  −35.07   37.72   3.87   NEC2-H
        10m   28.500   2145.3   +890.2   2322.1  238.37  +98.91  258.05   5.41   NEC2-H
```

Four output files are written: `optimizer_report.txt`, `optimizer_plot.png`, `optimizer_best.csv`, `best_antenna.nec`.

---

## 4. Input: The Band CSV

The CSV is the most powerful input method. It lets you define every band with its exact centre frequency, whether it is active for VSWR scoring, the starting wire and CP lengths, antenna heights, and the UnUn ratio — all in one place.

### 4.1 Required Columns

| Column | Type | Description |
|---|---|---|
| `band` | string | Band name, e.g. `40m`, `20m`, `custom1` |
| `freq_mhz` | float | Centre frequency in MHz |
| `active` | YES/NO | Include in VSWR scoring? (`YES`, `Y`, `TRUE`, `1`, `ACTIVE` all accepted) |
| `lambda_half_m` | float | Half-wavelength in metres (`c / (2f)`) |
| `wire_len_m` | float | Starting wire length (sets the search window centre) |
| `r_wire_ohm` | float | Feedpoint resistance (empirical or measured). Set to 0 to let the script compute it. |
| `x_wire_ohm` | float | Feedpoint reactance (empirical or measured). Set to 0 to let the script compute it. |
| `vswr_no_cp` | float | VSWR without counterpoise (set to 0 to auto-compute) |

### 4.2 Optional Columns

| Column | Type | Description |
|---|---|---|
| `lambda_qtr_m` | float | Quarter-wavelength in metres |
| `L_over_lhalf` | float | Wire length / λ½ ratio |
| `vswr_with_cp` | float | VSWR with counterpoise (reference only) |
| `Z_eff_ohm` | float | Effective feedpoint impedance magnitude (reference) |
| `Zcp_ohm` | float | Counterpoise series impedance (reference) |
| `unun_ratio` | float | UnUn ratio for this band row (single unique value used for all) |
| `avoidance_score` | float | Pre-computed avoidance score (overrides the computed value if non-zero) |
| `quality_rating` | string | Pre-computed quality label (reference only) |
| `cp_len_m` | float | Starting counterpoise length (sets the CP search window centre) |
| `cp_height_m` | float | Counterpoise height above ground in metres |
| `wire_height_m` | float | Antenna wire height above ground in metres |
| `num_radials` | int | Number of counterpoise radials (reference only; simulation uses 1) |

Column names are matched **case-insensitively** and leading/trailing spaces are ignored.

### 4.3 Example CSV

```csv
band,freq_mhz,active,lambda_half_m,wire_len_m,r_wire_ohm,x_wire_ohm,vswr_no_cp,unun_ratio,cp_len_m,cp_height_m,wire_height_m
160m,1.850,NO,81.025,21.0,0,0,0,9,5.0,0.5,8.0
80m,3.650,YES,41.067,21.0,0,0,0,9,5.0,0.5,8.0
40m,7.100,YES,21.112,21.0,0,0,0,9,5.0,0.5,8.0
30m,10.125,NO,14.793,21.0,0,0,0,9,5.0,0.5,8.0
20m,14.175,YES,10.567,21.0,0,0,0,9,5.0,0.5,8.0
17m,18.118,NO,8.276,21.0,0,0,0,9,5.0,0.5,8.0
15m,21.225,YES,7.066,21.0,0,0,0,9,5.0,0.5,8.0
12m,24.940,NO,6.011,21.0,0,0,0,9,5.0,0.5,8.0
10m,28.500,YES,5.260,21.0,0,0,0,9,5.0,0.5,8.0
6m,50.200,NO,2.985,21.0,0,0,0,9,5.0,0.5,8.0
```

> **Note:** Setting `r_wire_ohm`, `x_wire_ohm`, and `vswr_no_cp` to `0` tells the script to compute them from the empirical formulas. Supply actual measured or NEC2-derived values if you have them — the script will not overwrite non-zero entries.

### 4.4 European Locale CSVs

If your CSV uses semicolons as separators and commas as decimal separators (common in Excel when the system locale is set to Spanish, German, French, etc.), the script detects this automatically and normalises the file before parsing:

```
  CSV format    : European locale (';' sep, ',' decimal) — normalised
```

No manual conversion is needed.

---

## 5. All Command-Line Options

Run `python nec2_length_optimizer.py --help` to see the full list. Below is a structured reference.

### 5.1 Band / Frequency Source

| Flag | Default | Description |
|---|---|---|
| `--csv FILE` | — | Band CSV file. If supplied, all band/frequency/height/UnUn data is read from it. |
| `--bands NAMES` | — | Comma-separated band names when not using a CSV. E.g. `40m,20m,15m`. |
| `--freqs MHZ` | auto | Comma-separated centre frequencies in MHz, one per `--bands` entry. Optional when all names are in the built-in frequency table. Required for unrecognised names. |
| `--active-bands BANDS` | all | Override which bands are scored for VSWR. E.g. `40m,20m` to score only those two regardless of the CSV `active` column. |
| `--unun RATIO` | from CSV | UnUn ratio, e.g. `9` for 9:1. Read from CSV if present; prompted interactively otherwise. |

### 5.2 Search Window

| Flag | Default | Description |
|---|---|---|
| `--wire-len M` | from CSV | Starting wire length in metres. Sets the search window centre when `--wire-min`/`--wire-max` are not given. |
| `--cp-len M` | from CSV | Starting CP length in metres. Sets the search window centre. |
| `--margin M` | `2.0` | Search radius (metres) added/subtracted from the starting lengths to form the default window. Ignored when explicit `--wire-min`/`--wire-max` are given. |
| `--wire-min M` | auto | Hard minimum wire length to search. Overrides `--margin` for the lower bound. |
| `--wire-max M` | auto | Hard maximum wire length to search. Overrides `--margin` for the upper bound. |
| `--wire-step M` | `0.25` | Grid step size for wire length (metres). |
| `--cp-min M` | auto | Hard minimum CP length to search. |
| `--cp-max M` | auto | Hard maximum CP length to search. |
| `--cp-step M` | `0.25` | Grid step size for CP length (metres). |

**How the search window is built:**

```
wire_min = max(1.0, wire_ref − margin)
wire_max = wire_ref + margin
```

where `wire_ref` comes from `--wire-len`, or the mean of the `wire_len_m` column in the CSV. The same logic applies to the CP.

### 5.3 Geometry

| Flag | Default | Description |
|---|---|---|
| `--wire-height M` | from CSV or `8.0` | Height of the antenna wire above ground in metres. |
| `--cp-height M` | from CSV or `0.5` | Height of the counterpoise above ground in metres. |
| `--cp-type` | `both` | Counterpoise orientation: `horizontal`, `vertical`, or `both`. |
| `--ground-cond S/M` | `0.005` | Ground conductivity in S/m. Typical values: very poor = 0.001, average = 0.005, good = 0.01, sea water = 4.0. |
| `--ground-diel EPS` | `13.0` | Ground relative permittivity. Typical values: dry sandy = 3, average = 13, rich soil = 20. |

### 5.4 Simulation Control

| Flag | Default | Description |
|---|---|---|
| `--mode MODE` | `auto` | `auto` (use NEC2 if available, else empirical), `nec2` (require NEC2), `empirical` (force empirical). |
| `--nec2c PATH` | auto | Explicit path to the `nec2c` binary. Overrides auto-discovery. |

### 5.5 Retry & Boundary Expansion

| Flag | Default | Description |
|---|---|---|
| `--retry N` | `0` | If the best candidate is at a search boundary, re-run the sweep up to N times, shifting the window in the direction of the warning. `0` disables auto-retry. |

### 5.6 Output Files

| Flag | Default | Description |
|---|---|---|
| `--out-txt FILE` | `optimizer_report.txt` | Full ranked text report. |
| `--out-png FILE` | `optimizer_plot.png` | Score heat map + per-band VSWR bar charts. |
| `--out-csv FILE` | `optimizer_best.csv` | Best candidate in the same CSV format as the input, ready to feed back as `--csv`. |
| `--out-nec FILE` | `best_antenna.nec` | Ready-to-use NEC2 input deck for the best geometry, with radiation-pattern cards for all active bands. |
| `--out-radiation FILE` | `radiation_diagrams.png` | Elevation and azimuth radiation diagrams per band (NEC2 mode only). |
| `--top-n N` | `20` | Number of top candidates to show in the report. |

### 5.7 Misc

| Flag | Default | Description |
|---|---|---|
| `--lang LANG` | auto | Interface language: `en` (English) or `es` (Español). Auto-detected from system locale if not set. |
| `--no-interactive` | off | Do not prompt for missing inputs; exit with an error instead. Suitable for scripted/automated use. |
| `--quiet` / `-q` | off | Suppress progress output during the sweep. |

---

## 6. Usage Examples

### 6.1 Minimal: known bands, no CSV

The simplest invocation. Band frequencies are auto-resolved from the built-in table. A ±2 m search window is built around the provided wire and CP lengths.

```bash
python nec2_length_optimizer.py \
    --bands 80m,40m,20m,15m,10m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9
```

Expected console output (abridged):
```
  Frequencies   : auto-resolved from band names
      80m → 3.65 MHz
      40m → 7.1 MHz
      20m → 14.175 MHz
      15m → 21.225 MHz
      10m → 28.5 MHz
  Search margin : ±2.0 m around --wire-len 21.000 m
  --wire-min    : 19.0 m
  --wire-max    : 23.0 m
  Grid size     : 289 candidates
```

### 6.2 With a band CSV

```bash
python nec2_length_optimizer.py --csv my_bands.csv
```

All band data, the UnUn ratio, and the starting lengths are read from the CSV. The `active` column controls which bands enter the VSWR objective.

### 6.3 Active-band override

Score only 40 m and 20 m even though the CSV also has 80 m, 15 m, and 10 m defined:

```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --active-bands 40m,20m
```

Bands not in `--active-bands` still appear in the avoidance calculation but do not affect the VSWR term.

### 6.4 Custom / unknown bands

If you are not working in the amateur bands you must supply `--freqs`:

```bash
python nec2_length_optimizer.py \
    --bands CB,Marine,Aviation \
    --freqs 27.185,156.800,121.500 \
    --wire-len 5.5 \
    --cp-len 2.0 \
    --unun 4 \
    --mode empirical
```

### 6.5 Fine-tuning around a known good length

After a first run finds the best at 21.25 m / 5.50 m, refine with a finer grid over a tighter window:

```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --wire-min 20.5 \
    --wire-max 22.0 \
    --wire-step 0.05 \
    --cp-min 5.0 \
    --cp-max 6.0 \
    --cp-step 0.05 \
    --out-txt refined_report.txt \
    --out-png refined_plot.png
```

The smaller step (0.05 m vs the default 0.25 m) gives 30×30 = 900 candidates, evaluating the neighbourhood at 5 cm resolution.

### 6.6 Pure empirical mode (no nec2c)

Useful for a fast first pass or when `nec2c` is not installed:

```bash
python nec2_length_optimizer.py \
    --bands 40m,20m,15m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9 \
    --mode empirical \
    --wire-step 0.1 \
    --cp-step 0.1
```

With 0.1 m steps over a ±2 m window this evaluates 41 × 41 = 1681 candidates in under a second.

### 6.7 Force NEC2 mode, explicit binary

```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --mode nec2 \
    --nec2c /opt/nec2c/bin/nec2c \
    --cp-type both \
    --wire-height 10.0 \
    --cp-height 1.0 \
    --ground-cond 0.010 \
    --ground-diel 20.0
```

This simulates both horizontal and vertical CP for each candidate over rich soil (σ = 0.010 S/m, εᵣ = 20) with the antenna wire at 10 m.

### 6.8 Automatic boundary expansion with --retry

If you do not know a good starting length and want the optimizer to explore outward automatically:

```bash
python nec2_length_optimizer.py \
    --bands 80m,40m,20m,15m,10m \
    --wire-len 20.0 \
    --cp-len 5.0 \
    --unun 9 \
    --margin 3.0 \
    --retry 4
```

If the first pass finds its best at the 23 m edge, the second pass searches 23–26 m; if that best is again at 26 m, the third pass searches 26–29 m, and so on up to 4 retries. Each retry narrows the new window to `[best, best+margin]` (for "may be longer") or `[best−margin, best]` (for "may be shorter") and stops as soon as no improvement is found.

Console output during retry:
```
  🔁  --retry: wire boundary at maximum — expanding upper bound to 26.000 m (retry 2/4)
  ✔  --retry: new best after retry — wire = 25.250 m   cp = 5.500 m   score = 0.4102
  ✔  --retry: boundary no longer hit — converged after 2 retry(s).
```

### 6.9 Non-interactive / scripted use

For use in shell scripts, cron jobs, or CI pipelines where there is no terminal for interactive input:

```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --no-interactive \
    --quiet \
    --out-txt /results/report.txt \
    --out-csv /results/best.csv \
    --out-png /results/plot.png
```

`--no-interactive` causes the script to exit with a non-zero code instead of prompting if `nec2c` is not found, the UnUn is missing, or other inputs are absent. `--quiet` suppresses the progress counter during the sweep.

### 6.10 Spanish interface

The language is auto-detected from the system locale. Override explicitly:

```bash
python nec2_length_optimizer.py --csv bandas.csv --lang es
```

All console messages, report headers, and plot labels will appear in Spanish.

---

## 7. Output Files

### 7.1 optimizer_report.txt

A plain-text file (ANSI colour codes stripped) containing:

- **Run parameters:** mode, UnUn ratio, wire and CP search ranges, active bands, total candidates evaluated.
- **Top N candidates table:** wire length, CP length, CP orientation, combined score, VSWR penalty, avoidance score, and per-band VSWR.
- **Pareto-optimal front:** all candidates not dominated on (VSWR penalty, avoidance).
- **Best candidate detailed breakdown:** per-band impedance on both the antenna side and the transmitter (post-UnUn) side, VSWR label, avoidance rating.
- **Boundary warnings** (if applicable).
- **UnUn analysis:** current vs best standard vs continuous-optimal ratio, per-band optimal UnUn.
- **Theory notes** explaining the scoring, avoidance metric, empirical formulas, and next steps.

### 7.2 optimizer_plot.png

A multi-panel PNG figure (requires `matplotlib`):

- **Score heat map:** 2-D grid of all evaluated candidates coloured by combined score; Pareto front highlighted; best candidate marked with a star.
- **Per-band VSWR bar charts:** one bar per active band at the best candidate, coloured green (≤ 1.5), yellow (≤ 3), or red (> 3).
- **Pareto space scatter plot:** VSWR penalty vs avoidance, showing the trade-off frontier.

### 7.3 optimizer_best.csv

The best candidate written in the same format as the input CSV, pre-populated with the optimal wire length, CP length, and UnUn ratio. You can immediately feed this file back as `--csv` for a refined search or pass it to companion analysis tools.

### 7.4 best_antenna.nec

A complete NEC2 input deck for the best geometry, ready to open in `xnec2c`, `4nec2`, or any NEC2 front-end. Includes:

- `GW` geometry cards for the antenna wire and counterpoise.
- `GN` ground card with the configured conductivity and permittivity.
- `EX` excitation card at the feedpoint (segment 1 of wire 1).
- `FR` + `XQ` + `RP` cards for every active band, generating both impedance and radiation-pattern output.
- `CM` comment cards recording the wire length, CP length, type, and heights.

### 7.5 radiation_diagrams.png

Available in **NEC2 mode only**. For the best candidate, a full radiation-pattern sweep is run (18 elevation × 72 azimuth points per band). The figure shows one row per active band:

- **Left panel:** Elevation pattern (−90° to +90° in polar form). Dashed red lines indicate the take-off angle.
- **Right panel:** Azimuth pattern at the elevation of maximum gain.
- Titles include the band, frequency, VSWR, maximum gain (dBi), and take-off angle (TOA).

---

## 8. Understanding the Console Output

### 8.1 Boundary Warnings

If the best candidate lands at the edge of the search window, a yellow warning is printed **and** written to the report:

```
  ⚠  WIRE LENGTH at search maximum (23.000 m).  3/5 top candidates hit this boundary.
     The true optimum may be longer. Re-run with a larger --wire-max or increase --margin.
```

The `3/5` fraction counts how many of the top-5 ranked candidates also hit that boundary. If all 5 hit it, the optimum is very likely outside the window. If only 1 hits it, the warning is less urgent.

The four possible warnings are:

| Warning | Meaning | Action |
|---|---|---|
| WIRE at search **maximum** | True optimum may be **longer** | Increase `--wire-max` or `--margin`; use `--retry` |
| WIRE at search **minimum** | True optimum may be **shorter** | Decrease `--wire-min` or `--margin`; use `--retry` |
| CP at search **maximum** | True optimum may be **longer** | Increase `--cp-max` or `--margin`; use `--retry` |
| CP at search **minimum** | True optimum may be **shorter** | Decrease `--cp-min` or `--margin`; use `--retry` |

### 8.2 Retry Messages

When `--retry N` is active, the retry loop prints progress in cyan/yellow/green:

```
  🔁  --retry: wire boundary at maximum — expanding upper bound to 26.000 m (retry 1/3)
  ✔  --retry: new best after retry — wire = 25.250 m   cp = 5.500 m   score = 0.4102
  🔁  --retry: wire boundary at maximum — expanding upper bound to 28.000 m (retry 2/3)
  ℹ  --retry: no improvement found — keeping previous best (wire = 25.250 m, cp = 5.500 m).
```

The loop stops as soon as `no improvement found` appears (the new window is worse or equivalent) or the boundary is no longer hit (`converged`).

### 8.3 Impedance Table

```
  Impedance — antenna side & transmitter side (UnUn 9:1):
      Band      MHz    R_ant    X_ant   |Z_ant|    R_tx    X_tx   |Z_tx|   VSWR       Src
      ────────────────────────────────────────────────────────────────────────────────────
        40m    7.100    312.4   +154.8    349.1   34.71  +17.20   38.79   1.64   NEC2-H
        20m   14.175    891.2   −230.5    921.5   99.02  −25.61  102.27   2.14   NEC2-H
        15m   21.225    124.8   −315.6    339.3   13.87  −35.07   37.72   3.87   NEC2-H
        10m   28.500   2145.3   +890.2   2322.1  238.37  +98.91  258.05   5.41   NEC2-H
```

- **R_ant / X_ant:** Antenna-side feedpoint impedance in Ω (from NEC2 or empirical formula).
- **|Z_ant|:** Magnitude of antenna impedance.
- **R_tx / X_tx:** Transmitter-side impedance after the UnUn (both divided by the UnUn ratio n).
- **|Z_tx|:** Magnitude of transmitter-side impedance.
- **VSWR:** VSWR relative to 50 Ω at the transmitter side. Coloured green (≤ 1.5), yellow (≤ 3), red (> 3).
- **Src:** Source of the impedance data: `NEC2-H` (horizontal CP simulation), `NEC2-V` (vertical CP), or `empirical`.

### 8.4 UnUn Analysis

After the best geometry is identified, a UnUn sweep is performed:

```
  UnUn Analysis (best geometry: 21.250 m / 5.500 m):
    Current ratio    : 9:1  (aggregate VSWR penalty 1.3842)
    Best standard    : 9:1  (aggregate VSWR penalty 1.3842)
    Continuous opt.  : 8.73:1  (aggregate VSWR penalty 1.3719)
    → Current 9:1 is optimal among standard ratios.
```

If the optimal standard ratio differs significantly from the one you are using, a recommendation to switch is printed. Per-band optimal ratios are also tabulated.

---

## 9. Antenna Geometry in NEC2

The NEC2 deck models the following geometry:

```
                          wire_height_m
                 ─────────────────────────────── Wire 1 (antenna)
                 feedpoint (0,0,wire_height_m)
                 |
                 | drop wire (if cp_height < wire_height, horizontal CP only)
                 |
  cp_height_m    ──────────── Wire 2/3 (counterpoise, horizontal or L-shaped)
```

For a **horizontal** counterpoise:
- Wire 1: `(0,0,h) → (L,0,h)` — the antenna, length `wire_len_m`, at height `wire_height_m`.
- Wire 2 (drop): `(0,0,h) → (0,0,cp_h)` — vertical drop from feedpoint to CP height (omitted if cp_height ≥ wire_height).
- Wire 3 (CP): `(0,0,cp_h) → (−cp_len,0,cp_h)` — horizontal CP, going in the −x direction.

For a **vertical** counterpoise:
- Wire 1: same antenna.
- Wire 2: `(0,0,h) → (0,0,bottom)` — vertical drop, where `bottom = max(cp_height, wire_height − cp_len)`.
- Wire 3 (if needed): horizontal remainder at the bottom, going in the −x direction.

The excitation (`EX` card) is placed at segment 1 of wire 1 — the first segment at the feedpoint end `(0,0,wire_height_m)`.

The ground model uses `GN 2` (Sommerfeld-Norton real ground) with the configured conductivity and permittivity.

---

## 10. Known-Band Frequency Table

When `--bands` is used without `--freqs`, these ITU centre frequencies are used:

| Band | Frequency (MHz) | Band | Frequency (MHz) |
|---|---|---|---|
| 2200m | 0.1365 | 17m | 18.118 |
| 630m | 0.475 | 15m | 21.225 |
| 160m | 1.850 | 12m | 24.940 |
| 80m | 3.650 | 10m | 28.500 |
| 60m | 5.350 | 6m | 50.200 |
| 40m | 7.100 | 4m | 70.200 |
| 30m | 10.125 | 2m | 144.200 |
| 20m | 14.175 | 70cm | 432.100 |
| | | 23cm | 1296.200 |

Band names are matched case-insensitively and accept with or without the trailing `m` (e.g. `40` and `40m` both work).

For any other frequency, supply `--freqs` with explicit values:

```bash
--bands MyBand1,MyBand2 --freqs 27.185,50.000
```

---

## 11. Workflow Recommendations

### First run — coarse scan
```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --margin 5.0 \
    --wire-step 0.5 \
    --cp-step 0.5 \
    --retry 3
```
Use a wide margin (5 m) and coarse step (0.5 m) to quickly map the landscape. `--retry 3` lets the window walk until it finds the true region.

### Second run — fine-tune
```bash
python nec2_length_optimizer.py \
    --csv my_bands.csv \
    --wire-min 20.0 \
    --wire-max 23.0 \
    --wire-step 0.05 \
    --cp-min 4.5 \
    --cp-max 6.5 \
    --cp-step 0.05
```
Narrow the window around the coarse best and refine at 5 cm resolution.

### Validate UnUn
Look at the **UnUn Analysis** section of the report. If the continuous optimum `n` is far from your installed transformer ratio, consider building or buying a different core.

### Compare orientations
Run once with `--cp-type horizontal`, once with `--cp-type vertical`, and compare the combined scores and per-band VSWR. In practice, vertical CPs can outperform horizontal ones at low heights.

### Validate on the bench
The optimizer gives you the best geometry *on paper*. Always verify with a VNA or antenna analyser before cutting the final wire. Ground conditions, nearby structures, and actual wire sag all affect the real-world result.

### Typical ground parameters

| Ground type | σ (S/m) | εᵣ |
|---|---|---|
| Very dry / sandy | 0.001 | 3 |
| Average / mixed | 0.005 | 13 |
| Good / rich soil | 0.010 | 20 |
| Marshy / wet | 0.030 | 30 |
| Sea water | 4.000 | 80 |

---

## 12. Troubleshooting

**`nec2c` is not found automatically**

```
  nec2c binary not found automatically.
  Options:
    • Install:  sudo apt install nec2c   (Debian/Ubuntu)
    •           brew install nec2c        (macOS / Homebrew)
    • Re-run with:  --nec2c /full/path/to/nec2c
    • Set env var:  export NEC2C=/full/path/to/nec2c
```

Either install `nec2c` or pass its path explicitly with `--nec2c`. If you just want fast results without it, add `--mode empirical`.

---

**No active bands found**

```
  No active bands found.  Set the 'active' column to YES in the CSV,
  or use --active-bands, or omit --active-bands to activate all --bands.
```

Check that the `active` column in your CSV contains `YES` (or `Y`, `TRUE`, `1`, `ACTIVE`) for at least one row. If you are using `--bands` without a CSV, all bands are active by default.

---

**`--freqs` mismatch error**

```
  ERROR: --bands has 3 entries but --freqs has 2 entries.  They must match one-to-one.
```

Count your comma-separated values in `--bands` and `--freqs` — they must be equal.

---

**Boundary warning persists after `--retry`**

If `--retry N` exhausts all N retries and the boundary warning is still present, the true optimum may be beyond what is physically reasonable. Consider:
- Whether such a long/short wire is physically buildable at your site.
- Whether the frequency allocation or UnUn ratio is causing an inherently bad match (try `--unun 4` or `--unun 16`).
- Running with `--mode empirical` and a very wide range to survey the full landscape cheaply before committing to a long NEC2 run.

---

**All VSWR values are very high**

If every band shows VSWR > 6:
1. The UnUn ratio may be wrong. Check the `UnUn Analysis` section — it will suggest a better ratio.
2. The wire length may be resonant on most bands simultaneously (avoidance score near 0). Try adding or subtracting 1–2 m.
3. The ground model may not match reality. Try different `--ground-cond` / `--ground-diel` values.
4. In empirical mode, results near resonances can be inaccurate. Try `--mode nec2`.

---

**Plot file is not generated**

`matplotlib` is not installed. Install it:
```bash
pip install matplotlib
```

---

**Radiation diagrams are missing**

Radiation diagrams require NEC2 mode. Check that:
1. `nec2c` is installed and found.
2. `--mode` is `nec2` or `auto` (not `empirical`).
3. There is at least one active band.

---

## 13. License

```
CC0 1.0 Universal (CC0 1.0) Public Domain Dedication

To the extent possible under law, the author (LU3VEA) has waived all
copyright and related or neighbouring rights to this work.
You can copy, modify, distribute and perform the work, even for
commercial purposes, all without asking permission.

https://creativecommons.org/publicdomain/zero/1.0/
```
