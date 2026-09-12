<p align="center">
  <img src="https://github.com/hiperiondev/Long_Wire_Antenna/raw/main/images/logo.png" width="150">
</p>

<div align="center">

# NEC2 Antenna Length Optimizer

**Find the wire length (and counterpoise length) that gives the lowest VSWR across every ham band you care about — backed by real NEC-2 method-of-moments simulation, not guesswork.**

Author: **LU3VEA** · License: **CC0 1.0** (public domain, script and documentation only — see [Third-party licensing note](#third-party-licensing-note)) · Platform: Windows installer, Linux AppImage, or cross‑platform Python script

</div>

---

## What it does

If you're building a multi-band end-fed or sloping wire antenna, the eternal question is: *how long should the wire be?* This tool answers that question empirically instead of by rule of thumb.

It sweeps a grid of candidate **radiator lengths** and **counterpoise lengths** *(the counterpoise is the secondary wire or ground reference that provides the RF return path for an end-fed antenna — see [Glossary](#glossary))*, and for every combination:

1. Generates a NEC-2 `.nec` input deck (sloping radiator + sloping counterpoise, with ground and wire-material modeling).
2. Runs [`nec2c`](https://www.nec2.org/) to simulate the antenna at the center frequency of each of your target bands.
3. Parses the impedance results and computes an **aggregate VSWR score** across all active bands, with penalties for bands that miss your target take-off angle or gain.
4. Tracks the **Pareto-optimal** candidates (best trade-offs between the bands, rather than a single band winning at the expense of the others).

At the end you get a ranked report, a scatter plot of the whole search space, a CSV of the best candidates, a ready-to-simulate `.nec` file for the winner, radiation-pattern diagrams, a construction diagram, and an optional one-page PDF "antenna brochure" summarizing the build.

It can also recommend the best standard **UnUn transformation ratio** (e.g. 9:1, 4:1, 1:1 — an UnUn is an "unbalanced-to-unbalanced" impedance-transforming feedline matching transformer; see [Glossary](#glossary)) for your feedline, and warn you when no ratio removes the impedance mismatch cleanly enough on a given band.

---

## Highlights

- 🎯 **Multi-band optimization** — optimize for any combination of bands simultaneously (e.g. `40m,20m,17m,15m,10m`), not just one.
- 📡 **Real NEC-2 physics** — uses method-of-moments simulation (`nec2c`) rather than closed-form approximations, including realistic ground models (Sommerfeld/Norton or perfect ground).
- ⚡ **Fast empirical mode** — an `--mode empirical` fallback using closed-form formulas when you don't have `nec2c` installed or just want a quick estimate; `--mode auto` picks the best available.
- 🌍 **Multilingual CLI** — full English, Spanish, and Italian interfaces, auto-detected from your system locale (or force with `--lang`).
- 🖥️ **GUI mode** — a Tkinter front-end (`--gui`) for anyone who'd rather not touch a terminal.
- 🔧 **Physically realistic modeling** — configurable wire diameter and material (copper, aluminium, brass, silver, steel, or lossless "perfect"), sloped or horizontal wire geometry, real-world height and ground parameters.
- 🔌 **UnUn ratio advisor** — evaluates standard transformation ratios against the raw antenna impedance and tells you which one gets you closest to a clean match on every band.
- 📊 **Rich output** — ranked text report, scatter plot (PNG), CSV of top candidates, best-candidate `.nec` deck, radiation-pattern diagrams, construction diagram, and a PDF brochure.
- 🪟 **One-click Windows installer** — bundles Python, `nec2c`, and all dependencies so non-technical hams can get running without touching a package manager.
- 🐧 **One-click Linux AppImage** — same idea for Linux, no `pip install` or package manager required.

There is currently **no packaged installer for macOS**. macOS users should use [Option C](#option-c--run-the-python-script-directly-windowsmacoslinux) below.

---

## Repository contents

| File / folder                                                | Description                                                                                                                                                |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/Long_Wire_Antenna.py`                                    | The optimizer itself — a self-contained Python script (CLI + optional GUI). This is the file you run directly for [Option C](#option-c--run-the-python-script-directly-windowsmacoslinux). |
| `Setup_Long_Wire_Antenna.exe`                                 | Prebuilt, self-contained Windows installer (embeds `Long_Wire_Antenna.py`, `nec2c.exe`, the launcher, and the post-install script — nothing else needs to sit alongside it).                                            |
| `Long_Wire_Antenna-x86_64.AppImage`                            | Prebuilt Linux AppImage — the one-click equivalent of the Windows installer for x86\_64 Linux.                                                              |
| `documentation/Long_Wire_Antenna_Manual_EN.md`                 | Extended English user manual.                                                                                                                               |
| `documentation/Long_Wire_Antenna_Manual_ES.md`                 | Extended Spanish user manual.                                                                                                                               |
| `documentation/Long_Wire_Antenna_Manual_IT.md`                 | Extended Italian user manual.                                                                                                                               |
| `images/logo.png`, `images/icon.png`                           | Project logo (shown at the top of this README) and application icon (used for the Windows installer/shortcuts and the Linux AppImage).                     |
| `others/build_windows_installer.sh`                            | Build script that compiles `Setup_Long_Wire_Antenna.exe` from the sources in `others/windows_installer/` using NSIS (`makensis`). Run on Fedora/RHEL or Debian/Ubuntu; installs `nsis` and `imagemagick` automatically if missing. |
| `others/windows_installer/long_wire_antenna_installer.nsi`     | [NSIS](https://nsis.sourceforge.io/) script that defines the Windows installer, built by `build_windows_installer.sh` above.                                |
| `others/windows_installer/nec2c.exe`                           | Prebuilt Windows binary of the [NEC-2 method-of-moments engine](https://www.nec2.org/) that gets embedded into `Setup_Long_Wire_Antenna.exe`. Third-party binary — see [licensing note](#third-party-licensing-note). Not meant to be used standalone — see [Option C](#option-c--run-the-python-script-directly-windowsmacoslinux) if you need a `nec2c` binary for a manual/non-Windows setup. |
| `others/windows_installer/payload/run_gui.bat`                 | Launcher batch file installed alongside the script; this is what the Desktop shortcut actually runs. It sets UTF-8 console/Python encoding, points the `NEC2C` environment variable at the bundled engine, and then runs `Long_Wire_Antenna.py --gui`. |
| `others/windows_installer/payload/post_install_setup.py`       | Runs once, automatically, at the end of installation (using the just-installed Python interpreter) to `pip install` the required packages and finish setting up the NEC2 engine. See the [Windows installer note](#option-a--windows-easiest) below. |
| `others/build_appimage.sh`                                     | Build script that produces the portable, self-contained Linux AppImage (bundled Python + Tk + statically-built `nec2c`, no host dependencies).             |
| `LICENSE`                                                       | CC0 1.0 Universal (public domain dedication) — applies to this project's own script and documentation, not to bundled third-party binaries.                |

> **Note on binary files in this repository:** the Windows installer (`Setup_Long_Wire_Antenna.exe`), the installer's bundled `nec2c.exe`, and the Linux AppImage (`Long_Wire_Antenna-x86_64.AppImage`) are committed directly to this git repository rather than published as separate GitHub Releases. This is convenient for direct download but means the repository history includes binary blobs. No SHA-256 checksums are currently published for these files in this README; if you need to verify integrity, compute the hash yourself after download (`sha256sum <file>` on Linux/macOS, `certutil -hashfile <file> SHA256` on Windows) and compare against a checksum obtained from a trusted channel, since none is published here yet.

---

## Installation

### Option A — Windows (easiest)

Download and run **`Setup_Long_Wire_Antenna.exe`**. It's fully self-contained — no other files need to sit alongside it. It will:

1. Check for a Python 3 interpreter and silently install Python 3.12.7 (64-bit) from python.org if missing (with pip, the `py` launcher, and PATH configured).
2. Install `Long_Wire_Antenna.py`, the `run_gui.bat` launcher, `post_install_setup.py`, the app icon, and the license text into the target install directory (`C:\Program Files\LongWireAntenna` by default).
3. Install the bundled `nec2c.exe` into `%INSTDIR%\nec2c\`, and also mirror a copy to `C:\Program Files\OpenNEC\` and `C:\Program Files (x86)\OpenNEC\`.
4. Run `post_install_setup.py`, which `pip install`s the Python packages (`numpy`, `matplotlib`, `tabulate`, `colorama`, `reportlab`) and then double-checks the NEC2 engine — see the note below.
5. Create a Desktop shortcut that runs `run_gui.bat`, which in turn launches `Long_Wire_Antenna.py --gui`.
6. Register a standard Windows uninstaller.

> ⚠️ **Extra dependency note:** step 4 also `pip install`s a fifth package, **`tabulate`**, alongside the four the script actually needs. `Long_Wire_Antenna.py` does **not** import or use `tabulate` anywhere — it is unused leftover in the installer's dependency list, not a real requirement. It costs nothing except a few extra seconds of install time and disk space, and you don't need it if you're setting the script up manually ([Option C](#option-c--run-the-python-script-directly-windowsmacoslinux)).

> ⚠️ **Known installer quirk (engine self-upgrade step):** as part of step 4, `post_install_setup.py` optionally tries to download a newer NEC2 engine build from an external GitHub project and, if it finds one, verifies it starts correctly before using it — falling back to "the bundled engine" if the download fails or the downloaded build doesn't run. However, its fallback logic looks for a bundled file named `onec.exe` / `onec_bundled.exe`, while the installer only ever ships a file named `nec2c.exe`. In practice this just means the optional online-upgrade step can't find that baseline file to fall back to, so it's a no-op unless the network download succeeds. It does **not** break a normal install: `run_gui.bat` independently looks for (and finds) `nec2c\nec2c.exe` and points the `NEC2C` environment variable at it directly, so the bundled engine is used correctly either way. Worth knowing if you're troubleshooting install logs that mention `onec.exe`.
>
> ⚠️ **Known bug (Windows, only if you bypass `run_gui.bat`):** step 3 mirrors the engine to `C:\Program Files\OpenNEC\nec2c.exe` and `C:\Program Files (x86)\OpenNEC\nec2c.exe`. However, `Long_Wire_Antenna.py`'s own hardcoded Windows fallback search paths look for a file named **`onec.exe`** in those same two folders, not `nec2c.exe` — the filenames don't match, so the script's built-in `Program Files\OpenNEC` fallback will **not** find the installer's copy there. This has no effect on the normal Desktop-shortcut flow, because `run_gui.bat` sets the `NEC2C` environment variable directly and never relies on this fallback. It only matters if you open a plain terminal/PowerShell after installing and run `python Long_Wire_Antenna.py` (or `py Long_Wire_Antenna.py`) yourself, *without* `run_gui.bat`, without `%NEC2C%` set, and without `%INSTDIR%\nec2c` on your `PATH` — in that specific case, NEC2 mode will report "binary not found" even though a working engine is sitting in `Program Files\OpenNEC`. Work around it with `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"`, or by setting `NEC2C` yourself, or by using the Desktop shortcut / `run_gui.bat` instead.

### Option B — Linux (AppImage, easiest for most distros)

Download **`Long_Wire_Antenna-x86_64.AppImage`**, make it executable, and run it:

```
chmod +x Long_Wire_Antenna-x86_64.AppImage
./Long_Wire_Antenna-x86_64.AppImage
```

The AppImage bundles its own Python 3.11 interpreter (with Tkinter), `numpy`, `matplotlib`, `colorama`, `reportlab`, `pillow`, and a statically-linked `nec2c` binary — nothing else needs to be installed on the host system, and no `pip install` step is required.

> ⚠️ **The AppImage always launches straight into the GUI**, regardless of any command-line arguments you pass it — GUI mode is forced unconditionally. This mirrors how `--gui` behaves when passed to the raw Python script (see the [`--gui` warning in Usage](#launch-the-gui) below): the GUI opens with its own defaults, and there is currently **no way to pre-fill it from the command line**. To use the CLI instead, run [Option C](#option-c--run-the-python-script-directly-windowsmacoslinux).

You can rebuild it yourself from source with `others/build_appimage.sh` (best run on an old base like Ubuntu 20.04, or the official AppImage builder Docker image, to keep the glibc requirement low).

### Option C — Run the Python script directly (Windows/macOS/Linux)

This is also the **only supported path for macOS**, since there is no packaged macOS installer.

**Requirements:**

- Python 3.8+
- [`nec2c`](https://www.nec2.org/) on your `PATH` (or point to it with `--nec2c`) — optional if you only plan to use `--mode empirical`
- Python packages:

```
pip install numpy matplotlib colorama reportlab
```

`colorama`, `matplotlib`, `numpy`, and `reportlab` are all optional — the script degrades gracefully (no color, no plot/PDF output) if they aren't installed. `numpy` is only actually needed for the radiation-pattern diagrams and is normally installed automatically as a dependency of `matplotlib`, so you rarely need to install it by hand.

**NEC2C binary discovery order:**

1. `--nec2c /path/to/nec2c` (explicit flag)
2. `$NEC2C` environment variable
3. `PATH` (`nec2c`, `nec2c-mpich`, `onec`)
4. Common install paths (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, etc.)
5. Interactive prompt (unless `--no-interactive` is set)

If `nec2c` cannot be found through any of these and `--no-interactive` is set (or you decline the prompt), the script falls back to `--mode empirical` when `--mode auto` is in effect, or exits with an error if you explicitly requested `--mode nec2`.

---

## Usage

### Basic — known bands

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Center frequencies for known bands are resolved automatically, so `--freqs` is optional here.

### Custom / unknown bands

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

### Restrict which bands actually drive the score

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

### Launch the GUI

```
python src/Long_Wire_Antenna.py --gui
```

> ⚠️ **`--gui` overrides everything else.** It is checked *before* the rest of the command line is parsed, so if you combine it with other flags (e.g. `python src/Long_Wire_Antenna.py --gui --bands 40m,20m`), **those other flags are silently ignored** — no warning or error is printed, and the GUI simply opens with its own built-in defaults. There is currently no way to pre-populate GUI fields from CLI arguments. Once the GUI is open, use its own fields to set everything.

### Full help

```
python src/Long_Wire_Antenna.py --help
```

Supported band presets span LF through UHF: `2200m, 630m, 160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 4m, 2m, 70cm, 23cm`.

---

## Key options

| Flag                                                                                                     | Purpose                                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--bands` / `--freqs`                                                                                    | Bands to model, and their frequencies (MHz) if not in the known-band table.                                                                                                              |
| `--active-bands`                                                                                         | Subset of `--bands` that actually contributes to the optimization score.                                                                                                                 |
| `--wire-len`, `--cp-len`                                                                                 | Starting/center radiator and counterpoise lengths (m).                                                                                                                                   |
| `--wire-min/max/step`, `--cp-min/max/step`                                                               | Define the search grid around the starting lengths.                                                                                                                                      |
| `--mode {empirical,nec2,auto}`                                                                           | Use closed-form formulas, full NEC-2 simulation, or auto-select.                                                                                                                         |
| `--height`                                                                                               | Antenna height above ground (m).                                                                                                                                                         |
| `--wire-slope-end-height`, `--cp-end-height`                                                             | Model a sloping wire/counterpoise by setting the far-end height (0 = end at ground level).                                                                                               |
| `--no-counterpoise`                                                                                      | Model a counterpoise-less end-fed antenna. In NEC2 mode the RF return path defaults to `ground-rod`; use `--no-cp-return` to pick `coax-stub` instead, or to `reject` the configuration. |
| `--no-cp-return {ground-rod,coax-stub,reject}`                                                           | How the RF return path is modeled when there's no counterpoise.                                                                                                                          |
| `--ground-model {sommerfeld,perfect}`                                                                    | Ground model used by NEC-2.                                                                                                                                                              |
| `--ground-cond`, `--ground-diel`                                                                         | Ground conductivity (S/m) and dielectric constant.                                                                                                                                        |
| `--wire-diameter`, `--wire-material`                                                                     | Physical wire diameter (mm) and material (`copper`, `aluminium`/`aluminum`, `brass`, `silver`, `steel`, `perfect`).                                                                      |
| `--target-toa`                                                                                           | Target radiation take-off angle (degrees) used in scoring.                                                                                                                               |
| `--gain-weight`                                                                                          | Weight of gain vs. VSWR in the aggregate score.                                                                                                                                           |
| `--top-n`                                                                                                | Number of ranked candidates to report.                                                                                                                                                    |
| `--out-txt`, `--out-png`, `--out-csv`, `--out-nec`, `--out-radiation`, `--out-construction`, `--out-pdf` | Output file paths for each report artifact.                                                                                                                                               |
| `--lang {en,es,it}`                                                                                      | Force UI language (auto-detected from locale otherwise).                                                                                                                                  |
| `--gui`                                                                                                  | Launch the Tkinter GUI instead of the CLI. **Overrides and silently ignores all other flags** — see the [warning above](#launch-the-gui).                                                |
| `--quiet` / `-q`                                                                                         | Suppress non-essential console output.                                                                                                                                                    |

Run `--help` for the complete, up-to-date list — the script has many more fine-tuning knobs (segments per half-wave, fast/converge modes, retry counts, etc.).

---

## Output

A typical run produces:

- **`optimizer_report.txt`** — ranked text report of the best candidates and their per-band VSWR.
- **`optimizer_plot.png`** — scatter plot of the entire search space with the Pareto front highlighted.
- **`optimizer_best.csv`** — top candidates in CSV form, ready to import elsewhere.
- **`best_antenna.nec`** — the NEC-2 deck for the winning geometry, ready to re-simulate or tweak.
- **`radiation_diagrams.png`** — radiation pattern plots for the winning antenna.
- **`antenna_construction.png`** — a construction/build diagram.
- **`antenna_brochure.pdf`** — a one-page PDF summary (requires `reportlab`).

---

## How the scoring works

For each candidate `(wire_len, cp_len)` pair, the script computes a per-band VSWR from the simulated (or empirically estimated) feedpoint impedance, then aggregates those into a single penalized score that also accounts for:

- Deviation from the desired radiation take-off angle (weighted by `--gain-weight`).
- How far the counterpoise length is from an "ideal" quarter-wave relationship for each band.
- Non-Pareto-dominated candidates are flagged so you can see genuine multi-band trade-offs rather than a single best number.

The tool then separately checks standard UnUn transformer ratios (1:1, 4:1, 9:1, etc.) against the winning antenna's raw impedance and reports which ratio(s) bring VSWR closest to 1:1 on each band — and flags bands where no standard ratio resolves the mismatch, since forcing a single feedline design to cover many unrelated bands is sometimes physically impossible.

---

## Glossary

- **Counterpoise** — a wire (or set of wires) connected to the RF-return/ground side of an end-fed antenna's feedpoint, used instead of (or in addition to) a true earth ground to provide the return path for RF current.
- **VSWR (Voltage Standing Wave Ratio)** — a measure of how well the antenna's impedance is matched to the feedline; 1:1 is a perfect match, higher numbers mean more reflected power.
- **UnUn (Unbalanced-to-Unbalanced transformer)** — an RF transformer that changes impedance (e.g. 9:1, 4:1) between an unbalanced feedline (coax) and an unbalanced antenna such as an end-fed wire, used to bring the antenna's raw impedance closer to the feedline's characteristic impedance (typically 50 Ω).
- **Take-off angle (TOA)** — the vertical angle above the horizon at which an antenna radiates its peak far-field signal; lower angles generally favor long-distance (DX) propagation.
- **Pareto-optimal candidate** — a candidate `(wire_len, cp_len)` pair for which no other candidate is simultaneously at least as good on every active band and strictly better on at least one; i.e. a genuine multi-band trade-off rather than a dominated (strictly worse) option.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `--mode nec2` exits immediately with a "binary not found" style error | `nec2c` could not be located by any discovery step, and `--mode nec2` does not fall back | Install `nec2c`, or pass `--nec2c /full/path/to/nec2c`, or set the `$NEC2C` environment variable. With `--mode auto` instead, the script falls back to `--mode empirical` automatically rather than exiting. |
| On Windows, `nec2c`/`onec.exe` is not found even though the installer succeeded, and you did **not** launch via the Desktop shortcut | You ran `Long_Wire_Antenna.py` directly (bypassing `run_gui.bat`) without `%NEC2C%` set — see the [known bug above](#option-a--windows-easiest) about the `nec2c.exe`/`onec.exe` filename mismatch under `Program Files\OpenNEC` | Use the Desktop shortcut / `run_gui.bat`, or pass `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"` explicitly, or set `NEC2C` yourself. |
| A band is flagged as poorly matched by every standard UnUn ratio | The raw antenna impedance on that band is far enough from every ratio in the built-in sweep (1:1, 1.5:1, 2:1, 3:1, 4:1, 6:1, 9:1, ...) that none of them bring VSWR close to 1:1 | This is expected for some multi-band designs — a single feedline strategy cannot always match unrelated bands equally well. Options: accept the higher VSWR on that band, use the Transmatch (tapped-coil) calculator instead of, or in addition to, the UnUn for that band, or re-run the optimizer with a different/narrower search window or a different `--active-bands` selection to find a geometry that compromises less on it. |
| `matplotlib`/`numpy`/`reportlab` is missing but a plot/PDF was requested | Optional package not installed | The run still completes and writes the non-graphical outputs (text report, CSV, `.nec` deck); the script prints which optional output was skipped and why. Install the missing package(s) with `pip install matplotlib numpy reportlab` (see [Option C](#option-c--run-the-python-script-directly-windowsmacoslinux)) and re-run. |

<!-- TODO(maintainer): The rows above were reconstructed from reading the script's own control
     flow (see find_nec2c(), the --mode resolution block in main(), the UnUn ratio sweep in
     STANDARD_UNUN_RATIOS, and the optional-import guards at the top of the file) rather than
     from exact captured error text. Consider replacing the free-text descriptions with the
     literal console messages (the T("...") message keys) the next time this file is updated,
     and add NEC-2 convergence/--retry-specific cases if they come up in practice. -->

## Third-party licensing note

This project's own source code (`src/Long_Wire_Antenna.py`), build scripts, and documentation are released under **CC0 1.0 Universal** (public domain) — see [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE).

The bundled `nec2c.exe` (Windows) and the statically-linked `nec2c` binary inside the Linux AppImage are **third-party software** — the [`nec2c`](https://www.nec2.org/) C translation of NEC-2 by Neoklis Kyriazis (5B4AZ), itself derived from the original NEC-2 code developed at Lawrence Livermore National Laboratory. These binaries are **not** covered by this project's CC0 dedication; they retain their own upstream licensing terms.

<!-- TODO(maintainer): State the exact upstream license (e.g. specific BSD variant / public-domain
     status) that applies to the bundled nec2c binary, and confirm redistribution terms are
     satisfied by shipping the compiled binary in this repository. -->

If you redistribute this project (including the bundled installer, AppImage, or `nec2c.exe`), make sure your redistribution also complies with `nec2c`'s own license terms, not just this project's CC0 dedication.

---

## License

This project's own code and documentation are released under **CC0 1.0 Universal** — public domain. Do whatever you like with it, no attribution required. See [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE) for the full legal text. Bundled third-party binaries are excluded — see [Third-party licensing note](#third-party-licensing-note) above.

## Acknowledgements

- [NEC-2](https://www.nec2.org/) (Numerical Electromagnetics Code) — the underlying antenna simulation engine.
- Built by **LU3VEA** for the amateur radio community.

---

*73! If this tool helped you build a better antenna, consider sharing your results with the community.*
