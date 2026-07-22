@echo off
setlocal EnableDelayedExpansion

:: ======================================================================
::   Power Debug Monitor - Windows 10 Schnell-Setup (Debug-PC / Acer One 10)
:: ======================================================================
::  Fuer den Neuaufsatz nach frischer Windows 10 (64-bit) Installation.
::  Erledigt in einem Durchgang:
::    1. Python automatisch finden (kein hartcodierter Pfad mehr)
::    2. Firewall-Regeln
::    3. Python-Abhaengigkeiten (PyQt6 etc.)
::    4. Performance-Optimierungen fuer schwache Hardware (Atom/2GB RAM)
::    5. Autologin einrichten
::    6. Autostart-Verknuepfung (Kiosk, kein Konsolenfenster)
::    7. WLAN-Hotspot Hinweis
::    8. GUI zum Test starten
::
::  Aufruf: als Administrator ausfuehren, im Ordner pc_setup\ liegend
::  (erwartet ..\requirements.txt und ..\rpi5_monitor\ eine Ebene hoeher)
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

set "APP_DIR=%~dp0.."

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
    echo   Bitte zuerst Python 3.x ^(64-bit^) installieren:
    echo   https://www.python.org/downloads/
    echo   ^(Haekchen "Add python.exe to PATH" beim Installer nicht vergessen^)
    pause
    exit /b 1
)

:: pythonw.exe liegt im selben Ordner wie python.exe (kein Konsolenfenster)
set "PYTHONW_EXE=%PYTHON_EXE:python.exe=pythonw.exe%"
echo   Gefunden: %PYTHON_EXE%

:: 64-bit pruefen: PyQt6-Wheels gibt es auf PyPI nur fuer win_amd64 -
:: unter 32-bit Python schlaegt "pip install PyQt6" fehl.
"%PYTHON_EXE%" -c "import struct,sys; sys.exit(0 if struct.calcsize('P')*8==64 else 1)"
if errorlevel 1 (
    echo.
    echo   WARNUNG: Es wurde eine 32-bit Python-Installation gefunden.
    echo   PyQt6 stellt auf PyPI keine 32-bit-Wheels mehr bereit -
    echo   die Installation der Abhaengigkeiten wird fehlschlagen.
    echo   Bitte 64-bit Python ^(und ggf. 64-bit Windows^) installieren.
    pause
)

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
::  SCHRITT 3 - Python-Abhaengigkeiten
:: ======================================================================
echo.
echo [3/8] Python-Abhaengigkeiten installieren ...
if exist "%APP_DIR%\requirements.txt" (
    "%PYTHON_EXE%" -m pip install --upgrade pip >nul
    "%PYTHON_EXE%" -m pip install -r "%APP_DIR%\requirements.txt"
) else (
    echo   requirements.txt nicht gefunden - installiere Basispakete direkt.
    "%PYTHON_EXE%" -m pip install "PyQt5" "pyqtgraph" "numpy"
)
echo   Abhaengigkeiten bereit.

:: ======================================================================
::  SCHRITT 4 - Performance-Optimierungen (schwache Hardware, z.B. Atom/2GB)
:: ======================================================================
echo.
echo [4/8] Performance-Optimierungen anwenden ...

:: Hoechstleistungs-Energieplan aktivieren
powercfg -setactive SCHEME_MIN >nul 2>&1

:: Bildschirm/Standby/Ruhezustand nie automatisch abschalten (Kiosk-Betrieb)
powercfg -change -monitor-timeout-ac 0 >nul 2>&1
powercfg -change -standby-timeout-ac 0 >nul 2>&1
powercfg -change -hibernate-timeout-ac 0 >nul 2>&1
powercfg -change -disk-timeout-ac 0 >nul 2>&1

:: SysMain (Superfetch) und Windows Search deaktivieren - spart RAM/IO
sc config "SysMain" start= disabled >nul 2>&1
sc stop "SysMain" >nul 2>&1
sc config "WSearch" start= disabled >nul 2>&1
sc stop "WSearch" >nul 2>&1

:: Visuelle Effekte auf "Beste Leistung"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" /v VisualFXSetting /t REG_DWORD /d 2 /f >nul 2>&1

:: Windows Update automatische Neustarts unterbinden (kein ungewollter Reboot im Feldbetrieb)
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f >nul 2>&1

echo   Energieplan, Hintergrunddienste und Effekte angepasst.

