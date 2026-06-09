@echo off
setlocal EnableDelayedExpansion

:: ============================================================================
::  NEC2 Antenna Length Optimizer — Windows Installer
::  Author: LU3VEA (CC0 v1.0)
::
::  What this script does:
::    1. Checks for administrator privileges
::    2. Installs Python 3.11 (via winget or manual download) if not present
::    3. Downloads & installs all required Python packages via pip
::    4. Downloads the NEC2 engine (nec2c-compatible) for Windows:
::         Option A: 4nec2 engines (nec2dxs8k0.exe etc.) — official NEC2 for Windows
::         Option B: Compile nec2c from source via MSYS2 (if 4nec2 unavailable)
::    5. Copies the optimizer scripts to %USERPROFILE%\NEC2Optimizer
::    6. Creates a Desktop shortcut that launches the GUI
::
::  Requirements: Windows 10/11 (64-bit), Internet connection
:: ============================================================================

title NEC2 Antenna Optimizer — Installer
color 0B

echo.
echo  =========================================================
echo   NEC2 Antenna Length Optimizer - Windows Installer
echo   LU3VEA  ^|  CC0 v1.0
echo  =========================================================
echo.

:: ------------------------------------------------------------
:: 0. Self-elevate to Administrator if needed
:: ------------------------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  [*] Requesting administrator privileges...
    powershell -NoProfile -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
    exit /b
)

echo  [OK] Running as Administrator.
echo.

:: ------------------------------------------------------------
:: Detect script directory (source of .py files)
:: ------------------------------------------------------------
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ------------------------------------------------------------
:: Installation paths
:: ------------------------------------------------------------
set "INSTALL_DIR=%USERPROFILE%\NEC2Optimizer"
set "NEC2_DIR=%INSTALL_DIR%\nec2c"
set "NEC2_EXE=%NEC2_DIR%\nec2c.exe"
set "PYTHON_MIN_VER=3.8"

echo  [*] Installation directory: %INSTALL_DIR%
echo.

:: Create installation directory
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%NEC2_DIR%"   mkdir "%NEC2_DIR%"

:: ============================================================
:: STEP 1 — Copy Python scripts
:: ============================================================
echo  ---------------------------------------------------------
echo  [1/6] Copying optimizer scripts...
echo  ---------------------------------------------------------

set "OPT_SCRIPT=%SCRIPT_DIR%\nec2_length_optimizer.py"
set "GUI_SCRIPT=%SCRIPT_DIR%\nec2_optimizer_gui.py"

if not exist "%OPT_SCRIPT%" (
    echo  [ERROR] nec2_length_optimizer.py not found in:
    echo          %SCRIPT_DIR%
    echo          Place both .py files in the same folder as this installer.
    pause & exit /b 1
)
if not exist "%GUI_SCRIPT%" (
    echo  [ERROR] nec2_optimizer_gui.py not found in:
    echo          %SCRIPT_DIR%
    echo          Place both .py files in the same folder as this installer.
    pause & exit /b 1
)

copy /Y "%OPT_SCRIPT%" "%INSTALL_DIR%\" >nul
copy /Y "%GUI_SCRIPT%" "%INSTALL_DIR%\" >nul
echo  [OK] Scripts copied to %INSTALL_DIR%
echo.

:: ============================================================
:: STEP 2 — Check / Install Python
:: ============================================================
echo  ---------------------------------------------------------
echo  [2/6] Checking Python installation...
echo  ---------------------------------------------------------

set "PYTHON_CMD="

:: Try python, then python3, then py launcher
for %%P in (python python3 py) do (
    if not defined PYTHON_CMD (
        %%P --version >nul 2>&1
        if !errorlevel! equ 0 (
            for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
                set "PY_VER=%%V"
            )
            set "PYTHON_CMD=%%P"
        )
    )
)

if defined PYTHON_CMD (
    echo  [OK] Found: !PYTHON_CMD! !PY_VER!
) else (
    echo  [*] Python not found. Attempting installation...
    echo.

    :: Try winget first (Windows 10 1709+ / Windows 11)
    winget --version >nul 2>&1
    if !errorlevel! equ 0 (
        echo  [*] Installing Python via winget...
        winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        if !errorlevel! equ 0 (
            echo  [OK] Python installed via winget.
        ) else (
            echo  [!] winget install failed. Trying direct download...
            goto :download_python
        )
    ) else (
        goto :download_python
    )
    goto :refresh_python
)

