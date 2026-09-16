#!/usr/bin/env bash
# =============================================================================
# Build script: NEC2 Antenna Length Optimizer — portable x86_64 AppImage
# Run this on an OLD base (Ubuntu 20.04 or the official AppImage builder
# docker image) to keep the glibc floor low: docker run --rm -it -v $PWD:/w
# -w /w ubuntu:20.04 bash build_appimage.sh
# =============================================================================
set -euo pipefail

# This script lives in others/, one level below the project root. Capture
# both paths now, before any `cd`, so later steps can find things regardless
# of the current working directory:
#   SCRIPT_DIR    = others/                (this script's own directory; used
#                                            as the scratch/build workspace)
#   PROJECT_ROOT  = project root            (parent of others/; holds
#                                            src/Long_Wire_Antenna.py and
#                                            images/icon.png as inputs, and
#                                            is where the finished
#                                            .AppImage is written as output)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# apt-get/package install needs root. Use sudo if not already root.
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: this script needs root privileges to install build" \
             "dependencies (apt-get), and 'sudo' is not available." >&2
        echo "Re-run as root, e.g.: sudo ./build_appimage.sh" >&2
        exit 1
    fi
    SUDO="sudo"
fi

APP=nec2-optimizer
# Desktop-entry ID / icon name (APP, above) stays a clean lowercase-hyphen
# identifier per desktop-file conventions; the final .AppImage filename is
# tracked separately so it can use a different, human-facing project name.
OUTPUT_NAME=Long_Wire_Antenna
ARCH=x86_64
BUILD=$SCRIPT_DIR/build
APPDIR=$BUILD/AppDir
PY_VER=3.11

rm -rf "$BUILD"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/src"

# ---------------------------------------------------------------------------
# 1. System build deps (only needed on the BUILD machine, not the target).
#    Detect the distro via /etc/os-release FIRST (authoritative), falling
#    back to package-manager binary detection only if that's inconclusive.
#    (Some environments have a stray/foreign apt-get binary present even on
#    Fedora, so checking `command -v apt-get` alone is not reliable.)
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

if [ "$PKG_MGR" = "apt" ]; then
    # Sanity check: some minimal/base container images ship with EMPTY
    # /etc/apt/sources.list (no repos configured at all), which makes
    # every package "not found" even though apt-get update reports success.
    if ! apt-cache policy bash 2>/dev/null | grep -q 'Candidate:'; then
        echo "No apt sources configured; attempting to write default Debian/Ubuntu sources..." >&2
        if [ -f /etc/os-release ]; then . /etc/os-release; fi
        if [ "${ID:-}" = "ubuntu" ]; then
            CODENAME="${VERSION_CODENAME:-jammy}"
            cat <<REPOS | $SUDO tee /etc/apt/sources.list >/dev/null
deb http://archive.ubuntu.com/ubuntu $CODENAME main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $CODENAME-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu $CODENAME-security main restricted universe multiverse
REPOS
        elif [ "${ID:-}" = "debian" ]; then
            CODENAME="${VERSION_CODENAME:-bookworm}"
            cat <<REPOS | $SUDO tee /etc/apt/sources.list >/dev/null
deb http://deb.debian.org/debian $CODENAME main
deb http://deb.debian.org/debian $CODENAME-updates main
deb http://security.debian.org/debian-security $CODENAME-security main
REPOS
        else
            echo "ERROR: unrecognized apt-based distro (no ID in /etc/os-release)." >&2
            echo "Fix /etc/apt/sources.list manually, then re-run this script." >&2
            exit 1
        fi
        $SUDO apt-get update -qq
        if ! apt-cache policy bash 2>/dev/null | grep -q 'Candidate:'; then
            echo "ERROR: still no usable apt sources after writing defaults." >&2
            echo "Check network access and /etc/apt/sources.list manually." >&2
            exit 1
        fi
    fi
    $SUDO apt-get update -qq
    $SUDO apt-get install -y --no-install-recommends \
        build-essential wget curl file git ca-certificates autoconf automake \
        python3 python3-pip \
        tk-dev tcl-dev libx11-dev libxft-dev libxext-dev \
        zlib1g-dev musl-tools
elif [ "$PKG_MGR" = "dnf" ]; then
    $SUDO dnf install -y \
        gcc gcc-c++ make wget curl file git ca-certificates autoconf automake \
        python3 python3-pip \
        tk-devel tcl-devel libX11-devel libXft-devel libXext-devel \
        zlib-devel musl-gcc
else
    echo "ERROR: no supported package manager found (need apt-get or dnf)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Portable CPython with Tk built in (python-appimage manylinux base