:: ======================================================================
::  SCHRITT 5 - Autologin einrichten
:: ======================================================================
echo.
echo [5/8] Autologin einrichten
echo   ^(Passwort wird im Klartext in der Registry gespeichert - Standard-
echo    verfahren von Windows, siehe auch "netplwiz". Nur auf einem
echo    physisch abgesicherten Debug-Geraet verwenden.^)
echo.
set /p SETUP_AUTOLOGIN="Autologin jetzt einrichten? [j/N] "
if /i "%SETUP_AUTOLOGIN%"=="j" (
    set /p WINUSER="  Windows-Benutzername: "
    set /p WINPASS="  Windows-Passwort: "
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d "!WINUSER!" /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultPassword /t REG_SZ /d "!WINPASS!" /f >nul
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultDomainName /t REG_SZ /d "%COMPUTERNAME%" /f >nul
    echo   Autologin fuer "!WINUSER!" eingerichtet.
) else (
    echo   Autologin uebersprungen - kann spaeter per "netplwiz" nachgeholt werden.
)

:: ======================================================================
::  SCHRITT 6 - Autostart einrichten (Kiosk, ohne Konsolenfenster)
:: ======================================================================
echo.
echo [6/8] Autostart-Verknuepfung erstellen ...

:: GUI-Einstiegspunkt automatisch finden: bevorzugt die neue QML-GUI,
:: Fallback auf die aeltere main.py (Struktur analog setup_rpi5.sh).
set "GUI_SCRIPT="
if exist "%APP_DIR%\rpi5_monitor\New_PyQT_QML\main_qml.py" (
    set "GUI_SCRIPT=%APP_DIR%\rpi5_monitor\New_PyQT_QML\main_qml.py"
) else if exist "%APP_DIR%\rpi5_monitor\main.py" (
    set "GUI_SCRIPT=%APP_DIR%\rpi5_monitor\main.py"
)

if not defined GUI_SCRIPT (
    echo   WARNUNG: Kein GUI-Einstiegspunkt gefunden ^(main_qml.py / main.py^).
    echo   Autostart-Verknuepfung wird uebersprungen - bitte Pfad pruefen.
) else (
    set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    powershell -NoProfile -Command ^
      "$s = (New-Object -COM WScript.Shell).CreateShortcut('%STARTUP_DIR%\PowerDebugMonitor.lnk');" ^
      "$s.TargetPath = '%PYTHONW_EXE%';" ^
      "$s.Arguments = '\"%GUI_SCRIPT%\"';" ^
      "$s.WorkingDirectory = '%APP_DIR%\rpi5_monitor';" ^
      "$s.WindowStyle = 1;" ^
      "$s.Save()"
    echo   Autostart-Verknuepfung angelegt: %STARTUP_DIR%\PowerDebugMonitor.lnk
    echo   Startet: %GUI_SCRIPT%
    echo   Hinweis: showFullScreen^(^) muss in der App selbst beim Start
    echo   aufgerufen werden, damit sie automatisch im Vollbild oeffnet.
)

:: ======================================================================
::  SCHRITT 7 - WLAN Hotspot
:: ======================================================================
echo.
echo [7/8] WLAN-Hotspot einrichten
echo =======================================================
echo                    WICHTIGER HINWEIS
echo =======================================================
echo Windows 10 unterstuetzt je nach WLAN-Treiber entweder den
echo integrierten Mobile Hotspot ODER den alten "hostednetwork"-Modus.
echo.
echo Falls der Treiber "hostednetwork" unterstuetzt, kann folgender
echo Befehl manuell verwendet werden ^(einmalig^):
echo   netsh wlan set hostednetwork mode=allow ssid=RoboDebug key=robodebug123
echo   netsh wlan start hostednetwork
echo.
echo Ansonsten bitte den integrierten Mobile Hotspot verwenden:
echo 1. Das Hotspot-Einstellungsfenster oeffnet sich nun.
echo 2. Aktiviere den Mobile Hotspot.
echo 3. Bearbeite die Eigenschaften:
echo    - Netzwerkname: RoboDebug
echo    - Passwort:     robodebug123
echo 4. Verbinde den Raspberry Pi Zero mit diesem Hotspot.
echo =======================================================
echo.
start ms-settings:network-mobilehotspot
pause

:: ======================================================================
::  SCHRITT 8 - GUI zum Test starten
:: ======================================================================
echo.
echo [8/8] Setup abgeschlossen.
echo.
set /p START_NOW="GUI jetzt zum Test starten? [j/N] "
if /i "%START_NOW%"=="j" (
    if defined GUI_SCRIPT (
        cd /d "%APP_DIR%\rpi5_monitor"
        "%PYTHON_EXE%" "%GUI_SCRIPT%"
    ) else (
        echo   Kein GUI-Script gefunden - Start uebersprungen.
    )
)

echo.
echo =======================================================
echo   Setup abgeschlossen. Ab dem naechsten Neustart:
echo   - Autologin ^(falls eingerichtet^)
echo   - GUI startet automatisch im Autostart-Ordner
echo =======================================================
pause
