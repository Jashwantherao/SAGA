$ErrorActionPreference = "Stop"

function Test-MsvcLinker {
    if (Get-Command link.exe -ErrorAction SilentlyContinue) { return $true }

    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere)) { return $false }
    $installation = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    return -not [string]::IsNullOrWhiteSpace($installation)
}

if (-not (Test-MsvcLinker)) {
    throw @"
Microsoft C++ Build Tools are required by Tauri but were not found.
Install Visual Studio Build Tools 2022 with the 'Desktop development with C++' workload,
then open a new PowerShell window and run npm run desktop again.

Suggested D:-first install command (Microsoft will still use C: for shared installer/SDK data):
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --installPath D:\BuildTools --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
"@
}

function Get-ListenerPid([int]$Port) {
    $match = netstat -ano -p tcp |
        Select-String -Pattern "127\.0\.0\.1:$Port\s+.*LISTENING\s+(\d+)$" |
        Select-Object -First 1
    if (-not $match) { return $null }
    return [int]$match.Matches[0].Groups[1].Value
}

function Test-SagaEndpoint([int]$Port) {
    try {
        $url = if ($Port -eq 8765) {
            "http://127.0.0.1:8765/api/health"
        } else {
            "http://127.0.0.1:5173/"
        }
        $response = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 3
        if ($Port -eq 8765) {
            return $response.Content -match '"checks"' -and
                $response.Content -match '"settings"' -and
                $response.Content -match '"output_root"'
        }
        return $response.Content -match '<title>SAGA Studio</title>'
    } catch {
        return $false
    }
}

$blocked = @()
foreach ($port in 5173, 8765) {
    $listenerPid = Get-ListenerPid $port
    if (-not $listenerPid) { continue }

    if (-not (Test-SagaEndpoint $port)) {
        $blocked += "Port $port is owned by non-SAGA PID $listenerPid"
        continue
    }

    Write-Host "Stopping stale SAGA listener on port $port (PID $listenerPid)..."
    Stop-Process -Id $listenerPid -Force
}

if ($blocked.Count) {
    throw ($blocked -join "; ")
}

Start-Sleep -Milliseconds 500
foreach ($port in 5173, 8765) {
    $listenerPid = Get-ListenerPid $port
    if ($listenerPid) {
        throw "SAGA development port $port is still occupied by PID $listenerPid"
    }
}
