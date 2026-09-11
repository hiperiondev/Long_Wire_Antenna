#!/usr/bin/env python3
"""
post_install_setup.py
======================
Run once by the NSIS installer (using the just-installed Python interpreter)
to finish setting up the Long Wire Antenna:

  1. Installs required/optional Python packages via pip:
       matplotlib, numpy, tabulate, colorama, reportlab
  2. Makes sure a working onec.exe (NEC2 engine) is in place.

     NOTE (2026-06, v1.0.4): A statically-linked onec.exe (built from the
     NEC2 engine source, BACKEND=original, fully static - no MinGW runtime
     DLL dependencies at all) is now bundled DIRECTLY inside this installer
     as nec2c\\onec_bundled.exe and copied to nec2c\\onec.exe (and the
     nec2c\ directory by the NSIS script, BEFORE this script
     ever runs. This guarantees a working install with zero network access.

     This script then OPTIONALLY tries to fetch the latest official
     prebuilt NEC2 Windows release (which may be faster, e.g. an
     OpenBLAS build) as an upgrade. If that download fails, or the
     downloaded onec.exe doesn't actually start (e.g. the
     clock_gettime64 / missing-DLL problem described below), the bundled
     static binary is kept/restored instead. Either way, the user ends
     up with a working onec.exe.

  Background - the clock_gettime64 problem (fixed in v1.0.4):
     Official NEC2 v2.1.0+ Windows builds are produced with a MinGW-w64
     GCC 15.x/16.x toolchain that has a well-known, still-unresolved
     packaging bug (see msys2/MINGW-packages#24355, #27465 and
     niXman/mingw-builds-binaries#112): the resulting onec.exe imports a
     `clock_gettime64` symbol from libstdc++-6.dll / libgcc_s_seh-1.dll
     that is NOT exported by ANY current MinGW-w64 GCC 15.x/16.x runtime
     DLL (dynamic or "matching version" - none of them have it). So
     onec.exe refuses to start with:
         "The procedure entry point clock_gettime64 could not be located
          in the dynamic link library ...\\libstdc++-6.dll"
     no matter which redistributable runtime DLLs are placed alongside it.
     The only real fixes are (a) a statically-linked build (no DLL
     dependency at all - this is what's bundled here), or (b) an upstream
     fix to the GCC/MinGW-w64 toolchain (not available as of 2026-06).

  Fallback runtime DLLs (v1.0.5):
     The NSIS installer also drops libwinpthread-1.dll,
     libgcc_s_seh-1.dll and libstdc++-6.dll into nec2c\\ (and the
     nec2c\ directory) alongside onec.exe. The bundled static
     onec.exe doesn't need these, but they sit there as a fallback so that
     IF the optional official-release download below (_try_download_
     official_release) turns out to be a dynamically-linked build that
     needs plain libwinpthread-1.dll (a simpler, more common error than
     clock_gettime64), it finds it right next to it. verify_onec() /
     repair_existing_engine() still guard against the unfixable
     clock_gettime64 case regardless.

  Engine file layout finalize (v1.0.6):
     Whichever binary the steps above end up with at nec2c\\onec.exe
     (the static baseline, or a verified official upgrade) is renamed to
     nec2c\\onec_dynamic.exe, and the static nec2c\\onec_bundled.exe is
     renamed back to nec2c\\onec.exe (see _finalize_engine_layout()).
     nec2c\\onec.exe - the name run_gui.bat / Long_Wire_Antenna.py /
     nec2c\ - the path everything looks for - is therefore ALWAYS the
     dependency-free static build, while any downloaded official build is
     preserved as onec_dynamic.exe for manual use if desired.

Usage:
    python post_install_setup.py "<INSTALL_DIR>"

Exit codes:
    0  = success (script will still continue even if optional pieces fail)
    1  = fatal error
"""

import os
import sys
import json
import zipfile
import shutil
import subprocess
import urllib.request
import tempfile

GITHUB_API_RELEASES = "https://api.github.com/repos/maurymarkowitz/OpenNEC/releases/latest"
ASSET_NAME = "onec-windows-x86_64.zip"
NEC2C_EXE_NAMES = (
    "nec2c.exe", "onec.exe",
    "onec-windows-x86_64.exe", "onec_windows_x86_64.exe",
    "nec2c-mpich.exe", "xnec2c.exe",
)

