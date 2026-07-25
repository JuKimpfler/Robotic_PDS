# ======================================================================
#  start_hotspot.ps1
#  Startet den "RoboDebug"-WLAN-Hotspot automatisch beim Systemstart.
#  Wird ueber die Aufgabenplanung (Task "RoboDebug_Hotspot", Trigger:
#  "Beim Start", Benutzer: SYSTEM) ausgefuehrt - also bereits VOR dem
#  Login. Funktioniert auf 32- und 64-bit Windows 10 gleichermassen.
#
#  Vorgehen:
#    Pfad A: klassischer "Hosted Network"-Modus (netsh). Benoetigt
#            KEINEN Internet-Uplink - ideal fuer reine Telemetrie
#            zwischen PC und Raspberry Pi. Wird bevorzugt, wenn der
#            WLAN-Treiber es unterstuetzt.
#    Pfad B: Windows "Mobile Hotspot" ueber die WinRT-API. Setzt voraus,
#            dass der Hotspot einmalig manuell in den Einstellungen
#            konfiguriert wurde (SSID/Passwort werden dabei gespeichert
#            und von StartTetheringAsync() wiederverwendet).
# ======================================================================

$ssid = "RoboDebug"
$key  = "robodebug123"

$logDir  = "$env:ProgramData\RoboDebug"
$logFile = "$logDir\hotspot.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Log([string]$msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -Append -FilePath $logFile -Encoding utf8
}

Log "---- Hotspot-Start ausgeloest ----"

# WLAN-Dienst abwarten (kann beim Systemstart noch nicht bereit sein,
# insbesondere auf langsamer Atom-Hardware)
$svc = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
$tries = 0
while ($svc -and $svc.Status -ne 'Running' -and $tries -lt 20) {
    Start-Sleep -Seconds 2
    $svc = Get-Service -Name WlanSvc -ErrorAction SilentlyContinue
    $tries++
}
Log "WlanSvc Status: $($svc.Status) (nach $tries Wartezyklen)"

# --- Pfad A: Hosted Network (netsh) ---
netsh wlan set hostednetwork mode=allow ssid=$ssid key=$key | Out-Null
netsh wlan start hostednetwork | Out-Null

if ($LASTEXITCODE -eq 0) {
    Log "Hosted Network erfolgreich gestartet (Pfad A). SSID=$ssid"
    exit 0
}

Log "Hosted Network fehlgeschlagen (ExitCode $LASTEXITCODE) - versuche Mobile Hotspot (Pfad B)."

# --- Pfad B: WinRT Mobile Hotspot ---
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()

    if ($null -eq $connectionProfile) {
        Log "WARNUNG: Kein Internet-Verbindungsprofil gefunden. Ohne aktive Netzwerkverbindung (z.B. Ethernet oder ein anderes WLAN) kann die Mobile-Hotspot-API u.U. keinen Tethering-Manager erzeugen."
    }

    $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)

    if ($tetheringManager.TetheringOperationalState -eq 1) {
        Log "Mobile Hotspot war bereits aktiv."
    } else {
        $tetheringManager.StartTetheringAsync() | Out-Null
        Start-Sleep -Seconds 3
        Log "Mobile-Hotspot-Start angestossen (Pfad B). Aktueller Status: $($tetheringManager.TetheringOperationalState)"
    }
} catch {
    Log "Pfad B ebenfalls fehlgeschlagen: $($_.Exception.Message)"
    Log "Hinweis: Falls noch nie manuell eingerichtet, bitte einmalig unter"
    Log "Einstellungen > Netzwerk und Internet > Mobiler Hotspot SSID/Passwort setzen."
}
