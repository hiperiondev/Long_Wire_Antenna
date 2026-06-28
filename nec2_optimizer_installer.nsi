; ============================================================================
;  NEC2 Antenna Length Optimizer - Windows Installer
;  Built with NSIS (Nullsoft Scriptable Install System)
;
;  This installer:
;    1. Checks for a Python 3 interpreter; if missing, silently downloads
;       and installs Python 3.12 (64-bit) from python.org with pip + PATH.
;    2. Moves nec2_length_optimizer.py (shipped beside Setup.exe, NOT
;       embedded in this installer) into the install dir, and copies the
;       small helper files (run_gui.bat, post_install_setup.py, icon,
;       license) which ARE embedded as usual.
;    3. Copies nec2c.exe (shipped beside Setup.exe, NOT embedded in this
;       installer) into $INSTDIR\nec2c\ and C:\Program Files\OpenNEC\
;       (and the (x86) variant).
;    4. Runs a post-install script that:
;         - pip-installs: numpy, matplotlib, tabulate, colorama, reportlab
;    5. Creates a Desktop shortcut that launches:
;           nec2_length_optimizer.py --gui
;    6. Registers an uninstaller.
;
;  Build:
;     makensis nec2_optimizer_installer.nsi
;
;  Distribute as:
;    SomeFolder\
;      NEC2_Length_Optimizer_Setup.exe
;      nec2_length_optimizer.py
;      nec2c.exe
; ============================================================================

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

; ---------------------------------------------------------------------------
; General configuration
; ---------------------------------------------------------------------------
!define APP_NAME        "NEC2 Antenna Length Optimizer"
!define APP_VERSION     "1.0.7"
!define APP_PUBLISHER   "LU3VEA"
!define APP_EXE_SCRIPT  "nec2_length_optimizer.py"
!define APP_LAUNCHER    "run_gui.bat"
!define NEC2C_EXE       "nec2c.exe"
!define UNINST_KEY      "Software\Microsoft\Windows\CurrentVersion\Uninstall\NEC2LengthOptimizer"

; Python installer to fetch if Python is not found (64-bit, official python.org)
!define PYTHON_VERSION    "3.12.7"
!define PYTHON_INSTALLER  "python-${PYTHON_VERSION}-amd64.exe"
!define PYTHON_URL          "https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_INSTALLER}"

Name "${APP_NAME}"
OutFile "NEC2_Length_Optimizer_Setup.exe"
Unicode True
InstallDir "$PROGRAMFILES64\NEC2LengthOptimizer"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

; ---------------------------------------------------------------------------
; Interface
; ---------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON   "assets\app.ico"
!define MUI_UNICON "assets\app.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "assets\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_LAUNCHER}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch NEC2 Antenna Length Optimizer now"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------
; Helper: detect Python (any version) by querying 'py -3' / 'python'
; Sets $PythonFound = "1" or "0" and $PythonExe to the path if found.
; ---------------------------------------------------------------------------
Var PythonFound
Var PythonExe

Function DetectPython
    StrCpy $PythonFound "0"
    StrCpy $PythonExe ""

    ; Try the 'py' launcher first (installed by python.org installers)
    nsExec::ExecToStack 'py -3 -c "import sys; print(sys.executable)"'
    Pop $0  ; return code
    Pop $1  ; output
    ${If} $0 == 0
        StrCpy $PythonFound "1"
        StrCpy $PythonExe "py -3"
        Return
    ${EndIf}

    ; Fall back to 'python' on PATH
    nsExec::ExecToStack 'python -c "import sys; print(sys.executable)"'
    Pop $0
    Pop $1
    ${If} $0 == 0
        StrCpy $PythonFound "1"
        StrCpy $PythonExe "python"
        Return
    ${EndIf}
FunctionEnd

