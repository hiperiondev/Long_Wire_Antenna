# 📡 Long Wire Antenna + UnUn — Multi-Band Optimizer

> An Excel-based engineering calculator for designing non-resonant long-wire (end-fed random wire) HF antennas with impedance-matching UnUn transformers. Supports multi-band optimization from 160 m through 6 m, with resonance avoidance scoring, VSWR estimation, UnUn ratio sweep, and counterpoise recommendations.

---

## Table of Contents

1. [Background & Theory](#1-background--theory)
   - [What Is a Long Wire Antenna?](#11-what-is-a-long-wire-antenna)
   - [Why Impedance Matching Matters](#12-why-impedance-matching-matters)
   - [The UnUn (Unbalanced-to-Unbalanced Transformer)](#13-the-unun-unbalanced-to-unbalanced-transformer)
   - [Impedance at the Feedpoint — The Physics](#14-impedance-at-the-feedpoint--the-physics)
   - [Resonance Avoidance — The Core Design Problem](#15-resonance-avoidance--the-core-design-problem)
   - [Velocity Factor](#16-velocity-factor)
   - [The Counterpoise (Ground Reference)](#17-the-counterpoise-ground-reference)
2. [Features of this Calculator](#2-features-of-this-calculator)
3. [Workbook Structure](#3-workbook-structure)
   - [Sheet 1 — Calculator](#31-sheet-1--calculator)
   - [Sheet 2 — VSWR Calculator](#32-sheet-2--vswr-calculator)
   - [Sheet 3 — UnUn Ratio Optimizer](#33-sheet-3--unun-ratio-optimizer)
   - [Sheet 4 — Length Sweep](#34-sheet-4--length-sweep)
   - [Sheet 5 — UnUn Calculator](#35-sheet-5--unun-calculator)
   - [Sheet 6 — Toroid Database](#36-sheet-6--toroid-database)
4. [How to Use the Calculator](#4-how-to-use-the-calculator)
   - [Step-by-Step Quick Start](#41-step-by-step-quick-start)
   - [Interpreting the Avoidance Score](#42-interpreting-the-avoidance-score)
   - [Interpreting the VSWR Results](#43-interpreting-the-vswr-results)
   - [Selecting the Best UnUn Ratio](#44-selecting-the-best-unun-ratio)
5. [Mathematical Model](#5-mathematical-model)
   - [Half-Wave Formula with Velocity Factor](#51-half-wave-formula-with-velocity-factor)
   - [Resonance Avoidance Score Formula](#52-resonance-avoidance-score-formula)
   - [Feedpoint Impedance Estimation Model](#53-feedpoint-impedance-estimation-model)
   - [VSWR Calculation](#54-vswr-calculation)
   - [Counterpoise Length Formula](#55-counterpoise-length-formula)
   - [UnUn Turns Ratio and Impedance Ratio](#56-unun-turns-ratio-and-impedance-ratio)
6. [Practical Construction Guidance](#6-practical-construction-guidance)
   - [Wire Length Recommendations](#61-wire-length-recommendations)
   - [Building a 9:1 UnUn Transformer](#62-building-a-91-unun-transformer)
   - [Toroid Core Selection](#63-toroid-core-selection)
   - [Counterpoise Design and Installation](#64-counterpoise-design-and-installation)
   - [Antenna Configurations](#65-antenna-configurations)
   - [Common-Mode Choke / RF Choke](#66-common-mode-choke--rf-choke)
7. [Supported HF Bands](#7-supported-hf-bands)
8. [Limitations and Caveats](#8-limitations-and-caveats)
9. [Glossary](#9-glossary)
10. [References and Further Reading](#10-references-and-further-reading)
11. [License](#11-license)

---

## 1. Background & Theory

### 1.1 What Is a Long Wire Antenna?

In strict technical terms, a **long wire antenna** is a traveling-wave antenna many wavelengths long, with directivity that increases with length. However, in everyday amateur radio usage the term "long wire" refers to any **end-fed random-length wire** — typically between 10 m and 60 m of bare or insulated copper wire, fed at one end against a counterpoise.

This is also called:
- **EFRW** — End-Fed Random Wire
- **Non-resonant end-fed wire**
- **Random wire antenna**

The wire is suspended as high as possible and as horizontally as practical, exiting the shack or transmitter location and running to a convenient support (tree, mast, fence post). On transmission it radiates in all directions; on reception it collects signals from all directions. The great advantages are **simplicity**, **low cost**, and the ability to operate on **multiple HF bands** with a single wire and a single matching device.

### 1.2 Why Impedance Matching Matters

Modern HF transceivers and receivers present a **50 Ω unbalanced** (coaxial) port. The feedpoint impedance of an end-fed wire, however, fluctuates dramatically with frequency and wire length — varying from roughly 20–50 Ω (near a quarter-wave resonance, very low) up to several thousand ohms (near a half-wave resonance, very high). Without matching, this mismatch causes:

- High **Reflected Power** and standing-wave ratio (SWR) on the feedline
- Possible damage to the transmitter's output stage
- Efficiency loss due to reflected waves on lossy coaxial cable
- Erratic ATU (Antenna Tuner Unit) behaviour or inability to tune

A **broadband impedance transformer** placed at the antenna feedpoint pre-matches the wire's impedance to a value within the tuning range of the transceiver or of an auxiliary ATU, dramatically reducing these problems.

### 1.3 The UnUn (Unbalanced-to-Unbalanced Transformer)

A **UnUn** (from *Un*balanced-to-*Un*balanced) is a broadband RF transformer where both the primary (feedline side) and the secondary (antenna side) are unbalanced with respect to ground. This distinguishes it from a **BalUn** (Balanced-to-Unbalanced), which is appropriate for balanced antenna systems such as dipoles.

A long-wire end-fed antenna is **inherently unbalanced**: one side of the feedpoint goes to the radiating wire, the other to the counterpoise (or ground). The 50 Ω coaxial feedline is also unbalanced: the center conductor carries the signal and the shield is the return path. Therefore, a UnUn is the correct choice for this application — using a BalUn here would be technically incorrect, even though many commercial products are mislabeled.

**How the UnUn transforms impedance:**

The most common ratio used with long-wire antennas is **9:1**, meaning the impedance at the antenna side is 9× that at the coaxial side. So:

```
Z_antenna ≈ 9 × Z_feedline = 9 × 50 Ω = 450 Ω
```

This means the antenna wire should ideally present approximately **450 Ω** at the feedpoint for a direct 9:1 match, which happens at wire lengths that are roughly **3/8 λ or 5/8 λ** — the midpoints between quarter-wave (low-impedance) and half-wave (high-impedance) resonances.

In practice, because a long wire must cover many bands simultaneously, an exact 450 Ω match is impossible everywhere. The 9:1 UnUn simply brings the feedpoint impedance within a range manageable by an ATU (typically below 5:1 SWR).

Other common UnUn ratios include:
- **4:1** — useful when the wire presents impedances in the 100–250 Ω range
- **16:1** — for high-impedance wires
- **49:1** (7:1 turns ratio) — widely used for End-Fed Half-Wave (EFHW) antennas, where feedpoint impedance is very high (~2500–5000 Ω). Note: some commercial products label this as "1:49" using a coax-to-antenna direction convention, which is the inverse of the impedance-ratio convention used throughout this document.

This calculator sweeps **all ratios from 4:1 to 69:1** to find the optimal choice for each wire length and band combination.

### 1.4 Impedance at the Feedpoint — The Physics

The feedpoint impedance of an end-fed wire is extremely sensitive to the ratio of the wire's physical length to the wavelength at the operating frequency (L/λ):

| L/λ ratio | Approximate feedpoint impedance | Character |
|---|---|---|
| λ/4 (0.25λ) | ~20–50 Ω | Resistive minimum, low Z — current maximum, voltage minimum. After 9:1 UnUn: ~2.2–5.5 Ω, extremely mismatched to 50 Ω coax |
| 3/8 λ (0.375λ) | ~200–600 Ω | Moderate, best for 9:1 UnUn — **ideal match region** |
| λ/2 (0.50λ) | ~2 000–10 000 Ω | Resistive maximum, very high Z — voltage node, current minimum. After 9:1 UnUn: ~220–1100 Ω, still highly mismatched |
| 5/8 λ (0.625λ) | ~200–800 Ω | Moderate, again suitable for 9:1 UnUn |
| λ (1.0λ) | ~100–300 Ω | Second current maximum |

The impedance model used in this workbook is a simplified cosine-based approximation:

```
Z_wire ≈ 50 × 80^cos²(π × frac(L / λ½))  [Ω]
```

Where `frac(x)` is the fractional part of x (i.e., `x - floor(x)`). This captures the broad shape of the impedance variation (low near λ/4, high near λ/2, moderate between) without requiring a full NEC-based numerical electromagnetic simulation. The model repeats every half-wavelength because `frac(L/λ½)` resets at each integer multiple of λ/2.

**Model verification points:**
- At λ/4: L/λ½ = 0.5, frac(0.5) = 0.5, cos²(π × 0.5) = cos²(π/2) = 0, therefore 80^0 = 1 and Z = 50 × 1 = 50 Ω ✓
- At λ/2: L/λ½ = 1.0, frac(1.0) = 0, cos²(π × 0) = cos²(0) = 1, therefore 80^1 = 80 and Z = 50 × 80 = 4000 Ω ✓
- At 3λ/8: L/λ½ = 0.75, frac(0.75) = 0.75, cos²(π × 0.75) = cos²(3π/4) = 0.5, therefore 80^0.5 ≈ 8.94 and Z ≈ 50 × 8.94 ≈ 447 Ω ✓

**Alternative constant:** Some references (e.g., AA5TB) suggest using a constant of 94 instead of 80, which gives Z_max ≈ 4700 Ω, closer to measured values for certain wire configurations. The spreadsheet allows exploration of both values.

Real-world feedpoint impedance is also affected by:
- Height above ground and ground conductivity
- Wire inclination (horizontal, sloping, inverted-L)
- Proximity to structures
- Coupling to the counterpoise
- Wire diameter (thicker wire = lower impedance)

### 1.5 Resonance Avoidance — The Core Design Problem

When a wire is at, or very near, an exact **half-wavelength** on any of the desired operating bands, the feedpoint impedance soars into the thousands of ohms. Most UnUn transformers and ATUs cannot handle this extreme transformation, leading to:
- SWR beyond the tuner's range
- Very high voltages across the UnUn core → core saturation and losses
- Possible arcing in the transformer housing

Conversely, when a wire is at an exact **quarter-wavelength**, feedpoint impedance drops to near zero, and:
- Very high currents flow through the UnUn
- Efficiency drops because ground/counterpoise resistance becomes dominant
- The 9:1 UnUn transforms to ~5.5 Ω, which is extremely mismatched to 50 Ω coax

Therefore, the **design goal** for a non-resonant long-wire is to choose a length that stays **as far from both λ/2 and λ/4** as possible, across all desired operating bands simultaneously. This is exactly what the **Resonance Avoidance Score** in this calculator quantifies.

Traditional recommended non-resonant lengths (in feet) from ham radio literature include: 29, 35.5, 41, 58, 71, 84 (≈ 25.6 m), 107, 119, 148, and others. This calculator generalizes and optimizes this for any set of active bands, in meters.

### 1.6 Velocity Factor

The **velocity factor (VF)** of a wire expresses the ratio at which electromagnetic waves travel along that conductor relative to the speed of light in free space. For bare wire in free air, VF ≈ 0.95–1.00. For insulated wire, the dielectric surrounding the conductor slows propagation slightly, giving VF ≈ 0.93–0.98, with the exact value depending on the insulation thickness, material permittivity, and wire gauge.

This calculator allows you to set the velocity factor (default: **0.95**, appropriate for insulated wire with end-effect; matches the classic 468/f formula). The formula for half-wavelength is:

```
λ/2 (m) = VF × 150 / f_center (MHz)
```

**Relationship to the classic 468/f formula:** The well-known amateur radio formula for dipole length in feet is `L(ft) = 468 / f(MHz)`. Converting to meters: `L(m) = 468 / 3.281 / f(MHz) ≈ 142.6 / f(MHz)`. With VF = 0.95: `L(m) = 0.95 × 150 / f(MHz) = 142.5 / f(MHz)`, which closely matches the 468/f formula. This confirms VF = 0.95 as the appropriate default for typical insulated antenna wire.

For bare wire in free air, use VF = 0.975–0.98. For thick PVC-jacketed wire, consider 0.92–0.96.

An incorrect VF would shift all resonance calculations, potentially causing the "optimized" wire length to fall near a resonance despite the score appearing safe.

### 1.7 The Counterpoise (Ground Reference)

Every single-wire antenna — whether transmitting or receiving — requires a **return current path**. In a dipole this is the other half of the antenna. In an end-fed system it is the **counterpoise** (or ground system).

A counterpoise is a wire (or set of wires) connected to the ground terminal of the UnUn transformer. It serves as:
1. A reference conductor for the RF return current
2. A "second element" that, combined with the radiating wire, forms the complete antenna system
3. A low-inductance path to prevent RF from flowing on the outside of the coaxial braid back into the shack

**Recommended counterpoise length:** λ/4 of the lowest active band. A λ/4 conductor is at current-maximum resonance and presents a low impedance at its base, providing an efficient RF return path to the antenna feedpoint. This minimises ground-loss resistance and ensures the return current is carried by the counterpoise rather than by lossy soil or the coaxial shield. Multiples of λ/4 at higher frequencies are also effective.

**Multiple radials:** Using several counterpoise wires of different lengths (e.g., λ/4 at 40 m, λ/4 at 20 m) improves system efficiency across all bands. The counterpoise should be kept as straight as possible and elevated slightly above ground if practical. Coiling or routing it back toward the shack degrades performance.

> **Important safety note:** The counterpoise and the feedpoint carry significant RF voltage and current during transmission, which can cause severe RF burns. Keep both the radiator and counterpoise away from areas where humans or pets may touch them, and insulate them where they pass through or near conductive structures. At high-impedance operation (near λ/2 resonance), feedpoint voltages can reach hundreds or thousands of volts even at modest power levels — exercise extreme caution.

---

## 2. Features of this Calculator

| Feature | Description |
|---|---|
| **Band selection** | Enable/disable each of 11 standard HF/VHF bands (160 m–6 m) individually via dropdown |
| **Velocity Factor** | Editable input; default 0.95 (insulated wire with end-effect, matches classic 468/f formula) |
| **Length Sweep** | Sweeps wire lengths from 5.0 m to 60.0 m in 0.1 m steps; computes avoidance score for each |
| **Top 5 recommendations** | Automatically identifies the 5 best wire lengths given active bands |
| **Avoidance score** | Per-band and overall score (0.00–0.25); penalizes both λ/2 and λ/4 resonances |
| **Quality rating** | ★★ GOOD / ★ FAIR / ⚠ MARGINAL / ✗ AVOID labels on each candidate length |
| **VSWR estimator** | Simplified model computes expected SWR per band after the 9:1 UnUn |
| **UnUn ratio optimizer** | Sweeps 4:1 to 69:1 for all 5 recommended wires; finds optimal ratio per band |
| **VSWR color coding** | Green ≤ 2.0 / Orange 2.0–4.0 / Red > 4.0 visual guide |
| **Square-ratio flagging** | Marks integer turns ratios n²:1 (4:1, 9:1, 16:1, 25:1, 36:1, 49:1, 64:1) — easier to wind |
| **Counterpoise calculator** | Recommends counterpoise length as λ/4 of lowest active band |
| **UnUn design calculator** | Computes turns ratio, secondary turns, compensation capacitance, and magnetics check |
| **Toroid database** | Reference table of common ferrite and powdered-iron cores with AL values and dimensions |
| **All units in meters** | Consistent SI units throughout |

---

## 3. Workbook Structure

The workbook contains **six sheets**, each serving a distinct analytical purpose.

### 3.1 Sheet 1 — Calculator

The **main input and output sheet**. Here you:

- Set the **Velocity Factor** (blue input cell, default 0.95)
- Toggle each band **ACTIVE / NO** using dropdown menus
- Read the **Top 5 recommended wire lengths** with avoidance scores, quality ratings, and counterpoise recommendations

The calculator automatically counts active bands and determines the minimum required wire length (λ/4 of the lowest active band). Wires shorter than this minimum receive a score of 0 (automatic AVOID), regardless of resonance proximity.

The **Practical Notes** column in the Top 5 table categorizes wires as:
- *Long wire – max performance* (≥ 40 m)
- *Excellent home station* (25–40 m)
- *Good portable/home* (15–25 m)

### 3.2 Sheet 2 — VSWR Calculator

Enter any wire length (meters) and read the estimated **VSWR per active band** after transformation through a configurable UnUn ratio. Includes:

- Computed L/λ½ ratio for each band (fractional part)
- Estimated feedpoint impedance (Ω)
- VSWR value (numeric and chart bar)
- Quality assessment:
  - ✔ Excellent — no tuner needed (VSWR < 1.5)
  - ✔ Good — most tuners handle this (VSWR 1.5–3.0)
  - ⚠ Marginal — tuner required (VSWR 3.0–6.0)
  - ✗ Poor — high-loss mismatch (VSWR > 6.0)

An embedded bar chart displays the SWR profile visually, with dashed reference lines at VSWR = 1.5 and VSWR = 3.0.

### 3.3 Sheet 3 — UnUn Ratio Optimizer

The most detailed analytical sheet. For each of the **5 recommended wire lengths**, across all active bands:

**Section 1** — Feedpoint impedance (Ω) per band for all 5 wires.

**Section 2** — For each wire × band combination, the optimal UnUn ratio (4:1 → 69:1) that minimises VSWR, along with the best achievable VSWR. The optimal ratio is found by evaluating all 66 possible ratios and selecting the one that gives the lowest VSWR for that specific wire length and band.

**Section 3** — Full VSWR table sweeping all 66 ratio steps (4:1 through 69:1) for all 5 wires and all active bands. Color-coded green/orange/red. Integer turns ratios marked ★.

**Section 4** — Best overall UnUn ratio per antenna (the ratio that minimises **average VSWR** across all active bands). The average is computed as the arithmetic mean of VSWR values across all active bands for each ratio, and the ratio with the lowest average is selected.

This section answers the key question: *"If I can only choose one UnUn transformer, which ratio works best for my wire on all my bands at once?"*

### 3.4 Sheet 4 — Length Sweep

The computational engine that feeds the Top 5 results in Sheet 1. It evaluates **551 candidate lengths** (5.0 m to 60.0 m in 0.1 m steps) and computes:

- Per-band avoidance score (0.00–0.25)
- Overall minimum score (the bottleneck band)
- Rank (1 = best)
- Quality rating label

Green rows indicate recommended lengths; red/orange rows indicate those to avoid. This sheet updates automatically whenever band selections change on the Calculator sheet.

### 3.5 Sheet 5 — UnUn Calculator

A dedicated design tool for building custom UnUn transformers:

- **Inputs:** Operating frequency, target input impedance (Rin, Xin), output/load impedance (Rout, Xout), toroid core selection, primary winding turns
- **Outputs:**
  - Impedance ratio and turns ratio
  - Calculated and rounded secondary turns
  - Actual impedance ratio based on integer turns
  - Transformed load reactance seen at input
  - Required compensation reactance (Xcomp) and component type (series L or C) with value
  - Primary inductance (Lp) and primary reactance (XLp) at operating frequency
  - Design check: XLp > 4×Rin rule-of-thumb verification

### 3.6 Sheet 6 — Toroid Database

A reference table of common toroid cores used in antenna matching applications:

| Core Name | Material | AL (nH/N²) | OD (mm) | ID (mm) | Height (mm) |
|---|---|---|---|---|---|
| FT-114-43 | Ferrite Mix 43 | 510 | 29 | 19 | 7.5 |
| FT-140-43 | Ferrite Mix 43 | 885 | 35.6 | 22.9 | 12.7 |
| FT-240-43 | Ferrite Mix 43 | 1075 | 61 | 35.6 | 12.7 |
| FT-114-31 | Ferrite Mix 31 | 800 | 29 | 19 | 7.5 |
| FT-140-31 | Ferrite Mix 31 | 1390 | 35.6 | 22.9 | 12.7 |
| FT-240-31 | Ferrite Mix 31 | 1800 | 61 | 35.6 | 12.7 |
| FT-114-52 | Ferrite Mix 52 | 175 | 29 | 19 | 7.5 |
| FT-140-52 | Ferrite Mix 52 | 225 | 35.6 | 22.9 | 12.7 |
| FT-240-52 | Ferrite Mix 52 | 300 | 61 | 35.6 | 12.7 |
| FT-114-61 | Ferrite Mix 61 | 79.3 | 29 | 19 | 7.5 |
| FT-140-61 | Ferrite Mix 61 | 140 | 35.6 | 22.9 | 12.7 |
| FT-240-61 | Ferrite Mix 61 | 170 | 61 | 35.6 | 12.7 |
| T-130-2 | Iron Powder Mix 2 | 11 | 33 | 19.8 | 11.1 |
| T-200-2 | Iron Powder Mix 2 | 12 | 50.8 | 31.8 | 14 |
| T-130-6 | Iron Powder Mix 6 | 9.6 | 33 | 19.8 | 11.1 |
| T-200-6 | Iron Powder Mix 6 | 11.6 | 50.8 | 31.8 | 14 |

---

## 4. How to Use the Calculator

### 4.1 Step-by-Step Quick Start

**Step 1 — Open the workbook in Microsoft Excel or LibreOffice Calc.**

The workbook uses standard formulas and dropdown validation. No macros (VBA) are required.

**Step 2 — Go to the *Calculator* sheet.**

**Step 3 — Set your Velocity Factor (optional).**

The default is **0.95**, which is appropriate for most outdoor installations using insulated copper wire (matches the classic 468/f formula). For bare wire in free air, use 0.975–0.98. For thick PVC-jacketed wire, consider 0.92–0.96.

**Step 4 — Select your active bands.**

In the "ACTIVE?" column, change each band to **YES** or **NO** using the dropdown. Enable only the bands you actually intend to use. Enabling too many bands makes it harder for the algorithm to find a good compromise length. A typical multi-band HF station uses 40 m, 30 m, 20 m, 17 m, 15 m, 12 m, and 10 m — all enabled by default.

**Step 5 — Read the Top 5 recommended lengths.**

The table shows the five wire lengths (in meters and centimeters) with the highest avoidance scores. Pick **Rank #1** if you have the space. With the default 40–10 m band selection (7 active bands) and VF = 0.95, the top recommendations will typically be in the 44–47 m range with FAIR to MARGINAL ratings.

**Step 6 — Check the counterpoise recommendation.**

The counterpoise length equals λ/4 of the lowest active band. Run this wire straight and keep it as elevated as possible. Multiple radials of different lengths further improve multi-band performance.

**Step 7 — Verify VSWR on the *VSWR Calculator* sheet.**

Enter your chosen wire length and check that SWR is acceptable (or at least manageable with an ATU) on all active bands.

**Step 8 — Optimize the UnUn ratio on the *UnUn Ratio Optimizer* sheet.**

Section 4 of this sheet tells you which single UnUn ratio gives the lowest average VSWR for your wire. For most 40–10 m installations, a **9:1** UnUn is a very good starting point, but the optimizer may suggest alternatives like 7:1 or 4:1 for specific wire lengths.

**Step 9 — Design your UnUn on the *UnUn Calculator* sheet (optional).**

If building a custom transformer, use this sheet to calculate turns, compensation components, and verify the magnetics design.

### 4.2 Interpreting the Avoidance Score

The **Avoidance Score** ranges from 0.00 to 0.25:

| Score | Meaning | Quality | Rating |
|---|---|---|---|
| 0.25 | Perfect — wire is exactly at 3λ/8 or 5λ/8 relative to every active band (maximum distance from all resonances) | Theoretical ideal | — |
| ≥ 0.20 | Excellent avoidance | ★★ GOOD | ★★ |
| ≥ 0.12 | Good practice, minor tuner assistance likely | ★ FAIR | ★ |
| ≥ 0.05 | Acceptable; some bands may need tuner | ⚠ MARGINAL | ⚠ |
| < 0.05 | Close to λ/2 or λ/4 on at least one band | ✗ AVOID | ✗ |
| 0.00 | Wire IS resonant (exactly λ/2 or λ/4 on some band) | ✗ AVOID | ✗ |

The score is computed as the **minimum** across all active bands. A single "bad" band drags the entire score down. This conservative approach ensures no band is neglected.

**Why 0.25 is the maximum:** The score measures the minimum distance from either λ/2 or λ/4 resonance. The best possible position is exactly halfway between λ/4 and λ/2, which is at 3λ/8 (0.375λ) or equivalently 5λ/8 (0.625λ). At this point, the distance from both λ/4 (0.25λ) and λ/2 (0.50λ) is 0.125λ. Since the score is normalized to the half-wavelength period, this distance is 0.125 / 0.5 = 0.25.

### 4.3 Interpreting the VSWR Results

VSWR after the UnUn is categorized as:

| VSWR | Verdict |
|---|---|
| < 1.5 | ✔ Excellent — direct connection to transceiver is likely fine |
| 1.5–3.0 | ✔ Good — a simple ATU or the radio's internal tuner will handle this |
| 3.0–6.0 | ⚠ Marginal — a dedicated external ATU is required |
| > 6.0 | ✗ Poor — high loss; adjust wire length or UnUn ratio |

In a realistic installation with a 9:1 UnUn, expect VSWR < 3:1 on the majority of bands for a well-chosen wire length. Bands near resonance (λ/2 or λ/4) will show high VSWR regardless of UnUn ratio — this confirms why resonance avoidance is critical.

### 4.4 Selecting the Best UnUn Ratio

The **UnUn Ratio Optimizer** (Sheet 3, Section 4) outputs:

- **Best ratio (any):** The ratio that minimizes average VSWR across all active bands for a given wire length. This may be a non-integer-turns ratio (e.g., 7:1), requiring a tapped or fractional winding design.
- **Best square ratio ★:** The integer-turns ratio (4:1, 9:1, 16:1, 25:1, 36:1, 49:1, 64:1) that minimizes average VSWR. These are simpler to build and widely available commercially.

For most situations, the recommended approach is:
1. Use the **best square ratio** as your primary UnUn
2. Add an external **ATU** to trim the remaining mismatch per band

---

## 5. Mathematical Model

### 5.1 Half-Wave Formula with Velocity Factor

The electrical half-wavelength (λ/2) for a given band center frequency, adjusted for wire velocity factor:

```
λ/2 (m) = VF × 150 / f_center (MHz)
λ/4 (m) = λ/2 / 2
Min Wire (m) = λ/4 at f_center of lowest active band
```

The ITU amateur band center frequencies used in this calculator:

| Band | f_low (MHz) | f_high (MHz) | f_center (MHz) |
|---|---|---|---|
| 160 m | 1.800 | 2.000 | 1.900 |
| 80 m | 3.500 | 3.800 | 3.650 |
| 60 m | 5.3515 | 5.3665 | 5.359 |
| 40 m | 7.000 | 7.300 | 7.150 |
| 30 m | 10.100 | 10.150 | 10.125 |
| 20 m | 14.000 | 14.350 | 14.175 |
| 17 m | 18.068 | 18.168 | 18.118 |
| 15 m | 21.000 | 21.450 | 21.225 |
| 12 m | 24.890 | 24.990 | 24.940 |
| 10 m | 28.000 | 29.700 | 28.850 |
| 6 m | 50.000 | 54.000 | 52.000 |

>*Note: The 80m band allocation varies by ITU Region. Region 2 (the Americas) extends from 3.5 to 4.0 MHz, while Region 1 generally operates from 3.5 to 3.8 MHz. This calculator uses 3.65 MHz as the center frequency, which is appropriate for Region 1 and the lower portion of Region 2. For Region 2 full allocation, the center would be 3.750 MHz.*

### 5.2 Resonance Avoidance Score Formula

For each active band, the score measures how far the wire length `L` is from both the half-wave and quarter-wave resonance:

```
L_frac = L / (λ/2)                      ; fractional length in half-waves

score_λ2 = MIN( MOD(L_frac, 1),  1 − MOD(L_frac, 1) )     ; distance from integer multiples (λ/2 nodes)
score_λ4 = | MOD(L_frac, 1) − 0.5 |                         ; distance from half-integer multiples (λ/4 nodes)

score_band = MIN(score_λ2, score_λ4)
```

The **overall score** is the minimum across all active bands:

```
score_overall = MIN(score_band) for all ACTIVE bands
```

The maximum possible value is **0.25**, achieved when the wire is at exactly 3λ/8 or 5λ/8 relative to every active band — the midpoint between every resonance.

**Why both λ/2 and λ/4 are penalized:**
- At λ/2: feedpoint impedance is very high (~2000–10000 Ω), causing extreme mismatch and high voltages
- At λ/4: feedpoint impedance is very low (~20–50 Ω), causing high currents and ground-loss dominance
- Both conditions are undesirable for UnUn matching and ATU operation

### 5.3 Feedpoint Impedance Estimation Model

The simplified impedance model used in the VSWR Calculator:

```
Z_wire (Ω) ≈ 50 × 80^cos²(π × frac(L / λ½))
```

Where `frac(x) = x − floor(x)` is the fractional part, ensuring the model repeats every half-wavelength.

This is a **heuristic empirical model**, not a rigorous analytical solution. It produces:
- Z ≈ 50 Ω at λ/4: when L = λ/4, the ratio L/λ½ = 0.5, so frac(0.5) = 0.5, cos²(π × 0.5) = cos²(π/2) = 0; therefore 80^0 = 1 and Z = 50 × 1 = 50 Ω ✓
- Z → high values as L/λ½ → any integer n (λ/2 resonances): frac(n) = 0, cos²(π × 0) = cos²(0) = 1; Z = 50 × 80 = 4000 Ω ✓
- Z ≈ 450 Ω near 3λ/8: L/λ½ = 0.75, frac(0.75) = 0.75, cos²(π × 0.75) = cos²(3π/4) = 0.5; Z = 50 × 80^0.5 ≈ 50 × 8.94 ≈ 447 Ω ✓

**Alternative constant:** The model constant of 80 gives Z_max = 4000 Ω. Some references (AA5TB) suggest using 94, which gives Z_max ≈ 4700 Ω, closer to measured values for thin wire at modest heights. The spreadsheet allows exploration of both values.

**Note:** Real feedpoint impedance varies significantly with installation geometry, height, ground conductivity, and other environmental factors. NEC-based simulation (e.g., EZNEC, 4NEC2) should be used for precision engineering. This model is suitable for **preliminary design** and **comparative ranking** of wire lengths.

### 5.4 VSWR Calculation

After impedance transformation by the UnUn (valid for the resistive-only heuristic model; reactive components are not included):

```
Z_coax = Z_wire / ratio_UnUn
VSWR = MAX(Z_coax / 50,  50 / Z_coax)
```

> **Note:** This formula assumes Z_wire is purely resistive. In practice the feedpoint impedance has a reactive component (capacitive or inductive) at non-resonant lengths. The actual VSWR may therefore be higher than calculated, particularly at frequencies where the wire has significant reactance. A VNA or antenna analyzer is needed to measure the true complex impedance.

For a 9:1 UnUn with Z_wire = 450 Ω:

```
Z_coax = 450 / 9 = 50 Ω  →  VSWR = 1.0  (perfect match)
```

### 5.5 Counterpoise Length Formula

The recommended counterpoise length is:

```
L_counterpoise (m) = λ/4 at f_lowest = VF × 75 / f_lowest (MHz)
```

Where f_lowest is the center frequency of the lowest active band. This ensures the counterpoise presents a low-impedance RF return path at the fundamental operating frequency.

For multiple radials, use λ/4 at each band of interest:
- 40 m band: L ≈ 0.95 × 75 / 7.15 ≈ 10.0 m
- 20 m band: L ≈ 0.95 × 75 / 14.175 ≈ 5.0 m
- 10 m band: L ≈ 0.95 × 75 / 28.85 ≈ 2.5 m

### 5.6 UnUn Turns Ratio and Impedance Ratio

The relationship between turns ratio and impedance ratio for a transformer:

```
Impedance Ratio = (Turns Ratio)²
Turns Ratio = N_secondary / N_primary
```

Common integer-turns ratios and their impedance transformations:

| Turns Ratio (n:1) | Impedance Ratio (n²:1) | Z_out for 50 Ω input |
|---|---|---|
| 2:1 | 4:1 | 200 Ω |
| 3:1 | 9:1 | 450 Ω |
| 4:1 | 16:1 | 800 Ω |
| 5:1 | 25:1 | 1250 Ω |
| 6:1 | 36:1 | 1800 Ω |
| 7:1 | 49:1 | 2450 Ω |
| 8:1 | 64:1 | 3200 Ω |

Non-integer turns ratios (e.g., 5.5:1 → 30.25:1) require tapped autotransformer designs and are more complex to construct.

---

## 6. Practical Construction Guidance

### 6.1 Wire Length Recommendations

With the default 40–10 m band selection (7 active bands) and VF = 0.95, the calculator yields these top candidates:

| Rank | Length | Score | Rating | Notes |
|---|---|---|---|---|
| 1 | **46.3 m** | 0.103 | ★ FAIR | Long wire — maximum performance |
| 2 | **46.2 m** | 0.086 | ★ FAIR | Long wire — maximum performance |
| 3 | **44.1 m** | 0.069 | ⚠ MARGINAL | Excellent home station |
| 4 | **46.1 m** | 0.068 | ⚠ MARGINAL | Long wire — maximum performance |
| 5 | **46.4 m** | 0.068 | ⚠ MARGINAL | Long wire — maximum performance |

Adding 160 m or 80 m to the active bands changes the optimal lengths significantly, since λ/2 at those low frequencies is very long (75 m and 39 m respectively). With all 11 bands active, the best compromise lengths shift toward the 46 m range to avoid the 80 m λ/2 resonance at ~39 m.

**Rule of thumb:** When in doubt, longer is better. A wire of 40–55 m covers 40 m through 10 m comfortably, and is forgiving of minor installation variations.

**Practically impossible exact lengths:** Due to practical installation constraints (tree placement, building layout), cutting to within ±0.5 m of the calculated optimum is perfectly acceptable. The avoidance score changes gradually near a good candidate length.

### 6.2 Building a 9:1 UnUn Transformer

A 9:1 UnUn uses a **3:1 turns ratio** (since impedance ratio = turns ratio²: 3² = 9). It is typically wound as a trifilar (3-wire) autotransformer on a ferrite toroid core.

**Winding topology (autotransformer):**

The 9:1 UnUn is wound as a **trifilar autotransformer** — a single continuous winding with a tap, not an isolated primary/secondary transformer. All three trifilar wires are connected in series on the antenna side (full winding = secondary), while the coax uses only one-third of the full winding (the inner tap = primary). This shared-winding topology is what makes it an autotransformer.

```
Antenna ──────────────── Entire winding (3N turns total)
│
├── tap at N turns from ground end (coax center conductor)
│
Counterpoise ──── Coax shield ──── Ground end of winding
```

**Construction procedure (example for FT240-43 core):**

1. Cut three equal lengths of enameled copper wire (AWG 20–16 depending on power level). Twist them loosely together at ~3–5 twists per 10 cm to ensure tight magnetic coupling.
2. Wind **9 trifilar turns** through the toroid core (each of the three wires passes through the core 9 times = 27 individual passes total, but only 9 magnetic turns).
3. Connect all three wires in series to form the full 27-conductor-turn winding — this is the **antenna side** (high-impedance side, 9 × 50 = 450 Ω).
4. The **coax center conductor** taps in at the junction between the first (lowest) 9-conductor-pass section and the remaining two sections. This one-third tap is the 9-turn tap from ground, giving a 3:1 voltage ratio (9:1 impedance ratio).
5. The **coax shield** and **counterpoise** both connect to the grounded (cold) end of the winding.
6. Install in a weatherproof enclosure (PVC or ABS box — do **not** use a metallic enclosure as it will short the magnetic field), with SO-239 (UHF female) connector for coax and screw terminals for antenna wire and counterpoise.

**Alternative construction:** Some builders use **8 primary turns and 24 secondary turns** (ratio 3:1) with separate (bifilar or trifilar) windings — as described in many commercial kit instructions.

**Compact/Low-power version:**
- FT82-43 core: 9 trifilar turns, up to 25 W QRP
- FT140-43 core: 9 trifilar turns, up to 150–200 W SSB

### 6.3 Toroid Core Selection

The most critical variable in UnUn performance is the **ferrite core material (mix)**.

| Core | OD (inches) | Mix | Freq. Range | Max Power (SSB) | Application |
|---|---|---|---|---|---|
| FT82-43 | 0.825" | 43 | 1–50 MHz | 25 W | QRP, portable |
| FT140-43 | 1.4" | 43 | 1–50 MHz | 150–200 W | Home 100 W station |
| FT240-43 | 2.4" | 43 | 1–50 MHz | 500–1000 W | High power |
| FT240-31 | 2.4" | 31 | 1–30 MHz | 500 W | Low-band emphasis (80/160 m) |
| FT240-61 | 2.4" | 61 | 5–200 MHz | 500 W | Upper HF / VHF emphasis |

> **Note on Core Material:** **Mix 43 ferrite** (µ_i ≈ 850) is the most popular for broadband HF UnUns because it provides high enough magnetizing inductance to work on 80 m and 40 m while remaining efficient on the upper HF bands. Avoid using powdered iron cores (such as Type 2, e.g., T200-2) for 9:1 broadband impedance matching. While older literature sometimes suggests them, powdered iron cores have inferior frequency response curves compared to ferrite in this specific transformer application. Mix 31 works better for 160 m and 80 m but underperforms slightly on 10 m.

For **digital modes** (FT8, PSK31, RTTY) with high duty cycles, size up one core category from the SSB rating — digital modes sustain power continuously unlike SSB which has natural pauses.

**Power derating for high VSWR:** If the antenna is not well-matched (e.g., VSWR > 3:1 after the UnUn), the core sees higher circulating currents. Apply a safety factor of 2–3× (i.e., use an FT240 core for a 100 W installation with poor matching).

### 6.4 Counterpoise Design and Installation

The **counterpoise** is at least as important as the wire length choice. A poorly designed counterpoise degrades efficiency and can cause RF in the shack.

**Minimum counterpoise length:**

```
L_counterpoise = VF × 75 / f_lowest (MHz)   [= λ/4 of lowest band]
```

For 40 m as the lowest band (7.15 MHz center):

```
L_counterpoise = 0.95 × 75 / 7.15 ≈ 10.0 m
```

**Practical installation tips:**
- Run the counterpoise wire **straight** from the UnUn transformer ground terminal — do not coil or fold it
- Elevate it a few centimeters above ground if possible to reduce losses in lossy soil
- Keep it away from metallic structures (fences, gutters, downpipes) that could absorb RF
- For multi-band operation, use **multiple radials** at different λ/4 lengths (e.g., one for 40 m ≈ 10 m, one for 20 m ≈ 5 m, one for 10 m ≈ 2.5 m)
- Do **not** connect the counterpoise back to the station RF ground or protective earth — this short-circuits the antenna system and routes RF into the building

### 6.5 Antenna Configurations

The long-wire antenna can be deployed in several configurations depending on available space:

**Horizontal wire (best radiation pattern, needs high support at both ends):**

```
[Support A]=============================[Support B]
|
[UnUn transformer]
|
[Counterpoise]
|
[Coax to shack]
```

**Inverted-L (most common practical choice):**

```
[Mast/Tree]
|
| Vertical section (as high as possible)
|
├──────────────────────────── Horizontal section
|
[UnUn at base of vertical section]
|
[Counterpoise horizontal at ground level]
```

**Sloper (wire from high point sloping down to low support):**
Provides some directional gain and is useful in limited-space installations.

**Inverted-V:** Wire rises to a central apex then slopes down to both sides; not truly end-fed, requires center feed — not applicable here.

### 6.6 Common-Mode Choke / RF Choke

An issue with end-fed wire antennas is that RF current can easily flow on the **outside of the coaxial braid** back toward the shack. This causes:
- RF interference with computers, audio equipment
- Unexpected resonances affecting SWR
- Inaccurate SWR meter readings

**Solution:** Install a **1:1 common-mode choke** (CMC), also called an RF choke or line isolator, on the coaxial feedline. Where you place this choke depends heavily on your counterpoise design:

1. **If you have a robust physical counterpoise (radials):** Place the CMC **directly at the UnUn**. Because you have provided an efficient RF return path via the radials, the choke will forcefully isolate the feedline, preventing it from radiating and keeping common-mode currents completely out of the shack.
2. **If you CANNOT install a physical counterpoise:** Install the CMC **4–8 m down the feedline** from the UnUn. In this compromised setup, the section of the coaxial shield between the UnUn and the choke is forced to act as your counterpoise.

The CMC can be built from:
- 10–12 turns of RG-58 or RG-316 coax wound on an FT240-43 toroid
- A ferrite sleeve (split bead) clamped around the coax
- A commercial current balun (1:1)

---

## 7. Supported HF Bands

| Band Name | Range (MHz) | 
|---|---|
| **160 m** | **1.800 – 2.000** |
| **80/75 m** | **3.500 – 3.800** |
| **60 m** | **5.3515 – 5.3665** | 
| **40 m** | **7.000 – 7.300** |
| **30 m** | **10.100 – 10.150** |
| **20 m** | **14.000 – 14.350** | 
| **17 m** | **18.068 – 18.168** | 
| **15 m** | **21.000 – 21.450** | 
| **12 m** | **24.890 – 24.990** |
| **10 m** | **28.000 – 29.700** | 
| **6 m** | **50.000 – 54.000** |

> **Note:** 60 m is included with its current ITU channelized allocation (5 channels at 5.3515–5.3665 MHz). Check your national regulator for specific channelized access rules.

---

## 8. Limitations and Caveats

This calculator is a **pre-design tool** for rapid comparison and ranking. Users should be aware of the following:

**1. A UnUn is NOT a Tuner:**
The 9:1 UnUn brings the extreme impedances of the random wire down to a manageable level (usually under 5:1 SWR), but it *does not* eliminate the need for an Antenna Tuner (ATU). A capable internal radio tuner or external ATU is still required for multi-band operation.

**2. Simplified impedance model:**
The Z_wire formula is a heuristic approximation. Real feedpoint impedance depends on height above ground, ground conductivity, wire sag, and nearby objects. Variations of ±50% from the model values are normal. For accurate impedance, use NEC simulation software (EZNEC, 4NEC2, OpenEMS) or measure with a VNA or antenna analyzer.

**3. Sweep resolution:**
The Length Sweep evaluates at 0.1 m intervals. Optimal lengths may fall between sweep points. The top 5 results are indicative starting points; fine-tuning ±0.5 m in the field may improve performance.

**4. Single-wire counterpoise only:**
The counterpoise recommendation is for a single λ/4 radial. Real installations with multiple radials of various lengths will perform differently. The calculator does not model the ground system.

**5. No propagation modeling:**
The calculator optimizes matching efficiency only. It does not account for radiation angle, gain, directivity, or propagation conditions — all of which affect actual QSO success more than a 0.5 dB matching improvement.

**6. Lossiness of ferrite at high VSWR:**
When the UnUn core is presented with a highly mismatched impedance, circulating currents cause core heating and insertion loss. This reduces effective radiated power in addition to the feedline mismatch loss. Monitor the UnUn housing temperature during operation; if it becomes warm, consider improving the match or increasing core volume.

**7. Regulatory compliance:**
Wire length, height, and operating power must comply with your national radio communications regulations. Ensure appropriate licensing, power limits, and antenna height clearances.

**8. High voltage warning:**
At wire lengths near λ/2 resonance, feedpoint voltages can reach hundreds to thousands of volts even at modest power (e.g., 100 W). Ensure all connections are properly insulated and rated for the expected voltage. Arcing can occur in poorly designed UnUn housings.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **ATU** | Antenna Tuner Unit — a variable L-network or T-network that compensates feedpoint reactance to present a 50 Ω match to the transceiver |
| **BalUn** | Balanced-to-Unbalanced transformer — used with balanced antennas (dipoles, doublets) |
| **Counterpoise** | A conductor providing the RF return current path for an end-fed antenna; equivalent to a partial ground plane |
| **EFHW** | End-Fed Half-Wave — a wire exactly λ/2 long on its fundamental band, with very high (~2500–5000 Ω) feedpoint impedance |
| **EFRW** | End-Fed Random Wire — a non-resonant end-fed wire deliberately chosen to avoid λ/2 and λ/4 on all desired bands |
| **Feedpoint impedance** | The complex impedance presented at the feed terminals of an antenna; combination of radiation resistance, loss resistance, and reactance |
| **HF** | High Frequency — 3–30 MHz, encompassing the major amateur radio bands |
| **Inverted-L** | An antenna configuration with a vertical section and a horizontal section forming an L-shape |
| **λ/2** | Half-wavelength — the wire length at which a resonant maximum of feedpoint impedance occurs |
| **λ/4** | Quarter-wavelength — the wire length at which a resonant minimum of feedpoint impedance occurs |
| **NEC** | Numerical Electromagnetics Code — the standard electromagnetic simulation engine for antenna modeling |
| **QRP** | Low-power amateur radio operation (typically < 5 W) |
| **Radial** | A single wire in a ground/counterpoise system, extending radially from the antenna feed point |
| **RF Choke** | A common-mode inductance placed on a feedline to suppress current flow on the coax shield exterior |
| **SWR / VSWR** | (Voltage) Standing Wave Ratio — ratio of forward to reflected voltage on a feedline; 1:1 = perfect match |
| **Toroid** | A donut-shaped ferrite or powdered-iron magnetic core used to wind transformers and chokes |
| **Turns ratio** | The ratio of the number of turns on the primary to secondary winding of a transformer; impedance ratio = turns ratio² |
| **UnUn** | Unbalanced-to-Unbalanced transformer — used where both feedline and antenna are unbalanced |
| **VF / Velocity Factor** | The ratio of wave propagation speed in a conductor to the speed of light in vacuum (0 < VF ≤ 1) |
| **VNA** | Vector Network Analyzer — instrument for measuring antenna impedance, SWR, and complex S-parameters |

---

## 10. References and Further Reading

### Technical Papers and Articles

- **ARRL Antenna Book** (24th edition and later) — comprehensive coverage of end-fed antennas, impedance matching, and feedline theory
- Lewallen, R., W7EL — *NEC-based Antenna Modeling Software*, EZNEC documentation (http://www.eznec.com)
- Moxon, L.A., G6XN — *HF Antennas for All Locations*, RSGB, 1982 — classic reference for practical HF wire antennas
- Sprott, J.C. — *"Optimal Length of a Random Wire Antenna"*, technical note, University of Wisconsin, https://sprott.physics.wisc.edu/technote/randwire.htm
- AA5TB — *"End-Fed Half-Wave Antenna"*, https://www.aa5tb.com/efha.html — detailed analysis of EFHW impedance and transformer design
- W8JI — *"Long Wire Antenna"*, https://www.w8ji.com/long_wire_antenna.htm — authoritative practical analysis including counterpoise design and feed system problems
- G3TXQ — *"Wideband Transformers"*, extensive research on ferrite vs. powdered iron core performance for UnUn applications

### Online Resources

| Resource | URL | Content |
|---|---|---|
| W8JI — Long Wire Antenna | https://www.w8ji.com/long_wire_antenna.htm | Authoritative practical analysis of long-wire systems including counterpoise design |
| Bob Cromwell, AC6V — 9:1 UnUn Build | https://cromwell-intl.com/radio/9-1-unun/ | Detailed construction guide with NanoVNA measurements |
| M0UKD — 9:1 Magnetic Longwire Balun | https://m0ukd.com/homebrew/baluns-and-ununs/91-magnetic-longwire-balun-unun/ | Step-by-step with photos |
| KB6NU — End-Fed Wire and 9:1 UnUn | https://www.kb6nu.com/playing-end-fed-wire-antennas-91-ununs/ | Discussion of core selection and practical results |
| HFkits — Manual 1:9 UnUn | https://www.hfkits.com/manual-19-unun-600-watts-for-long-wire-antennas/ | Commercial kit instructions with winding details |
| Electronics Notes — End-Fed Wire | https://www.electronics-notes.com/articles/antennas-propagation/end-fed-wire-antenna/ | Beginner-friendly theoretical overview |
| PA9X — Common Mode Choke | https://www.pa9x.com/the-broadband-common-mode-choke/ | Core ratings, choke construction, power limits |
| Toroids.info | https://toroids.info | Online calculator for AL values and inductance of ferrite toroids |
| 73QRZ Choke Calculator | https://73qrz.com/choke-calc | Online tool for balun/choke/UnUn core selection |
| Practical Antennas | https://practicalantennas.com/designs/end-fed/ | Comprehensive analysis of end-fed types |
| Ham Radio Outside The Box | https://hamradiooutsidethebox.ca/2024/09/04/random-wire-antennas-a-challenge-to-common-knowledge/ | Critical analysis and measured results on random wire impedance |
| VU2NSB — EFHW Antenna | https://vu2nsb.com/antenna/wire-antennas/multiband-efhw-antenna/ | Detailed harmonic analysis of EFHW antenna |
| Battery Eliminator Store — EFHW Deep Dive | https://batteryeliminatorstore.com/blogs/ocf-masters-articles/a-deep-dive-into-end-fed-half-wave-antennas-original | Analysis of transformer ratios from 9:1 to 64:1 |
| Wikipedia — Random Wire Antenna | https://en.wikipedia.org/wiki/Random_wire_antenna | Historical context and impedance characteristics |
| Wikipedia — Counterpoise | https://en.wikipedia.org/wiki/Counterpoise_(ground_system) | Ground system theory |
| RF.Guru — Feed Point Impedance | https://shop.rf.guru/pages/feed-point-impedance-vs-height-for-end-fed-antennas | Feedpoint impedance vs. height and geometry analysis |
| KM1NDY — 64:1 UnUn Build | https://km1ndy.com/diy-linked-efhw-64-to-1-antenna/ | DIY construction of 64:1 UnUn for linked EFHW |
| HF Underground — 9:1 vs 49:1 Discussion | https://www.hfunderground.com/board/index.php?topic=59165.0 | Community discussion on UnUn ratio selection |
| dbBear — EFHW Transformer Theory | https://www.dbbear.com/k0emt/kits/2024-efhw/theory/index.html | Transformer theory and capacitor compensation |

### Software Tools for Advanced Modeling

| Tool | Platform | Description |
|---|---|---|
| **EZNEC** | Windows | Industry-standard NEC-2 antenna modeler by W7EL; recommended for precise feedpoint impedance validation |
| **4NEC2** | Windows (free) | Free NEC-2/NEC-4 GUI with optimizer; excellent for wire antenna design |
| **MMANA-GAL** | Windows (free) | Simple NEC-based modeler, popular with beginners |
| **OpenEMS** | Cross-platform (free) | Full-wave FDTD simulator for advanced analysis |
| **NanoVNA** | Hardware | Low-cost vector network analyzer (50 kHz–1.5 GHz); ideal for validating built UnUn transformers and antenna impedance |
| **miniVNA Tiny** | Hardware/Software | Another popular portable VNA for antenna measurement |

---

## 11. License

This spreadsheet calculator is released under the **Creative Commons Attribution 4.0 International (CC BY 4.0)** license.

You are free to:
- **Share** — copy and redistribute in any medium or format
- **Adapt** — remix, transform, and build upon the material for any purpose

Under the following terms:
- **Attribution** — You must give appropriate credit, provide a link to the license, and indicate if changes were made.

Full license text: https://creativecommons.org/licenses/by/4.0/

---

*73 de the author — good DX and may your SWR always be low!*

---

> **Disclaimer:** This tool is provided for educational and experimental purposes. The author makes no warranties regarding the accuracy of the impedance models or the suitability of any recommended configuration for any specific installation. Always verify designs with proper measurement equipment (VNA, antenna analyzer) before connecting to a transmitter. Comply with all applicable regulations regarding antenna installations and transmitter power limits. High voltages may be present at the antenna feedpoint during operation — exercise appropriate caution.
