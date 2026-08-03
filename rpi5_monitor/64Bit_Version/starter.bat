@echo off
REM ============================================================
REM  Power Debug Monitor — Start unter Windows
REM ============================================================
REM  Startet die QML-Oberflaeche (main_qml.py) relativ zum Ort
REM  dieser Datei. Vorher standen hier ein fest verdrahteter
REM  Benutzerpfad und "rpi5_monitor\main.py" -- beides existiert
REM  auf keinem anderen Rechner bzw. gar nicht mehr an der Stelle.
REM
REM  Optional: --simulate  (synthetische Testdaten ohne Teensy)
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 main_qml.py %*
) else (
    python main_qml.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FEHLER] Start fehlgeschlagen ^(Exit-Code %ERRORLEVEL%^).
    echo Abhaengigkeiten installieren mit:
    echo     pip install PyQt6 numpy pygame
)
pause
endlocal
