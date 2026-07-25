@echo off
setlocal EnableDelayedExpansion

:: ======================================================================
::   Power Debug Monitor - Windows 10 Schnell-Setup (32-bit, PyQt5)
:: ======================================================================
::  Reihenfolge beim Booten, die dieses Skript einrichtet:
::    1. Systemstart (vor Login)  -> Task "RoboDebug_Hotspot" (SYSTEM)
::       startet den WLAN-Hotspot ueber start_hotspot.ps1
::    2. Login (Autologin)        -> Task "RoboDebug_GUI" startet die
::       Python-GUI im Vollbild, mit Verzoegerung, damit der Hotspot
::       bereits steht
::
::  Erwartete Ordnerstruktur:
::    ...\pc_setup\setup_windows.bat   <- dieses Skript
::    ...\pc_setup\start_hotspot.ps1   <- muss danebenliegen
::    ...\requirements.txt
::    ...\rpi5_monitor\...             <- GUI-Code
:: ======================================================================

:: --- Admin-Pruefung ---
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Dieses Skript benoetigt Administratorrechte.
    echo Bitte per Rechtsklick "Als Administrator ausfuehren" starten.
    pause
    exit /b 1
)

echo =======================================================
echo     Power Debug Monitor - Windows 10 PC Setup
echo =======================================================

set "SETUP_DIR=%~dp0"
set "APP_DIR=%~dp0.."
set "HOTSPOT_PS1=%SETUP_DIR%start_hotspot.ps1"

if not exist "%HOTSPOT_PS1%" (
    echo   FEHLER: start_hotspot.ps1 wurde nicht neben diesem Skript gefunden.
    echo   Erwarteter Pfad: %HOTSPOT_PS1%
    pause
    exit /b 1
)

:: ======================================================================
::  SCHRITT 1 - Python automatisch finden
:: ======================================================================
echo.
echo [1/8] Python-Installation suchen ...

set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
    )
)
if not defined PYTHON_EXE (
    echo   Python wurde nicht gefunden.
    echo   Bitte zuerst Python 3.x installieren: https://www.python.org/downloads/
    echo   ^(Haekchen "Add python.exe to PATH" beim Installer nicht vergessen^)
    pause
    exit /b 1
)
set "PYTHONW_EXE=%PYTHON_EXE:python.exe=pythonw.exe%"
echo   Gefunden: %PYTHON_EXE%

:: ======================================================================
::  SCHRITT 2 - Firewall-Regeln
:: ======================================================================
echo.
echo [2/8] Windows Firewall konfigurieren ...
netsh advfirewall firewall show rule name="RoboDebug UDP Port 5001" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="RoboDebug UDP Port 5001" dir=in action=allow protocol=UDP localport=5001 >nul
)
netsh advfirewall firewall show rule name="RoboDebug UDP Port 5002" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="RoboDebug UDP Port 5002" dir=in action=allow protocol=UDP localport=5002 >nul
)
echo   Firewall-Regeln gesetzt.

:: ======================================================================
::  SCHRITT 3 - Python-Abhaengigkeiten (PyQt5)
:: ======================================================================
echo.
echo [3/8] Python-Abhaengigkeiten installieren ...
if exist "%APP_DIR%\requirements.txt" (
    "%PYTHON_EXE%" -m pip install --upgrade pip >nul
    "%PYTHON_EXE%" -m pip install -r "%APP_DIR%\requirements.txt"
) else (
    echo   requirements.txt nicht gefunden - installiere Basispakete direkt.
    "%PYTHON_EXE%" -m pip install "PyQt5>=5.15.0" "pyqtgraph>=0.13.3" "numpy>=1.24.0"
)
echo   Abhaengigkeiten bereit.

:: ======================================================================
::  SCHRITT 4 - Performance-Optimierungen (schwache Hardware, z.B. Atom/2GB)
:: ======================================================================
echo.
echo [4/8] Performance-Optimierungen anwenden ...
powercfg -setactive SCHEME_MIN >nul 2>&1
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -disk-timeout-ac 0 >nul 2>&1
sc config "SysMain" start= disabled >nul 2>&1
sc stop "SysMain" >nul 2>&1
sc config "WSearch" start= disabled >nul 2>&1
sc stop "WSearch" >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" /v VisualFXSetting /t REG_DWORD /d 2 /f >nul 2>&1
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f >nul 2>&1
echo   Energieplan, Hintergrunddienste und Effekte angepasst.

:: ======================================================================
::  SCHRITT 5 - Autologin einrichten
:: ======================================================================
echo.
echo [5/8] Autologin einrichten
echo   ^(Passwort wird im Klartext in der Registry gespeichert - Standard-
echo    verfahren von Windows ^(wie "netplwiz"^). Nur auf einem physisch
echo    abgesicherten Debug-Geraet verwenden.^)
echo.
set "WINUSER=%USERNAME%"
set /p SETUP_AUTOLOGIN="Autologin jetzt einrichten? [j/N] "
if /i "%SETUP_AUTOLOGIN%"=="j" (
    set /p WINUSER="  Windows-Benutzername [%USERNAME%]: "
    if "!WINUSER!"=="" set "WINUSER=%USERNAME%"
    set /p WINPASS="  Windows-Passwort: "
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d "!WINUSER!" /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "!WINPASS!" /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultDomainName /t REG_SZ /d "%COMPUTERNAME%" /f >nul
    echo   Autologin fuer "!WINUSER!" eingerichtet.
) else (
    echo   Autologin uebersprungen - Task "RoboDebug_GUI" wird trotzdem fuer
    echo   den Benutzer "!WINUSER!" eingerichtet und startet beim naechsten
    echo   ^(manuellen^) Login.
)

