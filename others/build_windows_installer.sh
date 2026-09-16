#!/usr/bin/env bash
# =============================================================================
# Build script: Long Wire Antenna — Windows installer (Setup_Long_Wire_Antenna.exe)
#
# Builds a self-contained Windows installer with NSIS (makensis) from the
# sources in others/windows_installer/. Run this on Fedora, Ubuntu, or
# Debian; the distro is detected automatically and the right packages
# (nsis, imagemagick) are installed if missing.
#
#   ./others/build_windows_installer.sh
#
# =============================================================================
set -euo pipefail

# This script lives in others/, one level below the project root. Capture
# both paths now, before any `cd`, so later steps can find things regardless
# of the current working directory:
#   SCRIPT_DIR    = others/                     (this script's own directory)
#   PROJECT_ROOT  = project root                (parent of others/; holds
#                                                 src/Long_Wire_Antenna.py,
#                                                 images/logo.png, LICENSE,
#                                                 and is where the finished
#                                                 Setup_Long_Wire_Antenna.exe
#                                                 is written as output)
#   INSTALLER_DIR = others/windows_installer/   (NSIS sources: the .nsi
#                                                 script, nec2c.exe, payload/
#                                                 and assets/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALLER_DIR="$SCRIPT_DIR/windows_installer"

NSI_FILE="long_wire_antenna_installer.nsi"
OUTPUT_NAME="Setup_Long_Wire_Antenna.exe"

PY_SCRIPT="$PROJECT_ROOT/src/Long_Wire_Antenna.py"
LOGO_PNG="$PROJECT_ROOT/images/logo.png"
LICENSE_FILE="$PROJECT_ROOT/LICENSE"
NEC2C_EXE="$INSTALLER_DIR/nec2c.exe"

echo "==> Project root:    $PROJECT_ROOT"
echo "==> Installer files: $INSTALLER_DIR"

# ---------------------------------------------------------------------------
# 0. Sanity-check required inputs before touching the system at all.
# ---------------------------------------------------------------------------
for f in "$PY_SCRIPT" "$LOGO_PNG" "$LICENSE_FILE" "$NEC2C_EXE" \
         "$INSTALLER_DIR/$NSI_FILE" \
         "$INSTALLER_DIR/payload/run_gui.bat" \
         "$INSTALLER_DIR/payload/post_install_setup.py"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: required file not found: $f" >&2
        exit 1
    fi
done

# apt-get/dnf package install needs root. Use sudo if not already root.
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: this script needs root privileges to install build" \
             "dependencies (nsis, imagemagick), and 'sudo' is not available." >&2
        echo "Re-run as root, e.g.: sudo ./others/build_windows_installer.sh" >&2
        exit 1
    fi
    SUDO="sudo"
fi

# ---------------------------------------------------------------------------
# 1. Detect the distro via /etc/os-release FIRST (authoritative), falling
#    back to package-manager binary detection only if that's inconclusive.
# ---------------------------------------------------------------------------
PKG_MGR=""
if [ -f /etc/os-release ]; then . /etc/os-release; fi
case "${ID:-}${ID_LIKE:-}" in
    *fedora*|*rhel*) PKG_MGR="dnf" ;;
    *debian*|*ubuntu*) PKG_MGR="apt" ;;
esac
if [ -z "$PKG_MGR" ]; then
    if command -v dnf >/dev/null 2>&1; then PKG_MGR="dnf"
    elif command -v apt-get >/dev/null 2>&1; then PKG_MGR="apt"
    fi
fi

if [ -z "$PKG_MGR" ]; then
    echo "ERROR: could not detect a supported distro (need Fedora/RHEL or" >&2
    echo "Debian/Ubuntu, with dnf or apt-get available)." >&2
    exit 1
fi
echo "==> Detected package manager: $PKG_MGR (ID=${ID:-unknown})"

# ---------------------------------------------------------------------------
# 2. Install build dependencies: makensis (NSIS compiler) and ImageMagick
#    (used to convert images/logo.png into a multi-resolution .ico).
#    Only installs whatever is actually missing.
# ---------------------------------------------------------------------------
need_nsis=1
need_magick=1
command -v makensis >/dev/null 2>&1 && need_nsis=0
{ command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1; } && need_magick=0