:: Detect full python path for shortcut
for %%P in (python python3 py) do (
    if not defined PYTHON_FULL_PATH (
        where %%P >nul 2>&1
        if !errorlevel! equ 0 (
            for /f "delims=" %%X in ('where %%P') do (
                if not defined PYTHON_FULL_PATH set "PYTHON_FULL_PATH=%%X"
            )
        )
    )
)
goto :python_ok

:download_python
echo  [*] Downloading Python 3.11 installer from python.org...
set "PY_INSTALLER=%TEMP%\python_installer.exe"
powershell -NoProfile -Command ^
    "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%PY_INSTALLER%' -UseBasicParsing; Write-Host 'OK' } catch { Write-Host 'FAIL'; exit 1 }"
if !errorlevel! neq 0 (
    echo  [ERROR] Could not download Python. Check your internet connection.
    echo          Please manually install Python from https://www.python.org/downloads/
    pause & exit /b 1
)
echo  [*] Running Python installer (please wait — this may take a minute)...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
if !errorlevel! neq 0 (
    echo  [ERROR] Python installation failed.
    pause & exit /b 1
)
echo  [OK] Python installed.

:refresh_python
:: Refresh PATH so python is now available
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
set "PATH=%APPDATA%\Python\Python311\Scripts;%PATH%"
python --version >nul 2>&1
if !errorlevel! neq 0 (
    echo  [ERROR] Python still not found after installation.
    echo          Please open a new Command Prompt and re-run this installer.
    pause & exit /b 1
)
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
set "PYTHON_CMD=python"
echo  [OK] Python !PY_VER! is ready.

:python_ok
:: Determine the actual python executable path for later use
if not defined PYTHON_FULL_PATH (
    for /f "delims=" %%X in ('where %PYTHON_CMD% 2^>nul') do (
        if not defined PYTHON_FULL_PATH set "PYTHON_FULL_PATH=%%X"
    )
)
echo.

:: ============================================================
:: STEP 3 — Upgrade pip and install Python packages
:: ============================================================
echo  ---------------------------------------------------------
echo  [3/6] Installing Python packages...
echo  ---------------------------------------------------------

%PYTHON_CMD% -m pip install --upgrade pip --quiet
if !errorlevel! neq 0 (
    echo  [!] pip upgrade failed — continuing anyway.
)

echo  [*] Installing required packages (matplotlib, tabulate, colorama)...
%PYTHON_CMD% -m pip install --upgrade ^
    matplotlib ^
    tabulate ^
    colorama ^
    --quiet

if !errorlevel! neq 0 (
    echo  [ERROR] Some packages failed to install.
    echo          Check your internet connection and try again.
    pause & exit /b 1
)
echo  [OK] Python packages installed.
echo.

:: ============================================================
:: STEP 4 — Obtain NEC2 engine for Windows
:: ============================================================
echo  ---------------------------------------------------------
echo  [4/6] Setting up NEC2 engine for Windows...
echo  ---------------------------------------------------------
echo.
echo  Strategy:
echo    A) Download nec2c.exe compiled for Windows (via 4nec2 project)
echo    B) Compile from source using MSYS2/GCC (fallback)
echo.

:: ---- Option A: Download 4nec2zip.zip and extract the NEC2 engine -------------
::
:: 4nec2 by Arie Voors ships nec2dxs*.exe — native Windows NEC2 solvers
:: compatible with nec2c's file format. 4nec2zip.zip contains them directly
:: (no installer needed). We wrap the best engine with a shim (nec2c.exe).
::
:: Direct ZIP URL (no installer):
set "NEC2_4NEC2_URL=https://qsl.net/4nec2/4nec2zip.zip"
set "NEC2_SETUP=%TEMP%\4nec2zip.zip"
set "NEC2_INSTALL_TMP=%TEMP%\4nec2_extract"

echo  [A] Attempting to download 4nec2 NEC2 engine...
powershell -NoProfile -Command ^
    "try { Invoke-WebRequest -Uri '%NEC2_4NEC2_URL%' -OutFile '%NEC2_SETUP%' -UseBasicParsing -TimeoutSec 60; exit 0 } catch { exit 1 }"