#    already includes a self-contained interpreter + Tk; using it avoids
#    hand-rolling relocatable Tcl/Tk paths).
#
#    niess/python-appimage rebuilds this release WEEKLY, so a pinned
#    filename (e.g. python3.11.9-...) goes stale and 404s. Instead, query
#    the GitHub Releases API for the "python3.11" tag and pick whatever the
#    current manylinux2014_x86_64 asset actually is.
# ---------------------------------------------------------------------------
echo "==> Resolving latest python-appimage release asset..."
BASE_URL="$(curl -fsSL https://api.github.com/repos/niess/python-appimage/releases/tags/python$PY_VER \
    | grep -o '"browser_download_url": *"[^"]*manylinux2014_x86_64\.AppImage"' \
    | head -n1 | sed -E 's/.*"(https[^"]+)"/\1/')"
if [ -z "$BASE_URL" ]; then
    echo "ERROR: could not resolve a python-appimage manylinux2014_x86_64 asset" >&2
    echo "for python$PY_VER from the GitHub API. Check network access, or browse" >&2
    echo "https://github.com/niess/python-appimage/releases/tag/python$PY_VER manually." >&2
    exit 1
fi
echo "==> Using: $BASE_URL"
wget -O "$BUILD/base.AppImage" "$BASE_URL"
chmod +x "$BUILD/base.AppImage"

echo "==> Extracting base runtime..."
( cd "$BUILD" && ./base.AppImage --appimage-extract >/dev/null )
rm -rf "$APPDIR"
mv "$BUILD/squashfs-root" "$APPDIR"
mkdir -p "$APPDIR/usr/src"   # wiped when the base runtime replaced $APPDIR
echo "==> Base runtime extracted to $APPDIR"

# The python-appimage base ships its own AppStream metadata describing the
# bare Python runtime (usr/share/metainfo/python3.<ver>.appdata.xml). It
# has no <launchable>/desktop-file entry for OUR app, so appimagetool's
# appstreamcli validation pass fails on it ("desktop-file-not-found") and
# aborts packaging in step 8 — even though our own $APP.desktop is fine.
# It describes the interpreter, not this app, so just drop it.
rm -f "$APPDIR"/usr/share/metainfo/python*.appdata.xml
rmdir --ignore-fail-on-non-empty "$APPDIR/usr/share/metainfo" 2>/dev/null || true

PYROOT="$APPDIR/opt/python$PY_VER"

# Locate the bundled Tcl/Tk standard library so we can point TCL_LIBRARY /
# TK_LIBRARY at it explicitly in AppRun. Tkinter's built-in search paths
# (compiled in at build time on the manylinux image) don't survive
# relocation into an AppImage mount point, causing "Can't find a usable
# init.tcl" at runtime.
TCL_LIB_REL="$(find "$APPDIR" -name 'init.tcl' -print -quit | sed "s|^$APPDIR/||;s|/init.tcl$||")"
TK_LIB_REL="$(find "$APPDIR" -name 'tk.tcl' -print -quit | sed "s|^$APPDIR/||;s|/tk.tcl$||")"
if [ -z "$TCL_LIB_REL" ] || [ -z "$TK_LIB_REL" ]; then
    echo "ERROR: could not locate init.tcl / tk.tcl inside $APPDIR." >&2
    echo "The bundled Python runtime may not include Tcl/Tk; GUI mode will not work." >&2
    exit 1
fi
echo "==> Found Tcl library at: $TCL_LIB_REL"
echo "==> Found Tk library at:  $TK_LIB_REL"

# ---------------------------------------------------------------------------
# 3. Python dependencies — installed INTO the bundled interpreter, using
#    manylinux wheels only (no compiling against the build host's libs).
# ---------------------------------------------------------------------------
echo "==> Installing Python dependencies into bundled interpreter..."
"$PYROOT/bin/python$PY_VER" -m pip install --no-cache-dir \
    numpy matplotlib colorama reportlab pillow

# ---------------------------------------------------------------------------
# 4. nec2c — build statically (musl) so it needs NOTHING from the host:
#    no glibc version dependency at all, runs on literally any x86_64 Linux.
# ---------------------------------------------------------------------------
echo "==> Building nec2c (static musl)..."
cd "$APPDIR/usr/src"
# Force plain anonymous HTTPS clone: some environments have GIT_ASKPASS /
# credential helpers configured globally that make git try to authenticate
# even for public read-only clones. Disable all of that for this call.
GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true SSH_ASKPASS=/bin/true \
    git -c credential.helper= clone --depth 1 \
    https://github.com/KJ7LNW/nec2c.git nec2c-src
