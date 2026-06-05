# install_windows.ps1
# Deploys Firewall rules for Telemetry Streamer. Requires Administrator execution.

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Dieses Skript muss als Administrator ausgefuehrt werden!"
    Write-Host "Bitte oeffnen Sie PowerShell als Administrator und fuehren Sie das Skript erneut aus."
    Exit
}

Write-Host "Richte Windows-Firewallregel fuer Port 9000 (UDP) ein..."
netsh advfirewall firewall add rule name="TelemetryBridge" protocol=UDP dir=in localport=9000 action=allow

Write-Host "Firewallregel erfolgreich hinzugefuegt!"