:: ======================================================================
::  SCHRITT 6 - Alte Startup-Verknuepfung entfernen (falls vorhanden)
:: ======================================================================
echo.
echo [6/8] Alte Autostart-Methode aufraeumen ...
set "OLD_SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PowerDebugMonitor.lnk"
if exist "%OLD_SHORTCUT%" (
    del /q "%OLD_SHORTCUT%"
    echo   Alte Verknuepfung entfernt: %OLD_SHORTCUT%
) else (
    echo   Keine alte Verknuepfung gefunden - ueberspringe.
)

:: ======================================================================
::  SCHRITT 7 - Task Scheduler: Hotspot (bei Systemstart) + GUI (bei Login)
:: ======================================================================
echo.
echo [7/8] Aufgabenplanung einrichten ...

:: GUI-Einstiegspunkt automatisch finden
set "GUI_SCRIPT="
if exist "%APP_DIR%\rpi5_monitor\New_PyQT_QML\main_qml.py" (
    set "GUI_SCRIPT=%APP_DIR%\rpi5_monitor\New_PyQT_QML\main_qml.py"
) else if exist "%APP_DIR%\rpi5_monitor\main.py" (
    set "GUI_SCRIPT=%APP_DIR%\rpi5_monitor\main.py"
)

if not defined GUI_SCRIPT (
    echo   WARNUNG: Kein GUI-Einstiegspunkt gefunden ^(main_qml.py / main.py^).
    echo   Task "RoboDebug_GUI" wird uebersprungen - bitte Pfad pruefen.
) else (
    :: kleiner Wrapper, der zuerst ins richtige Arbeitsverzeichnis wechselt
    :: (haeufigste Fehlerursache bei Autostart: falsches Arbeitsverzeichnis
    :: -> QML-/Ressourcendateien werden nicht gefunden)
    set "GUI_WRAPPER=%SETUP_DIR%start_gui.bat"
    (
        echo @echo off
        echo cd /d "%APP_DIR%\rpi5_monitor"
        echo start "" "%PYTHONW_EXE%" "%GUI_SCRIPT%"
    ) > "!GUI_WRAPPER!"
    echo   Wrapper erstellt: !GUI_WRAPPER!

    schtasks /create /tn "RoboDebug_GUI" ^
        /tr "\"!GUI_WRAPPER!\"" ^
        /sc onlogon /ru "!WINUSER!" /delay 0000:20 /rl highest /f >nul
    echo   Task "RoboDebug_GUI" angelegt: startet 20s nach Login von "!WINUSER!".
)

schtasks /create /tn "RoboDebug_Hotspot" ^
    /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%HOTSPOT_PS1%\"" ^
    /sc onstart /delay 0000:15 /ru SYSTEM /rl highest /f >nul
echo   Task "RoboDebug_Hotspot" angelegt: startet 15s nach Systemstart als SYSTEM.

echo.
echo   Hinweis: Falls dein WLAN-Treiber "Hosted Network" NICHT unterstuetzt,
echo   muss der Mobile Hotspot ^(SSID "RoboDebug"^) einmalig manuell unter
echo   Einstellungen ^> Netzwerk und Internet ^> Mobiler Hotspot eingerichtet
echo   werden - das Skript nutzt danach automatisch den Fallback-Weg.
echo.
set /p OPEN_HOTSPOT_SETTINGS="Hotspot-Einstellungen jetzt zur Kontrolle oeffnen? [j/N] "
if /i "%OPEN_HOTSPOT_SETTINGS%"=="j" start ms-settings:network-mobilehotspot

:: ======================================================================
::  SCHRITT 8 - Test
:: ======================================================================
echo.
echo [8/8] Setup abgeschlossen.
echo.
set /p TEST_NOW="Hotspot-Task und GUI jetzt zum Test manuell ausloesen? [j/N] "
if /i "%TEST_NOW%"=="j" (
    echo   Starte Hotspot-Task ...
    schtasks /run /tn "RoboDebug_Hotspot"
    timeout /t 5 >nul
    echo   Pruefe Log: %ProgramData%\RoboDebug\hotspot.log
    type "%ProgramData%\RoboDebug\hotspot.log" 2>nul
    if defined GUI_SCRIPT (
        echo   Starte GUI-Task ...
        schtasks /run /tn "RoboDebug_GUI"
    )
)

echo.
echo =======================================================
echo   Fertig. Ab dem naechsten Neustart:
echo   1. Hotspot startet ~15s nach dem Booten (Task "RoboDebug_Hotspot")
echo   2. GUI startet ~20s nach dem Login (Task "RoboDebug_GUI")
echo.
echo   Zum Debuggen bei Problemen:
echo   - Task Scheduler ^> Bibliothek ^> RoboDebug_Hotspot / RoboDebug_GUI
echo     ^(rechte Maustaste ^> Alle Tasks-Verlaeufe aktivieren, dann
echo     Reiter "Verlauf" pruefen^)
echo   - Log-Datei: %%ProgramData%%\RoboDebug\hotspot.log
echo =======================================================
pause