cd nec2c-src
# Static musl build: fully self-contained ELF, no ldd dependencies.
[ -x ./autogen.sh ] && ./autogen.sh
CC=musl-gcc CFLAGS="-O2 -static" ./configure --disable-shared || \
    { autoreconf -fi && CC=musl-gcc CFLAGS="-O2 -static" ./configure --disable-shared; }
make -j"$(nproc)"
cp nec2c "$APPDIR/usr/bin/nec2c"
strip "$APPDIR/usr/bin/nec2c"
file "$APPDIR/usr/bin/nec2c"   # sanity check: should say "statically linked"
cd "$BUILD"
rm -rf "$APPDIR/usr/src"
echo "==> nec2c built successfully"

# ---------------------------------------------------------------------------
# 5. Drop in the application script
# ---------------------------------------------------------------------------
echo "==> Copying application script..."
cp "$PROJECT_ROOT/src/Long_Wire_Antenna.py" "$APPDIR/usr/bin/Long_Wire_Antenna.py"

# ---------------------------------------------------------------------------
# 6. AppRun — ALWAYS launches GUI mode, regardless of how the AppImage is
#    invoked, and points env vars at the bundled interpreter/Tk/nec2c.
#    IMPORTANT: the python-appimage base ships its own AppRun as a SYMLINK
#    into usr/bin/AppRun. `cat > "$APPDIR/AppRun"` would follow that symlink
#    and silently write into usr/bin/AppRun instead of replacing the real
#    top-level entry point, breaking path resolution at runtime. Remove
#    whatever is there first (symlink or file) so we get a real, plain file.
# ---------------------------------------------------------------------------
rm -f "$APPDIR/AppRun"
cat > "$APPDIR/AppRun" <<EOF
#!/usr/bin/env bash
set -e
# Prefer \$APPDIR, which the AppImage runtime sets to the mounted squashfs
# root — more reliable than resolving \$0, which can itself be a symlink.
HERE="\${APPDIR:-\$(dirname "\$(readlink -f "\${0}")")}"
export PYTHONHOME="\$HERE/opt/python$PY_VER"
export PATH="\$HERE/usr/bin:\$PYTHONHOME/bin:\$PATH"
export NEC2C="\$HERE/usr/bin/nec2c"
# Tcl/Tk standard library locations, resolved at BUILD time (see step 2)
# since they don't survive relocation via Tkinter's compiled-in defaults.
export TCL_LIBRARY="\$HERE/$TCL_LIB_REL"
export TK_LIBRARY="\$HERE/$TK_LIB_REL"
# Writable cache dirs (some live/read-only-home systems need this):
export MPLCONFIGDIR="\${XDG_CACHE_HOME:-\$HOME/.cache}/nec2-optimizer/mpl"
export XDG_CACHE_HOME="\${XDG_CACHE_HOME:-\$HOME/.cache}"
mkdir -p "\$MPLCONFIGDIR"
# Force GUI mode no matter what args were passed to the AppImage.
exec "\$PYTHONHOME/bin/python$PY_VER" \\
    "\$HERE/usr/bin/Long_Wire_Antenna.py" --gui "\$@"
EOF
chmod +x "$APPDIR/AppRun"

# ---------------------------------------------------------------------------
# 7. Desktop entry + icon (required by appimagetool)
# ---------------------------------------------------------------------------
cat > "$APPDIR/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NEC2 Antenna Length Optimizer
Comment=Optimize antenna wire/counterpoise length with NEC2
Exec=AppRun
Icon=$APP
Categories=Science;Electronics;
Terminal=false
EOF
# Project icon lives at images/icon.png at the project root.
cp "$PROJECT_ROOT/images/icon.png" "$APPDIR/$APP.png"

# ---------------------------------------------------------------------------
# 8. Package it
# ---------------------------------------------------------------------------
echo "==> Downloading appimagetool and packaging..."
wget -q -O "$BUILD/appimagetool" "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$ARCH.AppImage"
chmod +x "$BUILD/appimagetool"
( cd "$BUILD" && ./appimagetool --appimage-extract-and-run "$APPDIR" "$PROJECT_ROOT/$OUTPUT_NAME-$ARCH.AppImage" )

echo "==> Built: $PROJECT_ROOT/$OUTPUT_NAME-$ARCH.AppImage"

# ---------------------------------------------------------------------------
# 9. Clean up the scratch build workspace (others/build). Only reached if
#    every prior step succeeded, since `set -e` aborts the script on any
#    earlier failure — so the directory is deliberately left in place for
#    inspection/debugging when something goes wrong.
# ---------------------------------------------------------------------------
echo "==> Cleaning up build directory..."
rm -rf "$BUILD"
echo "==> Done."