if [ "$need_nsis" -eq 1 ] || [ "$need_magick" -eq 1 ]; then
    if [ "$PKG_MGR" = "apt" ]; then
        echo "==> Installing build dependencies via apt..."
        # Don't let an unrelated broken third-party repo abort the whole
        # build: apt-get update still refreshes every OTHER working list
        # even when one repo 404s/403s, so a non-zero exit here is only
        # fatal if the subsequent install actually fails.
        $SUDO apt-get update -qq || true
        if ! $SUDO apt-get install -y --no-install-recommends nsis imagemagick; then
            echo "ERROR: apt-get install failed for nsis/imagemagick." >&2
            echo "Check /etc/apt/sources.list (and sources.list.d) and network access." >&2
            exit 1
        fi
    elif [ "$PKG_MGR" = "dnf" ]; then
        echo "==> Installing build dependencies via dnf..."
        $SUDO dnf install -y nsis ImageMagick
    fi
else
    echo "==> makensis and ImageMagick already present - skipping package install."
fi

if ! command -v makensis >/dev/null 2>&1; then
    echo "ERROR: makensis is still not available after attempting to install" \
         "the 'nsis' package. Install NSIS manually and re-run this script." >&2
    exit 1
fi

MAGICK_CMD=""
if command -v magick >/dev/null 2>&1; then
    MAGICK_CMD="magick"
elif command -v convert >/dev/null 2>&1; then
    MAGICK_CMD="convert"
else
    echo "ERROR: neither 'magick' nor 'convert' (ImageMagick) is available" \
         "after attempting to install it. Install ImageMagick manually and" \
         "re-run this script." >&2
    exit 1
fi
echo "==> Using makensis: $(command -v makensis)"
echo "==> Using ImageMagick: $(command -v "$MAGICK_CMD")"

# ---------------------------------------------------------------------------
# 3. Stage the payload/assets that the .nsi script embeds. These are
#    generated/copied fresh on every run and are NOT meant to be committed
#    to the repo (only the .nsi, nec2c.exe, run_gui.bat and
#    post_install_setup.py are tracked sources).
# ---------------------------------------------------------------------------
echo "==> Staging installer payload..."
mkdir -p "$INSTALLER_DIR/payload" "$INSTALLER_DIR/assets"

cp -f "$PY_SCRIPT" "$INSTALLER_DIR/payload/Long_Wire_Antenna.py"
cp -f "$LICENSE_FILE" "$INSTALLER_DIR/assets/LICENSE.txt"

# Application icon: convert images/logo.png into a multi-resolution
# Windows .ico (used for the installer, shortcuts, and Add/Remove Programs).
echo "==> Generating assets/app.ico from images/logo.png..."
"$MAGICK_CMD" "$LOGO_PNG" -define icon:auto-resize=256,128,64,48,32,16 \
    "$INSTALLER_DIR/assets/app.ico"

# nec2c.exe already lives at others/windows_installer/nec2c.exe and is used
# from there as-is (its location is not changed); the .nsi script embeds it
# directly via a relative "File" reference.

# ---------------------------------------------------------------------------
# 4. Build the installer with makensis.
# ---------------------------------------------------------------------------
echo "==> Running makensis..."
rm -f "$INSTALLER_DIR/$OUTPUT_NAME"
( cd "$INSTALLER_DIR" && makensis "$NSI_FILE" )

if [ ! -f "$INSTALLER_DIR/$OUTPUT_NAME" ]; then
    echo "ERROR: makensis did not produce $OUTPUT_NAME." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Move the finished installer to the project root and clean up the
#    generated staging files (keep the repo tree clean between builds).
# ---------------------------------------------------------------------------
mv -f "$INSTALLER_DIR/$OUTPUT_NAME" "$PROJECT_ROOT/$OUTPUT_NAME"

rm -f "$INSTALLER_DIR/payload/Long_Wire_Antenna.py" \
      "$INSTALLER_DIR/assets/LICENSE.txt" \
      "$INSTALLER_DIR/assets/app.ico"

echo "==> Done: $PROJECT_ROOT/$OUTPUT_NAME"