; ---------------------------------------------------------------------------
; Section: Install Python (only runs if Python was not detected)
; ---------------------------------------------------------------------------
Section "Python 3 Runtime" SecPython

    Call DetectPython
    ${If} $PythonFound == "1"
        DetailPrint "Python already installed - skipping Python installation."
        Goto python_done
    ${EndIf}

    DetailPrint "Python not found. Downloading Python ${PYTHON_VERSION} (64-bit)..."
    SetOutPath "$TEMP"

    ; Use PowerShell (built into Windows) instead of NSISdl - it handles
    ; HTTPS/TLS1.2 and redirects reliably regardless of NSIS build/locale.
    DetailPrint "  Downloading: ${PYTHON_URL}"
    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri $\'${PYTHON_URL}$\' -OutFile $\'$TEMP\${PYTHON_INSTALLER}$\' -UseBasicParsing } catch { Write-Host $$_.Exception.Message; exit 1 }"'
    Pop $0

    IfFileExists "$TEMP\${PYTHON_INSTALLER}" python_downloaded 0

    DetailPrint "  First attempt failed, retrying once..."
    nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri $\'${PYTHON_URL}$\' -OutFile $\'$TEMP\${PYTHON_INSTALLER}$\' -UseBasicParsing } catch { Write-Host $$_.Exception.Message; exit 1 }"'
    Pop $0

    IfFileExists "$TEMP\${PYTHON_INSTALLER}" python_downloaded 0

    ; ---- Both download attempts failed ----
    MessageBox MB_ICONEXCLAMATION|MB_YESNO \
        "Could not download the Python installer automatically (no internet access, proxy, or firewall block).$\r$\n$\r$\nDo you want to continue the setup anyway?$\r$\n$\r$\nIf you continue, please install Python 3.10+ manually from:$\r$\nhttps://www.python.org/downloads/$\r$\n(check 'Add python.exe to PATH' during install), then re-run this setup to finish installing dependencies." \
        IDYES python_done IDNO 0
    Abort

    python_downloaded:
    DetailPrint "Installing Python ${PYTHON_VERSION} silently (this may take a minute)..."
    ; PrependPath=1 adds Python + Scripts to PATH for all users
    ExecWait '"$TEMP\${PYTHON_INSTALLER}" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1' $0
    ${If} $0 != 0
        MessageBox MB_ICONEXCLAMATION "Python installation returned exit code $0.$\r$\n$\r$\nSetup will continue, but if Python wasn't installed correctly please install it manually from https://www.python.org/downloads/ and re-run this setup afterwards."
    ${EndIf}
    Delete "$TEMP\${PYTHON_INSTALLER}"

    ; Refresh detection after install
    Call DetectPython
    ${If} $PythonFound != "1"
        ; PATH may need a new shell session to refresh - try the default install path
        StrCpy $PythonExe "$PROGRAMFILES64\Python312\python.exe"
        IfFileExists "$PythonExe" 0 +2
            StrCpy $PythonFound "1"
    ${EndIf}

    python_done:
SectionEnd

; ---------------------------------------------------------------------------
; Section: Application files
; ---------------------------------------------------------------------------
Section "Application Files" SecApp

    SetOutPath "$INSTDIR"

    ; -----------------------------------------------------------------
    ; nec2_length_optimizer.py is intentionally NOT embedded/compressed
    ; into this installer.  It is shipped as a loose .py file in the
    ; SAME FOLDER as Setup.exe ($EXEDIR) and is MOVED into $INSTDIR here.
    ;
    ; Distribution layout expected:
    ;   SomeFolder\
    ;     NEC2_Length_Optimizer_Setup.exe
    ;     nec2_length_optimizer.py
    ;     nec2c.exe
    ; -----------------------------------------------------------------
    IfFileExists "$EXEDIR\${APP_EXE_SCRIPT}" 0 script_not_at_exedir
        ; Try a fast rename (move) first; fall back to copy+delete if
        ; $EXEDIR and $INSTDIR are on different volumes (Rename fails
        ; across volumes and sets the error flag).
        ClearErrors
        Rename "$EXEDIR\${APP_EXE_SCRIPT}" "$INSTDIR\${APP_EXE_SCRIPT}"
        IfErrors 0 script_moved
            CopyFiles /SILENT "$EXEDIR\${APP_EXE_SCRIPT}" "$INSTDIR\${APP_EXE_SCRIPT}"
            Delete "$EXEDIR\${APP_EXE_SCRIPT}"
        script_moved:
        Goto script_done

    script_not_at_exedir:
        ; Not found beside Setup.exe -- maybe this is a repair/re-run and
        ; it was already moved into place by a previous run.
        IfFileExists "$INSTDIR\${APP_EXE_SCRIPT}" script_done 0
        MessageBox MB_ICONEXCLAMATION "${APP_EXE_SCRIPT} was not found next to this installer ($EXEDIR) and is not already installed.$\r$\n$\r$\nPlace ${APP_EXE_SCRIPT} in the same folder as Setup.exe and re-run, or copy it manually into:$\r$\n$INSTDIR"

    script_done:

    File "payload\run_gui.bat"
    File "payload\post_install_setup.py"
    File "assets\app.ico"
    File "assets\LICENSE.txt"

