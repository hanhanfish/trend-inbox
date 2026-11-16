#requires -Version 5.1
param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $bundledUv = Join-Path $PSScriptRoot '.setup\uv\uv.exe'
    $systemUv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $bundledUv -PathType Leaf) {
        $uv = $bundledUv
    } elseif ($systemUv) {
        $uv = $systemUv.Source
    } else {
        $answer = (Read-Host 'Download the runtime tool into this project folder and continue? [Y/n]').Trim()
        if ($answer -and $answer -notmatch '^(y|yes)$') { exit 1 }
        $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        $target = switch ($arch) {
            'AMD64' { 'x86_64-pc-windows-msvc' }
            'ARM64' { 'aarch64-pc-windows-msvc' }
            default { throw 'This installer requires 64-bit Windows.' }
        }
        $directory = Split-Path -Parent $bundledUv
        $null = New-Item -ItemType Directory -Path $directory -Force
        $archive = Join-Path $directory 'uv.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-$target.zip" -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $directory -Force
        if (-not (Test-Path -LiteralPath $bundledUv -PathType Leaf)) {
            $downloaded = Get-ChildItem -LiteralPath $directory -Recurse -File -Filter uv.exe | Select-Object -First 1
            if (-not $downloaded) { throw 'The official archive did not contain uv.exe.' }
            Copy-Item -LiteralPath $downloaded.FullName -Destination $bundledUv
        }
        $uv = $bundledUv
    }
    if (-not $env:UV_CACHE_DIR) { $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.setup\cache' }
    if (-not $env:UV_PYTHON_INSTALL_DIR) { $env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.setup\python' }
    $env:PYTHONUTF8 = '1'
    & $uv sync --locked
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $PrepareOnly) {
        & $uv run --locked python -m agent_digest.setup_wizard
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