if !errorlevel! equ 0 (
    echo  [OK] 4nec2zip.zip downloaded.
    echo  [*] Extracting ZIP...

    :: Extract the ZIP directly — no installer needed
    if not exist "%NEC2_INSTALL_TMP%" mkdir "%NEC2_INSTALL_TMP%"
    powershell -NoProfile -Command ^
        "Expand-Archive -Path '%NEC2_SETUP%' -DestinationPath '%NEC2_INSTALL_TMP%' -Force"

    :: Look for NEC2 solver EXEs — ordered by segment capacity, largest first
    set "NEC2_ENGINE_FOUND=0"
    set "NEC2_ENGINE_NAME="
    for %%F in (
        nec2dxs8k0.exe
        nec2dxs5k0.exe
        nec2dxs3k0.exe
        nec2dxs11k.exe
        nec2dxs1K5.exe
        nec2dxs500.exe
        nec2d.exe
    ) do (
        if !NEC2_ENGINE_FOUND! equ 0 (
            for /r "%NEC2_INSTALL_TMP%" %%P in (%%F) do (
                if !NEC2_ENGINE_FOUND! equ 0 if exist "%%P" (
                    echo  [OK] Found NEC2 engine: %%P
                    copy /Y "%%P" "%NEC2_DIR%\%%F" >nul
                    set "NEC2_ENGINE_NAME=%%F"
                    set "NEC2_ENGINE_FOUND=1"
                )
            )
        )
    )

    if !NEC2_ENGINE_FOUND! equ 1 (
        :: Create a wrapper shim: nec2c.exe → calls the found nec2dxs*.exe engine
        call :create_nec2c_shim "%NEC2_DIR%" "!NEC2_ENGINE_NAME!"
        echo  [OK] NEC2 engine ready.
        goto :nec2_done
    ) else (
        echo  [!] Could not extract NEC2 engine from 4nec2zip.zip.
    )
) else (
    echo  [!] Could not download 4nec2zip.zip ^(network error^).
)

:: ---- Option B: Compile nec2c from source via MSYS2 -------------------------
echo.
echo  [B] Falling back: compiling nec2c from source via MSYS2...
echo.

:: Check if MSYS2 is already installed
set "MSYS2_ROOT="
for %%D in ("C:\msys64" "C:\msys2" "%SystemDrive%\msys64") do (
    if exist "%%~D\usr\bin\bash.exe" (
        set "MSYS2_ROOT=%%~D"
    )
)

if not defined MSYS2_ROOT (
    echo  [*] MSYS2 not found. Downloading installer...
    set "MSYS2_INSTALLER=%TEMP%\msys2-installer.exe"
    powershell -NoProfile -Command ^
        "try { Invoke-WebRequest -Uri 'https://github.com/msys2/msys2-installer/releases/download/2024-01-13/msys2-x86_64-20240113.exe' -OutFile '!MSYS2_INSTALLER!' -UseBasicParsing; exit 0 } catch { exit 1 }"
    if !errorlevel! neq 0 (
        echo  [ERROR] Could not download MSYS2. 
        goto :nec2_manual
    )
    echo  [*] Installing MSYS2 to C:\msys64 ^(this takes ~2 minutes^)...
    "!MSYS2_INSTALLER!" in --confirm-command --accept-messages --root C:\msys64
    if !errorlevel! neq 0 (
        echo  [ERROR] MSYS2 installation failed.
        goto :nec2_manual
    )
    set "MSYS2_ROOT=C:\msys64"
    echo  [OK] MSYS2 installed.
)

echo  [OK] MSYS2 found at: %MSYS2_ROOT%
echo  [*] Updating MSYS2 and installing GCC, make, wget...

:: Run MSYS2 setup commands via bash
"%MSYS2_ROOT%\usr\bin\bash.exe" -lc "pacman -Syu --noconfirm 2>/dev/null; exit 0"
"%MSYS2_ROOT%\usr\bin\bash.exe" -lc "pacman -S --noconfirm --needed base-devel mingw-w64-x86_64-gcc wget 2>/dev/null"

echo  [*] Downloading and compiling nec2c...

