# 📡 Long Wire Antenna & 9:1 UnUn Optimizer

Welcome to the **Long Wire / End-Fed Random Wire (EFRW) Optimizer**. This repository contains a powerful, automated spreadsheet calculator designed to help amateur radio operators find the absolute best wire length for multi-band, end-fed antenna operations.

Before diving into the tool, it's crucial to understand the physics and theory behind why "random" wires aren't actually random, and why the 9:1 UnUn is the right tool for the job.

---

## 📖 Antenna Theory: The End-Fed Random Wire (EFRW)

### What is a Long Wire / Random Wire Antenna?

An End-Fed Random Wire (EFRW) antenna is a single piece of wire driven at one end, typically routed over a tree, pole, or roof. Unlike resonant antennas (like dipoles or End-Fed Half-Waves), a random wire is explicitly designed to be **non-resonant** on all amateur radio bands you intend to operate on.

The goal is to find a wire length that presents a moderate impedance (typically between 200 $\Omega$ and 600 $\Omega$) across multiple bands.

### Why a 9:1 UnUn?

An **UnUn** (Unbalanced-to-Unbalanced transformer) matches the unbalanced coax line to the unbalanced end-fed wire.

Modern transceivers expect a 50 $\Omega$ load. A random wire cut to a non-resonant length will typically present an impedance of roughly 450 $\Omega$. A 9:1 UnUn steps this impedance down by a factor of 9:


$$Z_{\text{out}} = \frac{Z_{\text{in}}}{9} = \frac{450}{9} = 50 \Omega$$

**EFRW (9:1) vs. EFHW (49:1):** An End-Fed Half-Wave (EFHW) is cut exactly to a half-wavelength ($\lambda/2$). At $\lambda/2$, the voltage is at a maximum and current is at a minimum, creating an extremely high feedpoint impedance (often >3000 $\Omega$). This requires a 49:1 or 64:1 transformer. A 9:1 UnUn cannot match a half-wave wire; therefore, when using a 9:1 UnUn, **you must avoid half-wavelengths at all costs.**

### The Rules of Wire Length

To make the 9:1 UnUn work efficiently with your radio's internal tuner, the wire length must obey these rules:

1. **Avoid $\lambda/2$ (Half-Wave Multiples):** If the wire is a multiple of a half-wavelength on a given band, the impedance spikes to thousands of ohms, causing high VSWR, RF in the shack, and core saturation/heating.
2. **Avoid $\lambda/4$ (Quarter-Wave Multiples):** At quarter-wave multiples, the impedance drops very low (~50 $\Omega$). If fed through a 9:1 UnUn, the radio sees roughly 5.5 $\Omega$, which most tuners cannot match.
3. **Aim for $3\lambda/8$ or $5\lambda/8$:** The "sweet spot" mid-gap between a quarter-wave and half-wave. This yields the moderate impedance (~450 $\Omega$) the 9:1 UnUn was designed for.
4. **Minimum Length:** The wire must be at least $\lambda/4$ of the lowest operating frequency. Anything shorter becomes highly capacitive and inefficient.

### Counterpoise & Grounding

Because the antenna is unbalanced, the RF current needs a return path. If you do not provide a counterpoise, the current will use the outside shield of your coaxial cable, leading to common-mode noise and RF bites in the shack.

* **Recommendation:** Use a counterpoise wire attached to the ground lug of the UnUn. It should ideally be $\lambda/4$ of your lowest active band. Alternatively, keep your coax long and use a 1:1 choke right before the radio.

---

## 🛠️ About the Calculator

This spreadsheet is an exhaustive sweep-calculator. Instead of guessing or relying on old charts, the algorithm calculates every length from **5.0 meters to 60.0 meters** against the specific bands *you* want to operate on.

It uses an **Avoidance Score** algorithm:

* The score checks the distance of a given wire length from both $\lambda/2$ and $\lambda/4$ across all selected bands.
* **0.00:** The wire is perfectly resonant (Avoid at all costs).
* **0.25:** The wire is perfectly positioned in the mid-gap (Ideal).
* The final score for a length is the *lowest* (worst-case) score among your active bands.

---

## 🚀 How to Use the Spreadsheet

The workbook is divided into four main sheets:

### 1. Calculator (Main Dashboard)

This is where you set up your station parameters.

* **Velocity Factor (VF):** Editable in the blue cell. Bare wire in free air is usually between 0.95 and 1.00. The default is set to **0.975** (typical for outdoor insulated wire).
* **Band Selection:** Change the `ACTIVE?` column to **YES** or **NO**. If you don't care about 160m or 6m, turn them off! The algorithm will stop penalizing lengths that resonate on those bands, opening up new optimal wire lengths for the bands you *do* use.
* **Counterpoise:** The calculator will automatically suggest the minimum counterpoise length based on your lowest active band.
* **Top 5 Recommended Lengths:** Based on your active bands, the spreadsheet will dynamically recommend the five best wire lengths, providing a Quality Rating (★★ GOOD, ★ FAIR) and practical notes.

### 2. VSWR Estimator

If you already have a wire cut, or you want to see how a specific length performs, enter it here.

* Type your wire length (in meters) into the input cell.
* The sheet uses a simplified impedance model to estimate the $Z_{\text{wire}}$ and the resulting VSWR after the 9:1 transformation.
* A visual chart categorizes the match:
* **< 1.5:** Excellent (No tuner needed)
* **1.5 – 3.0:** Good (Tuner helpful/required)
* **3.0 – 6.0:** Marginal (Wide-range tuner required)
* **> 6.0:** Poor (High-loss mismatch)



### 3. Length Sweep

This is the raw data engine of the calculator.

* It displays lengths from 5.0m to 60.0m in 0.5m steps.
* You can see the exact Avoidance Score for every single band.
* Green rows highlight safe, recommended lengths. Use this if the Top 5 lengths don't fit your yard and you need to find a compromise length.

### 4. Technical Reference

A handy quick-reference guide containing:

* Core material recommendations (e.g., FT-240-43).
* Winding ratios (8 primary / 24 secondary turns).
* The underlying math and formulas driving the Avoidance Score.
