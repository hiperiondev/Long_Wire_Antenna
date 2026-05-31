# 📡 Long Wire Antenna — Multi-Band Optimizer

## ⚠ WORK IN PROGRESS — Some features are under development. Verify all output against known reference designs before use in a real installation.

> An Excel-based engineering calculator for designing non-resonant long-wire (end-fed random wire) HF antennas with impedance-matching networks. Supports multi-band optimization from 160 m through 6 m, with resonance avoidance scoring, VSWR estimation (resistive and complex), counterpoise impedance correction modelling, UnUn ratio sweep, core saturation analysis, counterpoise recommendations, and alternative air-core antenna tuner design.

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
   - [Sheet 4 — Transmatch Calculator](#34-sheet-4--transmatch-calculator)
   - [Sheet 5 — Length Sweep](#35-sheet-5--length-sweep)
   - [Sheet 6 — UnUn Calculator](#36-sheet-6--unun-calculator)
   - [Sheet 7 — Toroid Database](#37-sheet-7--toroid-database)
4. [How to Use the Calculator](#4-how-to-use-the-calculator)
   - [Step-by-Step Quick Start](#41-step-by-step-quick-start)
   - [Interpreting the Avoidance Score](#42-interpreting-the-avoidance-score)
   - [Interpreting the VSWR Results](#43-interpreting-the-vswr-results)
   - [Selecting the Best Impedance Matching Method](#44-selecting-the-best-impedance-matching-method)
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

**⚠️ CRITICAL CORRECTION — Measured vs. Theoretical Impedance (2024–2025 Research):**

Recent field measurements from multiple sources have demonstrated that the actual antenna feedpoint impedance is often **significantly less than the theoretical 450 Ω** assumption on each band. This challenges decades of conventional wisdom. The "450 Ω rule of thumb" is a gross oversimplification that depends heavily on:
- Wire length and geometry
- Height above ground
- Counterpoise configuration and length
- Environmental factors (proximity to structures, ground conductivity)

**Evidence**: A 2024 study by "Ham Radio Outside the Box" measured a specific 84-foot random wire and found impedances were **well below 450 Ω across all tested bands**. This invalidates the assumption that a 9:1 transformer is optimal for all installations.

**Implications for UnUn Selection:** 
- A 9:1 transformer may be **overmatched** for many installations
- Some wire lengths work better with 4:1, 6:1, 7:1, 16:1, 25:1, or 49:1 ratios
- **Best practice**: Measure actual antenna impedance with a VNA or antenna analyzer BEFORE construction
- This calculator provides the theoretical foundation, but real-world impedance must be validated experimentally

### 1.4 Impedance at the Feedpoint — The Physics

The feedpoint impedance of a wire antenna depends on:

- **Length relative to wavelength**: Quarter-wave (λ/4) presents very low impedance (~20–50 Ω); half-wave (λ/2) presents very high impedance (several thousand ohms)
- **Height above ground**: Higher antennas radiate more efficiently but may have different impedance
- **Wire diameter**: Thicker conductors have slightly lower impedance
- **Nearby objects**: Metal structures, buildings, and terrain affect impedance
- **Frequency**: The same wire has different impedance at different frequencies

For a non-resonant (random) wire of length between 10–60 m operating on HF (1.8–54 MHz), the impedance typically varies:
- **Magnitude**: 50 Ω to 2000+ Ω depending on frequency
- **Reactance**: Capacitive or inductive depending on proximity to quarter-wave and half-wave multiples
- **Pattern**: Usually a mix of resistive and reactive components

### 1.5 Resonance Avoidance — The Core Design Problem

The central design challenge with random-wire antennas is **avoiding resonances** where the impedance becomes unacceptably high or low.

**Why resonances are problematic:**
- At **half-wave resonance** (λ/2): Impedance becomes several thousand ohms; most tuners cannot match this
- At **quarter-wave resonance** (λ/4): Impedance becomes very low; little power is radiated
- **Between these points** (3/8 λ, 5/8 λ, etc.): Impedance is moderate and tunable

**The solution:** Choose a wire length that **avoids half-wave and quarter-wave multiples** of all bands you want to operate on. The **avoidance score** in this calculator measures how far your chosen length is from these "forbidden" resonance points. Scores range from 0 (on resonance) to 1.0 (maximum distance from all resonances).

**Key reference**: J.C. Sprott's research (revised 2022) identified that **74 feet (22.6 m)** has the largest gap (376 kHz) between quarter-wave resonances, making it the single best length for 80–10 m multi-band coverage.

### 1.6 Velocity Factor

The speed at which an electromagnetic wave travels through a conductor is less than the speed of light in free space (300,000 km/s). The **velocity factor (VF)** is the ratio of this reduced speed to the speed of light.

**Typical values:**
- **Bare copper wire in free air**: 0.95–0.98 (wire's electrical length is 95–98% of physical length)
- **Insulated wire (PVC/polyethylene)**: 0.92–0.96 (insulation slows the wave further)
- **Coaxial cable (solid PE dielectric)**: 0.66
- **Open-wire transmission line**: 0.95–0.97

**Why it matters**: When calculating resonant lengths, you must multiply the theoretical wavelength by the VF. A dipole cut for 14 MHz in free space using VF=1.0 would be electrically too long and resonant at a slightly lower frequency.

**Default in this calculator**: VF = 0.95, which accounts for both the wire's inherent VF and "end effect" (capacitance at wire ends). This is appropriate for insulated copper wire with typical end effects.

### 1.7 The Counterpoise (Ground Reference)

A **counterpoise** is a wire or set of wires that acts as a reference return path (ground plane substitute) for the antenna. It is electrically and RF-wise "in parallel" with the antenna feedline and carries the return RF current.

**Why it's needed:**
- The antenna circuit must be complete (outgoing current must have a return path)
- In a balanced antenna (like a dipole), the return path is symmetrical
- In an unbalanced antenna (like a long wire), the return path is the counterpoise
- Without a counterpoise, RF current flows on the coax shield → RFI in the shack

**Counterpoise design (Updated 2025):**

The traditional formula is **λ/4 of the lowest operating frequency**. However, recent research (PA9X 2025, RF.Guru 2025) provides a more practical guideline:

**Ideal length: 0.05 × longest wavelength you plan to transmit on**

Example: For 80–10 m operation (80 m is longest), λ = 80 m, so 0.05 × 80 = **4 meters** is sufficient. This length:
- Provides adequate return current path
- Doesn't radiate as a co-radiator
- Is much easier to implement than λ/4 (which would be ~20 m)

**Number of radials:**
- **Single radial**: 1–2 meters minimum; works for QRP
- **Multiple radials** (preferred): 2–4 radials each ~1.5–2 m → Impedance halves with each additional parallel radial
- **Ground system**: Buried radials more effective than elevated wires

---

## 2. Features of this Calculator

This workbook provides a comprehensive toolkit for long-wire antenna design:

- ✅ **Resonance avoidance algorithm** — Identifies wire lengths that avoid problematic resonances on all selected bands
- ✅ **Top-10 ranking** — Recommends best wire lengths ranked by avoidance score
- ✅ **Feedpoint impedance modeling** — Empirical estimation of antenna impedance at each frequency
- ✅ **VSWR prediction** — Estimates standing-wave ratio across bands for chosen wire length
- ✅ **Counterpoise design** — Recommends counterpoise length and configuration
- ✅ **UnUn ratio optimization** — Tests multiple transformer ratios and recommends the best
- ✅ **UnUn transformer design** — Calculates ferrite toroid windings and specifications
- ✅ **Air-core antenna tuner design** — Alternative approach using tapped air-core coil
- ✅ **Core saturation awareness** — Notes power limits and saturation risk (see Limitations)
- ✅ **Comprehensive references** — Links to research papers, standards, and practical guides

---

## 3. Workbook Structure

This workbook contains **seven interconnected sheets** for designing and optimizing long-wire antennas:

### 3.1 Sheet 1 — Calculator

**Purpose**: Main user interface and dashboard for wire length selection and band optimization

**What It Does**:
- Select which HF bands you'll operate on (160m–6m with YES/NO dropdowns)
- Automatically calculates optimal wire lengths using resonance-avoidance algorithm
- Recommends Top-10 wire lengths ranked by "avoidance score"
- Suggests counterpoise length for selected bands
- Provides installation guidance for common-mode chokes (CMC) and baluns

**Key Inputs** (Blue cells):
- **Velocity Factor**: Default 0.95 (insulated wire + end-effect); adjustable for bare copper (0.97–0.98)
- **Band Selection**: Set to YES for bands you want to use (ACTIVE column)

**Key Outputs**:
- **Top 10 Recommended Wire Lengths**: Ordered by avoidance score (EXCELLENT ★★★ to AVOID ✗)
- **Recommended Counterpoise Length**: 0.05 × longest wavelength (updated 2025)
- **Choke/Balun Installation Guidance**: Placement, impedance targets, core recommendations

**Typical Workflow**: Start here, select your bands, note Top-1 or Top-3 wire length, then verify with VSWR Calculator.

---

### 3.2 Sheet 2 — VSWR Calculator

**Purpose**: Estimate feedpoint impedance and predict VSWR for your chosen wire length

**What It Does**:
- Predicts antenna feedpoint impedance (R + jX) at each HF frequency using empirical model
- Models counterpoise impedance and its effect on feedpoint
- Calculates VSWR across bands for specified wire length
- Accounts for counterpoise height, length, and number of radials
- Provides impedance vs. frequency analysis

**Key Inputs**:
- **Wire length** (m): Select from Top-10 list or enter custom value
- **UnUn Ratio** (N:1): Usually 9:1; can test alternatives (6:1, 7:1, 16:1, 49:1)
- **Counterpoise configuration**: Height, length, number of radials

**Key Outputs**:
- **Impedance per band**: R and X components (resistance & reactance)
- **Feedpoint impedance magnitude**: |Z| = √(R² + X²)
- **Phase angle**: Direction of impedance in complex plane
- **VSWR**: Voltage Standing Wave Ratio with color coding
- **Return loss**: Reflection coefficient in dB

**⚠️ Important Caveat**:
- Model is **empirical, not NEC2-based**
- Accuracy: ±20–30%
- **Real antenna impedance depends on**: height, ground type, environment, weather
- **Always validate** with antenna analyzer or VNA before connecting to transmitter

**Typical Workflow**: After selecting wire length, check VSWR on each band here. If SWR >3:1 on all bands, consider alternative wire length.

---

### 3.3 Sheet 3 — UnUn Ratio Optimizer

**Purpose**: Suggest the best ferrite UnUn impedance ratio for your chosen antenna

**What It Does**:
- Tests multiple UnUn ratios (9:1, 16:1, 25:1, 49:1) for your specific wire length
- Calculates average SWR and return loss for each ratio across all active bands
- Recommends which ratio provides best broadband performance
- Shows trade-offs between different ratios

**Key Inputs**:
- Wire length: Automatically pulls from VSWR Calculator (Sheet 2)
- Antenna impedance data: Calculated from impedance model

**Key Outputs**:
- **Recommended ratio**: Which of 9:1, 16:1, 25:1, 49:1 is optimal
- **SWR comparison**: How each ratio performs on each band
- **Average SWR**: Across all bands for comparison

**Typical Workflow**: 
1. Select wire length on Calculator (Sheet 1)
2. Check impedance on VSWR Calculator (Sheet 2)
3. Use this sheet to confirm best UnUn ratio
4. Go to UnUn Calculator (Sheet 6) to design the transformer

---

### 3.4 Sheet 4 — Transmatch Calculator

**Purpose**: Design an **air-core antenna tuning network** (impedance matching coil with multiple taps)

**⚠️ IMPORTANT**: This is a **COMPLETELY DIFFERENT APPROACH** from ferrite UnUn transformers. Use **ONE or the OTHER**, not both.

#### **When to Use Transmatch vs. UnUn:**

| Aspect | UnUn (Sheet 6) | Transmatch (Sheet 4) |
|--------|---|---|
| **What it is** | Fixed-ratio ferrite wideband transformer | Air-core tapped coil tuner |
| **Matching** | Same impedance ratio all bands (9:1, 16:1, etc.) | Different tap optimized per band |
| **Setup** | Plug-and-play; broadband | Manual tap switching (or relays) |
| **Efficiency** | 95%+ (ferrite losses) | 98%+ (air-core, minimal loss) |
| **Complexity** | Simple build (1–2 hours) | Moderate (3–4 hours); requires tap switching |
| **Cost** | Low-moderate | Low |
| **Best for** | QRP portable, multiband easy operation | Home station, optimization, experimentation |
| **Power handling** | Limited by core size (50W–1500W) | Essentially unlimited (wire gauge limited) |
| **Optimization** | Fixed by transformer ratio | Can optimize each band separately |

#### **What the Transmatch Calculator Does:**

1. **Designs an air-core coil** with multiple taps for different bands
2. **Calculates tap positions** — Each tap optimized for a specific frequency/band
3. **Predicts SWR for each tap** — Shows which tap is best for each band
4. **Provides construction details** — Turns per section, wire length needed, winding geometry
5. **Accounts for actual antenna impedance** — Links to impedance model in VSWR Calculator

#### **Key Inputs**:
- **Antenna length** (m): Inherited from VSWR Calculator
- **Coil dimensions**: Diameter (mm), wire gauge (AWG or mm)
- **Target output impedance**: Always 50 Ω (coax)
- **Active bands**: Inherited from Calculator sheet

#### **Key Outputs**:
- **Tap summary**: Which tap for which band, required turns ratio, impedance
- **Winding details**: Cumulative turns, delta turns per section, wire length
- **RF performance**: SWR, return loss, phase angle for each tap/band
- **Construction guide**: Color-coded interpretation (green SWR <1.5, red SWR >3.0)

#### **How to Build an Air-Core Transmatch:**

1. **Wind the coil** on air-core form (PVC pipe, cardboard tube, etc.)
   - Diameter: Specified in C11 (typically 50 mm)
   - Wire: AWG #18–#12 enamel copper (typically 1 mm ≈ AWG #18)
   - Spacing: ~1 mm between turns (allows air cooling and better coupling)

2. **Mark tap points** at cumulative turn counts from calculator
   - Use small PCB pads, solder pads, or banana jacks
   - Label each tap clearly with band (80m, 40m, 20m, 10m, etc.)

3. **Connect to antenna:**
   - **Bottom tap** (lowest turn count) → Hot lead to antenna wire
   - **Reference point** (middle turns) → Counterpoise connection
   - **Switching mechanism** → Select tap for desired band

4. **Add switching method:**
   - **Manual**: Alligator clip on desired tap (portable, field use)
   - **Relay**: Motorized relay per band (home station, automatic)
   - **Plug**: Banana jack at each tap (convenient, stable)

5. **Test with antenna analyzer or VNA:**
   - Measure actual impedance at each band
   - Compare to calculator predictions (should be ±10%)
   - Fine-tune tap spacing if needed

#### **Advantages of Transmatch:**
✅ Very high efficiency (no ferrite losses; air-core ~2% max)  
✅ Can be optimized for any impedance (not fixed)  
✅ Low cost (wire + coil form)  
✅ Fully reversible (no ferrite saturation)  
✅ Can be rebuilt if needs change  
✅ Unlimited power handling (only wire gauge limited)  

#### **Disadvantages of Transmatch:**
❌ Requires tap switching (manual or automatic)  
❌ Each tap is optimal only at one frequency  
❌ More complex design than broadband UnUn  
❌ Requires antenna analyzer for validation  
❌ Not ideal for QRP portable (many taps)  

#### **Typical Workflow** (Alternative to UnUn):
1. Select wire length on Calculator
2. Use Transmatch Calculator to design air-core coil
3. Build coil with marked tap points
4. Test with antenna analyzer; fine-tune tap positions if needed
5. Use manual alligator clip or relay to switch taps per band

---

### 3.5 Sheet 5 — Length Sweep

**Purpose**: Visual analysis of antenna impedance vs. wire length

**What It Does**:
- Calculates impedance for ALL possible wire lengths (10 m to 150 m, 0.1 m increments)
- Computes resonance avoidance score for each length
- Creates visual "heatmap" showing good lengths (green) vs. bad lengths (red)
- Ranks all lengths by avoidance score
- Identifies which lengths resonate on which bands

**Key Inputs**:
- Band selection: Inherited from Calculator (E12:E22)
- Velocity factor: Inherited from Calculator (C7)

**Key Outputs**:
- **Large data table**: Impedance (R, X, |Z|) for every 0.1 m increment
- **Avoidance score column**: Color-coded (green = good, red = bad)
- **Sorted ranking**: All lengths ranked by avoidance score
- **Visual chart**: (if present) Shows impedance vs. length graphically

**What "Avoidance Score" Means**:
- **1.0 (best)**: Maximum distance from all resonances
- **0.5 (good)**: Well-positioned between resonances
- **0.2 (marginal)**: Getting close to a resonance
- **0.0 (worst)**: On a resonance (λ/2 or λ/4 multiple)

**Typical Workflow**: 
- Provides data for Top-10 list in Calculator
- Use to understand why certain lengths are better than others
- If you have a specific length in mind, check its score here

---

### 3.6 Sheet 6 — UnUn Calculator

**Purpose**: Design a **ferrite-based wideband UnUn transformer** (impedance matching)

**What It Does**:
- Calculates ferrite toroid specifications for your UnUn
- Designs windings: Number of turns, wire gauge, connections
- Predicts impedance matching performance across 1.8–30 MHz
- Provides step-by-step construction instructions

**Key Inputs** (Blue cells):
- **UnUn Ratio** (N:1): 9:1 (most common), 16:1, 25:1, 49:1, or custom
- **Wire diameter**: AWG or mm (for coil winding)
- **Core type & size**: FT-82, FT-114, FT-140, FT-240 (from Toroid Database)
- **Turns**: Default calculated; can adjust for experimentation

**Key Outputs**:
- **Winding design**: Primary turns, secondary turns, impedance ratio confirmed
- **RF Performance** (per frequency): Impedance transformation, phase shift
- **Construction Notes**: How to connect, polarity, box specifications

**⚠️ CRITICAL CORRECTIONS** (Updated 2025):
1. **Do NOT use Mix 31 ferrite** for UnUn; use Mix 43, 52, or 61 only
   - Mix 31 (MnZn) is for 1:1 chokes ONLY
   - Mix 43, 52, 61 (NiZn) are for impedance transformers
   - See Section 6.3 for detailed ferrite selection

2. **Core power limits** (1.8–30 MHz, 9:1 ratio):
   - FT-82 (mix 43): 50–75 W max
   - FT-114 (mix 43): 100–150 W max
   - FT-140 (mix 43): 300–400 W max
   - FT-240 (mix 43): 1000–1500 W max

3. **Saturation not fully modeled** — Keep actual power ≤50% of rated for safety margin

**Typical Workflow**:
1. Get recommended ratio from UnUn Ratio Optimizer (Sheet 3)
2. Select core size from Toroid Database (Sheet 7)
3. Input core type & ratio here
4. Note turn counts and construction details
5. Build & test with VNA/analyzer

---

### 3.7 Sheet 7 — Toroid Database

**Purpose**: Reference table of ferrite core specifications and recommendations

**What It Contains**:
- **Fair-Rite & Micrometals cores**: Common part numbers and specifications
- **Mix types**: 31, 43, 52, 61, 75 (organized by material)
- **AL values**: Inductance per-turn-squared (nH/turn²)
- **Dimensions**: O.D., I.D., height (mm & inches)
- **Frequency range**: Best operating range for each material
- **Power ratings**: Approximate max watts for different impedance ratios
- **Recommended uses**: Which cores for what applications

**How to Use**:
1. Decide on **impedance ratio** (9:1, 16:1, 25:1, 49:1)
2. Choose **power level** you need (QRP: 5–10W, SSB: 50–100W, AM: 100–400W)
3. Look up **core size** from table matching power & ratio
4. Note **part number** and **AL value**
5. Input into UnUn Calculator (Sheet 6)

**⚠️ CRITICAL NOTE (Updated 2025)**:
- **Mix 31 (MnZn) is ONLY for 1:1 chokes**, not UnUn transformers
- **Never use Mix 31 for impedance transformers** — it will have:
  - Poor frequency bandwidth
  - Higher losses
  - Low power handling
- **Always use Mix 43, 52, or 61** (NiZn) for UnUn applications

**Example**:
- Want: 9:1 UnUn for 100 W
- Look in table: FT-140-43 rated ~300–400 W
- Choose FT-140-43 (NiZn Mix 43)
- Use AL value (from spec sheet)
- Input into UnUn Calculator

---

## 4. How to Use the Calculator

### 4.1 Step-by-Step Quick Start

#### **Step 1: Open the Workbook**
- Open `LongWire_Antenna_Calculator.xlsx` in Microsoft Excel or compatible spreadsheet software
- You should see the **Calculator** sheet (Sheet 1) as the default

#### **Step 2: Select Your Operating Bands**
- Locate the **Band Selection** table (rows 11–22)
- For each band, set the **ACTIVE** column to:
  - **YES** — You want to operate on this band
  - **NO** — You don't need coverage on this band
- Default: 40m, 20m, 10m are set to YES

**Example:**
```
160m: NO
80m:  YES  ← You selected 80m
60m:  NO
40m:  YES  ← You selected 40m
20m:  YES  ← You selected 20m
10m:  NO
...
```

#### **Step 3: Adjust Velocity Factor (Optional)**
- Cell C7: Default is **0.95** (insulated wire + end-effect)
- For bare copper wire in free air: Use **0.97–0.98**
- For heavily insulated wire: Use **0.92–0.94**

#### **Step 4: Review the Top-10 Recommended Wire Lengths**
- See rows 28–38 in the Calculator sheet
- Each row shows:
  - **Wire Length** (meters)
  - **Avoidance Score** (0.0–1.0; higher is better)
  - **Quality Rating** (★★★ EXCELLENT to ✗ AVOID)

**Interpretation:**
- **#1 (Best)** — Longest distance from all resonances on selected bands
- **#2–#3** — Also excellent; choose if #1 is inconvenient
- **#4–#5** — Good, practical options
- **#6–#10** — Acceptable but less optimal

#### **Step 5: Note the Recommended Counterpoise Length**
- Cell D25: Automatically calculated as 0.05 × longest wavelength of active bands
- Example: For 80–10m, counterpoise ≈ 4 meters (0.05 × 80m)

#### **Step 6: Choose Your Wire Length**
- Copy the length of Top-1 or Top-3 recommendation
- This becomes your antenna wire length

#### **Step 7: Verify with VSWR Calculator**
- Go to **Sheet 2** (VSWR Calculator)
- Cell C4: Paste your chosen wire length
- Review the **SWR** column (rows 8–18)
- If SWR >2:1 on critical bands, try next-best length

#### **Step 8: Choose Your Matching Method**
- **Option A: UnUn Transformer (Fixed Ratio)**
  - Go to Sheet 3 (UnUn Ratio Optimizer)
  - Check recommended ratio (9:1, 16:1, 49:1, etc.)
  - Go to Sheet 6 (UnUn Calculator) to design
  - Build ferrite-based transformer

- **Option B: Air-Core Transmatch (Switched Taps)**
  - Go to Sheet 4 (Transmatch Calculator)
  - Design air-core coil with multiple taps
  - Build and test with antenna analyzer

#### **Step 9: Build and Test**
- Construct your chosen transformer/tuner
- Validate with **antenna analyzer or VNA**
- Test at **low power (5–10W)** first
- Measure **final SWR** at transmitter end
- Check for **RFI** in shack

---

### 4.2 Interpreting the Avoidance Score

The **avoidance score** measures how far your chosen wire length is from problematic resonances.

**Scale**:
- **1.0 (Perfect)** — Maximum distance from ALL quarter-wave and half-wave resonances
- **0.7–0.9 (Excellent)** — ★★★ Score; large gap between resonances
- **0.4–0.6 (Good)** — ★★ Score; acceptable gap; easy to tune
- **0.2–0.4 (Fair)** — ★ Score; close to a resonance; needs careful tuning
- **0.05–0.2 (Marginal)** — ⚠ Score; very close to resonance; difficult to tune
- **0.0 (Worst)** — ✗ AVOID; on a quarter-wave or half-wave resonance

**Why it matters:**
- Wire at **high avoidance score** (0.7+): Antenna impedance is moderate and easy to match with UnUn/tuner
- Wire at **low avoidance score** (<0.2): Antenna impedance will be very high or very low; difficult to achieve good SWR

**Example:**
```
74 feet (22.6 m):  Score 0.376 (★★★ EXCELLENT) — Large gap; recommended
63 feet (19.2 m):  Score 0.118 (★★ GOOD)       — Acceptable gap
50 feet (15.2 m):  Score 0.000 (✗ AVOID)       — On half-wave of 80m; very high impedance
```

---

### 4.3 Interpreting the VSWR Results

The **VSWR Calculator** (Sheet 2) predicts standing-wave ratio for your chosen wire and transformer.

**Color Coding** (from interpretation guide at bottom of sheet):
- 🟢 **Green** — SWR ≤ 1.5:1 → Excellent match; <4% reflected power
- ⚪ **White** — SWR 1.5–3.0:1 → Acceptable for most ham radio work
- 🔴 **Red** — SWR > 3.0:1 → Poor match; consider different wire length

**Reading the Results**:
- **SWR Column** (per band): Voltage Standing Wave Ratio (1.0 = perfect, 3.0 = poor)
- **Return Loss** (dB): Reflection coefficient (>14 dB = acceptable)
- **Phase** (degrees): Reactance angle (0° = purely resistive, ±90° = purely reactive)

**What to Do**:
- **If all bands are green**: Your wire length is excellent; proceed to transformer design
- **If some bands are white**: Acceptable; use antenna tuner on those bands
- **If any band is red**: Try a different wire length from the Top-10 list

**Important**: These are **theoretical predictions** based on an empirical model. **Always validate with an antenna analyzer** before full power.

---

### 4.4 Selecting the Best Impedance Matching Method

You have **two main options** for matching your antenna to 50 Ω coax:

#### **Option 1: Ferrite UnUn Transformer (Sheet 6)** — Recommended for most users

**Advantages:**
✅ Simple, broadband match  
✅ No switching needed  
✅ Works on all bands simultaneously  
✅ Good efficiency (95%+)  
✅ Easy to build (1–2 hours)  
✅ Ideal for portable/field use  
✅ No tap adjustment needed  

**Disadvantages:**
❌ Fixed impedance ratio (9:1, 16:1, etc.)  
❌ May not be optimal for every band  
❌ Limited power handling (depends on core size)  
❌ Ferrite saturation risk at high power  
❌ Ferrite core cost  

**Best for:** QRP portable, multiband operation, set-and-forget approach

**How to proceed:**
1. Go to Sheet 3 (UnUn Ratio Optimizer)
2. Note the recommended ratio
3. Go to Sheet 6 (UnUn Calculator)
4. Select ferrite core from Sheet 7 (Toroid Database)
5. Build using winding instructions

---

#### **Option 2: Air-Core Transmatch (Sheet 4)** — For optimization and experimentation

**Advantages:**
✅ Extremely high efficiency (98%+)  
✅ No ferrite losses  
✅ Unlimited power handling  
✅ Can optimize each band separately  
✅ Low cost (just wire)  
✅ Fully reversible (rebuild if needed)  
✅ No saturation risk  

**Disadvantages:**
❌ Requires tap switching (manual or relay)  
❌ More complex build (3–4 hours)  
❌ Each tap only optimal at one frequency  
❌ Requires antenna analyzer for validation  
❌ Not ideal for portable (many taps)  
❌ More tuning effort needed  

**Best for:** Home station, optimization, experimentation, high-power use

**How to proceed:**
1. Go to Sheet 4 (Transmatch Calculator)
2. Note calculated tap positions
3. Build air-core coil with marked tap points
4. Test with antenna analyzer
5. Use manual clips or relay to switch taps

---

## 5. Mathematical Model

### 5.1 Half-Wave Formula with Velocity Factor

The electrical length of a half-wavelength at frequency f is:

```
λ/2 = (150 / f_MHz) × VF  [meters]
λ/2 = (492 / f_MHz) × VF  [feet]
```

Where:
- **f_MHz** = Frequency in megahertz
- **VF** = Velocity factor (0.95 for typical insulated wire)

Example: 80m band center frequency = 3.6 MHz
```
λ/2 = 150 / 3.6 × 0.95 = 39.6 meters
```

This means a wire of 39.6 m will resonate (half-wave) at 3.6 MHz.

### 5.2 Resonance Avoidance Score Formula

The avoidance score measures how far your wire is from the nearest resonance:

```
distance_to_resonance = |L - nearest_λ/2|  [normalized to 0–1 scale]
avoidance_score = 1 - MIN(|L - λ/2_all_bands|)
```

Interpretation:
- Score **close to 1.0**: Wire is far from all resonances
- Score **close to 0.0**: Wire is on a resonance

The calculator computes this for all quarter-wave and half-wave multiples across all selected bands.

### 5.3 Feedpoint Impedance Estimation Model

The feedpoint impedance is estimated using empirical formulas:

```
R_est = 50 · 80^(cos²(π·L/λ½))
X_est = 1500 · sin(2π·L/λ½)
Z_antenna = R_est + j·X_est
```

Where:
- **L** = Wire length (m)
- **λ½** = Half-wavelength at frequency (m)
- **j** = Complex number operator

**Important**: This model is **empirical, not physics-based**. Real impedance depends on height, ground, environment. **Accuracy: ±20–30%**

### 5.4 VSWR Calculation

Once antenna impedance is known:

```
Γ = (Z_antenna - Z₀) / (Z_antenna + Z₀)  [reflection coefficient, complex]
VSWR = (1 + |Γ|) / (1 - |Γ|)
Return Loss = -20 log₁₀(|Γ|)  [dB]
```

Where:
- **Z₀** = 50 Ω (source impedance)
- **|Γ|** = Magnitude of reflection coefficient

Example: If antenna impedance is 400 Ω (at resonance):
```
Γ = (400 - 50) / (400 + 50) = 350 / 450 = 0.78
VSWR = (1 + 0.78) / (1 - 0.78) = 1.78 / 0.22 = 8.1:1  (very poor match)
```

With 9:1 UnUn: Z_antenna transforms to ~45 Ω, giving VSWR ≈ 1.1:1 (excellent).

### 5.5 Counterpoise Length Formula

**Traditional formula** (λ/4 of lowest frequency):
```
L_cp = (75 / f_low_MHz)  [meters]
```

**Updated formula** (2025 — 0.05 × longest wavelength):
```
L_cp = 0.05 × (150 / f_lowest_MHz)  [meters]
```

Example: For 80–10m operation (80m is lowest frequency):
- Traditional: λ/4 = 150 / 1.8 = **83 m** (impractical!)
- Updated: 0.05 × 150 / 1.8 = **4.2 m** (practical, sufficient)

Both approaches work; the updated formula is more practical.

### 5.6 UnUn Turns Ratio and Impedance Ratio

For a ferrite UnUn transformer:

```
N_turns = √(Z_antenna / Z₀)  [turns ratio]
Impedance_ratio = (N_primary / N_secondary)²  [impedance transformation]
```

For **9:1 UnUn**:
```
N_primary / N_secondary = √9 = 3 (e.g., 3 primary, 9 secondary turns)
Z_out = Z_in / 9  (e.g., 450 Ω antenna transforms to 50 Ω)
```

---

## 6. Practical Construction Guidance

### 6.1 Wire Length Recommendations

**Common recommended lengths** (from W0IPL analysis and Sprott research):

| Length (feet) | Length (meters) | Best Coverage | Notes |
|---|---|---|---|
| 42 | 12.8 | 40m+ | Compact portable |
| 63 | 19.2 | 80–10m | Good all-band compromise |
| 74 | 22.6 | 80–10m | **Best gap (376 kHz)** — most recommended |
| 84 | 25.6 | 80–10m | Commonly used alternative |
| 111.5 | 34.0 | 160–10m | Extended coverage |
| 135 | 41.1 | 160m+ | For 160m coverage |

**For your specific needs:**
- Use **Calculator sheet** to find Top-10 lengths for YOUR selected bands
- All Top-3 recommendations are excellent
- Test with **VSWR Calculator** to compare performance

### 6.2 Building a 9:1 UnUn Transformer

A **9:1 autotransformer** is the most common and practical design. Here's how to build one:

#### **Materials Needed:**
- 1× FT-240-43 ferrite toroid (or FT-140-43 for lower power)
- ~3 m of 18-20 AWG enamel copper wire (trifilar winding)
- Small enclosure (plastic food container, aluminum box ~4"×4"×2")
- 3× Banana jacks or wire posts (antenna, ground, coax center)
- 2× Coaxial connectors (SO-239 or SMA) OR wire terminals
- Heat shrink tubing
- Silicone seal (weatherproofing)

#### **Construction Steps:**

1. **Prepare the wire**
   - Cut three lengths ~1.5 m each of 18 AWG enamel wire
   - Measure and mark: First 3 turns will be primary; next 9 turns will be secondary

2. **Wind the toroid (Trifilar method)**
   - Twist three wires together loosely (to keep parallel)
   - Wind all three wires through toroid simultaneously:
     - Turns 1–3: All three wires together (primary section)
     - Turns 4–12: All three wires together (secondary section)
   - Total: ~12 passes through toroid

3. **Strip and Identify Leads**
   - Carefully scrape enamel off all six wire ends
   - Label them: P1, P2 (primary); S1, S2, S3, S4 (secondary); G (ground reference)

4. **Make Connections** (autotransformer configuration)
   - **Primary (coax side)**:
     - Coax center → P1
     - Coax shield → G (ground)
   - **Secondary (antenna side)**:
     - Antenna wire → S1
     - Counterpoise → S4
     - (S2, S3 unused in basic 9:1; could add taps for testing)
   - **Ground connection**: G to enclosure (RF ground)

5. **Mount in Enclosure**
   - Place toroid in center
   - Mount connectors on side
   - Keep leads short and direct
   - Apply silicone seal for weatherproofing
   - Drill small drain hole at bottom for water drainage

6. **Validate** (before connecting to antenna)
   - Use antenna analyzer or VNA
   - Measure impedance ratio at various frequencies
   - Should see roughly 9:1 across 1.8–30 MHz
   - If ratio is wrong, check connections

#### **Power Handling:**
- **FT-82-43**: 50–75 W max
- **FT-114-43**: 100–150 W max
- **FT-140-43**: 300–400 W max
- **FT-240-43**: 1000–1500 W max

Use **50% margin**: If 100W is your target, use FT-140-43 (rated 300–400W).

### 6.3 Toroid Core Selection — CRITICAL MATERIAL SELECTION RULES

**⚠️ FERRITE MIX SELECTION (Updated 2025):**

**DO NOT USE Mix 31** for UnUn/Balun impedance transformers. Mix 31 (Manganese-Zinc ferrite) is only suitable for 1:1 common-mode choking applications. According to Palomar Engineers and Fair-Rite specifications:

**Ferrite Mix Comparison:**

| Mix | Material | Frequency Range | Best Use | Impedance Transformer? | Notes |
|-----|----------|---|---|---|---|
| **31** | MnZn | 1–10 MHz | 1:1 RF chokes ONLY | ❌ NO | Low frequency; NOT for UnUn |
| **43** | NiZn | 10–250 MHz | UnUn 9:1, 16:1, 25:1 | ✅ YES | **BEST for HF UnUn** |
| **52** | NiZn | 200–1000 MHz | High-frequency UnUn | ✅ YES | More turns needed for HF |
| **61** | NiZn | 200–2000 MHz | Ultra-wideband | ✅ YES | Very low µ; many turns needed |

**For HF Long-Wire UnUn applications (1.8–54 MHz):**
- ✅ **Best choice: Mix 43** — Ideal balance of permeability, bandwidth, and efficiency
- ✅ **Secondary: Mix 52** — If higher frequencies needed (not typical for HF)
- ❌ **NEVER Mix 31** — Not suitable for impedance transformers

**Core Size and Power Handling (Ferrite):**

| Core Size | Max Power (PEP) @ 1.8–30 MHz | Recommended For | Notes |
|-----------|------------------------------|---|---|
| FT-82 (mix 43) | 50–75 W | QRP (5–10W sustained) | Small; limited thermal mass |
| FT-114 (mix 43) | 100–150 W | SSB voice (10–50W sustained) | Compact, moderate power |
| FT-140 (mix 43) | 300–400 W | Linear amp (50–150W sustained) | Larger; good thermal mass |
| FT-240 (mix 43) | 1000–1500 W | High power (100W+ sustained) | Large; excellent thermal performance |

**⚠️ CORE SATURATION AND TEMPERATURE EFFECTS:**
- Ferrite saturation flux density (Bsat) decreases by 20–30% with every 50°C temperature rise
- If core is warm to touch during operation, saturation may be occurring
- Design safety margin: Keep flux density at <50% of Bsat at room temperature
- **Never use a core at maximum rated power continuously** — leave 30–50% margin for sustained operation
- Small cores (FT-82) heat quickly and saturate far below rated power

**Stacking Cores for High Power:**
- Single FT-240-43: ~1000–1500 W @ 1.8–30 MHz
- Two FT-240-43 stacked: ~2000–3000 W @ 1.8–30 MHz
- Stacking reduces saturation risk and extends bandwidth

### 6.4 Counterpoise Design and Installation — Updated Guidance (2025)

A **counterpoise** is a wire or set of wires that acts as a reference return path (ground plane substitute) for the antenna. It is electrically and RF-wise "in parallel" with the antenna feedline and carries the return RF current.

**Counterpoise Length Formula (Updated 2025):**

The traditional rule of thumb is: **λ/4 of the lowest operating frequency**

However, recent research (PA9X 2025, RF.Guru 2025) provides more nuanced guidance:
- **Ideal length**: 0.05 × longest wavelength you plan to transmit on
- **Example**: For 80–10m operation (80m is longest), λ = 80 m, so 0.05 × 80 = **4 meters** is sufficient
- This length:
  - Provides return current path without radiating as co-radiator
  - Much more practical than λ/4 (~20m for 80m)
  - Verified effective by multiple 2025 studies

**Number of Radials:**
- **Single radial**: 1–2 meters minimum; works well for QRP
- **Multiple radials** (preferred): 2–4 radials each ~1.5–2 m → Impedance halves with each additional radial in parallel
- **Ground system**: Buried radials more effective than elevated wires

**Configuration Options:**
1. **Separate counterpoise wire** (preferred)
   - Run dedicated wire from UnUn ground to suitable point
   - Can be elevated or buried
   - Completely isolated from feedline

2. **Coax braid as counterpoise** (practical but less ideal)
   - Section of coax between UnUn and first CMC acts as return path
   - Length: Use 0.05λ formula
   - Note: Part of coax does carry RF; this is intentional and necessary

3. **Combination** (good compromise)
   - Dedicated counterpoise wire + coax section
   - Provides low-impedance return path
   - Reduces reliance on coax alone

### 6.5 Antenna Configurations

**Long-wire antennas can be mounted in several configurations:**

1. **Horizontal (far field favored)**
   - Wire runs horizontally, suspended as high as possible
   - Radiates best in horizontal plane
   - Ideal for DX (distant) communications
   - Requires high supports (trees, towers)

2. **Sloper (favored for NVIS)**
   - Wire angles downward from one high support to lower point
   - Radiates at higher angles (up toward sky)
   - Good for NVIS (Near Vertical Incidence Skywave) on low bands
   - Works with single support

3. **Inverted-L**
   - Vertical section + horizontal section forming an "L"
   - Combines vertical and horizontal radiation
   - Can provide good low-angle radiation for DX
   - Requires single tall support

4. **End-fed (antenna only)**
   - Fed at one end, other end open or terminated
   - Can be any of above configurations
   - Feed point impedance varies with configuration
   - Most common for this calculator

5. **Center-fed (dipole-like, for comparison)**
   - Fed at center; requires parallel feedline or balanced line
   - Not primary focus of this calculator
   - Would require BalUn (Balanced-to-Unbalanced), not UnUn

**Recommendation:** Horizontal or sloper configuration at maximum practical height gives best overall performance.

### 6.6 Common-Mode Choke / RF Choke — CRITICAL PLACEMENT (2025 Correction)

A **common-mode choke** (also called 1:1 balun or 1:1 UnUn) suppresses RF current flowing on the outside of the coaxial shield. This prevents the feedline from radiating and causing RFI.

**⚠️ CRITICAL PLACEMENT ERROR IN MANY DESIGNS:**

The CMC placement is critical and often done incorrectly. Here is the **correct 2025 guidance**:

**INCORRECT (often mistakenly recommended)**: CMC immediately at the UnUn feedpoint  
**CORRECT (2025 best practice)**: CMC at the radio end of the feedline, **before it enters the shack**

**Why the difference:**
- With a CMC at the feedpoint, it blocks the coax braid from acting as the counterpoise
- The antenna requires the coax to carry some return current — this is **intentional and necessary** for impedance matching
- A CMC at the feedpoint destabilizes the impedance transformation
- The CMC should allow the coax to act as counterpoise near the antenna, then suppress common-mode current before it reaches sensitive equipment

**Recommended Installation (Correct Order):**

1. **UnUn at antenna feedpoint** (no CMC here!)
2. **Coaxial feedline** (typically 1–50 feet)
   - Outer braid carries return RF current (necessary for impedance matching)
   - This is intentional; don't block it
3. **Optional: 1:1 ferrite choke** at 16–50 feet from UnUn (if additional isolation needed)
   - Provides extra isolation on low bands
   - FT-240-31 or similar
   - 10–12 bifilar turns
4. **Coaxial feedline continues to shack**
   - Can be bundled with other cables
5. **CMC / 1:1 balun BEFORE ENTERING HOUSE/RADIO ROOM** ← **Critical placement!**
   - This is where common-mode current is suppressed
   - Prevents RF in shack
   - Shields radio and AC mains from antenna currents

**Exception**: For EFHW (end-fed half-wave) with **separate dedicated counterpoise wire**, place CMC as close as possible to the UnUn (30–50 cm acceptable). This prevents the coax from acting as an unintended counterpoise.

**CMC Core Selection & Design:**
- **Mix 31** (MnZn): Best for 1.8–10 MHz (≥ 1000 Ω at 1.8 MHz)
- **Mix 43** (NiZn): 10–250 MHz broadband choking
- **Recommended**: FT-240-31 or FT-240-43 with 10–12 bifilar turns
  - Provides 1000+ Ω from 1.8–30 MHz
- For maximum performance: Two FT-240-31 stacked with 12 bifilar turns each
- Target choking impedance: ≥1000 Ω at lowest operating frequency

**Coax Braid Current (Expected):**
- Small amount of RF current on coax shield is **NORMAL and EXPECTED**
- This shields the inner conductor from field coupling
- Only suppress it with a CMC when it becomes excessive (causing RFI)
- Don't block this current at the antenna; allow it to return via coax, then suppress at shack

---

## 7. Supported HF Bands

This calculator supports all amateur radio HF bands from 160 meters to 6 meters:

| Band | Frequency Range | Wavelength (m) | λ/4 (m) | λ/2 (m) |
|------|---|---|---|---|
| 160m | 1.8–2.0 MHz | 167–150 m | 42–37.5 m | 83–75 m |
| 80m | 3.5–3.8 MHz | 86–79 m | 21–20 m | 43–39 m |
| 60m | 5.35–5.37 MHz | 56 m | 14 m | 28 m |
| 40m | 7.0–7.3 MHz | 43–41 m | 10.7–10.3 m | 21.4–20.5 m |
| 30m | 10.1–10.15 MHz | 30–29.5 m | 7.5–7.4 m | 15–14.8 m |
| 20m | 14–14.35 MHz | 21.4–20.9 m | 5.4–5.2 m | 10.7–10.4 m |
| 17m | 18.068–18.168 MHz | 16.6–16.5 m | 4.1–4.1 m | 8.3–8.2 m |
| 15m | 21–21.45 MHz | 14.3–14.0 m | 3.6–3.5 m | 7.1–7.0 m |
| 12m | 24.89–24.99 MHz | 12.0–12.0 m | 3.0–3.0 m | 6.0–6.0 m |
| 10m | 28–29.7 MHz | 10.7–10.1 m | 2.7–2.5 m | 5.4–5.0 m |
| 6m | 50–54 MHz | 6.0–5.6 m | 1.5–1.4 m | 3.0–2.8 m |

The calculator automatically finds wire lengths that avoid half-wave and quarter-wave resonances on all selected bands.

---

## 8. Limitations and Caveats

**Model Accuracy:**
- The feedpoint impedance model (R_est and X_est) used in the VSWR Calculator is **empirical, NOT based on NEC2** full-wave antenna modeling
- Real antenna impedance depends on: height, ground type, nearby objects, weather conditions (humidity/rain), exact geometry
- **Always validate with a VNA or antenna analyzer** before connecting to a transmitter at full power

**450 Ω Assumption (CORRECTED 2024):**
- ⚠️ **This calculator assumes the "standard" 450 Ω for 9:1 matching**, but measured data shows impedance varies widely
- A 9:1 UnUn may not be optimal for your specific wire length and installation
- Use the VSWR Calculator sheet to estimate actual impedance and select appropriate UnUn ratio
- Consider alternative ratios (4:1, 6:1, 7:1, 16:1, 49:1) if your measured impedance differs significantly from 450 Ω
- **Key source**: Ham Radio Outside the Box (Sept 2024) measured an 84-foot wire showing impedance LESS than 450 Ω on all bands

**Core Saturation Not Modeled:**
- The UnUn Calculator sheet does NOT account for ferrite core saturation in detail
- At high power (>100 W on HF), small cores heat up and lose permeability
- Check the "Toroid Core Selection" section for power ratings; do not exceed 50% of rated power for sustained operation
- **Never use FT-82 at full power** — limited thermal mass; saturates easily

**Counterpoise Impedance Model (Empirical):**
- The counterpoise impedance model in the VSWR Calculator is based on heuristic formulas, not NEC2 simulation
- Real counterpoise impedance depends on: length, height, number of radials, ground conductivity, soil type
- Use as a rough guide; actual values may vary ±30%
- **Validation**: Measure with antenna analyzer to confirm

**Ferrite Mix 31 Warning (Critical):**
- ⚠️ **Do NOT use Mix 31 for UnUn transformers**; use ONLY for 1:1 chokes
- Use Mix 43, 52, or 61 (NiZn) for all multi-ratio UnUn designs
- Mix 31 will have poor bandwidth, higher losses, and low power handling on HF

**Common-Mode Choke Placement (UPDATED):**
- CMC should be placed at the **radio end of the feedline**, NOT at the antenna feedpoint
- Placing CMC immediately at the UnUn can **degrade impedance matching** by blocking the counterpoise effect
- Correct placement: Before feedline enters house/radio room

**Temperature Effects:**
- Ferrite saturation flux density decreases 20–30% per 50°C temperature rise
- Design with 30–50% margin from rated saturation
- If core is warm to touch, you may be approaching saturation
- Stacking cores reduces saturation risk

**Empirical Model Accuracy:**
- This model is NOT validated against NEC2 or measured data across all conditions
- Predicted impedance is accurate to approximately ±20–30%
- Results may vary significantly with installation geometry, height, and environment
- **Always verify with measurement equipment before full-power operation**

---

## 9. Glossary

| Term | Definition |
|------|-----------|
| **Antenna tuner** | Device that matches antenna impedance to transmitter impedance; also called ATU or transmatch |
| **Avoidance score** | Metric (0–1) indicating distance from resonance; 1.0 = far from all resonances, 0.0 = on resonance |
| **BalUn** | Balanced-to-Unbalanced transformer; used for balanced antennas like dipoles |
| **Bandwidth** | Range of frequencies over which a component operates effectively |
| **Characteristic impedance** | Reference impedance of a transmission line (typically 50 Ω for coax) |
| **Common-mode choke** | RF choke that suppresses current flowing on cable shields (1:1 transformer function) |
| **Counterpoise** | Ground-plane substitute; return path for antenna current, running in parallel with feedline |
| **dB (decibel)** | Logarithmic ratio; 10 dB = 10× power, 20 dB = 10× voltage |
| **End-fed** | Antenna fed at one end; opposite of center-fed (dipole) |
| **EFRW** | End-Fed Random Wire; another name for long-wire antenna |
| **Feedpoint impedance** | Complex impedance presented at the feed terminals of an antenna; combination of radiation resistance, loss resistance, and reactance |
| **Ferrite** | Magnetic ceramic material; used in cores for transformers and chokes |
| **HF** | High Frequency — 3–30 MHz, encompassing the major amateur radio bands |
| **Impedance** | Opposition to AC current flow; combination of resistance (R) and reactance (X); Z = R + jX |
| **Inverted-L** | Antenna configuration with a vertical section and a horizontal section forming an L-shape |
| **λ/2** | Half-wavelength — the wire length at which a resonant maximum of feedpoint impedance occurs |
| **λ/4** | Quarter-wavelength — the wire length at which a resonant minimum of feedpoint impedance occurs |
| **NEC** | Numerical Electromagnetics Code — the standard electromagnetic simulation engine for antenna modeling |
| **QRP** | Low-power amateur radio operation (typically < 5 W) |
| **Radial** | A single wire in a ground/counterpoise system, extending radially from the antenna feed point |
| **RF choke** | Common-mode inductance placed on a feedline to suppress current flow on the coax shield exterior |
| **SWR / VSWR** | (Voltage) Standing Wave Ratio — ratio of forward to reflected voltage on a feedline; 1:1 = perfect match |
| **Toroid** | Donut-shaped ferrite or powdered-iron magnetic core used to wind transformers and chokes |
| **Transmatch** | Antenna tuning network; can be air-core (tapped coil) or ferrite-based (transformer) |
| **Turns ratio** | The ratio of the number of turns on the primary to secondary winding of a transformer; impedance ratio = turns ratio² |
| **UnUn** | Unbalanced-to-Unbalanced transformer — used where both feedline and antenna are unbalanced |
| **VF / Velocity Factor** | The ratio of wave propagation speed in a conductor to the speed of light in vacuum (0 < VF ≤ 1) |
| **VNA** | Vector Network Analyzer — instrument for measuring antenna impedance, SWR, and complex S-parameters |
| **VSWR** | See SWR |
| **X_est** | Estimated feedpoint reactance (Ω) — the imaginary part of the complex feedpoint impedance |
| **Zcp** | Counterpoise impedance — the RF impedance of the counterpoise wire, which appears in series with the antenna load at the UnUn primary |
| **Z0** | Characteristic impedance; typically 50 Ω for coaxial cable |

---

## 10. References and Further Reading

### Technical Papers and Articles

- **ARRL Antenna Book** (24th edition and later) — comprehensive coverage of end-fed antennas, impedance matching, and feedline theory
- Lewallen, R., W7EL — *NEC-based Antenna Modeling Software*, EZNEC documentation (http://www.eznec.com)
- Moxon, L.A., G6XN — *HF Antennas for All Locations*, RSGB, 1982 — classic reference for practical HF wire antennas
- Sprott, J.C. — *"Optimal Length of a Random Wire Antenna"*, technical note (April 2012, revised May 2022), University of Wisconsin, https://sprott.physics.wisc.edu/technote/randwire.htm — algorithmic approach to finding lengths that avoid all amateur band half-wave resonances simultaneously. Key result: **74 feet (≈ 22.6 m)** is identified as the length with the widest gap (376 kHz) between resonances, making it one of the most robust choices for 80–10 m multi-band coverage without a balun of large turns ratio.
- W0IPL — *"Optimal Non-Resonant Wire Lengths for HF Operation"* — table of odd quarter-wave multiples versus amateur band resonances; origin of the widely-cited 74-foot non-resonant recommendation; referenced in ARRL Antenna Book and the Wikipedia *Random wire antenna* article
- AA5TB — *"End-Fed Half-Wave Antenna"*, https://www.aa5tb.com/efha.html — detailed analysis of EFHW impedance and transformer design
- W8JI — *"Long Wire Antenna"*, https://www.w8ji.com/long_wire_antenna.htm — authoritative practical analysis including counterpoise design and the argument for a 1:1 current balun rather than a UnUn
- G3TXQ (Steve Hunt, SK 2015) — *"Wideband Transformers"* and *"Common Mode Chokes"*, http://www.karinya.net/g3txq/ — extensive research on ferrite vs. powdered iron core performance for UnUn applications (site archived; content remains an authoritative reference)
- Fair-Rite Products — *Material Data Sheets for Mix 31, 43, 52, 61*, https://fair-rite.com/product-category/toroid-cores/ — primary source for AL values, permeability curves, and frequency range data

### Online Resources — UPDATED with 2024–2025 Research

| Resource | URL | Content |
|---|---|---|
| **Ham Radio Outside the Box — Random Wire Antennas Challenge** ⭐ | https://hamradiooutsidethebox.ca/2024/09/04/random-wire-antennas-a-challenge-to-common-knowledge/ | **CRITICAL 2024 STUDY** — Measured 84-foot wire impedance is LESS than 450 Ω on all bands, directly contradicting conventional wisdom. Questions the optimality of 9:1 UnUns. |
| W8JI — Long Wire Antenna | https://www.w8ji.com/long_wire_antenna.htm | Authoritative practical analysis of long-wire systems including counterpoise design |
| Bob Cromwell, AC6V — 9:1 UnUn Build | https://cromwell-intl.com/radio/9-1-unun/ | Detailed construction guide with NanoVNA measurements and core material comparison |
| M0UKD — 9:1 Magnetic Longwire Balun | https://m0ukd.com/homebrew/baluns-and-ununs/91-magnetic-longwire-balun-unun/ | Step-by-step with photos |
| KB6NU — End-Fed Wire and 9:1 UnUn | https://www.kb6nu.com/playing-end-fed-wire-antennas-91-ununs/ | Discussion of core selection and practical results, including G3TXQ core comparisons |
| HFkits — Manual 1:9 UnUn | https://www.hfkits.com/manual-19-unun-600-watts-for-long-wire-antennas/ | Commercial kit instructions with winding details |
| Electronics Notes — End-Fed Wire | https://www.electronics-notes.com/articles/antennas-propagation/end-fed-wire-antenna/ | Beginner-friendly theoretical overview |
| PA9X — Common Mode Choke | https://www.pa9x.com/the-broadband-common-mode-choke/ | Core ratings, choke construction, power limits |
| Toroids.info | https://toroids.info | Online calculator for AL values and inductance of ferrite toroids |
| 73QRZ Choke Calculator | https://73qrz.com/choke-calc | Online tool for balun/choke/UnUn core selection |
| Practical Antennas | https://practicalantennas.com/designs/end-fed/ | Comprehensive analysis of end-fed types |
| **RF.Guru — Counterpoise Role & CMC Placement** ⭐ | https://shop.rf.guru/pages/understanding-the-role-of-the-counterpoise-in-4-1-and-9-1-antennas/ | August 2025: Detailed counterpoise design; optimal CMC placement guidance |
| **PA9X — Proper Counterpoise Design** ⭐ | https://www.pa9x.com/boost-your-end-fed-antenna-with-proper-counterpoise/ | October 2025: Rule of thumb for counterpoise length (0.05λ); RFI prevention |
| **PA9X — Why Antennas Need Counterpoises** ⭐ | https://www.pa9x.com/why-does-an-antenna-require-a-counterpoise/ | Complete explanation of counterpoise function |
| K7MEM — End-Fed Wire Calculator | https://k7mem.com/Ant_End_Fed.html | Interactive online calculator for non-resonant end-fed wire lengths; similar avoidance approach to this workbook |
| VU2NSB — EFHW Antenna | https://vu2nsb.com/antenna/wire-antennas/multiband-efhw-antenna/ | Detailed harmonic analysis of EFHW antenna |
| Battery Eliminator Store — EFHW Deep Dive | https://batteryeliminatorstore.com/blogs/ocf-masters-articles/a-deep-dive-into-end-fed-half-wave-antennas-original | Analysis of transformer ratios from 9:1 to 64:1 |
| Wikipedia — Random Wire Antenna | https://en.wikipedia.org/wiki/Random_wire_antenna | Historical context and impedance characteristics |
| Wikipedia — Counterpoise | https://en.wikipedia.org/wiki/Counterpoise_(ground_system) | Ground system theory |
| RF.Guru — Feed Point Impedance | https://shop.rf.guru/pages/feed-point-impedance-vs-height-for-end-fed-antennas | Feedpoint impedance vs. height and geometry analysis |
| KM1NDY — 64:1 UnUn Build | https://km1ndy.com/diy-linked-efhw-64-to-1-antenna/ | DIY construction of 64:1 UnUn for linked EFHW |
| HF Underground — 9:1 vs 49:1 Discussion | https://www.hfunderground.com/board/index.php?topic=59165.0 | Community discussion on UnUn ratio selection |
| dbBear — EFHW Transformer Theory | https://www.dbbear.com/k0emt/kits/2024-efhw/theory/index.html | Transformer theory and capacitor compensation |
| **Palomar Engineers — Ferrite Mix Selection** ⭐ | https://palomar-engineers.com/ferrite-cores-for-rfi-emi-noise-suppression-mix-31-43-61-75-palomar-engineers/ | Updated 2025: Mix 31 NOT for UnUn; detailed mix comparison |
| **Palomar Engineers — Power Ratings** ⭐ | https://palomar-engineers.com/choke-transformer-power-ratings | Core size power limits; saturation guidance |

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

> **Updated May 31, 2026** with corrections and new documentation based on 2024–2025 research including critical impedance measurement studies, ferrite mix selection corrections, and proper common-mode choke placement guidance.
