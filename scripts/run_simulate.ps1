# Startet das Telemetry-Backend im Simulationsmodus (Windows PowerShell).
# Nutzung: .\scripts\run_simulate.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "pc-backend"

# Go finden (PATH oder Standard-Installationspfad)
$go = Get-Command go -ErrorAction SilentlyContinue
if (-not $go) {
    $goExe = "C:\Program Files\Go\bin\go.exe"
    if (Test-Path $goExe) {
        $go = @{ Source = $goExe }
    } else {
        Write-Error "Go nicht gefunden. Bitte Go 1.22+ installieren: https://go.dev/dl/"
        exit 1
    }
}
$goCmd = if ($go.Source) { $go.Source } else { "go" }

Write-Host "Go: $(& $goCmd version)"
Write-Host "Starte Backend im Simulate-Modus..."
Write-Host "  HTTP:      http://localhost:8080"
Write-Host "  WebSocket: ws://localhost:9001/stream"
Write-Host ""

Set-Location $Backend

# Abhängigkeiten synchronisieren falls go.sum fehlt
if (-not (Test-Path "go.sum")) {
    Write-Host "go mod tidy ..."
    & $goCmd mod tidy
}

& $goCmd run . --simulate