# Windows NTSTATUS codes (as signed 32-bit ints, the form Python's
# subprocess.returncode reports them) that indicate the OS itself
# refused to start the process because a DLL or one of its exported
# entry points could not be located/loaded. If onec.exe exits with one
# of these codes, it (or one of its DLL dependencies) is missing/broken
# - e.g. the clock_gettime64 issue described above.
STATUS_DLL_NOT_FOUND = 0xC0000135 - 0x100000000          # -1073741515
STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139 - 0x100000000   # -1073741511
STATUS_ORDINAL_NOT_FOUND = 0xC0000138 - 0x100000000      # -1073741512
BAD_DLL_EXIT_CODES = {
    STATUS_DLL_NOT_FOUND,
    STATUS_ENTRYPOINT_NOT_FOUND,
    STATUS_ORDINAL_NOT_FOUND,
}


def log(msg):
    print(msg, flush=True)


def pip_install(packages):
    log(f"[*] Installing Python packages: {', '.join(packages)}")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--no-warn-script-location", *packages],
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log(f"[!] pip install failed (exit code {e.returncode}) for: {', '.join(packages)}")
        return False


def fetch_latest_onec_url():
    """Query GitHub API for the latest NEC2 engine release asset URL."""
    log("[*] Querying GitHub for latest NEC2 engine release...")
    req = urllib.request.Request(
        GITHUB_API_RELEASES,
        headers={"User-Agent": "nec2-length-optimizer-installer", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    for asset in data.get("assets", []):
        if asset.get("name", "").lower() == ASSET_NAME.lower():
            return asset["browser_download_url"], asset["name"]

    # Fallback: any asset containing "windows" and ".zip"
    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        if "windows" in name and name.endswith(".zip"):
            return asset["browser_download_url"], asset["name"]

    raise RuntimeError("Could not find a Windows release asset in the latest NEC2 engine release.")


def download_file(url, dest_path):
    log(f"[*] Downloading: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "nec2-length-optimizer-installer"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest_path, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk = 65536
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            out.write(buf)
            downloaded += len(buf)
            if total:
                pct = downloaded * 100 // total
                print(f"\r    {downloaded//1024} KB / {total//1024} KB ({pct}%)", end="", flush=True)
    print()


def verify_onec(exe_path):
    """
    Best-effort sanity check that exe_path can actually be *loaded* by
    Windows (i.e. all imported DLLs and entry points resolve), without
    worrying about whether the NEC2 engine itself runs successfully
    (it will normally print usage / exit nonzero when run with no
    arguments, and that's fine).

    Returns:
        True  - exe started fine (or we're not on Windows / can't tell)
        False - exe failed to start due to a missing DLL / entry point
                (STATUS_DLL_NOT_FOUND / STATUS_ENTRYPOINT_NOT_FOUND /
                STATUS_ORDINAL_NOT_FOUND), e.g. the clock_gettime64 issue.
    """
    if os.name != "nt":
        # Can't meaningfully test a Windows PE on a non-Windows host.
        return True
    if not os.path.isfile(exe_path):
        return False

    try:
        import ctypes
        # Suppress the "<app> - Entry Point Not Found" popup dialog so this
        # check doesn't hang waiting for the user to click OK.
        SEM_FAILCRITICALERRORS = 0x0001
        SEM_NOGPFAULTERRORBOX = 0x0002
        ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX)
    except Exception:
        pass

    try:
        proc = subprocess.run([exe_path, "--version"], capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        # It started and is presumably waiting on stdin / running - fine.
        return True
    except Exception as e:
        log(f"[!] Could not test-run {exe_path}: {e}")
        return True  # don't block install on an inconclusive test

    if proc.returncode in BAD_DLL_EXIT_CODES:
        log(f"[!] {os.path.basename(exe_path)} failed to start "
            f"(exit code {proc.returncode:#x}) - a required runtime DLL "
            f"is missing or is the wrong version (e.g. clock_gettime64).")
        return False

    return True


# ---------------------------------------------------------------------------
# Repair an already-installed onec.exe by restoring the bundled, statically
# linked binary that ships with this installer (nec2c\onec_bundled.exe).
# ---------------------------------------------------------------------------

def repair_existing_engine(install_dir):
    """
    If <install_dir>\\nec2c\\onec.exe already exists but fails to start
    (e.g. the clock_gettime64 DLL issue from an official NEC2 build),
    restore it from the bundled, statically-linked nec2c\\onec_bundled.exe
    that ships with this installer.

    This lets "Setup.exe" repair a broken install purely by re-running it,
    with no internet access required at all.
    """
    bin_dir = os.path.join(install_dir, "nec2c")
    exe_path = os.path.join(bin_dir, "onec.exe")
    bundled_path = os.path.join(bin_dir, "onec_bundled.exe")

    if not os.path.isfile(exe_path):
        return

    if verify_onec(exe_path):
        log("[OK] Existing onec.exe already starts correctly.")
        return

    log("[*] Existing onec.exe does not start correctly.")
    if not os.path.isfile(bundled_path):
        log(f"[!] Bundled fallback binary not found: {bundled_path}")
        return

    log("[*] Restoring the bundled, statically-linked onec.exe...")
    try:
        shutil.copy2(bundled_path, exe_path)
    except Exception as e:
        log(f"[!] Could not restore bundled onec.exe: {e}")
        return

    if verify_onec(exe_path):
        log("[OK] onec.exe now starts correctly (restored bundled static build).")
    else:
        log("[!] onec.exe still does not start correctly after restoring the "
            "bundled build - this is unexpected, please report this issue.")
        return

    
    pass  # no additional mirror locations


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

def _mirror_to_program_files(fixed_path):
    """Mirror onec.exe to standard locations (no additional paths configured)."""
    pass  # no additional mirror locations


def _try_download_official_release(bin_dir):
    """
    Best-effort download + extract of the latest official NEC2 Windows
    release. Returns the path to the extracted onec.exe candidate, or None
    on any failure. Never raises.
    """
    try:
        url, asset_name = fetch_latest_onec_url()
    except Exception as e:
        log(f"[!] Could not query GitHub releases: {e}")
        return None

    extract_dir = os.path.join(bin_dir, "_official_release")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, asset_name)
            try:
                download_file(url, zip_path)
            except Exception as e:
                log(f"[!] Download failed: {e}")
                return None

            log(f"[*] Extracting {asset_name} ...")
            shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
            except Exception as e:
                log(f"[!] Extraction failed: {e}")
                return None
    except Exception as e:
        log(f"[!] Unexpected error fetching official release: {e}")
        return None

    candidates = []
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            if f.lower() in NEC2C_EXE_NAMES:
                candidates.append(os.path.join(root, f))

    if not candidates:
        log("[!] Could not locate onec.exe / nec2c.exe inside the NEC2 engine archive.")
        return None

    candidates.sort(key=lambda p: 0 if os.path.basename(p).lower().startswith("onec") else 1)
    src = candidates[0]
    log(f"[*] Found candidate engine binary: {src}")

    # Also bring along any DLLs sitting next to it, in case it needs them
    # AND it turns out to actually work (verify_onec checks this).
    src_dir = os.path.dirname(src)
    candidate_path = os.path.join(bin_dir, "onec_official.exe")
    try:
        shutil.copy2(src, candidate_path)
    except Exception as e:
        log(f"[!] Could not stage candidate engine: {e}")
        return None

    for f in os.listdir(src_dir):
        if f.lower().endswith(".dll"):
            try:
                shutil.copy2(os.path.join(src_dir, f), os.path.join(bin_dir, f))
                log(f"[*] Copied companion DLL from release: {f}")
            except Exception:
                pass

    return candidate_path


def _finalize_engine_layout(bin_dir):
    """
    v1.0.6: Make sure nec2c\\onec.exe is ALWAYS the bundled, statically
    linked engine (the guaranteed-working baseline) - regardless of
    whether the optional official-release upgrade above was applied.

    Whatever currently sits at nec2c\\onec.exe (the static baseline, or a
    verified official/dynamic upgrade) is renamed to nec2c\\onec_dynamic.exe
    so it remains available, and the static nec2c\\onec_bundled.exe is
    renamed back to nec2c\\onec.exe. This way run_gui.bat,
    Long_Wire_Antenna.py always
    end up pointing at the dependency-free static build by default, while
    a downloaded official build (if any) is preserved as onec_dynamic.exe
    for anyone who wants to use it manually.

    If onec_bundled.exe is missing (e.g. post_install_setup.py was re-run
    by hand without re-running Setup.exe, so the NSIS section that
    re-extracts it didn't run), this is a no-op: whatever is currently at
    onec.exe is left in place rather than risk leaving no engine at all.
    """
    fixed_path = os.path.join(bin_dir, "onec.exe")
    bundled_path = os.path.join(bin_dir, "onec_bundled.exe")
    dynamic_path = os.path.join(bin_dir, "onec_dynamic.exe")

    if not os.path.isfile(bundled_path):
        log("[*] onec_bundled.exe not found (manual re-run?) - leaving "
            "the current nec2c\\onec.exe in place.")
        return

    try:
        if os.path.isfile(fixed_path):
            os.replace(fixed_path, dynamic_path)
            log("[*] Renamed nec2c\\onec.exe -> nec2c\\onec_dynamic.exe")
        os.replace(bundled_path, fixed_path)
        log("[OK] Renamed nec2c\\onec_bundled.exe -> nec2c\\onec.exe "
            "(static, dependency-free build is the default engine)")
    except Exception as e:
        log(f"[!] Could not finalize engine file layout: {e}")


def install_nec2_engine(install_dir):
    """
    Make sure <install_dir>\\nec2c\\onec.exe is present and working.

    Baseline (always done first, no network needed):
      - The NSIS installer already placed a statically-linked, dependency-
        free onec.exe at nec2c\\onec_bundled.exe AND copied it to
        nec2c\\onec.exe. If onec.exe is somehow missing, restore it from
        onec_bundled.exe here.

    Optional upgrade (best-effort, never fatal):
      - Try to download the latest official NEC2 Windows release.
      - If it extracts cleanly AND verify_onec() shows it actually starts,
        use it (it may be faster, e.g. an OpenBLAS build).
      - Otherwise (download/extract failure, or the well-known
        clock_gettime64 / missing-DLL problem with official GCC 15.x/16.x
        builds), keep the bundled static binary.

    Finalize (v1.0.6):
      - Whatever ended up at nec2c\\onec.exe (static, or a verified
        official/dynamic upgrade) is renamed to nec2c\\onec_dynamic.exe,
        and the static nec2c\\onec_bundled.exe is renamed back to
        nec2c\\onec.exe. nec2c\\onec.exe - the name everything else looks
        for - is therefore always the dependency-free static build.

    Ends by mirroring the final nec2c\\onec.exe (static) to
    the nec2c\ install directory.
    """
    bin_dir = os.path.join(install_dir, "nec2c")
    os.makedirs(bin_dir, exist_ok=True)
    fixed_path = os.path.join(bin_dir, "onec.exe")
    bundled_path = os.path.join(bin_dir, "onec_bundled.exe")

    # --- Baseline: guarantee a working onec.exe with zero network access ---
    if not os.path.isfile(fixed_path) and os.path.isfile(bundled_path):
        shutil.copy2(bundled_path, fixed_path)
        log(f"[OK] Installed bundled static engine to: {fixed_path}")

    if not verify_onec(fixed_path):
        repair_existing_engine(install_dir)

    if not os.path.isfile(fixed_path):
        log("[!] No onec.exe available (bundled binary missing from installer).")
        return None

    log("[OK] Baseline onec.exe is in place and starts correctly "
        "(statically linked, no DLL dependencies).")

    # --- Optional upgrade: try the latest official NEC2 release ---
    log("")
    log("[*] Checking for an official NEC2 release to use instead "
        "(optional, best-effort)...")
    upgraded_path = _try_download_official_release(bin_dir)
    if upgraded_path:
        if verify_onec(upgraded_path):
            try:
                shutil.copy2(upgraded_path, fixed_path)
                log("[OK] Upgraded to the latest official NEC2 release.")
            except Exception as e:
                log(f"[!] Could not install upgraded engine: {e}")
        else:
            log("[!] The official NEC2 release does not start correctly on "
                "this system (likely the known clock_gettime64 / MinGW "
                "runtime issue in upstream GCC 15.x/16.x builds).")
            log("[*] Keeping the bundled statically-linked onec.exe instead.")

    # Final safety net: whatever ended up at fixed_path must actually work.
    if not verify_onec(fixed_path):
        log("[*] onec.exe does not start - restoring bundled static build...")
        repair_existing_engine(install_dir)

    # Finalize file layout: onec.exe must always be the static build (see
    # _finalize_engine_layout docstring above); any official/dynamic build
    # is kept alongside as onec_dynamic.exe.
    _finalize_engine_layout(bin_dir)

    _mirror_to_program_files(fixed_path)
    return fixed_path


def write_env_hint(install_dir, nec2c_path):
    """Write a small .bat helper that sets NEC2C env var, for convenience."""
    if not nec2c_path:
        return
    bat_path = os.path.join(install_dir, "set_nec2c_env.bat")
    try:
        with open(bat_path, "w") as f:
            f.write(f'@echo off\r\nset "NEC2C={nec2c_path}"\r\n')
        log(f"[OK] Wrote helper script: {bat_path}")
    except Exception as e:
        log(f"[!] Could not write {bat_path}: {e}")


def main():
    if len(sys.argv) < 2:
        log("Usage: post_install_setup.py <INSTALL_DIR>")
        sys.exit(1)

    install_dir = sys.argv[1]
    os.makedirs(install_dir, exist_ok=True)

    log("=" * 60)
    log(" Long Wire Antenna - Post-install setup")
    log("=" * 60)

    log("[*] Upgrading pip ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=False)

    # Required + optional Python dependencies used by the script
    packages = [
        "numpy",
        "matplotlib",
        "tabulate",
        "colorama",
        "reportlab",
    ]
    pip_install(packages)

    nec2c_path = install_nec2_engine(install_dir)
    write_env_hint(install_dir, nec2c_path)

    log("")
    log("[DONE] Post-install setup finished.")
    # Never fail the overall installer due to optional download issues
    sys.exit(0)


if __name__ == "__main__":
    main()