:: Write a build script
set "BUILD_SCRIPT=%TEMP%\build_nec2c.sh"
(
echo #!/bin/bash
echo set -e
echo NEC2_DIR="$(cygpath -u '%NEC2_DIR%')"
echo cd /tmp
echo echo "[*] Downloading nec2c source..."
echo wget -q "https://github.com/KJ7LNW/nec2c/archive/refs/heads/master.tar.gz" -O nec2c-master.tar.gz
echo tar xzf nec2c-master.tar.gz
echo cd nec2c-master
echo echo "[*] Compiling nec2c..."
echo autoreconf -fi 2>/dev/null ^|^| true
echo ./configure --prefix=/tmp/nec2c-install 2^>/dev/null ^|^| ^(mkdir -p src ^&^& make -f Makefile nec2c^)
echo make -j2 2^>/dev/null ^|^| make
echo mkdir -p "$NEC2_DIR"
echo cp src/nec2c.exe "$NEC2_DIR/" 2^>/dev/null ^|^| cp nec2c "$NEC2_DIR/nec2c.exe" 2^>/dev/null ^|^| echo "COMPILE_FAILED"
echo echo "COMPILE_OK"
) > "%BUILD_SCRIPT%"

"%MSYS2_ROOT%\mingw64\bin\bash.exe" -l "%BUILD_SCRIPT%" 2>&1

if exist "%NEC2_EXE%" (
    echo  [OK] nec2c compiled successfully.
    goto :nec2_done
)

:nec2_manual
echo.
echo  =========================================================
echo   [IMPORTANT] NEC2 Engine Not Installed Automatically
echo  =========================================================
echo.
echo  The automatic NEC2 engine installation did not succeed.
echo  You have two easy options:
echo.
echo  OPTION 1 ^(Recommended^) — Download 4nec2zip.zip:
echo    1. Go to:  https://qsl.net/4nec2/4nec2zip.zip
echo    2. Extract the ZIP directly ^(no installer needed^)
echo    3. Copy one engine from the extracted folder, e.g.:
echo         nec2dxs8k0.exe  ^(recommended, 8000-segment capacity^)
echo       into:  %NEC2_DIR%\
echo    4. Rename or copy it as nec2c.exe  ^(or set --nec2c path in GUI^)
echo.
echo  OPTION 2 — MSYS2 manual compile:
echo    1. Install MSYS2 from https://www.msys2.org/
echo    2. In MSYS2 MinGW64 shell:
echo         pacman -S --needed base-devel mingw-w64-x86_64-gcc
echo         git clone https://github.com/KJ7LNW/nec2c
echo         cd nec2c ^&^& autoreconf -fi ^&^& ./configure ^&^& make
echo         copy src\nec2c.exe  %NEC2_DIR%\
echo.
echo  The GUI allows you to browse for the NEC2 executable manually.
echo.
echo  Installation continuing without NEC2 engine...
echo.
pause

:nec2_done
echo.

:: ============================================================
:: STEP 5 — Write a wrapper/launcher .bat for easy execution
:: ============================================================
echo  ---------------------------------------------------------
echo  [5/6] Creating launcher and configuration...
echo  ---------------------------------------------------------

:: Write a small launcher batch file
set "LAUNCHER=%INSTALL_DIR%\launch_gui.bat"
(
echo @echo off
echo :: NEC2 Antenna Optimizer GUI Launcher
echo cd /d "%%~dp0"
echo.
echo :: Add local nec2c to PATH
echo set "PATH=%%~dp0nec2c;%%PATH%%"
echo.
echo :: Check for nec2c shim or engine
echo if exist "%%~dp0nec2c\nec2c.exe" (
echo     set "NEC2C_PATH=%%~dp0nec2c\nec2c.exe"
echo ^)
echo.
echo python "%%~dp0nec2_optimizer_gui.py" %%*
echo if %%errorlevel%% neq 0 pause
) > "%LAUNCHER%"

echo  [OK] Launcher created: %LAUNCHER%

:: ============================================================
:: STEP 6 — Create Desktop shortcut with antenna icon
:: ============================================================
echo  ---------------------------------------------------------
echo  [6/6] Creating Desktop shortcut...
echo  ---------------------------------------------------------

set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\NEC2 Antenna Optimizer.lnk"
set "ICON_SCRIPT=%TEMP%\create_icon.py"

