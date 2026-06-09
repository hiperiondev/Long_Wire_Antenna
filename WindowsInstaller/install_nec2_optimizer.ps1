#Requires -Version 5.1
<#
.SYNOPSIS
    NEC2 Antenna Length Optimizer — Windows Installer (PowerShell)
    Author: LU3VEA (CC0 v1.0)

.DESCRIPTION
    Installs everything needed to run the NEC2 Antenna Length Optimizer GUI:
      • Python 3.11 (via winget or direct download from python.org)
      • Required pip packages: matplotlib, tabulate, colorama, pillow
      • NEC2 engine for Windows (4nec2 nec2dxs8k0.exe + shim, or compiled nec2c)
      • Desktop shortcut with antenna icon

.NOTES
    Run this script as Administrator, or it will self-elevate.
    Requires Windows 10/11 (64-bit) and an internet connection.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ─── Self-elevate if not admin ──────────────────────────────────────────────
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host " [*] Requesting administrator privileges..." -ForegroundColor Yellow
    Start-Process PowerShell "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs -Wait
    exit
}

# ─── Banner ─────────────────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host "  NEC2 Antenna Length Optimizer — Windows Installer" -ForegroundColor Cyan
Write-Host "  LU3VEA  |  CC0 v1.0" -ForegroundColor Cyan
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " [OK] Running as Administrator." -ForegroundColor Green
Write-Host ""

# ─── Paths ───────────────────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $PSCommandPath
$InstallDir  = Join-Path $env:USERPROFILE "NEC2Optimizer"
$Nec2Dir     = Join-Path $InstallDir "nec2c"
$Nec2Exe     = Join-Path $Nec2Dir "nec2c.exe"
$LauncherBat = Join-Path $InstallDir "launch_gui.bat"
$ReadmeFile  = Join-Path $InstallDir "README_NEC2.txt"
$Desktop     = [Environment]::GetFolderPath("Desktop")
$Shortcut    = Join-Path $Desktop "NEC2 Antenna Optimizer.lnk"

Write-Host " Installation directory: $InstallDir" -ForegroundColor White

