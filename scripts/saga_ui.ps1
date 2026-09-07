param(
    [ValidateSet("browser", "desktop", "check", "package", "release")]
    [string]$Mode = "desktop"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $repoRoot.StartsWith("D:\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "SAGA UI tooling must stay on D:. Resolved repository: $repoRoot"
}

$tooling = Join-Path $repoRoot ".tooling"
$cargoHome = Join-Path $tooling "cargo"
$rustupHome = Join-Path $tooling "rustup"
$tempDir = Join-Path $tooling "tmp"
$appDataDir = Join-Path $tooling "appdata"
$localAppDataDir = Join-Path $tooling "localappdata"
$llvmRoot = Join-Path $tooling "llvm-mingw\llvm-mingw-20260616-ucrt-x86_64"
$llvmBin = Join-Path $llvmRoot "bin"
$uiRoot = Join-Path $repoRoot "ui"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $cargoHome, $rustupHome, $tempDir, $appDataDir, $localAppDataDir | Out-Null
$env:CARGO_HOME = $cargoHome
$env:RUSTUP_HOME = $rustupHome
$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:APPDATA = $appDataDir
$env:LOCALAPPDATA = $localAppDataDir
$env:npm_config_cache = Join-Path $tooling "npm-cache"

if (-not (Test-Path -LiteralPath $python)) {
    throw "SAGA virtual environment is missing: $python"
}

Push-Location $uiRoot
try {
    if ($Mode -eq "browser") {
        & "C:\Program Files\nodejs\npm.cmd" run dev:stack
        exit $LASTEXITCODE
    }

    $gnuCargo = Join-Path $cargoHome "bin\cargo.exe"
    $gnuCompiler = Join-Path $llvmBin "x86_64-w64-mingw32-clang.exe"
    if (-not (Test-Path -LiteralPath $gnuCargo) -or -not (Test-Path -LiteralPath $gnuCompiler)) {
        throw "The D:-local Rust/LLVM toolchain is incomplete under $tooling"
    }

    $env:RUSTUP_TOOLCHAIN = "stable-x86_64-pc-windows-gnu"
    $env:Path = "$llvmBin;$cargoHome\bin;$env:Path"
    $env:CC_x86_64_pc_windows_gnu = $gnuCompiler
    $env:CXX_x86_64_pc_windows_gnu = Join-Path $llvmBin "x86_64-w64-mingw32-clang++.exe"
    $env:AR_x86_64_pc_windows_gnu = Join-Path $llvmBin "x86_64-w64-mingw32-llvm-ar.exe"

    if ($Mode -eq "check") {
        & $gnuCargo check --manifest-path (Join-Path $uiRoot "src-tauri\Cargo.toml")
    } elseif ($Mode -in @("package", "release")) {
        # Source-checkout fallback embedded in this local build. SAGA_ROOT is
        # still honored at runtime when the checkout moves.
        $env:SAGA_SOURCE_ROOT = $repoRoot
        if ($Mode -eq "package") {
            # The unoptimized GNU build avoids a known Windows Defender false
            # positive on locally compiled release-mode Rust build scripts.
            & "C:\Program Files\nodejs\npm.cmd" run desktop:build -- --debug --no-bundle
            $builtExe = Join-Path $uiRoot "src-tauri\target\debug\saga-studio.exe"
        } else {
            & "C:\Program Files\nodejs\npm.cmd" run desktop:build -- --no-bundle
            $builtExe = Join-Path $uiRoot "src-tauri\target\release\saga-studio.exe"
        }
        if ($LASTEXITCODE -eq 0) {
            $releaseDir = Join-Path $repoRoot "release"
            New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
            $releaseExe = Join-Path $releaseDir "SAGA-Studio-0.1.0.exe"
            $checksumFile = "$releaseExe.sha256"
            Copy-Item -LiteralPath $builtExe -Destination $releaseExe -Force
            $checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseExe).Hash.ToLowerInvariant()
            Set-Content -LiteralPath $checksumFile -Value "$checksum  SAGA-Studio-0.1.0.exe" -Encoding ascii
            Write-Host "SAGA Studio executable: $releaseExe"
            Write-Host "SHA-256 checksum: $checksumFile"
        }
    } else {
        & "C:\Program Files\nodejs\npm.cmd" run desktop
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
