@echo off
setlocal EnableDelayedExpansion

:: Check for administrative privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo This script requires administrative privileges. Please run as administrator.
    pause
    exit /b 1
)

echo =======================================================
echo     Power Debug Monitor - Windows 11 PC Setup
echo =======================================================

:: Firewall Rules
echo.
echo Configuring Windows Firewall...
netsh advfirewall firewall add rule name="RoboDebug UDP Port 5001" dir=in action=allow protocol=UDP localport=5001 >nul
netsh advfirewall firewall add rule name="RoboDebug UDP Port 5002" dir=in action=allow protocol=UDP localport=5002 >nul
echo Firewall rules added successfully.

:: Python Dependencies
echo.
echo Installing Python dependencies...
if exist "%~dp0..\requirements.txt" (
    "C:\Users\Roboter AG\AppData\Local\Programs\Python\Python314\python.exe" -m pip install -r "%~dp0..\requirements.txt"
) else (
    echo requirements.txt not found.
)

:: Hotspot
echo.
echo =======================================================
echo                    WICHTIGER HINWEIS
echo =======================================================
echo Auf Windows 11 wird der alte 'hostednetwork' Modus 
echo von WLAN-Treibern (wie Intel AX201) NICHT unterstuetzt.
echo.
echo Bitte nutze den integrierten Windows Mobile Hotspot!
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

:: Launch GUI
echo.
echo Starting Power Debug Monitor GUI...
cd "%~dp0.."
"C:\Users\Roboter AG\AppData\Local\Programs\Python\Python314\python.exe" rpi5_monitor\main.py

pause
