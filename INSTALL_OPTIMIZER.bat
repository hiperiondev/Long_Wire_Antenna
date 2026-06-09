@echo off
:: ============================================================================
::  NEC2 Antenna Optimizer — One-Click Installer
::  Double-click this file to install.
::  It launches the PowerShell installer with proper execution policy.
:: ============================================================================
title NEC2 Antenna Optimizer — Installer

:: Check if PowerShell is available (it always is on Win10/11)
where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo PowerShell not found. Running legacy batch installer...
    call "%~dp0WindowsInstaller\install_nec2_optimizer.bat"
    goto :eof
)

:: Launch the PowerShell installer (self-elevates automatically)
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0WindowsInstaller\install_nec2_optimizer.ps1"
