@echo off
REM Launcher for Long Wire Antenna (GUI mode)
REM This file lives in the installation directory and is targeted
REM by the Desktop shortcut created by the installer.

setlocal

set "HERE=%~dp0"

REM Switch the console code page to UTF-8 so Unicode box-drawing /
REM accented characters printed by the script (and by colorama)
REM don't crash with UnicodeEncodeError on the default cp1252 console.
chcp 65001 >nul

REM Force Python's stdout/stderr to UTF-8 regardless of console code page
REM (belt-and-braces alongside the chcp call above; works on Python 3.7+).
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM Point the script at the bundled NEC2 engine, if present.
REM post_install_setup.py normalizes the binary to nec2c\onec.exe, but
REM fall back to a recursive search in case of a different layout.
if exist "%HERE%nec2c\onec.exe" (
    set "NEC2C=%HERE%nec2c\onec.exe"
) else if exist "%HERE%nec2c\nec2c.exe" (
    set "NEC2C=%HERE%nec2c\nec2c.exe"
) else (
    for /r "%HERE%nec2c" %%F in (onec.exe nec2c.exe onec-windows-x86_64.exe) do (
        if exist "%%F" if not defined NEC2C set "NEC2C=%%F"
    )
)

REM Prefer 'py' launcher if available, fall back to 'python'.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py "%HERE%Long_Wire_Antenna.py" --gui %*
) else (
    python "%HERE%Long_Wire_Antenna.py" --gui %*
)

if errorlevel 1 (
    echo.
    echo The program exited with an error. Press any key to close...
    pause >nul
)

endlocal