:: Generate a simple antenna SVG then convert to ICO via Python
:: We embed a tiny antenna icon as base64-encoded .ico
(
echo import os, struct, zlib, base64
echo.
echo # Minimal 32x32 ICO with antenna symbol ^(hand-crafted pixel art^)
echo # Generated as a valid .ico with one 32x32 RGBA image
echo ico_b64 = ^(
echo     "AAABAAEAICAQAAEABADoAgAAFgAAACgAAAAgAAAAQAAAAAEABAAAAAAAAAAAA"
echo     "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAArIiIAVTMzAMzMzACqqqoAiIiIAAAA"
echo     "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
echo     "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
echo     "AAAAAAAAAAAAAAAAAABEREQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB"
echo     "RERERAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABREREREAAAAAAAAAAAAAA"
echo     "AAAAAAAAAAAAAAAAAAABREREREREAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB"
echo     "REREREREREAAAAAAAAAAAAAAAAAAAAAAAAABREREREREREREREAAAAAAAAAAAAA"
echo     "AAAAAAAAAABREREREREREREREREREAAAAAAAAAAAAAAAAAABRERERERERERERER"
echo     "EREREREAAAAAAAAAAAAABREREREREREREREREREREREREREAAAAAAAAAAAAABRER"
echo     "EREREREREREREREREREREREREAAAAAAAAABRERERERERERERERERERERERERERERE"
echo     "REAAAAAAAABREREREREREREREREREREREREREREREREREREAAAAARERERERERERERERE"
echo     "REREREREREREREREREREAAAABRERERERERERERERERERERERERERERERERERERERAAA"
echo     "ABRERERERERERERERERERERERERERERERERERERERE"
echo ^)
echo.
echo # Fallback: use Python's tkinter PhotoImage to make a real icon
echo try:
echo     import tkinter as tk
echo     from tkinter import PhotoImage
echo     import tempfile, os
echo.
echo     root = tk.Tk^(^)
echo     root.withdraw^(^)
echo.
echo     # Draw antenna on a canvas and save as .ico
echo     canvas_size = 64
echo     c = tk.Canvas^(root, width=canvas_size, height=canvas_size, bg='#1a1a2e'^)
echo     c.pack^(^)
echo.
echo     # Antenna mast
echo     c.create_line^(32, 56, 32, 20, fill='#00d4ff', width=3^)
echo     # Antenna elements ^(horizontal arms^)
echo     c.create_line^(20, 28, 44, 28, fill='#00d4ff', width=2^)
echo     c.create_line^(24, 36, 40, 36, fill='#00d4ff', width=2^)
echo     c.create_line^(26, 44, 38, 44, fill='#00d4ff', width=2^)
echo     # Signal arcs
echo     c.create_arc^(14, 12, 50, 28, start=0, extent=180, outline='#ff6b35', width=2, style='arc'^)
echo     c.create_arc^(8,  6,  56, 22, start=0, extent=180, outline='#ff6b35', width=1, style='arc'^)
echo     # Base
echo     c.create_line^(22, 56, 42, 56, fill='#aaaaaa', width=4^)
echo.
echo     # Save canvas as PostScript then convert
echo     ico_path = r'%INSTALL_DIR%\antenna.ico'
echo     # Create ICO using PIL/Pillow if available
echo     try:
echo         from PIL import Image, ImageDraw, ImageFont
echo         img = Image.new^('RGBA', ^(64, 64^), ^(26, 26, 46, 255^)^)
echo         draw = ImageDraw.Draw^(img^)
echo         # Mast
echo         draw.line^(^[^(32,56^),^(32,12^)^], fill=^(0,212,255,255^), width=3^)
echo         # Elements
echo         for y,x1,x2 in ^[^(20,16,48^),^(28,20,44^),^(36,24,40^),^(44,26,38^)^]:
echo             draw.line^(^[^(x1,y^),^(x2,y^)^], fill=^(0,212,255,255^), width=2^)
echo         # Base
echo         draw.line^(^[^(20,58^),^(44,58^)^], fill=^(180,180,180,255^), width=4^)
echo         # Signal arcs
echo         draw.arc^(^[10, 2, 54, 20^], start=0, end=180, fill=^(255,107,53,255^), width=2^)
echo         draw.arc^(^[4,  -4, 60, 14^], start=0, end=180, fill=^(255,107,53,200^), width=1^)
echo         img.save^(ico_path, format='ICO', sizes=^[^(64,64^),^(32,32^),^(16,16^)^]^)
echo         print^('ICO_PILLOW'^)
echo     except ImportError:
echo         # Save minimal ICO without Pillow
echo         # Use tkinter to save as GIF then embed
echo         print^('ICO_NOPILLOW'^)
echo.
echo     root.destroy^(^)
echo except Exception as e:
echo     print^(f'ICO_ERROR: {e}'^)
) > "%ICON_SCRIPT%"