SectionEnd

; ---------------------------------------------------------------------------
; Section: NEC2C engine (nec2c.exe) - loaded from beside the installer
;
; nec2c.exe is NOT embedded in this installer.  It must be placed in the
; SAME FOLDER as Setup.exe ($EXEDIR) before running the installer.
;
; Distribution layout:
;   SomeFolder\
;     NEC2_Length_Optimizer_Setup.exe
;     nec2_length_optimizer.py
;     nec2c.exe                        <-- required here
;
; The installer copies nec2c.exe into:
;   - $INSTDIR\nec2c\nec2c.exe         (primary engine location)
;   - C:\Program Files\OpenNEC\nec2c.exe
;   - C:\Program Files (x86)\OpenNEC\nec2c.exe
; ---------------------------------------------------------------------------
Section "NEC2C Engine (nec2c.exe)" SecEngine

    DetailPrint "Installing NEC2C engine (nec2c.exe)..."

    IfFileExists "$EXEDIR\${NEC2C_EXE}" nec2c_found 0
        ; Not beside Setup.exe -- check if already installed (repair run)
        IfFileExists "$INSTDIR\nec2c\${NEC2C_EXE}" nec2c_already_installed 0
        MessageBox MB_ICONEXCLAMATION "${NEC2C_EXE} was not found next to this installer ($EXEDIR).$\r$\n$\r$\nPlace ${NEC2C_EXE} in the same folder as Setup.exe and re-run to install the NEC2C engine, or copy it manually into:$\r$\n$INSTDIR\nec2c"
        Goto nec2c_done

    nec2c_found:
        CreateDirectory "$INSTDIR\nec2c"
        SetOutPath "$INSTDIR\nec2c"
        CopyFiles /SILENT "$EXEDIR\${NEC2C_EXE}" "$INSTDIR\nec2c\${NEC2C_EXE}"

        CreateDirectory "$PROGRAMFILES64\OpenNEC"
        CopyFiles /SILENT "$EXEDIR\${NEC2C_EXE}" "$PROGRAMFILES64\OpenNEC\${NEC2C_EXE}"

        CreateDirectory "$PROGRAMFILES32\OpenNEC"
        CopyFiles /SILENT "$EXEDIR\${NEC2C_EXE}" "$PROGRAMFILES32\OpenNEC\${NEC2C_EXE}"

        DetailPrint "NEC2C engine installed to $INSTDIR\nec2c and $PROGRAMFILES64\OpenNEC."
        Goto nec2c_done

    nec2c_already_installed:
        DetailPrint "nec2c.exe already in $INSTDIR\nec2c - skipping (repair run)."

    nec2c_done:
        SetOutPath "$INSTDIR"

SectionEnd

; ---------------------------------------------------------------------------
; Section: Python dependencies (post-install setup)
; ---------------------------------------------------------------------------
Section "Dependencies" SecDeps

    Call DetectPython
    ${If} $PythonFound != "1"
        DetailPrint "Python is not available - skipping Python package setup."
        DetailPrint "Install Python manually, then re-run this setup to finish (or run post_install_setup.py yourself)."
        MessageBox MB_ICONEXCLAMATION "Python could not be found on this system, so Python packages (numpy, matplotlib, etc.) were not installed.$\r$\n$\r$\nAfter installing Python 3.10+ manually, re-run this setup, or run:$\r$\n  python $\"$INSTDIR\post_install_setup.py$\" $\"$INSTDIR$\""
        Goto deps_done
    ${EndIf}

    DetailPrint "Installing required Python packages..."
    DetailPrint "(numpy, matplotlib, tabulate, colorama, reportlab)"

    ; Use 'cmd /c' so we can use the 'py -3' launcher (two tokens) uniformly
    nsExec::ExecToLog 'cmd /c $PythonExe "$INSTDIR\post_install_setup.py" "$INSTDIR"'
    Pop $0
    ${If} $0 != 0
        MessageBox MB_ICONEXCLAMATION "Some optional setup steps (Python packages) did not complete successfully.$\r$\n$\r$\nYou can re-run:$\r$\n  $PythonExe $\"$INSTDIR\post_install_setup.py$\" $\"$INSTDIR$\"$\r$\nlater."
    ${EndIf}

    deps_done:
SectionEnd

; ---------------------------------------------------------------------------
; Section: Shortcuts
; ---------------------------------------------------------------------------
Section "Shortcuts" SecShortcuts

    CreateDirectory "$SMPROGRAMS\NEC2 Antenna Length Optimizer"
    CreateShortCut "$SMPROGRAMS\NEC2 Antenna Length Optimizer\NEC2 Antenna Length Optimizer.lnk" \
        "$INSTDIR\${APP_LAUNCHER}" "" "$INSTDIR\app.ico" 0
    CreateShortCut "$SMPROGRAMS\NEC2 Antenna Length Optimizer\Uninstall.lnk" \
        "$INSTDIR\Uninstall.exe"

    ; Desktop shortcut (icon to run nec2_length_optimizer.py --gui)
    CreateShortCut "$DESKTOP\NEC2 Antenna Length Optimizer.lnk" \
        "$INSTDIR\${APP_LAUNCHER}" "" "$INSTDIR\app.ico" 0

SectionEnd

; ---------------------------------------------------------------------------
; Section: Uninstaller registration
; ---------------------------------------------------------------------------
Section -FinishSection

    WriteUninstaller "$INSTDIR\Uninstall.exe"

    WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\app.ico"
    WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
    WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"

SectionEnd

; ---------------------------------------------------------------------------
; Uninstaller
; ---------------------------------------------------------------------------
Section "Uninstall"

    Delete "$INSTDIR\${APP_EXE_SCRIPT}"
    Delete "$INSTDIR\${APP_LAUNCHER}"
    Delete "$INSTDIR\post_install_setup.py"
    Delete "$INSTDIR\set_nec2c_env.bat"
    Delete "$INSTDIR\app.ico"
    Delete "$INSTDIR\LICENSE.txt"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir /r "$INSTDIR\nec2c"
    RMDir /r "$INSTDIR\__pycache__"

    ; Remove the OpenNEC copies placed in Program Files
    Delete "$PROGRAMFILES64\OpenNEC\${NEC2C_EXE}"
    RMDir "$PROGRAMFILES64\OpenNEC"
    Delete "$PROGRAMFILES32\OpenNEC\${NEC2C_EXE}"
    RMDir "$PROGRAMFILES32\OpenNEC"

    ; If the user left generated reports/plots/CSVs in the install dir,
    ; ask before wiping the whole folder; otherwise just remove it.
    FindFirst $0 $1 "$INSTDIR\*.*"
    StrCpy $2 "0"
    leftover_loop:
        StrCmp $1 "" leftover_done
        StrCmp $1 "." leftover_next
        StrCmp $1 ".." leftover_next
        StrCpy $2 "1"
        Goto leftover_done
    leftover_next:
        FindNext $0 $1
        Goto leftover_loop
    leftover_done:
        FindClose $0

    ${If} $2 == "1"
        MessageBox MB_ICONQUESTION|MB_YESNO \
            "The folder$\r$\n$INSTDIR$\r$\nstill contains files (e.g. generated reports, plots, or CSVs).$\r$\n$\r$\nDelete this folder and all its contents?" \
            IDYES remove_instdir IDNO keep_instdir
        remove_instdir:
            RMDir /r "$INSTDIR"
        keep_instdir:
    ${Else}
        RMDir "$INSTDIR"
    ${EndIf}

    Delete "$DESKTOP\NEC2 Antenna Length Optimizer.lnk"
    Delete "$SMPROGRAMS\NEC2 Antenna Length Optimizer\NEC2 Antenna Length Optimizer.lnk"
    Delete "$SMPROGRAMS\NEC2 Antenna Length Optimizer\Uninstall.lnk"
    RMDir "$SMPROGRAMS\NEC2 Antenna Length Optimizer"

    DeleteRegKey HKLM "${UNINST_KEY}"

    MessageBox MB_ICONINFORMATION|MB_OK "NEC2 Antenna Length Optimizer has been removed from your computer.$\r$\n$\r$\nNote: Python and its packages (numpy, matplotlib, etc.) were left installed, as they may be used by other programs. Uninstall Python separately via 'Add or Remove Programs' if no longer needed."

SectionEnd
