# NEC2 Antenna Length Optimizer — Complete User Manual

**Author of the software:** LU3VEA (released CC0 v1.0)
**Manual version:** 1.6 (code-audited against the current source). Changes since 1.5: the entire **antenna-type** feature set is documented for the first time — the three topologies (`long-wire`, `ocfd`, `carolina-windom`), the GUI group that selects them ([6.1](#61-antenna-type-section)) and the fourteen previously undocumented CLI options that go with them; `--jobs` is corrected throughout — it is now honoured in **both** normal and `--fast-run` mode, and the GUI *does* emit it from a field on the Run tab; the CSV schema gains its six dipole-only columns; and the Python requirement is stated as 3.8+. Changes in 1.5: the `--converge` self-check is documented with its real segmentation factors (0.5× and 2×, not 2× and 4×); the previously undocumented `--fast-run`, `--jobs`, `--test-window`, `--refine-top` and `--feed-model` options are covered; the GUI walkthrough gains the Run tab's third check box ("Fast"), its Resume pane, the Physics tab's Feed model section, the Search Range tab's Test All / Test Window control and the UnUn tab's Core/Air and Compensate/Ratio toggles; the Transmatch compensation table's last column is corrected from "5 Ω-tolerant" to a 5 % residual; the CSV column list is completed; and every table-of-contents anchor is corrected (headings of the form `## N — Title` produce a *double* hyphen in the generated anchor).
**Scope of this manual:** installation, concepts, the Graphical User Interface (GUI) in full detail, the command‑line interface (CLI), the output files produced, and troubleshooting.

---

## Table of Contents

1. [What this software does](#1-what-this-software-does)
2. [How it works, in plain terms](#2-how-it-works-in-plain-terms)
3. [Requirements and installation](#3-requirements-and-installation)
4. [Starting the program](#4-starting-the-program)
5. [The Graphical User Interface (GUI) — overview](#5-the-graphical-user-interface-gui--overview)
6. [Tab 1 — Band / Source](#6-tab-1--band--source)
7. [Tab 2 — Search Range](#7-tab-2--search-range)
8. [Tab 3 — Physics](#8-tab-3--physics)
9. [Tab 4 — Output Files](#9-tab-4--output-files)
10. [Tab 5 — Run](#10-tab-5--run)
11. [Tab 6 — UnUn / Transmatch](#11-tab-6--unun--transmatch)
12. [Header bar and global controls](#12-header-bar-and-global-controls)
13. [Understanding the output files](#13-understanding-the-output-files)
    - [13.8 Important limitations of the outputs and the modelling](#138-important-limitations-of-the-outputs-and-the-modelling)
14. [The command-line interface (CLI) — full reference](#14-the-command-line-interface-cli--full-reference)
15. [Typical workflows, step by step](#15-typical-workflows-step-by-step)
16. [Troubleshooting](#16-troubleshooting)
17. [Glossary](#17-glossary)
18. [Appendix: known amateur radio bands](#18-appendix-known-amateur-radio-bands)
19. [Appendix: toroid core database (UnUn tab)](#19-appendix-toroid-core-database-unun-tab)

---

> **Scope note:** this program is a modelling and optimisation tool. It does not replace verification of the real installed antenna. Results depend on the geometric assumptions, ground model, losses, segmentation and nearby objects.

## 1. What this software does

The **NEC2 Antenna Length Optimizer** is a design tool for multi-band wire antennas. It models three topologies, selected with `--antenna-type` (or the dropdown described in [6.1](#61-antenna-type-section)):

- **`long-wire`** (default) — a sloping or horizontal radiator fed against a single feedpoint, with an optional counterpoise, ground rod or coax stub as the RF return path: the classic "random wire" / end-fed configuration used by many amateur radio operators. Matched with an **UnUn**.
- **`ocfd`** — an off-centre-fed dipole (Windom), where the two arms *are* the antenna and no return conductor is needed. Matched with a **balun**.
- **`carolina-windom`** — an OCFD with an additional radiating vertical section between the balun and a line isolator.

The antenna type changes what the length inputs mean, which matching device is designed, which empirical model is used when NEC2 is unavailable, and which geometry-quality metric the report prints. Everything below applies to all three unless a section says otherwise.

Given:

- one or more amateur (or custom) radio **bands** you want to operate on, and
- a **starting wire length** and **counterpoise length**,

the program searches nearby combinations of wire length and counterpoise length, evaluates each one's electrical performance (impedance and VSWR) on every requested band, and reports the combination that gives the best **aggregate performance across all bands simultaneously** — not just one band at the expense of the others.

It can evaluate candidates in two ways:

- **Empirical mode** — a very fast mathematical approximation for screening geometries. It does not model the real ground or counterpoise geometry, and its reactance values must not be used to design a matching network.
- **NEC2 mode** — runs the `nec2c` method-of-moments antenna simulation engine for every candidate geometry. It is a more detailed numerical electromagnetic calculation than the empirical model, but accuracy relative to the real antenna depends on the model, segmentation, ground and installation conditions.

Besides the antenna geometry itself, the software also includes two matching-network calculators reachable from the same window:

- An **UnUn (unbalanced-to-unbalanced) autotransformer designer** built around ferrite/iron-powder toroid cores.
- A **Transmatch (tapped-coil L/C matching network) designer**.

Both matching-network tools can automatically read the antenna impedances found by the optimizer and propose a matching solution for them.

---

## 2. How it works, in plain terms

1. **You describe the antenna problem**: which bands, roughly how long the wire and counterpoise should be, and how far around those lengths to search.
2. The program builds a **grid of candidate geometries** (every combination of wire length × counterpoise length inside the search window, spaced by the step sizes you choose).
3. **Each candidate is evaluated** on every band you asked about:
   - In *NEC2 mode*, the program writes a `.nec` input file describing the geometry (wire radius, material, ground type, segmentation, frequency) and invokes the external `nec2c` simulator, then reads back the feedpoint resistance (R) and reactance (X) and computes the Voltage Standing Wave Ratio (VSWR).
   - In *empirical mode*, R and X are estimated from closed-form approximations instead of a full simulation (much faster, less accurate close to resonance).
4. Each candidate receives an **aggregate score** that combines the VSWR penalty on every active band (worse VSWR = worse score), an "avoidance" penalty for candidates that sit awkwardly close to a band edge, and — optionally — a bonus/penalty related to low-angle radiated gain at a target takeoff angle.
5. The program also tracks the **Pareto-optimal set**: candidates for which no other candidate is simultaneously at least as good on every band. This shows you the real trade-offs available, not just a single "winner."
6. The best candidate (and, optionally, its neighbours) is **re-simulated at high accuracy** ("fine" segmentation) so that the numbers you actually build from are trustworthy, even if the broad search used a coarser, faster setting.
7. Finally the program **writes the results**: a ranked text report, a scatter/heatmap plot, a CSV of the winning geometry's per-band figures, a ready-to-use NEC2 deck, radiation-pattern diagrams, a construction drawing, and a one-page PDF "brochure" summarizing the design, if `reportlab` is installed.

---

## 3. Requirements and installation

### 3.1 Python

The tool is a single Python 3 script. It requires:

- **Python 3.8 or newer.**
- The **Tkinter** GUI toolkit, if you intend to use the graphical interface. Tkinter ships with most desktop Python installations; on some Linux distributions it must be installed separately:
  ```bash
  sudo apt install python3-tk
  ```
  If Tkinter is missing, the GUI will refuse to start and print this exact instruction.

### 3.2 Optional but recommended Python packages

| Package | Purpose | What happens if it is missing |
|---|---|---|
| `colorama` | Colored console output in the terminal | Falls back to plain text. No functional loss. |
| `matplotlib` | Search-space plot, radiation diagrams and construction drawings, including matching-tool drawings | Those graphical outputs cannot be generated without it. |
| `numpy` | Used internally by the radiation-diagram renderer | Radiation diagrams cannot be generated without it. In practice `numpy` is almost always already present, since it is installed automatically as a dependency of `matplotlib`. |
| `reportlab` | PDF brochure generation | The PDF is skipped if `reportlab` is not installed. |
| `Pillow` (`PIL`) | Embeds the construction/radiation PNGs into the PDF brochure | The PDF is still generated, but the affected image section is replaced with a "(unavailable)" placeholder instead of the picture. |

Typical installation:

```bash
pip install colorama matplotlib numpy reportlab pillow
```

`matplotlib`, `reportlab`, and `Pillow` are independent of each other: `matplotlib` creates the plot/diagram images, `reportlab` creates the PDF shell, and `Pillow` embeds images into that PDF. Missing one does not necessarily prevent the other outputs.

> **Note on the Windows installer:** `Setup_Long_Wire_Antenna.exe` also `pip install`s a package called `tabulate` alongside the packages above. The script does not actually import or use `tabulate` anywhere in its code — it is unused leftover in the installer's dependency list, not a real requirement of the tool. You do not need to install it if you are setting up the script manually.
>
> The installer also runs a post-install step (`post_install_setup.py`) that optionally tries to download a newer NEC2 engine build from an external GitHub project as an upgrade over the bundled `nec2c.exe`, falling back to the bundled binary if that fails. Its fallback logic looks for a file named `onec.exe`/`onec_bundled.exe`, which this installer does not actually ship (it only ships `nec2c.exe`), so that particular fallback path is currently a no-op — harmless, since the installed launcher (`run_gui.bat`) independently locates and uses `nec2c\nec2c.exe` regardless of this step's outcome. You can safely ignore any installer-log mentions of `onec.exe`.

### 3.3 NEC2 simulation engine (`nec2c`)

To use **NEC2 mode** (recommended for trustworthy final numbers) you need the `nec2c` binary — a compiled implementation of the NEC-2 method-of-moments antenna simulator — installed on your system. Typical sources:

- Your Linux distribution's package manager (package name varies, e.g. `nec2c`).
- Compiling from the public `nec2c` source project.

**Empirical mode does not need `nec2c` at all**. It can be used without an external NEC2 engine, but it remains an approximation.

> **Linux one-click alternative:** instead of installing `nec2c` and the Python packages above by hand, you can use the prebuilt `Long_Wire_Antenna-x86_64.AppImage` (or build your own with `others/build_appimage.sh`), which bundles its own Python interpreter, all optional packages, and a statically-linked `nec2c` binary in a single portable file. See the project's `README` for details. The AppImage always launches directly into the GUI.

### 3.4 Locating the `nec2c` binary

The program looks for `nec2c` automatically, in this order:

1. An explicit path given with `--nec2c /path/to/nec2c` (CLI) or typed into the **NEC2 binary** field (GUI).
2. The `$NEC2C` environment variable.
3. Your system `PATH` (checks for the executable names `nec2c`, `nec2c-mpich`, and `onec` — this is the current, correct list; older notes referencing `xnec2c` were incorrect and have been superseded).
4. A list of common install locations (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, `/opt/homebrew/bin`, etc.), including `onec`-specific paths such as `C:\Program Files\OpenNEC\onec.exe` on Windows.
5. As a last resort, on the command line only, it will interactively ask you to type the path (unless `--no-interactive` is set).

In the GUI, use the **Auto-detect** button on the Physics tab to trigger this search on demand.

`onec` is the executable name used by the OpenNEC project's build of the engine; `nec2c` and `nec2c-mpich` are the more common classic builds. All three are supported interchangeably by name-based auto-discovery.

> ⚠️ **Known bug — the hardcoded `Program Files\OpenNEC` search on Windows:** the Windows installer mirrors the engine to `C:\Program Files\OpenNEC\nec2c.exe` and `C:\Program Files (x86)\OpenNEC\nec2c.exe` as part of installation (see [§3.2](#32-optional-but-recommended-python-packages) above). However, the two hardcoded `OpenNEC` paths in discovery step 4's list of common install locations look for a file literally named **`onec.exe`**, not `nec2c.exe` — so that fallback will never actually find the copy the Windows installer places there. In normal use this is invisible, because launching via the Desktop shortcut (`run_gui.bat`) sets the `$NEC2C` environment variable directly (discovery step 2) and never needs this fallback at all. It only matters if you run `Long_Wire_Antenna.py` yourself from a plain terminal after a Windows-installer install, without `run_gui.bat` and without `$NEC2C` set — in that case, pass `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"` explicitly (or set `$NEC2C` yourself) rather than relying on auto-discovery.

---

## 4. Starting the program

### 4.1 Launching the GUI

```bash
python src/Long_Wire_Antenna.py --gui
```

This opens the interactive window described in the rest of this manual. No other flags are needed to open the GUI — every setting is then entered through the interface itself.

`--gui` is detected in a pre-parsing pass before the rest of the command line is read, so any other flags given alongside it (e.g. `python src/Long_Wire_Antenna.py --gui --bands 40m`) are silently ignored — the GUI opens with its own defaults regardless. Use the GUI's own fields, not extra CLI flags, to configure a GUI-mode run.

### 4.2 Running from the command line (no GUI)

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

See [Section 14](#14-the-command-line-interface-cli--full-reference) for the complete list of flags. The GUI is, in fact, a front-end that assembles exactly this kind of command line for you and runs it — every option you see in the GUI corresponds to one of these flags, and the **Run tab's command preview shows the command assembled from the current GUI settings** in real time.

### 4.3 Getting command-line help

```bash
python src/Long_Wire_Antenna.py --help
```

### 4.4 Interface language

The program's text (both CLI messages and the GUI) is available in **English, Spanish, and Italian**. See [Section 12.3](#123-language-switch) for how to change it in the GUI, and `--lang` for the CLI.

---

## 5. The Graphical User Interface (GUI) — overview

When launched with `--gui`, the program opens a single window containing:

- A **header bar** (title, language switch, font size controls).
- An **optimizer script path** row (which Python script file the GUI will actually execute — see [12.1](#121-optimizer-script-path)).
- A **notebook of six tabs**, each grouping related settings:
  1. **Band / Source** — which bands to design for, and the starting geometry.
  2. **Search Range** — how wide and how finely to search, plus counterpoise/ground-return options.
  3. **Physics** — simulation engine, ground model, wire conductor, and accuracy settings.
  4. **Output Files** — where results are written and what they are named.
  5. **Run** — the command preview, the Run/Stop controls, and a live console.
  6. **UnUn / Transmatch** — two independent matching-network calculators (sub-tabs).

The GUI **does not perform the main antenna optimisation inside the window itself** — it builds a command line from your settings and launches the optimizer script as a separate process, exactly as if you had typed that command line yourself. This means:

- The **command preview** on the Run tab reflects the current GUI settings and can be copied and run manually if you prefer.
- Long searches run in the background; the window stays responsive and you can watch progress in the console.
- You could, in principle, point the "optimizer script" field at a *different* copy or version of the script and the GUI would drive that one instead.

Every text field, checkbox, radio button, and dropdown in the six tabs is described exhaustively below, tab by tab.

---

## 6. Tab 1 — Band / Source

This tab defines **what** you are designing for: the antenna topology, the operating bands, the frequencies (if needed), and the initial guess for the two lengths.

### 6.1 "Antenna type" section

This is the **first control group on the tab**, and deliberately so: it changes what every other field in the program *means*. It is the only place in the GUI where the antenna topology itself is chosen.

- **Antenna type (dropdown)** — `long-wire` (default), `ocfd`, or `carolina-windom`. CLI: `--antenna-type`.
  - **`long-wire`** — the classic end-fed radiator plus a return conductor (counterpoise, ground rod, or coax stub). "Wire length" and "Counterpoise length" mean exactly what their names say, every counterpoise control on the Search Range tab applies, and the matching device is an **UnUn** whose ratio the optimizer searches for automatically.
  - **`ocfd`** — an **off-centre-fed dipole** (Windom). Both arms radiate and the dipole is its own return path, so **"Wire length" and "Counterpoise length" become the long arm and the short arm**; `--no-counterpoise` is rejected outright, the "No-counterpoise return path" section stops applying, and the matching device becomes a **balun** restricted to buildable ratios.
  - **`carolina-windom`** — an OCFD plus a **radiating vertical section** between the balun and a line isolator. Three conductors meet at the feed node, so the straddle feed is geometrically impossible and the feed model is **forced to `junction`** (the program says so on startup and recommends `--converge`). Expect slower convergence and a larger published uncertainty on X.
- **Offset** — short arm ÷ total length, dipole types only. Default `0.3333` (the classic Windom third); valid range `0.10`–`0.49`. At `0.50` it would be an ordinary centre-fed dipole; below `0.10` it is effectively an end feed. CLI: `--offset`. Greyed out for `long-wire`.
- **Balun kind** — `guanella` (default) or `ruthroff`: the transmission-line balun topology. Guanella is a current balun and is the correct choice for a balanced feed across all of HF. CLI: `--balun-kind`. Dipole types only.
- **Vertical length (m)** — Carolina Windom only: the length of the radiating vertical section between the balun and the line isolator. Default `3.0` m, minimum `0.5` m. CLI: `--cw-vert-len`.
- **Isolator Z (R,X)** — Carolina Windom only: model the line isolator as a **finite** series impedance (e.g. `1000,2000`) instead of an ideal open circuit. Leave blank for the ideal case; fill it in to study what an inadequate choke actually does to the antenna. CLI: `--cw-isolator-z`.

Controls the selected type cannot use are greyed out automatically. On the command line the equivalent combinations are **rejected with an explicit error** rather than silently ignored, so a run can never report a different antenna from the one your flags describe — for example, `--antenna-type ocfd --no-counterpoise` stops with an error instead of quietly modelling something else.

> The CLI carries several further antenna-type options that have no GUI control of their own: `--total-len`, `--offset-min` / `--offset-max` / `--offset-step`, `--balun-ratio`, `--balun-core`, `--balun-turns`, `--feed-choke` and `--match-model`. See [Section 14](#14-the-command-line-interface-cli--full-reference).

### 6.2 "Band(s)" field

- **What it is:** a comma-separated list of band names, e.g. `40m,20m,15m`.
- **Default:** `40m,20m,15m`.
- **Required:** yes — the optimizer cannot run without at least one band.
- Band names may be one of the **known amateur bands** (see [Appendix, Section 18](#18-appendix-known-amateur-radio-bands)) or an arbitrary custom name of your choosing (e.g. `mySpecialBand`).
- Directly beneath the field, a hint line lists every recognized band name, for reference.

### 6.3 "Frequencies (MHz)" field

- **What it is:** a comma-separated list of centre frequencies in MHz, one per band, in the *same order* as the Bands field, e.g. `7.1,14.2,21.2`.
- **When it is optional:** if every name typed into "Band(s)" is a *recognized* band (see the list under the field, or [Section 18](#18-appendix-known-amateur-radio-bands)), you may leave this field empty — the program automatically substitutes the standard centre frequency for each recognized band.
- **When it is required:** if you use any custom/unrecognized band name, you **must** supply a matching frequency for it here, or the program will stop with an error (in interactive command-line use it may prompt for it; the GUI will pass whatever you typed, so fill it in).
- A hint line under the field reminds you of this rule.

### 6.4 "Wire length (m)" field

- **What it is:** the starting length, in metres, of the sloping radiator wire — the centre point that the search window is built around.
- **Default:** `21.0`.
- **Required:** yes.
- A colored hint to the right of the field gives a short reminder of its role.

### 6.5 "Counterpoise length (m)" field

- **What it is:** the starting length, in metres, of the counterpoise wire — again, the centre of the search window.
- **Default:** `5.0`.
- **Required:** yes, **unless** you have unchecked "Use counterpoise" on the Search Range tab (see [7.3](#73-use-counterpoise-checkbox)), in which case this field is disabled (greyed out) because there is no counterpoise to size.

### 6.6 "Active Bands" section

- **Purpose:** lets you tell the optimizer to *evaluate* a geometry across every band you listed in 6.2, but only *score* (rank candidates by) a subset of those bands.
- **Field:** a comma-separated list of band names, which must be a subset of the names in "Band(s)".
- **Default:** empty, meaning **all** bands listed under "Band(s)" are treated as active and used for scoring.
- **Example use case:** you want the report to also show you how a design performs on 10 m out of curiosity, but you only actually operate on 40 m and 20 m — set Band(s) to `40m,20m,10m` and Active Bands to `40m,20m`.

### 6.7 "Optimizer language" (report language)

- **Purpose:** chooses which language the *optimizer's own console output and generated report/PDF* are written in — independent from the GUI's own display language (see [12.3](#123-language-switch)).
- **Options:** `auto` (detect from your system locale), `en`, `es`, `it`.
- **Default:** `auto`.

---

## 7. Tab 2 — Search Range

This tab controls **how wide and how fine** the search is, plus the counterpoise topology (present or absent) and, when absent, how the RF return path is modeled. It also holds antenna geometry (height, slope) and reporting size options.

### 7.1 "Search margin" field

- **What it is:** if you do *not* set explicit minimum/maximum bounds (7.2, 7.6), the optimizer searches ± this many metres around your starting Wire length and Counterpoise length.
- **Default:** `2.0` m.
- **Overridden by:** explicit Wire-min/Wire-max or CP-min/CP-max values, described next.

### 7.2 "Wire search range" section

Three fields, all optional:

| Field | Meaning | Default behaviour if left empty |
|---|---|---|
| `wire-min` | Minimum wire length to test (m) | Computed from starting length − margin |
| `wire-max` | Maximum wire length to test (m) | Computed from starting length + margin |
| `wire-step` | Increment between tested lengths (m) | `0.25` m |

A note under the fields reminds you that leaving them blank falls back to the margin-based automatic window.

### 7.3 "Use counterpoise" checkbox

- **Default:** checked (counterpoise present).
- **When checked:** the antenna is modeled as a sloping radiator **plus** a sloping counterpoise wire, both from the same feedpoint. All counterpoise-related fields elsewhere in the GUI (Counterpoise length on the Band/Source tab, the counterpoise range fields below, and the counterpoise end-height field) are enabled.
- **When unchecked:** the antenna is modeled **without** a counterpoise at all. Every counterpoise field is disabled (greyed out) but *keeps its typed value in memory* — re-checking the box restores exactly what you had. Unchecking this adds `--no-counterpoise` to the command, and activates the **"No-counterpoise return path"** section below, which becomes mandatory in this case.

### 7.4 "No-counterpoise return path" section

This section only matters — and is only enabled — when "Use counterpoise" (7.3) is **unchecked**. It selects how the RF return path is modeled in the absence of a counterpoise wire, since some kind of return path must exist for the simulation to be physically meaningful. Three mutually-exclusive radio-button choices:

- **`ground-rod`** (default) — models the return path as a direct earth/ground-rod connection.
- **`coax-stub`** — models the return path as a coaxial-braid stub of a specified length. Selecting this enables the **"CP stub length"** field below it (default: taken from the program's default stub length; edit as needed).
- **`reject`** — declines to synthesize any implicit return path; use this if you plan to model the return path yourself in a different way, or want the program to flag configurations where no return path is defined.

A colored hint line above the radio buttons explains the trade-off. In NEC2 mode, `reject` explicitly rejects the configuration; `ground-rod` is modelled with perfect ground (GN 1), while `coax-stub` retains the selected ground model. In empirical mode these return-path choices are not part of the empirical model.

### 7.5 "Radiation / take-off angle" section

Controls how (and whether) the scoring rewards low-angle radiated gain, which matters most for DX (long-distance) work:

| Field | Meaning | Default |
|---|---|---|
| Target take-off angle | The elevation angle (degrees above the horizon) at which the gain bonus/penalty is evaluated | `25.0°` |
| Gain weight | How strongly gain at that angle influences the aggregate score, in score-units per dB. Roughly, 5 dB of gain difference ≈ 1.0 score unit | `0.20` per dB |
| Re-rank top N | How many of the best VSWR-only candidates get a full radiation-pattern re-simulation (needed to actually measure gain at the target angle) before the gain bonus is applied | `6` |

A hint underneath explains the trade-off: re-ranking more candidates (higher N) costs more computation time but gives the gain-based re-ranking a wider pool of near-optimal candidates to choose from.

### 7.6 "Counterpoise search range" section

Mirrors the Wire search range section (7.2), but for the counterpoise length. Only meaningful (and only affects the command) when "Use counterpoise" is checked:

| Field | Meaning | Default behaviour if left empty |
|---|---|---|
| `cp-min` | Minimum counterpoise length to test (m) | Computed from starting length − margin |
| `cp-max` | Maximum counterpoise length to test (m) | Computed from starting length + margin |
| `cp-step` | Increment between tested lengths (m) | `0.25` m |

### 7.7 "Antenna geometry" section

One shared **feedpoint height** for the whole antenna, plus optional slope controls:

| Field | Meaning | Default |
|---|---|---|
| **Height** | Height of the feedpoint above ground (metres). Shared by both the radiator and the counterpoise, since both hang from the same feedpoint. | `8.0` m |
| **Wire slope end height** | Height above ground (metres) of the *far end* of the radiator wire (the end away from the feedpoint). `0.0` means the wire slopes all the way down to touch the ground (a fully diagonal wire). Leave empty to keep the wire perfectly horizontal at the feedpoint height. **Setting this value forces NEC2 mode** — the empirical formulas do not model sloped geometry. | empty (horizontal wire) |
| **Counterpoise end height** | Same idea, but for the far end of the counterpoise wire. Leave empty to keep the counterpoise level with the antenna's feedpoint height. | empty (level with antenna height) |

### 7.8 "Maximum retries" section

- **What it is:** if the winning candidate lands right at the *edge* of the search window (e.g., the best wire length found equals `wire-max`), that is a sign the true optimum may lie outside the window you searched. This setting tells the program to automatically re-run the search, shifting the window in the direction suggested by that warning, up to N additional times.
- **Control:** a spinbox from `0` to `10`.
- **Default:** `0` (disabled — no automatic retry).

### 7.9 "Report options" section

- **Top N** — how many of the best candidates to list in the final ranked report.
- **Control:** a spinbox from `5` to `200`.
- **Default:** `20`.

### 7.10 "Test All / Test Window" checkbox and "Refine top N"

In the window itself this control sits immediately below the **Search margin** field (7.1); it is described last here only so that the numbering of the other sections is unchanged from earlier revisions of this manual.

It decides **what a retry does** (7.8), and therefore has no effect at all unless **Maximum retries** is greater than `0`.

- **Checked — "Test All"** (default) — a retry **shifts** the search window outwards, at the original grid steps, when the winning candidate sits on a search boundary. This is the behaviour described in 7.8 and adds no flag to the command line.
- **Unchecked — "Test Window"** — a retry instead **refines**: the next pass covers only the bounding box of the best `N` candidates of the previous pass (padded by one current step and clamped to the window already swept), with **both grid steps halved**. It repeats until the retry budget runs out or both steps reach the floor of `0.01` m, at which point further halving is below any meaningful cutting accuracy. Unchecking the box adds `--test-window` to the command.
- **"Refine top N" spinbox** — how many top candidates define that bounding box. Range `1`–`50`, default `5`. Only used in Test Window mode; it emits `--refine-top N`.

Use Test Window when you already know roughly where the optimum is and want resolution finer than your step size; use Test All when you are not yet sure the optimum is inside the window at all.

---

## 8. Tab 3 — Physics

This tab controls the **simulation engine**, the **ground model**, the **wire conductor** properties, and the **numerical accuracy** (segmentation) of the NEC2 simulation.

### 8.1 "Evaluation mode" section

Three mutually-exclusive radio buttons:

- **`auto`** (default) — use NEC2 simulation if a working `nec2c` binary can be found; otherwise fall back to the empirical formulas.
- **`nec2`** — always use full NEC2 simulation. Fails with an error if no `nec2c` binary is available.
- **`empirical`** — always use the fast approximate formulas, even if `nec2c` is available. Useful for quick, coarse first passes.

### 8.2 "NEC2 binary" row

- **Text field:** the explicit filesystem path to the `nec2c` executable. Leave empty to rely on auto-discovery (see [Section 3.4](#34-locating-the-nec2c-binary)).
- **Browse button:** opens a file-picker dialog to select the binary from disk.
- **Auto-detect button:** immediately runs the same discovery search the optimizer performs at start-up (checks `$NEC2C`, `PATH`, common install directories) and fills the field in if something is found.
- A hint line beneath explains the discovery order.

### 8.3 "Ground" section

Controls the electrical properties of the earth beneath the antenna, used by the NEC2 Sommerfeld-Norton ground model:

| Field | Meaning | Default |
|---|---|---|
| **Conductivity** | Ground conductivity, in Siemens per metre (S/m) | `0.005` S/m |
| **Permittivity** | Ground relative permittivity (dimensionless) | `13.0` |

**Quick presets** — five buttons instantly fill both fields with commonly-used reference values:

| Preset | Conductivity (S/m) | Permittivity |
|---|---|---|
| Poor ground | `0.001` | `5` |
| Average ground | `0.005` | `13` |
| Good ground | `0.010` | `20` |
| Excellent ground | `0.030` | `25` |
| Salt water | `5.000` | `80` |

### 8.4 "Ground model" section

Two mutually-exclusive radio buttons:

- **`sommerfeld`** (default) — uses NEC2's Sommerfeld-Norton ground model, which properly accounts for the finite conductivity/permittivity values above. Physically realistic, recommended for real installations.
- **`perfect`** — assumes a perfectly conducting ground (an idealisation). Runs faster but is optimistic/unrealistic for most real sites; useful mainly for comparison or sanity-checking.

A hint below explains this trade-off.

### 8.5 "Wire / conductor" section

Controls the physical wire used to build the antenna model:

- **Wire diameter (mm)** — the conductor's diameter. Default corresponds to a 2 mm-diameter (1 mm radius) wire, roughly AWG 12 copper wire.
- **Wire material** — a dropdown (combobox) of conductor materials, each with a fixed conductivity value baked in:

  | Material (English key) | Conductivity (S/m) |
  |---|---|
  | Copper (default) | 5.80 × 10⁷ |
  | Aluminium / Aluminum | 3.54 × 10⁷ |
  | Brass | 1.56 × 10⁷ |
  | Silver | 6.30 × 10⁷ |
  | Steel (galvanised) | 6.99 × 10⁶ |
  | Perfect (lossless, for comparison only) | — (no loss card is written at all) |

  The dropdown label is shown in whichever language the GUI is currently displaying (e.g. "cobre" in Spanish), but internally the program always sends the canonical English name to the underlying script, so switching the GUI's display language never breaks this setting.

- **Wire conductivity override (S/m)** — an optional field to manually specify a conductivity value that does not match any of the standard materials above. Leave empty to use the value implied by the Material dropdown. A hint below explains when you would want to do this (e.g., a specific alloy or a manufacturer's datasheet value).

> **Why this matters:** without a conductivity/loss setting, NEC2 assumes every wire is a *perfect* (lossless) conductor, which overstates gain — especially for the thin wire and short counterpoises this tool tends to favour, where resistive (I²R) losses are not negligible. Setting a real material gives realistic, slightly more conservative gain figures.

### 8.6 "Accuracy / Segmentation" section

NEC2 subdivides each wire into short calculation "segments"; how many segments per half-wavelength strongly affects accuracy, especially for feedpoint impedance (as opposed to just radiation-pattern shape) — segmentation density can change both R and X. **More segments do not by themselves guarantee physical accuracy**: convergence should be checked, and NEC2 remains a numerical model of an idealised geometry.

Three mutually-exclusive radio buttons:

- **`fine`** (default) — 180 segments per half wavelength. This is the default density used for every number that actually gets published (the winning candidate's final figures, the exported `.nec` deck, the report, the CSV). **It is not a guarantee that the result has converged** — recommended for anything you intend to build, but pair it with "Re-check convergence" below for a final design.
- **`fast`** — 21 segments per half wavelength. This is deliberately coarse; the program's own segmentation-error model puts the resulting R uncertainty at roughly **28–31% (measured low)**, and it can also produce **reactance sign errors** in some cases.[^segs-warn-note] It is intended for fast sweeps and pattern-only work — its impedances must never be used to size a matching network or make a build decision.
- **`custom`** — enter your own segments-per-half-wavelength value in the adjoining field. The program's internal default for the search *sweep* itself (as opposed to the final published numbers) is 45 segments per half wavelength — a middle ground chosen because the ranking of candidates against each other is fairly insensitive to this density, even though the absolute numbers are not. Unless this option overrides both, the normal sweep uses 45 segments per half wavelength and the final run uses 180.

[^segs-warn-note]: The console/report message that accompanies `--fast` computes this percentage live from the tool's calibrated error model (`estimated_imp_uncertainty_pct()`, fitted as err% ≈ 420 / spw^0.86 against a Richardson-extrapolated reference), which gives ~30.6% at 21 segments per half wavelength — this is the number quoted above. One static GUI hint string elsewhere in the source still shows an older, uncorrected "~14%" figure left over from before that model was refitted; treat the dynamically-computed value (and this manual's figure) as the accurate one.

**"Re-check convergence" checkbox** — when enabled (CLI: `--converge`), the winning geometry is automatically re-simulated at **0.5× and 2× the working segmentation density**, and the report tells you how much R and X still moved across those runs. The factors *straddle* the working density rather than only refining it: with the publishing density already at 180 seg/half-wave, a 4× arm would clamp to the program's 400 seg/half-wave sanity cap and produce two nearly identical rows — a convergence check that cannot see any drift. The drift of every row is measured against the finest one, so the verdict does not depend on which density is called the baseline.

The approximately 3% threshold applies to R drift; X has a separate tolerance. If R moves by more than roughly 3%, the report flags it — a sign you may want to increase the fine-density setting further before building; if convergence is not satisfactory, do not size a matching network from X.

Two conditions and one interaction are worth knowing:

- The check only runs in **NEC2 mode with a working `nec2c` binary**. In empirical mode it is silently skipped, because there is no segmentation to vary.
- With **Fast run** enabled (`--fast-run`, see [10.1](#101-miscellaneous-section)), only the **0.5× arm** is kept. The 2× arm doubles the segment count and NEC-2 cost grows roughly as N³, so that single run can outweigh the rest of the program. The check still measures drift, over a 2:1 span of densities instead of 4:1, and the report header states which factors were used.
- A custom segments-per-half-wave value is clamped to the range `5`–`400` before use.

> **Important:** NEC2 figures are model results, not measurements of the real antenna. Height, geometry, conductor, ground, losses, nearby objects and the actual installation can change the result. For a final build, verify the real system by measurement (for example, with a VNA) before making final cuts or permanent installation.

A colored hint at the bottom of the section summarizes all of this.

### 8.7 "Feed model" section

In the window this section sits between **Ground model** (8.4) and **Wire / conductor** (8.5). It chooses **where the NEC-2 excitation (`EX`) card is placed relative to the junction between radiator and counterpoise** — a purely numerical choice that does not change the antenna being modelled, only how quickly the model converges near the feedpoint.

Two mutually-exclusive radio buttons:

- **`straddle`** (default) — when the return conductor is collinear with, and opposite to, the radiator (the usual horizontal radiator + horizontal counterpoise), both wires are written as **one continuous `GW` card** and the source is placed on the segment that *contains* the feed node. There is then no wire junction underneath the source at all. Same physical structure — same endpoints, same radius, same total length — but the feedpoint resistance settles by ~180 segments per half wavelength instead of still drifting at well over a thousand, and it removes the half-segment feed offset that the junction model otherwise has to account for in the report.
- **`junction`** — the historical model: two `GW` cards meeting at the feed node, with the source on segment 1 of wire 1. The source singularity and the junction charge-matching condition then land on the *same* segment, which is a known slow-convergence configuration in NEC-2. Useful mainly for comparing against older results or other modelling tools.

Geometries whose return conductor is **not** collinear — a hanging counterpoise, a ground rod, a coax stub, or a sloping radiator with a horizontal counterpoise — cannot be fused into one wire without changing the shape near the feed, so they fall back to the junction model automatically regardless of this setting.

Unless you are reproducing an older result, leave this on `straddle`. On the command line it is `--feed-model {straddle,junction}`; the GUI only adds the flag when you pick the non-default value.

---

## 9. Tab 4 — Output Files

This tab controls **where** the results are written and **what they are named**.

### 9.1 "Working directory" section

- **Field:** the folder where all output files will be written.
- **Default:** your home directory.
- **Browse button:** opens a folder-picker dialog.
- A hint line explains that this folder is created automatically if it does not already exist.

### 9.2 "Output files" section

Seven independently-editable filenames, each written inside the working directory above. Some outputs are conditional on the installed optional packages and on the selected evaluation mode:

| Field | Default filename | Contents |
|---|---|---|
| `out-txt` | `optimizer_report.txt` | Ranked report containing the top-N candidates, the Pareto-optimal set, and a plain-language interpretation of the winner |
| `out-png` | `optimizer_plot.png` | A scatter/heat-map plot of the search space plus per-band VSWR bar charts |
| `out-csv` | `optimizer_best.csv` | The winning candidate's per-band frequency/R/X figures, machine-readable — this is what the UnUn/Transmatch tab reads automatically |
| `out-nec` | `best_antenna.nec` | NEC2 input deck for the winning geometry, with RP cards for active bands; it can be loaded into compatible NEC2 tools, subject to their own NEC2 implementation limits |
| `out-radiation` | `radiation_diagrams.png` | Radiation-pattern diagrams for every active band; generated only with NEC2 evaluation |
| `out-construction` | `antenna_construction.png` | A dimensioned construction drawing you can build from |
| `out-pdf` | `antenna_brochure.pdf` | A one-page PDF summary ("brochure") combining the key numbers, plots, and construction drawing |

Leaving any of these fields blank is not recommended, since the corresponding output simply will not be produced under a predictable name; the defaults are sensible for almost all uses.

---

## 10. Tab 5 — Run

This is where you launch the optimizer, watch its progress, and jump straight to the generated files.

### 10.1 "Miscellaneous" section

Three checkboxes and one numeric field:

- **Fast** — adds `--fast-run`, the program's whole acceleration policy. **Default in the GUI: unchecked**, so an existing workflow keeps exactly the behaviour — and exactly the numbers — it had before this box existed. When enabled it: solves independent `nec2c` decks concurrently (in the sweep, the fine refinement pass and the radiation re-ranking pass); runs the sweep at the coarse segmentation, like `--fast`; recomputes fewer candidates at the publishing density (the winner and the Pareto front always are, but the tail of the TOP-N table keeps its sweep-density tag, which the report prints per row); shortens the radiation re-ranking shortlist to 3; and keeps only the 0.5× arm of the convergence self-check. Every one of those trade-offs stays visible in the report — the published impedances of the winner are **not** affected, since the final density is unchanged. Note that `--fast-run` is *not* the same thing as `--fast`, which only sets the sweep segmentation and is wired to the Segmentation radio buttons on the Physics tab ([8.6](#86-accuracy--segmentation-section)).
- **Quiet** — adds `--quiet` to the command, suppressing verbose progress/detail messages while retaining important results and warnings. **Default in the GUI: checked.** Uncheck for maximum diagnostic detail.
- **No interactive prompts** — adds `--no-interactive`, telling the optimizer to fail immediately if a required input is missing instead of prompting on the terminal. **Default in the GUI: checked.**

- **Jobs** — a numeric field, **blank by default**, that adds `--jobs N`: how many `nec2c` processes are solved concurrently. Left blank the GUI emits no flag at all, which means serial in normal mode and one worker per core (capped at 16) under **Fast** — exactly what every previously-saved command line already does.

> **`--jobs` and `--fast-run` are orthogonal, and `--jobs` works on its own.** `--jobs N` buys you the *same answer, sooner*: results are stored by grid index and reassembled in grid order, so the candidate list, the ranking, the Pareto front and every published impedance are bit-identical to a serial run — only the wall clock changes. `--fast-run` buys speed by computing a *different, cheaper* answer. `--jobs` is therefore honoured in **both** modes; earlier versions forced it to 1 unless `--fast-run` was also given, and that restriction has been removed (it cost the most in normal mode, which is precisely where the expensive work lives). Defaults: `1` (serial) without `--fast-run`, and one worker per CPU core capped at 16 with `--fast-run` and no `--jobs`. The program prints a note if `N` exceeds the number of cores it detects, and another if the engine is itself an MPI build (`nec2c-mpich`), where N workers × M ranks oversubscribes the machine badly.

### 10.2 "Command preview" box

A read-only text box showing the **exact command line** the GUI is about to execute, built live from every setting on every tab. This box updates automatically, with no button to press, every time you change any field anywhere in the program (with a short delay so rapid typing doesn't cause constant flicker). If you ever want to run the optimizer manually from a terminal with the exact same settings, you can copy this text directly.

### 10.3 Run / Stop controls and status

- **Run button** — starts the optimizer as a background process. Before starting, the GUI:
  1. Validates that all fields can be assembled into a valid command (if not, an error dialog explains what is wrong).
  2. Confirms the optimizer script file actually exists on disk.
  3. Creates the working directory if it doesn't already exist.

  While running, the Run button is disabled, the Stop button becomes active, and a progress bar animates.

- **Stop button** — terminates the running optimizer process immediately. Only enabled while a run is in progress.

- **"Show report" button** — opens the generated text report file in your system's default text viewer. Only enabled once a run has finished successfully **and** the report file exists on disk.

- **"Show radiation pattern" button** — opens the radiation-diagram PNG in your system's default image viewer. Same enabling condition as above.

- **"Show PDF" button** — opens the generated PDF brochure in your system's default PDF viewer. Same enabling condition as above.

- **Status label** — shows the current state in words: idle, running, finished successfully, finished with an error/exit code, or stopped by the user.

### 10.4 Console and Resume panes

The bottom of the Run tab is split into two panes by a draggable divider: the **Console** on the left and the **Resume** on the right. Drag the divider to give either side the width you need.

#### 10.4.1 Console (left pane)

A scrolling, read-only text area that mirrors everything the optimizer process prints to its console, byte for byte, in real time, with simple colour-coding:

- **Red** — lines containing error-like keywords (error, failed, traceback).
- **Yellow** — lines containing warning-like keywords.
- **Green** — lines indicating success (saved, done, best, checkmarks).
- **Header colour** — section-separator lines.

A **Clear** button empties the console view (this does not affect any files already written).

#### 10.4.2 Resume (right pane)

The same output stream, digested into a live status page — what is running right now, on what data, with which variables, and how the previous pass ended. Nothing here is filtered out of the console; the Resume is an additional rendering of it. It redraws on a throttle (and ticks once a second so the clock keeps moving between output lines), so it costs nothing measurable even during a long NEC2 sweep. It contains four blocks:

1. **What is running now** — the current stage in words (starting up, sweeping in NEC2 or empirical mode, refining, expanding the window, UnUn search, radiation re-ranking, recomputing at the publishing density, convergence check, writing outputs, radiation diagrams, PDF, finished, failed) with a one-line explanation of what that stage does; the final status once the run ends; progress as *done/total* with a percentage; the candidate being evaluated (wire, counterpoise, band); the rate in candidates per second and an ETA — both hidden for the first couple of seconds, since a rate measured over a fraction of a second is noise — and the elapsed time.
2. **Variables in play** — the kind of pass, the wire and counterpoise windows with their current step sizes, the grid size as *n_wire × n_cp = pairs*, the evaluation engine, the segmentation density in use, the UnUn ratio (including the seed→current transition and which pass changed it), the retry counter, and the best candidate so far with its score.
3. **Result of the last pass** — pass number and kind, engine, the windows it covered, how many candidates it evaluated, how many were Pareto-optimal, its best geometry and score, a verdict (better / unchanged), and how long it took.
4. **Events** — running counts of warnings and errors, the most recent of each in full, and the list of output files written so far.

The Resume is rebuilt in the current GUI language like every other label, and keeps its scroll position across redraws.

### 10.5 What happens automatically when a run finishes successfully

The GUI automatically attempts to load the freshly-produced `optimizer_best.csv` into the **UnUn / Transmatch tab** (Section 11) in the background, so the matching-network calculators are pre-populated with the antenna's own impedances the moment the optimization finishes — you do not need to switch tabs and reload manually (though you still can, via the Reload button described in 11.1).

---

## 11. Tab 6 — UnUn / Transmatch

This tab is **independent of the optimizer run** — you can use it at any time, with any impedance data, whether or not you have ever run an optimization. It contains two sub-tabs.

### 11.1 Sub-tab: UnUn Toroid

Designs a wideband autotransformer (UnUn) wound on a ferrite or iron-powder toroid core to transform the antenna's feedpoint impedance toward a standard coax impedance (typically 50 Ω).

#### 11.1.1 "Antenna" section

- **Band selector (dropdown)** — once antenna data has been loaded (see below), lets you pick which band's impedance to work with; selecting a band auto-fills the fields below with that band's frequency, R, and X.
- **Reload button** — re-reads the `optimizer_best.csv` file from the configured output location, refreshing the band dropdown and data.
- **Export button** — writes the contents of **both** sub-tabs to a plain-text file (a Save-as dialog opens on the working directory with `unun_transmatch.txt` proposed): the UnUn results panel, the multi-band table, the Transmatch tap results, and the coil-construction text. If `matplotlib` is available, it also saves the Transmatch coil drawing next to it, as `<name>_transmatch.png`. When any of the loaded impedances came from the empirical model rather than NEC2, that caveat is written into the exported file as well, so the provenance travels with the numbers.
- **Status line** — indicates whether antenna data has been successfully loaded, and from where.
- Manually-editable fields (auto-filled by the band selector, but freely editable so you can explore "what if" numbers without re-running the optimizer):
  - **Frequency (MHz)** — default `7.100`.
  - **R_out, X_out (Ω)** — the antenna-side (output) impedance the UnUn must transform *from*. Defaults `450`, `150`.
  - **R_in, X_in (Ω)** — the coax-side (input) impedance the UnUn must transform *to*. Defaults `50`, `0`.

#### 11.1.2 "Core" section

- **Core type checkbox** — **checked (default) = "Core"**: the transformer is wound on a ferrite or powdered-iron **toroid**, the core dropdown below is active, and the magnetics results (saturation, core loss, power handling) are shown. **Unchecked = "Air"**: the transformer is built instead as an **air-core single-layer solenoid**; the toroid dropdown is disabled, the two coil-former fields below take its place, and the toroid-only results are hidden. The label next to the box always spells out which mode you are in.
- **Core dropdown** — choose the toroid part number from the built-in database (see [Section 19](#19-appendix-toroid-core-database-unun-tab) for the full list and specifications). Default: `FT-240-31`. Only active in Core mode.
- **Info line** — shows key specifications of the selected core (material, A_L, outer/inner diameter, height, effective area).
- **Coil former diameter (mm)** — default `50`. Only active in Air mode.
- **Space between turns (mm)** — default `1.0`. Only active in Air mode.
- **Ratio mode checkbox** — **checked (default) = "Compensate"**: the turns ratio is calculated automatically from R_out / R_in. **Unchecked = "Ratio"**: the UnUn is built for a **fixed** ratio that you type into the Ratio field below (e.g. 9, 49, 64); R_out / R_in then no longer set the turns ratio, though they still feed the reactance-compensation and multi-band sections.
- **Ratio field** — the fixed ratio used when the box above is unchecked. Default `9`.
- **Number of primary turns (Np)** — default `15`.
- **Wire diameter (mm)** — default `2.0`.
- A **constructional diagram** — of the wound toroid, or of the solenoid in Air mode — is drawn to the right of these fields. An **UPDATE DRAWING** button redraws it from the current settings, a **Save PNG…** button writes it wherever you choose (`unun_toroid.png` or `unun_solenoid.png` by default), and clicking the image itself opens a zoomed view. The drawing requires `matplotlib`; without it the panel shows a placeholder instead.

#### 11.1.3 "Results" panel

A scrollable, colour-coded, monospaced text panel reporting the computed UnUn design: turns ratio, transformed impedance, expected match quality, core loss/heating estimate, and any warnings (e.g., insufficient turns, or core near saturation or over-temperature).

#### 11.1.4 "Multi-band" section

Because a single UnUn design is used across every band the antenna covers, this section evaluates how well **one chosen UnUn** performs across **all** the bands loaded from the optimizer's CSV simultaneously — not just the single band selected above.

- **Auto** checkbox (checked by default) — when enabled, the program automatically searches for the best matching-network component value and turns ratio across all bands; when unchecked, you supply the values manually.
- **Type** dropdown — `L`, `C`, or `none`: whether the multi-band compensation network is inductive, capacitive, or absent.
- **Value** field — the manually-chosen component value (only used when Auto is unchecked).
- **Ratio** field — the manually-chosen UnUn turns ratio (only used when Auto is unchecked).
- **Z0** field — the reference/target impedance for the multi-band evaluation. Default `50` Ω.
- **Results table** — one row per band, showing: band name, frequency, R, X, compensating reactance, resulting input impedance, VSWR without and with compensation, and the delta between them.

### 11.2 Sub-tab: Transmatch

Designs a tapped-coil (autotransformer-style) matching network — a classic "Transmatch" or "ATU" — as an alternative or complement to the UnUn.

#### 11.2.1 "Global" section

| Field | Meaning | Default |
|---|---|---|
| Z0 | Reference/target impedance | `50` Ω |
| Wire diameter | Coil wire diameter | `1.0` mm |
| Core / form diameter | Diameter of the coil former | `50` mm |
| Winding spacing | Spacing between turns | `1.0` mm |
| Reference winding (turns) | Number of turns used as the Z0 reference tap | empty (blank) |
| **Auto reference** checkbox | When checked, the reference winding length above is computed automatically instead of manually entered | checked by default |

> **Important engineering note built into this tool:** a tapped/wound coil only behaves as an ideal autotransformer *below* its own self-resonant frequency (SRF). Above the SRF, the winding becomes capacitively dominated and the simple turns-ratio model no longer applies — yet earlier, naive designs could silently report a plausible-looking (but wrong) VSWR for a band that actually sits above the winding's SRF. This tool checks the winding's SRF and will shorten/adjust the automatic reference winding until the SRF clears the highest requested band by a safety margin (1.5×), and it flags rows where the winding's own reactance is not comfortably larger than the antenna impedance (a sign the tap is being "loaded" by the coil rather than cleanly transforming through it).

#### 11.2.2 "Taps" table

An editable table of up to **11 rows**, each representing one band you want the Transmatch to cover, with columns: **Tap #**, **Band**, **Frequency (MHz)**, **R (Ω)**, **X (Ω)**, and an **Active** checkbox to include/exclude that row from the calculation. Three rows are pre-populated with example workbook defaults (40 m / 20 m / 10 m) so the page is usable even before you have ever run the optimizer:

| # | Band | Freq (MHz) | R (Ω) | X (Ω) |
|---|---|---|---|---|
| 1 | 40m | 7.150 | 75 | −12 |
| 2 | 20m | 14.170 | 67 | 23 |
| 3 | 10m | 28.000 | 45 | 10 |

A **constructional diagram** of the coil and its taps is drawn alongside this table and updates live.

#### 11.2.3 "Winding" results table

For every active tap row: band, frequency, R, realised R (after tap quantisation), the resulting error, turns from the reference, total/delta turns, wire length, DC resistance, cumulative length, resulting impedance and phase, VSWR, return loss, mismatch loss, and reflected power fraction.

#### 11.2.4 "Compensation" results table

For every active tap row, thirteen columns: band, frequency, R, X, the transformed reactance **X′** seen at the tap, the **SWR without compensation**, the equivalent **series** inductor and capacitor values, the equivalent **shunt** inductor and capacitor values, the **resistance seen after the shunt branch**, the **SWR of the shunt solution (real)**, and finally the **SWR of the series solution allowing a 5 % residual** — that last column is a *5 percent* tolerance on the residual reactance, not a 5 Ω one.

Series and shunt are two different answers to the same problem, and the table deliberately shows both. A single *shunt* reactance cancels the susceptance of the transformed load, which leaves the port looking at (R′² + X′²)/R′ rather than R′ — a good match only while X′ stays small. Above a residual SWR of about 1.5 the shunt branch should be read as reactance cancellation rather than as an alternative to the series branch, whose figures are the ones the tap table publishes.

#### 11.2.5 "Coil construction" text panel

A monospaced, colour-coded summary of exactly how to physically wind the coil: total turns, where to place each tap, wire length required, and any warnings (insufficient turns, unrealistic tap spacing, etc.).

#### 11.2.6 Build guidance note

A short reminder/label at the bottom of the sub-tab with practical construction guidance.

---

## 12. Header bar and global controls

### 12.1 Optimizer script path

At the very top of the window, below the header, a row lets you specify **which script file** the GUI should actually run when you press "Run" on the Run tab.

- **Field:** filesystem path to the `Long_Wire_Antenna.py` script.
- **Default:** the path of the script that was used to launch the GUI itself.
- **Browse button:** opens a file-picker dialog.

You would only need to change this if you keep multiple versions of the script and want to switch which one the GUI drives, without restarting the GUI from a different copy.

### 12.2 Font size controls

Two small buttons (`−` and `+`) next to a numeric label let you shrink or enlarge the GUI's font size on the fly, useful for high-resolution displays or visual comfort. The current size is shown between the two buttons.

### 12.3 Language switch

A button in the header toggles the **GUI's own display language** between English, Spanish, and Italian. This is separate from:

- The "Optimizer language" setting on the Band/Source tab (Section 6.7), which controls the language of the **optimizer's own console output and generated report/PDF**, not the GUI's menus and labels.
- The `--lang` CLI flag, which affects only command-line runs of the script without the GUI.

Switching languages relabels every tab, field, dropdown, and hint text in place, without losing anything you have typed — including the Wire Material dropdown, which is internally tracked by its canonical (English) value regardless of what label is currently displayed, so the underlying command line is never affected by a language switch.

---

## 13. Understanding the output files

### 13.1 The text report (`optimizer_report.txt`)

It contains, in general order:

1. An execution summary: evaluated bands, active bands, evaluation mode, geometry, ground, conductor and segmentation.
2. A ranked table of the top-N candidates (per the "Top N" setting), each with its wire length, counterpoise length, per-band R/X/VSWR, and its aggregate score.
3. The Pareto-optimal set: candidates for which no other candidate is at least as good on *every* band simultaneously — this is the set of genuine trade-offs, useful when you might be willing to sacrifice performance on one band to gain it on another.
4. A plain-language interpretation of the winning candidate, including any warnings (e.g., "the wire length may need to be longer — it landed at the edge of the search window").
5. When pattern data are available, a table of **maximum gain and gain at the target take-off angle (TOA)** for each active band, plus high-TOA warnings.
6. A per-band table containing antenna-side impedance (`R_ant`, `X_ant`) and transmitter-side impedance (`R_tx`, `X_tx`), VSWR and data source.
7. If `--converge` (the "Re-check convergence" checkbox) was used, a short section reporting how much R and X still moved at 0.5× and 2× the working segmentation density (only the 0.5× arm with `--fast-run`). The header of that section always states which factors were actually run.
8. UnUn analysis: selected ratio, standard-ratio sweep, continuous optimum and best ratio per band.

The report can also include search-boundary, geometry, convergence and result-quality warnings.

### 13.2 The scatter/plot PNG (`optimizer_plot.png`)

A heat-map/scatter representation of the entire search grid (wire length × counterpoise length), colour-coded by aggregate score, plus bar charts of VSWR achieved on each active band by the winning candidate.

### 13.3 The CSV (`optimizer_best.csv`)

Machine-readable per-band results for the *winning* candidate only, one row per band. A `long-wire` run writes these twenty columns:

| Column | Meaning |
|---|---|
| `band` | Band name as given on the command line |
| `freq_mhz` | Centre frequency used for this band |
| `active` | `YES` / `NO` — whether this band contributed to the score |
| `lambda_half_m`, `lambda_qtr_m` | Half- and quarter-wavelength at that frequency, metres |
| `wire_len_m` | Winning radiator length |
| `L_over_lhalf` | Radiator length expressed in half-wavelengths |
| `R_wire_ohm`, `X_wire_ohm` | **Antenna-side feedpoint impedance** — the numbers a matching network is sized from |
| `R_wire_source` | `nec2` or `empirical` — where the two columns above actually came from, per band |
| `vswr_no_cp` | Antenna-side VSWR referred to 50 Ω with no UnUn |
| `vswr_no_cp_source` | Always `empirical` — stated per row so a mixed-provenance row is self-describing |
| `vswr_with_cp` | Transmitter-side VSWR after the UnUn (blank for inactive bands) |
| `Z_eff_ohm` | Magnitude of the feedpoint impedance |
| `unun_ratio` | The UnUn ratio the evaluation used |
| `avoidance_score`, `quality_rating` | How comfortably the geometry sits away from an awkward resonance class, and its star rating |
| `cp_len_m`, `cp_height_m`, `num_radials` | Winning counterpoise length, antenna height, radial count |

For an **off-centre-fed dipole or Carolina Windom** run (`--antenna-type ocfd|carolina-windom`) the file carries **six additional columns** after those twenty, so a consumer can tell the two schemas apart without guessing from the numbers: `antenna_type`, `total_len_m`, `offset_frac`, `short_arm_m`, `long_arm_m` and `vert_len_m` (the last is non-zero only for a Carolina Windom). In that schema `wire_len_m` and `cp_len_m` are the **long and short arms** of the dipole, not a radiator and a counterpoise — read `antenna_type` before interpreting them.

`R_wire_source` is worth a second look before you wind anything: it is derived from the provenance the report and PDF print, not from the mere presence of a number, so a run made without `nec2c` can never claim `nec2` here. **This is the file the UnUn/Transmatch tab automatically reads** to pre-populate its band dropdown and tap table — and the tab uses this very column to warn you when a matching network is about to be sized from empirical estimates.

### 13.4 The NEC2 deck (`best_antenna.nec`)

A NEC2 input file describing the winning geometry at the final segmentation density, including RP request cards for active bands. It is intended to be loaded into a compatible NEC2 implementation; exact execution behaviour can vary between NEC2 engines.

### 13.5 Radiation diagrams (`radiation_diagrams.png`)

These are generated **only when the final evaluation uses NEC2 and a NEC2 binary is available**. They show calculated patterns for the active bands. In empirical mode this file is not generated because the empirical model does not calculate a NEC2 radiation pattern.

Elevation and/or azimuth radiation pattern plots for the winning antenna, one per active band.

### 13.6 Construction drawing (`antenna_construction.png`)

A dimensioned diagram intended to be used directly as a build reference: wire lengths, feedpoint height, slope angles, etc.

### 13.7 PDF brochure (`antenna_brochure.pdf`)

The program attempts to generate this one-page summary after a successful run with a valid candidate. It requires **`reportlab`**, not `matplotlib`. The PDF can include the construction drawing and, when available, NEC2 radiation diagrams. If `reportlab` is not installed, the program reports the problem and skips the PDF; the run and the other outputs do not depend on `reportlab`.

A single-page combined summary — key numbers, the winning geometry, and the construction drawing — suitable for printing or filing alongside your station notes. Embedding the construction/radiation images into the PDF additionally uses the **Pillow (`PIL`)** package if it is installed; if Pillow is missing, the brochure is still generated, but the image section is replaced with a "(construction diagram unavailable)" placeholder instead of failing outright.

### 13.8 Important limitations of the outputs and the modelling

- `matplotlib` is required for the search-space plot, the construction drawing, and the radiation diagrams.
- Radiation diagrams are NEC2-only. Empirical mode can produce optimisation numbers, but not a physically simulated radiation pattern.
- The exported NEC2 deck is a model, not a construction guarantee. Verify the real antenna with an analyzer/VNA and account for coax common-mode currents, supports, nearby conductors, real ground, and the actual installation geometry.
- The `ground-rod` return path in NEC2 is implemented as a galvanic connection to **perfect ground (GN 1)**. It is not a model of a real ground rod's impedance. The program switches the ground model to perfect for that case and logs a warning — this overrides whatever you set in `--ground-model` / the Ground model section for that run.
- The matching-network calculators (UnUn and Transmatch) use engineering models and idealised components. Their values are starting points for building and tuning, not measured values, and are not a substitute for final RF verification.

---

## 14. The command-line interface (CLI) — full reference

Every one of these flags corresponds to a GUI control described above; this table is the authoritative reference for exact flag names, types, and defaults, useful if you want to run the tool from scripts, cron jobs, or a terminal instead of the GUI.

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--bands NAMES` | string (comma list) | *(none — required)* | Comma-separated band names. |
| `--freqs MHZ` | string (comma list) | *(none)* | Centre frequencies in MHz, one per band. Optional for recognized bands, required for custom names. |
| `--wire-len M` | float | *(none — required)* | Starting wire length in metres (search-window centre). |
| `--cp-len M` | float | *(none — required unless `--no-counterpoise`)* | Starting counterpoise length in metres (search-window centre). |
| `--active-bands BANDS` | string (comma list) | all bands | Which bands to score; omit to score all of `--bands`. |
| `--mode {empirical,nec2,auto}` | choice | `auto` | Evaluation engine. |
| `--nec2c PATH` | path | *(auto-discovered)* | Explicit path to the `nec2c` binary. |
| `--margin M` | float | `2.0` | Search radius (metres) around the starting lengths. |
| `--wire-min M` | float | starting − margin | Minimum wire length to search. |
| `--wire-max M` | float | starting + margin | Maximum wire length to search. |
| `--wire-step M` | float | `0.25` | Wire length increment. |
| `--cp-min M` | float | starting − margin | Minimum counterpoise length to search. |
| `--cp-max M` | float | starting + margin | Maximum counterpoise length to search. |
| `--cp-step M` | float | `0.25` | Counterpoise length increment. |
| `--height M` / `--antenna-height M` | float | `8.0` | Feedpoint height above ground (shared by radiator and counterpoise). |
| `--wire-slope-end-height M` | float | *(unset = horizontal)* | Height of the radiator's far end. `0.0` = touches ground. Forces NEC2 mode. |
| `--cp-end-height M` | float | *(unset = level with antenna height)* | Height of the counterpoise's far end. |
| `--no-counterpoise` | flag | off | Model the antenna without a counterpoise. |
| `--no-cp-return {ground-rod,coax-stub,reject}` | choice | `ground-rod` | RF return-path model when there is no counterpoise. |
| `--cp-stub-len M` | float | `2.0` | Coax-braid stub length, used only with `--no-cp-return coax-stub`. |
| `--ground-model {sommerfeld,perfect}` | choice | `sommerfeld` | Ground electromagnetic model. |
| `--ground-cond S/M` | float | `0.005` | Ground conductivity, S/m. |
| `--ground-diel EPS` | float | `13.0` | Ground relative permittivity. |
| `--feed-model {straddle,junction}` | choice | `straddle` | Where the NEC-2 source card sits relative to the radiator/counterpoise junction. See [8.7](#87-feed-model-section). Forced to `junction` for `carolina-windom`. |
| `--antenna-type {long-wire,ocfd,carolina-windom}` | choice | `long-wire` | Antenna topology. The dipole types turn `--wire-len` / `--cp-len` into the **long and short arms** of a dipole. See [6.1](#61-antenna-type-section). |
| `--total-len M` | float | *(unset)* | Dipole types only: total length of **both** arms. With `--offset` it derives `--wire-len` and `--cp-len` — the usual way to specify an OCFD. |
| `--offset F` | float | `0.3333` | Dipole types only: short arm ÷ total length. Valid range `0.10`–`0.49`. |
| `--offset-min F` | float | `0.20` | Dipole types only: low end of the offset sweep. |
| `--offset-max F` | float | `0.45` | Dipole types only: high end of the offset sweep. |
| `--offset-step F` | float | `0.01` | Dipole types only: offset sweep step. |
| `--balun-ratio N` | `auto` or choice | `auto` | Dipole types only: `auto`, or one of `2` / `4` / `6` / `9`. A balun ratio is a hardware choice, so the search is restricted to buildable values. Rejected for `long-wire`, whose UnUn ratio is searched automatically. |
| `--balun-kind {guanella,ruthroff}` | choice | `guanella` | Transmission-line balun topology. Guanella is a current balun, correct for a balanced feed across all of HF. |
| `--cw-vert-len M` | float | `3.0` | Carolina Windom only: vertical radiator length between the balun and the line isolator (minimum `0.5` m). |
| `--cw-isolator-z R,X` | two floats | *(unset = ideal open)* | Carolina Windom only: model the line isolator as a finite series impedance, e.g. `1000,2000`. |
| `--balun-core CORE` | choice | `FT-240-31` | Toroid used for the balun **and** the line isolator, from the core database in [Section 19](#19-appendix-toroid-core-database-unun-tab). |
| `--balun-turns N` | int | `10` | Turns per transmission line on the balun. |
| `--feed-choke` | flag | off | Also design a feedline common-mode choke. Always designed for `carolina-windom`, where it *is* the line isolator. |
| `--match-model {ideal,real}` | choice | `ideal` | VSWR through the matching device: `ideal` divides R and X by the ratio; `real` also applies the finite magnetising reactance from the balun design. |
| `--wire-diameter MM` | float | `2.0` mm | Conductor diameter in millimetres. |
| `--wire-material {...}` | choice | `copper` | One of: `copper`, `aluminium`, `aluminum`, `brass`, `silver`, `steel`, `perfect`. |
| `--wire-conductivity S/M` | float | *(from material)* | Manual override of conductor conductivity. |
| `--segs-per-half-wave N` | int | *(45 sweep / 180 fine)* | Overrides both the sweep and final-run segmentation densities. Clamped to `5`–`400`. |
| `--fast` | flag | off | Sweep at coarse (21 seg/half-wave) density; the winner is still recomputed fine regardless. Sets segmentation only — it is not `--fast-run`. |
| `--fast-run` | flag | off | The whole acceleration policy: concurrent `nec2c` solves, coarse sweep segmentation, a shorter refined TOP-N tail (≤ 5), a shorter radiation re-rank shortlist (≤ 3), and only the 0.5× arm of `--converge`. Published impedances stay at the fine density. See [10.1](#101-miscellaneous-section). |
| `--jobs N` / `-j N` | int | `1` (serial); one per core capped at 16 under `--fast-run` | Worker threads for independent `nec2c` decks (sweep, fine refinement, radiation re-ranking). Honoured in **both** normal and `--fast-run` mode — parallelism alone changes no published number. |
| `--converge` | flag | off | Re-run the winner at 0.5× and 2× the working segmentation (0.5× only with `--fast-run`) and report how far R/X still move. NEC2 mode only. |
| `--target-toa DEG` | float | `25.0` | Elevation angle (degrees) at which the gain bonus is evaluated. |
| `--gain-weight W` | float | `0.20` | Score weight per dB of gain at the target take-off angle. |
| `--rerank-top N` | int | `6` | Number of top candidates re-simulated with a full radiation pattern for gain-based re-ranking. |
| `--top-n N` | int | `20` | Number of candidates shown in the report. |
| `--out-txt FILE` | path | `optimizer_report.txt` | Text report filename. |
| `--out-png FILE` | path | `optimizer_plot.png` | Scatter plot filename. |
| `--out-csv FILE` | path | `optimizer_best.csv` | Best-candidate CSV filename. |
| `--out-nec FILE` | path | `best_antenna.nec` | Exported NEC2 deck filename. |
| `--out-radiation FILE` | path | `radiation_diagrams.png` | Radiation-pattern PNG filename. |
| `--out-construction FILE` | path | `antenna_construction.png` | Construction-drawing PNG filename. |
| `--out-pdf FILE` | path | `antenna_brochure.pdf` | PDF brochure filename. |
| `--retry N` | int | `0` | Automatically re-run the sweep up to N extra times — shifting the window outwards if the winner sits at a search-window edge, or refining it if `--test-window` is given. |
| `--test-window` | flag | off | Turn each retry into a *refinement* (bounding box of the top candidates, both grid steps halved, floor `0.01` m) instead of an outward shift. Does nothing without `--retry N` > 0. See [7.10](#710-test-all--test-window-checkbox-and-refine-top-n). |
| `--refine-top N` | int | `5` | How many top candidates define the refined window. Must be ≥ 1; only used with `--test-window`. |
| `--no-interactive` | flag | off | Fail on missing required inputs instead of prompting interactively. |
| `--quiet` / `-q` | flag | off | Suppress verbose console output. |
| `--lang {en,es,it}` | choice | auto-detected from system locale | Interface/report language. |
| `--gui` | flag | off | Launch the graphical interface instead of running from the command line. |

### 14.1 Example command lines

**Simplest possible run** (known bands, defaults for everything else):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

**Custom/unknown bands** (frequencies required):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

**Evaluate three bands but score only two of them:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

**Antenna with no counterpoise, using a coax stub as the return path:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 21.0 \
    --no-counterpoise --no-cp-return coax-stub --cp-stub-len 3.0
```

**Force full NEC2 simulation with an explicit binary path, and check convergence:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --nec2c /usr/local/bin/nec2c --converge
```

**A large NEC2 sweep on a multi-core machine, accelerated:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --fast-run --jobs 8
```

**An off-centre-fed dipole (Windom), specified the usual way — total length plus offset:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,10m --antenna-type ocfd \
    --total-len 41.0 --offset 0.3333 --balun-ratio 4
```

**A Carolina Windom with a deliberately imperfect line isolator, to see what it costs:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,10m --antenna-type carolina-windom \
    --total-len 41.0 --cw-vert-len 3.0 --cw-isolator-z 1000,2000 --converge
```

**Zoom in on a promising region instead of widening the search:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 20.5 --cp-len 5.0 \
    --wire-min 19.5 --wire-max 21.5 --cp-min 4.0 --cp-max 6.0 \
    --retry 3 --test-window --refine-top 5
```

---

## 15. Typical workflows, step by step

### 15.1 First-time quick design (GUI)

1. Launch: `python src/Long_Wire_Antenna.py --gui`.
2. On **Band / Source**: type your bands (e.g. `40m,20m,15m`), leave Frequencies blank (they're recognized bands), set Wire length and Counterpoise length to your best rough guess.
3. On **Physics**: leave Evaluation mode on `auto`. If you have `nec2c` installed, click **Auto-detect** to confirm it's found.
4. On **Search Range**: leave the margin at its default `2.0` m for a first pass.
5. On **Output Files**: confirm or change the working directory.
6. On **Run**: review the command preview, click **Run**, and watch the console.
7. When finished, click **Show report** to see the ranked results, and **Show radiation pattern** to see the pattern plots.

### 15.2 Refining a design that hit a search boundary

If the report warns that the wire (or counterpoise) length "may need to be longer/shorter" because the winner sat at the edge of the search window:

- Either manually widen `wire-min`/`wire-max` (or `cp-min`/`cp-max`) on the **Search Range** tab and re-run, **or**
- Set **Maximum retries** (Section 7.8) to a small number (e.g. `2`) before the first run, and let the program shift the window automatically.

### 15.3 Getting a trustworthy, build-ready design

1. Run once in `auto`/`empirical` mode with the `fast` segmentation setting for a quick overview of the landscape.
2. Once you have a promising region, switch **Evaluation mode** to `nec2` and **Segmentation** to `fine` (the default), and re-run with a *narrower* search window centred on the promising region — this gives you physically accurate, high-density results without paying the full cost of a NEC2 fine sweep over the whole original range.
3. Enable **Re-check convergence** and confirm the report shows R drifting by well under the ~3% flag threshold between segmentation densities.
4. Use the exported `best_antenna.nec` file and the construction drawing PNG as your actual build references.

### 15.4 Designing the matching network for a finished antenna design

1. After a successful run, switch to the **UnUn / Transmatch** tab — it will already be pre-loaded with the winning antenna's per-band impedances.
2. On the **UnUn Toroid** sub-tab, pick a band from the dropdown to inspect a single-band match, or use the **Multi-band** section (with **Auto** checked) to have the program search for the best UnUn design across all your bands at once.
3. Alternatively (or additionally), use the **Transmatch** sub-tab to design a tapped-coil matching network instead of, or in combination with, the UnUn.

---

## 16. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| GUI won't start; message about `tkinter` | Tkinter not installed | `sudo apt install python3-tk` (or your distro's equivalent), then retry. |
| Error about a missing `--freqs` value | You used a custom/unrecognized band name without a matching frequency | Fill in the Frequencies field with one MHz value per band, in the same order as your Band(s) list. |
| Results look suspiciously good / reactance sign seems wrong | You are on the `fast` (21 seg/half-wave) segmentation setting | Switch to `fine` (default) before trusting any number for a real build; `fast` is pattern-grade only. |
| "NEC2 mode requested but no binary found" (or similar) | `nec2c` is not installed, or not discoverable automatically | Install `nec2c`, or type its full path into the **NEC2 binary** field on the Physics tab and/or click **Auto-detect**. |
| On Windows, `nec2c` is not found even though the installer succeeded, and you launched the script yourself instead of via the Desktop shortcut | The script's hardcoded `Program Files\OpenNEC` fallback looks for a file named `onec.exe`, but the installer mirrors the engine there as `nec2c.exe` — a known filename mismatch, see [§3.4](#34-locating-the-nec2c-binary) | Use the Desktop shortcut (`run_gui.bat`) instead, which sets `$NEC2C` directly and is unaffected; or pass `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"` / type that path into the **NEC2 binary** field; or set `$NEC2C` yourself. |
| Counterpoise-related fields are greyed out and won't accept input | "Use counterpoise" is unchecked | Check the "Use counterpoise" box on the Search Range tab if you do want a counterpoise. |
| The "No-counterpoise return path" section is greyed out | "Use counterpoise" is checked | This section only applies when there is *no* counterpoise; it activates automatically when you uncheck "Use counterpoise". |
| The winning wire/CP length equals the min or max of the search window | The true optimum may lie outside the searched range | Widen `wire-min`/`wire-max` (or `cp-min`/`cp-max`), or set **Maximum retries** > 0 and re-run. |
| UnUn/Transmatch tab shows "no data loaded" | No optimizer run has produced a CSV yet, or it's in a different folder than expected | Run the optimizer first, or click the **Reload** button on the UnUn sub-tab after pointing the Output Files' working directory at the folder containing `optimizer_best.csv`. |
| A Transmatch band shows a suspicious VSWR that doesn't seem to track the antenna's real reactance | The winding may be operating above its own self-resonant frequency (SRF) | Check the Winding results table for an SRF warning; with **Auto reference** checked, the tool already shortens the reference winding to keep the SRF above your highest band by margin, but a manually-entered reference winding can still be too long. |
| No PNG output is produced | `matplotlib` (or, for radiation diagrams specifically, `numpy`) is not installed | `pip install matplotlib numpy`, then re-run. |
| PDF is generated but a diagram section says "(unavailable)" | `Pillow` (`PIL`) is not installed | `pip install pillow`, then re-run — this does not require redoing the search, since it only affects PDF image embedding. |
| `--jobs` seems to be ignored and the run is still serial | Either you are on a version older than the one this manual describes (where `--jobs` was forced to 1 without `--fast-run`), or the GUI's **Jobs** field is blank — blank means serial in normal mode | Type a worker count into **Jobs** on the Run tab, or pass `--jobs N` explicitly. In current versions the flag works with or without `--fast-run`. |
| `--offset`, `--total-len` or `--balun-ratio` is rejected with an error | Those options apply only to the off-centre-fed types | Add `--antenna-type ocfd` (or `carolina-windom`). The program rejects the combination on purpose rather than ignoring the flag and reporting a different antenna. |
| The report says the feed model was forced to `junction` | You selected `carolina-windom`, which has three conductors at the feed node, so the straddle feed is geometrically impossible | Expected, not an error. Add `--converge` for that run and check how far R and X still move before sizing anything. |
| `--test-window` appears to do nothing | Refinement happens *on a retry*, and the retry budget defaults to zero | Set **Maximum retries** (`--retry N`) to at least 1. Refinement also stops once both grid steps reach the `0.01` m floor. |
| GUI's command preview shows something unexpected | A field was left with stale text, or a checkbox state doesn't match what you intended | Everything shown in the command preview box is exactly what will be executed — inspect it before running, and adjust the corresponding field. |

---

## 17. Glossary

- **VSWR (Voltage Standing Wave Ratio):** a measure of load mismatch relative to the feedline characteristic impedance. The minimum possible value is **1.0** (perfect match); values above 1.0 indicate increasing mismatch. VSWR cannot be below 1.0.
- **Feedpoint impedance (R + jX):** the resistance (R) and reactance (X), in ohms, that the antenna presents to its feedline at the point it is fed.
- **Counterpoise:** a wire (or set of wires) acting as the "other half" of the antenna circuit in an end-fed / unbalanced configuration, in place of a full ground plane or radial system.
- **NEC2 / `nec2c`:** the Numerical Electromagnetics Code version 2, a widely used method-of-moments antenna simulation standard; `nec2c` is a common open-source C implementation of it.
- **Segmentation (segs/half-wave):** how finely a NEC2 model subdivides each wire for calculation; more segments generally means more accuracy (up to a point) at the cost of computation time.
- **Sommerfeld-Norton ground model:** a physically realistic ground model in NEC2 that accounts for finite ground conductivity and permittivity, as opposed to assuming a perfect conductor.
- **Pareto-optimal set:** the subset of candidates for which no other candidate is at least as good on every scored metric (here, every active band) simultaneously — the genuine set of trade-offs available.
- **UnUn (Unun):** an "unbalanced-to-unbalanced" transformer, typically wound on a ferrite/iron-powder toroid, used to transform an antenna's feedpoint impedance toward the coax's characteristic impedance.
- **Transmatch:** a manually- or automatically-tuned matching network (often a tapped coil with capacitors), used between the feedline and the antenna (or station equipment) to present the transmitter with a good match.
- **Toroid core:** a ring-shaped magnetic core (ferrite or powdered iron) used to wind RF transformers/chokes; different "mixes" and sizes trade off frequency range, loss, and power handling.
- **Take-off angle (TOA):** in this program, the elevation angle above the horizon at which **gain is evaluated**. It is not necessarily the antenna's maximum-radiation angle. For gain re-ranking, the program takes the maximum gain over azimuth at that fixed elevation. Lower angles can be useful for some long-distance links, but the appropriate TOA depends on propagation and the link objective.

---

## 18. Appendix: known amateur radio bands

The following band names are recognized automatically, with their built-in centre frequency (MHz) — you do not need to supply `--freqs` / the Frequencies field for any of these:

| Band | Centre frequency (MHz) |
|---|---|
| 2200m | 0.1365 |
| 630m | 0.475 |
| 160m | 1.850 |
| 80m | 3.650 |
| 60m | 5.350 |
| 40m | 7.100 |
| 30m | 10.125 |
| 20m | 14.175 |
| 17m | 18.118 |
| 15m | 21.225 |
| 12m | 24.940 |
| 10m | 28.500 |
| 6m | 50.200 |
| 4m | 70.200 |
| 2m | 144.200 |
| 70cm | 432.100 |
| 23cm | 1296.200 |

Any band name not on this list is treated as **custom**, and you must supply its centre frequency explicitly.

---

## 19. Appendix: toroid core database (UnUn tab)

Cores available in the **Core** dropdown of the UnUn Toroid sub-tab, with their key specifications (AL in nH per turn², outer/inner diameter and height in mm, effective cross-sectional area Ae in cm², and an approximate recommended RF flux-density ceiling B_sat in mT):

| Core | Material | AL (nH/N²) | OD (mm) | ID (mm) | H (mm) | Ae (cm²) | B_sat (mT, approx.) |
|---|---|---|---|---|---|---|---|
| FT-114-43 | Ferrite Mix 43 | 510.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-43 | Ferrite Mix 43 | 885.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-43 | Ferrite Mix 43 | 1075.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-31 | Ferrite Mix 31 | 800.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-31 | Ferrite Mix 31 | 1390.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| **FT-240-31** (default) | Ferrite Mix 31 | 1800.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-52 | Ferrite Mix 52 | 175.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-52 | Ferrite Mix 52 | 225.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-52 | Ferrite Mix 52 | 300.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-61 | Ferrite Mix 61 | 79.3 | 29.0 | 19.0 | 7.5 | 0.38 | 236 |
| FT-140-61 | Ferrite Mix 61 | 140.0 | 35.6 | 22.9 | 12.7 | 0.63 | 236 |
| FT-240-61 | Ferrite Mix 61 | 170.0 | 61.0 | 35.6 | 12.7 | 1.52 | 236 |
| T-130-2 | Iron Powder Mix 2 | 11.0 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-2 | Iron Powder Mix 2 | 12.0 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |
| T-130-6 | Iron Powder Mix 6 | 9.6 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-6 | Iron Powder Mix 6 | 11.6 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |

> **Note on core loss modelling:** at HF, a ferrite transformer's practical power limit is set by **core heating**, not by magnetic saturation (the saturation limit only becomes relevant at much lower frequencies for a given turns count). The tool's loss model uses each material's complex permeability (µ′, µ″) at the working frequency to estimate a parallel loss resistance, and from it a continuous-power limit based on the core's surface area and an assumed allowable temperature rise. These figures are engineering approximations (good to roughly a factor of 1.5), not datasheet-grade numbers — treat the UnUn tab's power-handling estimates as a sanity check, not a certified rating.

---

*End of manual.*