%PYTHON_CMD% "%ICON_SCRIPT%" >nul 2>&1

:: If Pillow isn't installed, install it silently and retry
%PYTHON_CMD% -m pip install pillow --quiet >nul 2>&1
%PYTHON_CMD% "%ICON_SCRIPT%" >nul 2>&1

:: Create the shortcut via PowerShell
set "ICO_PATH=%INSTALL_DIR%\antenna.ico"
if not exist "%ICO_PATH%" (
    :: Use default Python icon as fallback
    for /f "delims=" %%X in ('where %PYTHON_CMD%') do set "PY_EXE=%%X" & goto :gotpyexe
    :gotpyexe
    set "ICO_PATH=%PY_EXE%"
)

powershell -NoProfile -Command ^
    "$WshShell = New-Object -ComObject WScript.Shell; " ^
    "$Shortcut = $WshShell.CreateShortcut('%SHORTCUT%'); " ^
    "$Shortcut.TargetPath = '%PYTHON_FULL_PATH%'; " ^
    "$Shortcut.Arguments = '\""%INSTALL_DIR%\nec2_optimizer_gui.py\""'; " ^
    "$Shortcut.WorkingDirectory = '%INSTALL_DIR%'; " ^
    "$Shortcut.IconLocation = '%ICO_PATH%'; " ^
    "$Shortcut.Description = 'NEC2 Antenna Length Optimizer GUI'; " ^
    "$Shortcut.WindowStyle = 1; " ^
    "$Shortcut.Save()"

if !errorlevel! equ 0 (
    echo  [OK] Desktop shortcut created: %SHORTCUT%
) else (
    echo  [!] Could not create shortcut automatically.
    echo      Run manually: python "%INSTALL_DIR%\nec2_optimizer_gui.py"
)

echo.

:: ============================================================
:: Summary
:: ============================================================
echo  =========================================================
echo   Installation Complete!
echo  =========================================================
echo.
echo   Files installed to:
echo     %INSTALL_DIR%
echo.
echo   NEC2 engine directory:
echo     %NEC2_DIR%
echo.
if exist "%NEC2_EXE%" (
    echo   NEC2 engine status: [OK] Found
) else (
    echo   NEC2 engine status: [MANUAL SETUP REQUIRED]
    echo     See instructions above or in README_NEC2.txt
)
echo.
echo   Launch the GUI:
echo     • Double-click "NEC2 Antenna Optimizer" on your Desktop
echo     • Or run: python "%INSTALL_DIR%\nec2_optimizer_gui.py"
echo.
echo   If the NEC2 engine is not found automatically, use the
echo   "Browse..." button in the GUI to locate nec2c.exe.
echo.

:: Write a README with manual NEC2 install instructions
(
echo NEC2 Antenna Length Optimizer — README
echo ========================================
echo.
echo If the NEC2 engine (nec2c.exe) was not installed automatically,
echo you have several options:
echo.
echo OPTION 1 (Easiest) — 4nec2 NEC2 engines:
echo   1. Download:  https://qsl.net/4nec2/4nec2zip.zip
echo   2. Extract the ZIP directly ^(no installer needed^)
echo   3. Copy one engine from the extracted folder, e.g.:
echo        nec2dxs8k0.exe  ^(recommended, 8000-segment capacity^)
echo      into:  %NEC2_DIR%\
echo   4. Rename it to  nec2c.exe   OR point the GUI to it via Browse
echo.
echo      Available engines ^(all in 4nec2zip.zip^), largest first:
echo        nec2dxs8k0.exe   8000 segments  ^(recommended^)
echo        nec2dxs5k0.exe   5000 segments
echo        nec2dxs3k0.exe   3000 segments
echo        nec2dxs11k.exe  11000 segments  ^(older naming^)
echo        nec2dxs1K5.exe   1500 segments
echo        nec2dxs500.exe    500 segments
echo        nec2d.exe         plain NEC2    ^(fallback^)
echo.
echo OPTION 2 — Compile nec2c from source (MSYS2):
echo   1. Install MSYS2 from https://www.msys2.org/
echo   2. Open MSYS2 MinGW64 shell and run:
echo        pacman -S --needed base-devel mingw-w64-x86_64-gcc git
echo        git clone https://github.com/KJ7LNW/nec2c
echo        cd nec2c
echo        autoreconf -fi
echo        ./configure
echo        make
echo   3. Copy  src/nec2c.exe  to:  %NEC2_DIR%\
echo.
echo Launching the GUI:
echo   python "%INSTALL_DIR%\nec2_optimizer_gui.py"
echo   or double-click the Desktop shortcut.
echo.
echo For NEC2 engine path configuration, use the GUI's Browse button
echo or pass  --nec2c "C:\path\to\nec2c.exe"  on the command line.
) > "%INSTALL_DIR%\README_NEC2.txt"