# Create directories
@($InstallDir, $Nec2Dir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Copy Python scripts
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [1/6] Copying optimizer scripts..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan

$OptScript = Join-Path $ScriptDir "nec2_length_optimizer.py"
$GuiScript = Join-Path $ScriptDir "nec2_optimizer_gui.py"

foreach ($f in @($OptScript, $GuiScript)) {
    if (-not (Test-Path $f)) {
        Write-Host " [ERROR] Not found: $f" -ForegroundColor Red
        Write-Host "         Place both .py files in the same folder as this installer." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Copy-Item -Path $f -Destination $InstallDir -Force
}
Write-Host " [OK] Scripts copied." -ForegroundColor Green


# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — Check / Install Python
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [2/6] Checking Python installation..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan

function Find-Python {
    foreach ($cmd in @('python', 'python3', 'py')) {
        try {
            $ver = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -match 'Python (\d+\.\d+)') {
                $major, $minor = $Matches[1] -split '\.' | ForEach-Object { [int]$_ }
                if ($major -ge 3 -and $minor -ge 8) {
                    return @{ cmd = $cmd; version = $Matches[1]; path = (Get-Command $cmd -ErrorAction SilentlyContinue).Source }
                }
            }
        } catch {}
    }
    return $null
}

$PyInfo = Find-Python

if ($PyInfo) {
    Write-Host " [OK] Found: $($PyInfo.cmd) $($PyInfo.version) — $($PyInfo.path)" -ForegroundColor Green
} else {
    Write-Host " [*] Python 3.8+ not found. Installing Python 3.11..." -ForegroundColor Yellow

    $installed = $false

    # Try winget
    try {
        $null = Get-Command winget -ErrorAction Stop
        Write-Host " [*] Installing via winget..." -ForegroundColor Yellow
        winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    } catch {}

    if (-not $installed) {
        # Direct download from python.org
        Write-Host " [*] Downloading Python 3.11.9 from python.org..." -ForegroundColor Yellow
        $PyInstaller = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
        try {
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
                -OutFile $PyInstaller -UseBasicParsing
            Write-Host " [*] Running Python installer..." -ForegroundColor Yellow
            Start-Process -FilePath $PyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
            $installed = $true
        } catch {
            Write-Host " [ERROR] Could not install Python: $_" -ForegroundColor Red
            Write-Host "         Please install manually from https://www.python.org/downloads/" -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
    }

    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")

    $PyInfo = Find-Python
    if (-not $PyInfo) {
        Write-Host " [ERROR] Python still not found after installation." -ForegroundColor Red
        Write-Host "         Please open a new terminal and re-run this installer." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host " [OK] Python $($PyInfo.version) installed." -ForegroundColor Green
}

$PythonCmd  = $PyInfo.cmd
$PythonPath = $PyInfo.path


# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — Install Python packages
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [3/6] Installing Python packages..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan

$packages = @('matplotlib', 'tabulate', 'colorama', 'pillow')

Write-Host " [*] Upgrading pip..." -ForegroundColor Yellow
& $PythonCmd -m pip install --upgrade pip --quiet

foreach ($pkg in $packages) {
    Write-Host " [*] Installing $pkg..." -ForegroundColor Yellow
    & $PythonCmd -m pip install --upgrade $pkg --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host " [OK] $pkg" -ForegroundColor Green
    } else {
        Write-Host " [!] $pkg — install failed (non-fatal)" -ForegroundColor Yellow
    }
}


# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — NEC2 engine for Windows
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [4/6] Setting up NEC2 engine for Windows..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host ""

# ── About the NEC2 engine on Windows ────────────────────────────────────────
# There is NO standalone precompiled nec2c.exe for Windows.
# nec2c's original author targets Linux/Unix only.
#
# Best Windows option: 4nec2 by Arie Voors ships several native Windows NEC2
# solvers (nec2dxs*.exe, nec2d.exe) fully compatible with nec2c's file format.
# We download 4nec2zip.zip which contains the exe files directly (no installer).
#
# Fallback: compile nec2c from source using MSYS2 + MinGW-w64 GCC.
# ────────────────────────────────────────────────────────────────────────────

$Nec2EngineFound = $false

function Write-Shim {
    param([string]$ShimDir, [string]$EngineName)
    # Python shim that translates nec2c CLI → nec2dxs*.exe / compiled nec2c
    $shimPy = Join-Path $ShimDir "nec2c_shim.py"
    $shimContent = @"
#!/usr/bin/env python3
"""
nec2c Windows shim — wraps $EngineName to behave like nec2c.
Translates:  nec2c -i<input> [-o<output>]
Into:        $EngineName <input> <output>
"""
import sys, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "$EngineName")

if not os.path.isfile(ENGINE):
    print(f"ERROR: NEC2 engine not found: {ENGINE}", file=sys.stderr)
    sys.exit(1)

input_file = output_file = None
for arg in sys.argv[1:]:
    if arg.startswith("-i"):
        input_file = arg[2:].strip() or None
    elif arg.startswith("-o"):
        output_file = arg[2:].strip() or None
    elif arg in ("-h", "--help", "-v", "--version"):
        print("nec2c shim v1.0 — wrapping $EngineName")
        sys.exit(0)

if not input_file:
    print("Usage: nec2c -i<input_file> [-o<output_file>]", file=sys.stderr)
    sys.exit(1)

if not output_file:
    output_file = os.path.splitext(input_file)[0] + ".out"

result = subprocess.run(
    [ENGINE, input_file, output_file],
    capture_output=True, text=True
)
sys.stdout.write(result.stdout or "")
sys.stderr.write(result.stderr or "")
sys.exit(result.returncode)
"@
    Set-Content -Path $shimPy -Value $shimContent -Encoding UTF8

    # Try to compile a standalone nec2c.exe shim with PyInstaller
    Write-Host " [*] Compiling nec2c.exe shim with PyInstaller..." -ForegroundColor Yellow
    & $PythonCmd -m pip install pyinstaller --quiet
    & $PythonCmd -m PyInstaller --onefile --console --name nec2c `
        --distpath $ShimDir `
        --workpath (Join-Path $env:TEMP "pyinstaller_work") `
        --specpath (Join-Path $env:TEMP "pyinstaller_spec") `
        $shimPy 2>&1 | Out-Null

    if (Test-Path (Join-Path $ShimDir "nec2c.exe")) {
        Write-Host " [OK] nec2c.exe shim compiled successfully." -ForegroundColor Green
    } else {
        # Fallback: batch file shim
        $batContent = "@echo off`r`n$PythonPath `"$shimPy`" %*"
        Set-Content -Path (Join-Path $ShimDir "nec2c.bat") -Value $batContent
        Set-Content -Path (Join-Path $ShimDir "nec2c.cmd") -Value $batContent
        Write-Host " [OK] nec2c.bat shim created (no PyInstaller)." -ForegroundColor Green
    }
}

# ── Option A: 4nec2 ZIP → extract nec2dxs*.exe engine ──────────────────────
Write-Host " [A] Trying to obtain NEC2 engine from 4nec2 project..." -ForegroundColor Yellow
Write-Host "     (4nec2 by Arie Voors ships a Windows-native NEC2 solver)" -ForegroundColor Gray

$FourNec2Url      = "https://qsl.net/4nec2/4nec2zip.zip"
$FourNec2Zip       = Join-Path $env:TEMP "4nec2zip.zip"
$FourNec2Extract   = Join-Path $env:TEMP "4nec2_extract"

try {
    Write-Host " [*] Downloading 4nec2 from $FourNec2Url ..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $FourNec2Url -OutFile $FourNec2Zip -UseBasicParsing -TimeoutSec 90
    Write-Host " [OK] Downloaded." -ForegroundColor Green

    # Extract the ZIP archive
    if (-not (Test-Path $FourNec2Extract)) { New-Item -ItemType Directory $FourNec2Extract | Out-Null }
    Expand-Archive -Path $FourNec2Zip -DestinationPath $FourNec2Extract -Force

    # Search for NEC2 engine EXEs — ordered by segment capacity, largest first.
    # These are the actual engines shipped directly inside 4nec2zip.zip.
    $engineFiles = @(
        "nec2dxs8k0.exe",   # 8000-segment extended NEC2 (largest)
        "nec2dxs5k0.exe",   # 5000-segment
        "nec2dxs3k0.exe",   # 3000-segment
        "nec2dxs11k.exe",   # 11000-segment (older naming)
        "nec2dxs1K5.exe",   # 1500-segment
        "nec2dxs500.exe",   # 500-segment
        "nec2d.exe"         # plain NEC2, no extended segments (fallback)
    )
    $engineFound = $null

    # Check common install paths
    $searchRoots = @(
        $FourNec2Extract,
        "${env:ProgramFiles(x86)}\4nec2\exe",
        "$env:ProgramFiles\4nec2\exe",
        "$env:ProgramFiles\4nec2",
        "${env:ProgramFiles(x86)}\4nec2"
    )

    foreach ($root in $searchRoots) {
        foreach ($name in $engineFiles) {
            $candidate = Join-Path $root $name
            if (Test-Path $candidate) {
                $engineFound = $candidate
                break
            }
        }
        if ($engineFound) { break }
    }

    # Also do a recursive search in extract dir
    if (-not $engineFound) {
        foreach ($name in $engineFiles) {
            $result = Get-ChildItem -Path $FourNec2Extract -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($result) { $engineFound = $result.FullName; break }
        }
    }

    if ($engineFound) {
        $engineName = Split-Path $engineFound -Leaf
        Write-Host " [OK] Found NEC2 engine: $engineFound" -ForegroundColor Green
        Copy-Item -Path $engineFound -Destination (Join-Path $Nec2Dir $engineName) -Force

        # Create shim
        Write-Shim -ShimDir $Nec2Dir -EngineName $engineName
        $Nec2EngineFound = $true
    } else {
        Write-Host " [!] Engine EXE not found in 4nec2 install tree." -ForegroundColor Yellow
    }
} catch {
    Write-Host " [!] 4nec2 download/install failed: $_" -ForegroundColor Yellow
}

# ── Option B: MSYS2 + compile nec2c from source ───────────────────────────
if (-not $Nec2EngineFound) {
    Write-Host ""
    Write-Host " [B] Fallback: compiling nec2c from source using MSYS2/MinGW..." -ForegroundColor Yellow

    # Check for existing MSYS2
    $Msys2Root = $null
    foreach ($d in @("C:\msys64","C:\msys2","$env:SystemDrive\msys64")) {
        if (Test-Path "$d\usr\bin\bash.exe") { $Msys2Root = $d; break }
    }

    if (-not $Msys2Root) {
        Write-Host " [*] MSYS2 not found. Downloading..." -ForegroundColor Yellow
        $Msys2Installer = Join-Path $env:TEMP "msys2-installer.exe"
        # Use a known stable MSYS2 release
        $Msys2Url = "https://github.com/msys2/msys2-installer/releases/download/2024-01-13/msys2-x86_64-20240113.exe"
        try {
            Invoke-WebRequest -Uri $Msys2Url -OutFile $Msys2Installer -UseBasicParsing -TimeoutSec 300
            Write-Host " [*] Installing MSYS2 to C:\msys64 (this may take 2–5 minutes)..." -ForegroundColor Yellow
            Start-Process -FilePath $Msys2Installer -ArgumentList "in --confirm-command --accept-messages --root C:\msys64" -Wait -NoNewWindow
            $Msys2Root = "C:\msys64"
            Write-Host " [OK] MSYS2 installed." -ForegroundColor Green
        } catch {
            Write-Host " [!] MSYS2 installation failed: $_" -ForegroundColor Yellow
            $Msys2Root = $null
        }
    }

    if ($Msys2Root) {
        Write-Host " [OK] MSYS2 at: $Msys2Root" -ForegroundColor Green
        $bash = Join-Path $Msys2Root "usr\bin\bash.exe"
        $Nec2DirUnix = & $bash -lc "cygpath -u '$Nec2Dir'" 2>$null

        # Update pacman and install tools
        Write-Host " [*] Installing build tools via pacman..." -ForegroundColor Yellow
        & $bash -lc "pacman -Syu --noconfirm 2>/dev/null; exit 0" 2>$null
        & $bash -lc "pacman -S --noconfirm --needed base-devel mingw-w64-x86_64-gcc git 2>/dev/null" 2>$null

        # Build script
        $buildSh = @"
#!/bin/bash
set -e
NEC2_OUT="$Nec2DirUnix"
mkdir -p /tmp/nec2c_build
cd /tmp/nec2c_build

echo "[*] Cloning nec2c..."
git clone --depth=1 https://github.com/KJ7LNW/nec2c.git 2>/dev/null || \
    (wget -q https://github.com/KJ7LNW/nec2c/archive/refs/heads/master.tar.gz -O nec2c.tar.gz && \
     tar xzf nec2c.tar.gz && mv nec2c-master nec2c)

cd nec2c
echo "[*] Configuring..."
autoreconf -fi 2>/dev/null || true
./configure LDFLAGS="-static-libgcc" 2>/dev/null || true

echo "[*] Compiling..."
make -j2 2>/dev/null || make

# Copy result
if [ -f src/nec2c.exe ]; then
    cp src/nec2c.exe "\$NEC2_OUT/nec2c.exe"
    echo "BUILD_SUCCESS"
elif [ -f nec2c ]; then
    cp nec2c "\$NEC2_OUT/nec2c.exe"
    echo "BUILD_SUCCESS"
else
    echo "BUILD_FAILED"
fi
"@
        $buildScript = Join-Path $env:TEMP "build_nec2c.sh"
        Set-Content -Path $buildScript -Value $buildSh -Encoding UTF8

        $bashMinGW = Join-Path $Msys2Root "mingw64\bin\bash.exe"
        if (-not (Test-Path $bashMinGW)) { $bashMinGW = $bash }

        $output = & $bashMinGW -l $buildScript 2>&1
        Write-Host $output

        if (Test-Path $Nec2Exe) {
            Write-Host " [OK] nec2c.exe compiled from source." -ForegroundColor Green
            $Nec2EngineFound = $true
        } else {
            Write-Host " [!] Compilation did not produce nec2c.exe." -ForegroundColor Yellow
        }
    }
}

# ── If all automated methods failed — instructions ───────────────────────────
if (-not $Nec2EngineFound) {
    Write-Host ""
    Write-Host " ============================================================" -ForegroundColor Yellow
    Write-Host "  [IMPORTANT] NEC2 Engine Requires Manual Setup" -ForegroundColor Yellow
    Write-Host " ============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Automated installation of the NEC2 engine did not succeed." -ForegroundColor White
    Write-Host ""
    Write-Host "  OPTION 1 (Recommended) — 4nec2 NEC2 engine:" -ForegroundColor Cyan
    Write-Host "    1. Download from:  https://qsl.net/4nec2/4nec2zip.zip" -ForegroundColor White
    Write-Host "    2. Extract the ZIP directly (no installer needed)" -ForegroundColor White
    Write-Host "    3. Copy one engine from the extracted folder, e.g.:" -ForegroundColor White
    Write-Host "         nec2dxs8k0.exe  (recommended, 8000-segment capacity)" -ForegroundColor White
    Write-Host "       Into:  $Nec2Dir\" -ForegroundColor White
    Write-Host "    4. Rename it to nec2c.exe  (or use the GUI's Browse button)" -ForegroundColor White
    Write-Host ""
    Write-Host "  OPTION 2 — Compile nec2c via MSYS2:" -ForegroundColor Cyan
    Write-Host "    See $ReadmeFile for full instructions." -ForegroundColor White
    Write-Host ""
    Write-Host "  The GUI allows browsing for the NEC2 engine manually." -ForegroundColor Gray
    Write-Host ""
}


# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — Create launcher batch file
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [5/6] Creating launcher..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan

$launcherContent = @"
@echo off
:: NEC2 Antenna Optimizer GUI Launcher
cd /d "%~dp0"

:: Add local nec2c engine to PATH so scripts find it automatically
set "PATH=%~dp0nec2c;%PATH%"

:: Launch the GUI
"$PythonPath" "%~dp0nec2_optimizer_gui.py" %*
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] GUI exited with error code %errorlevel%
    pause
)
"@
Set-Content -Path $LauncherBat -Value $launcherContent -Encoding ASCII
Write-Host " [OK] Launcher: $LauncherBat" -ForegroundColor Green


# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — Generate antenna icon and Desktop shortcut
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan
Write-Host " [6/6] Creating Desktop shortcut with antenna icon..." -ForegroundColor Cyan
Write-Host " ────────────────────────────────────────────────────────────" -ForegroundColor DarkCyan

$IcoPath = Join-Path $InstallDir "antenna.ico"

# Generate antenna icon using Python + Pillow
$iconScript = @"
import sys
try:
    from PIL import Image, ImageDraw
    
    sizes = [(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]
    images = []
    
    for (w, h) in sizes:
        img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        
        # Background circle
        d.ellipse([0, 0, w-1, h-1], fill=(26, 26, 46, 240))
        
        cx = w // 2
        mast_top = int(h * 0.12)
        mast_bot = int(h * 0.88)
        lw = max(1, w // 32)
        
        # Mast (vertical)
        d.line([(cx, mast_top), (cx, mast_bot)], fill=(0, 212, 255, 255), width=lw*2)
        
        # Base platform
        d.line([(int(w*0.25), mast_bot), (int(w*0.75), mast_bot)], fill=(160,160,160,255), width=lw*3)
        
        # Antenna elements (horizontal)
        elements = [0.25, 0.38, 0.52, 0.65]
        widths   = [0.70, 0.60, 0.50, 0.40]
        for ey, ew in zip(elements, widths):
            y = int(h * ey)
            x1 = int(cx - w * ew / 2)
            x2 = int(cx + w * ew / 2)
            d.line([(x1, y), (x2, y)], fill=(0, 212, 255, 255), width=lw*2)
        
        # Signal arcs (orange)
        for r_frac, alpha in [(0.28, 200), (0.40, 150), (0.52, 100)]:
            r = int(w * r_frac)
            x0, y0 = cx - r, int(h * 0.05)
            x1e, y1e = cx + r, int(h * 0.05) + r * 2
            d.arc([x0, y0, x1e, y1e], start=200, end=340, fill=(255, 107, 53, alpha), width=lw*2)
        
        images.append(img)
    
    ico_path = r'$IcoPath'
    images[0].save(ico_path, format='ICO', sizes=[(s[0], s[1]) for s in sizes], append_images=images[1:])
    print('ICO_OK')

except Exception as e:
    print(f'ICO_FAIL: {e}')
    sys.exit(1)
"@

$iconScriptPath = Join-Path $env:TEMP "gen_antenna_ico.py"
Set-Content -Path $iconScriptPath -Value $iconScript -Encoding UTF8

$iconResult = & $PythonCmd $iconScriptPath 2>&1
if ($iconResult -match "ICO_OK") {
    Write-Host " [OK] Antenna icon generated." -ForegroundColor Green
} else {
    Write-Host " [!] Icon generation failed: $iconResult" -ForegroundColor Yellow
    $IcoPath = $PythonPath  # Fallback to Python's own icon
}

# Create the Desktop shortcut
try {
    $WshShell  = New-Object -ComObject WScript.Shell
    $lnk       = $WshShell.CreateShortcut($Shortcut)
    $lnk.TargetPath       = $PythonPath
    $lnk.Arguments        = "`"$(Join-Path $InstallDir 'nec2_optimizer_gui.py')`""
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation     = "$IcoPath,0"
    $lnk.Description      = "NEC2 Antenna Length Optimizer GUI — LU3VEA"
    $lnk.WindowStyle      = 1
    $lnk.Save()
    Write-Host " [OK] Desktop shortcut: $Shortcut" -ForegroundColor Green
} catch {
    Write-Host " [!] Could not create shortcut: $_" -ForegroundColor Yellow
}


# ════════════════════════════════════════════════════════════════════════════
# Write README
# ════════════════════════════════════════════════════════════════════════════
$readme = @"
NEC2 Antenna Length Optimizer — README
=======================================

Installed files:
  $InstallDir\nec2_length_optimizer.py   (optimizer engine)
  $InstallDir\nec2_optimizer_gui.py      (tkinter GUI)
  $InstallDir\nec2c\                     (NEC2 engine directory)
  $InstallDir\launch_gui.bat             (launcher script)

Launch the GUI:
  • Double-click "NEC2 Antenna Optimizer" on your Desktop
  • Or run:  python "$InstallDir\nec2_optimizer_gui.py"
  • Or:      $InstallDir\launch_gui.bat

NEC2 Engine — Windows Notes
============================
There is no standalone precompiled nec2c.exe for Windows.
nec2c was written for Linux/Unix only.

Best Windows option — 4nec2 NEC2 engines (nec2dxs*.exe):
  The 4nec2 antenna modelling software by Arie Voors ships several native
  Windows NEC2 engines that are fully compatible with nec2c's file format
  (same NEC2 card format, same output format).

  1. Download:  https://qsl.net/4nec2/4nec2zip.zip
  2. Extract the ZIP directly (no installer needed)
  3. Copy one engine from the extracted folder, e.g.:
       nec2dxs8k0.exe  (recommended, 8000-segment capacity)
     Into: $Nec2Dir\
  4. Rename it to nec2c.exe   or point the GUI to it with Browse...

  The installer's NEC2 shim (nec2c.exe or nec2c.bat) in $Nec2Dir
  already handles argument translation automatically.

  Engine options (all from 4nec2zip.zip), largest capacity first:
    nec2dxs8k0.exe   8000 segments  ← recommended
    nec2dxs5k0.exe   5000 segments
    nec2dxs3k0.exe   3000 segments
    nec2dxs11k.exe  11000 segments  (older naming)
    nec2dxs1K5.exe   1500 segments
    nec2dxs500.exe    500 segments
    nec2d.exe         plain NEC2    (fallback)

Alternative — Compile nec2c from source (MSYS2):
  1. Install MSYS2 from https://www.msys2.org/
  2. Open MSYS2 MinGW64 shell:
       pacman -S --needed base-devel mingw-w64-x86_64-gcc git
       git clone https://github.com/KJ7LNW/nec2c
       cd nec2c
       autoreconf -fi && ./configure && make
  3. Copy src/nec2c.exe into: $Nec2Dir\

GUI NEC2 Path Configuration:
  If the engine is not found automatically, use the GUI's
  Browse button or pass:  --nec2c "C:\path\to\nec2c.exe"

Python packages installed:
  matplotlib  — plots and charts
  tabulate    — formatted text output
  colorama    — colored terminal output
  pillow      — icon generation

Author: LU3VEA  |  CC0 v1.0
"@
Set-Content -Path $ReadmeFile -Value $readme -Encoding UTF8


# ════════════════════════════════════════════════════════════════════════════
# Final summary
# ════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Python:        $PythonPath" -ForegroundColor White
Write-Host "  Install dir:   $InstallDir" -ForegroundColor White
Write-Host "  NEC2 engine:   $Nec2Dir" -ForegroundColor White

$nec2Status = if ($Nec2EngineFound) { "[OK] Engine ready" } else { "[!] Manual setup needed — see README" }
$nec2Color  = if ($Nec2EngineFound) { "Green" } else { "Yellow" }
Write-Host "  NEC2 status:   $nec2Status" -ForegroundColor $nec2Color

Write-Host ""
Write-Host "  Desktop shortcut: NEC2 Antenna Optimizer" -ForegroundColor White
Write-Host ""
Write-Host "  README:  $ReadmeFile" -ForegroundColor Gray
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to close"
