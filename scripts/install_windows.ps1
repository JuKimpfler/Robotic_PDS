# install_windows.ps1
# One-time Windows setup: firewall rule, Go check, frontend build.
# Requires Administrator for firewall rule.

param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Warning "Firewall-Regel erfordert Administratorrechte."
    Write-Host "Bitte PowerShell als Administrator starten fuer die Firewall-Konfiguration."
}

# ── Firewall: UDP 9000 inbound ───────────────────────────────────────────────
if (Test-Admin) {
    Write-Host "Richte Windows-Firewallregel fuer UDP Port 9000 ein..."
    netsh advfirewall firewall add rule name="TelemetryBridge" protocol=UDP dir=in localport=9000 action=allow 2>$null
    Write-Host "Firewallregel OK."
} else {
    Write-Host "Firewall-Regel uebersprungen (kein Admin)."
}

# ── Go Installation pruefen ──────────────────────────────────────────────────
Write-Host "Pruefe Go-Installation..."
$goCmd = Get-Command go -ErrorAction SilentlyContinue
if (-not $goCmd) {
    Write-Error "Go ist nicht installiert. Bitte Go 1.22+ von https://go.dev/dl/ installieren."
    exit 1
}
$goVersion = go version
Write-Host "  $goVersion"

# ── Node.js pruefen (fuer Frontend-Build) ────────────────────────────────────
Write-Host "Pruefe Node.js..."
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Warning "Node.js nicht gefunden — Frontend-Build wird uebersprungen."
    $SkipBuild = $true
} else {
    Write-Host "  $(node --version)"
}

# ── Frontend bauen ───────────────────────────────────────────────────────────
if (-not $SkipBuild) {
    $frontendDir = Join-Path $PSScriptRoot ".." "frontend"
    Write-Host "Baue Frontend nach pc-backend/frontend/dist ..."
    Push-Location $frontendDir
    if (-not (Test-Path "node_modules")) {
        npm install
    }
    npm run build
    Pop-Location
    Write-Host "Frontend-Build abgeschlossen."
}

# ── Go Backend bauen ─────────────────────────────────────────────────────────
$backendDir = Join-Path $PSScriptRoot ".." "pc-backend"
Write-Host "Baue Go Backend..."
Push-Location $backendDir
go build -o bin/telemetry.exe .
Pop-Location
Write-Host "Backend-Binary: pc-backend/bin/telemetry.exe"

Write-Host ""
Write-Host "Installation abgeschlossen. Starten mit:"
Write-Host "  cd pc-backend"
Write-Host "  go run . --simulate"
Write-Host "  -> http://localhost:8080"