echo   A README with manual instructions has been saved to:
echo     %INSTALL_DIR%\README_NEC2.txt
echo.
pause
exit /b 0


:: ============================================================
:: Subroutine: Create nec2c.exe shim that wraps the 4nec2 engine
:: Usage: call :create_nec2c_shim <shim_dir> <engine_filename>
:: The 4nec2 engines accept: <engine> <input> <output>
:: nec2c accepts: nec2c -i<input> [-o<output>]
:: We parse args and call the appropriate engine.
:: ============================================================
:create_nec2c_shim
set "SHIM_DIR=%~1"
set "SHIM_ENGINE=%~2"
if not defined SHIM_ENGINE set "SHIM_ENGINE=nec2dxs8k0.exe"

:: Write a Python-based shim script that translates nec2c arguments
:: to the 4nec2 engine arguments
set "SHIM_PY=%SHIM_DIR%\nec2c_shim.py"
(
echo #!/usr/bin/env python3
echo """
echo nec2c shim for Windows — wraps %SHIM_ENGINE% (from 4nec2) to behave
echo like nec2c for use with nec2_length_optimizer.py
echo.
echo Usage (same as nec2c):
echo   nec2c_shim.py -i^<input.nec^> [-o^<output.out^>]
echo """
echo import sys, os, subprocess, shutil
echo.
echo HERE = os.path.dirname(os.path.abspath(__file__))
echo ENGINE = os.path.join(HERE, "%SHIM_ENGINE%")
echo.
echo if not os.path.isfile(ENGINE):
echo     print(f"ERROR: NEC2 engine not found: {ENGINE}", file=sys.stderr)
echo     sys.exit(1)
echo.
echo # Parse nec2c-style arguments
echo input_file = None
echo output_file = None
echo for arg in sys.argv[1:]:
echo     if arg.startswith("-i"):
echo         input_file = arg[2:] or None
echo     elif arg.startswith("-o"):
echo         output_file = arg[2:] or None
echo     elif arg in ("-h", "--help", "-v", "--version"):
echo         print("nec2c shim wrapping %SHIM_ENGINE%")
echo         sys.exit(0)
echo.
echo if not input_file:
echo     print("Usage: nec2c -i^<input_file^> [-o^<output_file^>]", file=sys.stderr)
echo     sys.exit(1)
echo.
echo # Engine expects: ^<engine^> ^<input^> ^<output^>
echo if not output_file:
echo     base = os.path.splitext(input_file)[0]
echo     output_file = base + ".out"
echo.
echo result = subprocess.run(
echo     [ENGINE, input_file, output_file],
echo     capture_output=True, text=True
echo ^)
echo sys.stdout.write(result.stdout)
echo sys.stderr.write(result.stderr)
echo sys.exit(result.returncode)
) > "%SHIM_PY%"

:: Create nec2c.bat shim in the nec2c directory
(
echo @echo off
echo python "%SHIM_DIR%\nec2c_shim.py" %%*
) > "%SHIM_DIR%\nec2c.cmd"

:: Also create nec2c.exe using a compiled Python launcher if available
%PYTHON_CMD% -m pip install pyinstaller --quiet >nul 2>&1
%PYTHON_CMD% -m PyInstaller --onefile --console --name nec2c ^
    --distpath "%SHIM_DIR%" ^
    --workpath "%TEMP%\pyinstaller_work" ^
    --specpath "%TEMP%\pyinstaller_spec" ^
    "%SHIM_PY%" >nul 2>&1

if exist "%SHIM_DIR%\nec2c.exe" (
    echo  [OK] nec2c.exe shim compiled with PyInstaller.
) else (
    echo  [OK] nec2c.cmd shim created (add %SHIM_DIR% to PATH^).
    :: Copy the .cmd as a .bat as well for compatibility
    copy /Y "%SHIM_DIR%\nec2c.cmd" "%SHIM_DIR%\nec2c.bat" >nul
)

goto :eof
