[CmdletBinding()]
param(
    [string]$DestinationRoot = 'D:\CodexData'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-CodexIsClosed {
    $running = Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessName -like 'Codex*' -or
            $_.ProcessName -like 'OpenAI.Codex*'
        }

    if ($running) {
        $names = ($running.ProcessName | Sort-Object -Unique) -join ', '
        throw "Codex is still running ($names). Close Codex completely, then run this script again."
    }
}

function Get-AvailableBackupPath {
    param([Parameter(Mandatory)][string]$Path)

    $candidate = "$Path.backup"
    if (-not (Test-Path -LiteralPath $candidate)) {
        return $candidate
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    return "$Path.backup-$stamp"
}

function Move-WithJunction {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Warning "Skipping missing source: $Source"
        return
    }

    $sourceItem = Get-Item -LiteralPath $Source -Force
    if ($sourceItem.LinkType -eq 'Junction') {
        Write-Host "Already migrated: $Source -> $($sourceItem.Target)"
        return
    }

    if (Test-Path -LiteralPath $Destination) {
        $destinationItem = Get-Item -LiteralPath $Destination -Force
        if (-not $destinationItem.PSIsContainer) {
            throw "Destination exists and is not a directory: $Destination"
        }

        if (Get-ChildItem -LiteralPath $Destination -Force -ErrorAction SilentlyContinue) {
            throw "Destination is not empty: $Destination. Move or remove it before retrying."
        }
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    Write-Host "`nCopying:"
    Write-Host "  $Source"
    Write-Host "  -> $Destination"

    & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -gt 7) {
        throw "Robocopy failed for $Source with exit code $robocopyExitCode."
    }

    $sourceFileCount = @(Get-ChildItem -LiteralPath $Source -File -Force -Recurse).Count
    $destinationFileCount = @(Get-ChildItem -LiteralPath $Destination -File -Force -Recurse).Count
    if ($sourceFileCount -ne $destinationFileCount) {
        throw "Verification failed for $Source. Source files: $sourceFileCount; destination files: $destinationFileCount."
    }

    $backupPath = Get-AvailableBackupPath -Path $Source
    Move-Item -LiteralPath $Source -Destination $backupPath

    try {
        New-Item -ItemType Junction -Path $Source -Target $Destination | Out-Null
    } catch {
        Move-Item -LiteralPath $backupPath -Destination $Source
        throw
    }

    $junction = Get-Item -LiteralPath $Source -Force
    if ($junction.LinkType -ne 'Junction') {
        Remove-Item -LiteralPath $Source -Force
        Move-Item -LiteralPath $backupPath -Destination $Source
        throw "Junction verification failed for $Source. The original directory was restored."
    }

    Write-Host "Migrated successfully."
    Write-Host "Backup retained at: $backupPath"
}

Assert-CodexIsClosed

$resolvedDestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
if (-not $resolvedDestinationRoot.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "DestinationRoot must be located on D:. Received: $resolvedDestinationRoot"
}

New-Item -ItemType Directory -Path $resolvedDestinationRoot -Force | Out-Null

$codexHome = Join-Path $env:USERPROFILE '.codex'
$runtimeCache = Join-Path $env:USERPROFILE '.cache\codex-runtimes'

Move-WithJunction `
    -Source $codexHome `
    -Destination (Join-Path $resolvedDestinationRoot '.codex')

Move-WithJunction `
    -Source $runtimeCache `
    -Destination (Join-Path $resolvedDestinationRoot 'codex-runtimes')

Write-Host "`nMigration completed."
Write-Host "Start Codex and confirm that your tasks and plugins are available."
Write-Host "Backups were intentionally left on C:. Remove them only after Codex has been tested."
