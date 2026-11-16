#requires -Version 5.1
param([switch]$PrepareOnly, [string]$Python)

$ErrorActionPreference = 'Stop'

function Test-Python([string]$Path, [string[]]$LauncherArgs = @()) {
    try {
        & $Path @LauncherArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-Python {
    if ($Python) {
        $path = (Resolve-Path -LiteralPath $Python).ProviderPath
        if (-not (Test-Python $path)) { throw 'Python 3.11 or newer is required.' }
        return @{ Path = $path; Args = @() }
    }

    $commands = Get-Command python.exe, python3.exe, conda.exe -All -ErrorAction SilentlyContinue
    foreach ($command in $commands) {
        $path = $command.Source
        if ($command.Name -eq 'conda.exe') {
            $path = Join-Path (Split-Path -Parent (Split-Path -Parent $path)) 'python.exe'
        }
        if ($path -notmatch '[\\/]Microsoft[\\/]WindowsApps[\\/]' -and
            (Test-Path -LiteralPath $path -PathType Leaf) -and (Test-Python $path)) {
            return @{ Path = $path; Args = @() }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher -and $launcher.Source -notmatch '[\\/]Microsoft[\\/]WindowsApps[\\/]' -and
        (Test-Python $launcher.Source @('-3'))) {
        return @{ Path = $launcher.Source; Args = @('-3') }
    }
}

function Get-LocalUv {
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    $folder = Join-Path $PSScriptRoot '.setup\uv'
    $installed = Get-ChildItem -LiteralPath $folder -Recurse -Filter uv.exe -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($installed) { return $installed.FullName }
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $target = switch ($arch) {
        'AMD64' { 'x86_64-pc-windows-msvc' }
        'ARM64' { 'aarch64-pc-windows-msvc' }
        'x86' { 'i686-pc-windows-msvc' }
        default { throw 'Install Python 3.11+ first. This Windows architecture is not supported by setup.' }
    }
    $answer = Read-Host 'Python was not found. Download uv and Python into this project folder? [Y/n]'
    if ($answer -and $answer -notmatch '^(y|yes)$') { throw 'Install Python 3.11+ and run setup again.' }
    $null = New-Item -ItemType Directory -Force -Path $folder
    $archive = Join-Path $folder 'uv.zip'
    $curl = Get-Command curl.exe -ErrorAction Stop
    & $curl.Source -fLsS --connect-timeout 15 --max-time 180 -o $archive `
        "https://github.com/astral-sh/uv/releases/latest/download/uv-$target.zip"
    if ($LASTEXITCODE -ne 0) { throw 'The official uv download failed. Check the connection or install Python 3.11+ first.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $folder -Force
    $installed = Get-ChildItem -LiteralPath $folder -Recurse -Filter uv.exe -File | Select-Object -First 1
    if (-not $installed) { throw 'The uv archive did not contain uv.exe.' }
    return $installed.FullName
}

function Find-ManagedPython {
    $installs = Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory `
        -Filter 'cpython-3.12.*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    foreach ($install in $installs) {
        $path = Join-Path $install.FullName 'python.exe'
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Test-Python $path)) { return $path }
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $env:PYTHONUTF8 = '1'
    $env:PIP_CACHE_DIR = Join-Path $PSScriptRoot '.setup\pip-cache'
    $env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.setup\uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.setup\python'
    $venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venv -PathType Leaf)) {
        $pythonInfo = Find-Python
        if (-not $pythonInfo) {
            $managed = Find-ManagedPython
            if (-not $managed) {
                $uvPath = Get-LocalUv
                # A restricted Windows account may block uv's version alias after extraction.
                # The complete interpreter can still run directly without that alias.
                Write-Host 'Preparing Python 3.12 with uv...'
                $uvLog = Join-Path $PSScriptRoot '.setup\uv-python.log'
                $previousPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = 'Continue'
                    & $uvPath python install 3.12 --no-bin *> $uvLog
                } finally { $ErrorActionPreference = $previousPreference }
                $managed = Find-ManagedPython
                if (-not $managed) { Get-Content -LiteralPath $uvLog -Tail 8 }
            }
            if (-not $managed) { throw 'Could not prepare Python. Install Python 3.11+ and try again.' }
            $pythonInfo = @{ Path = $managed; Args = @() }
        }
        $launcherArgs = $pythonInfo.Args
        & $pythonInfo.Path @launcherArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
    }
    if (-not (Test-Python $venv)) { throw 'The existing .venv is unavailable. Use a fresh project folder or repair it.' }

    Write-Host 'Installing project dependencies...'
    & $venv -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

    if (-not $PrepareOnly) {
        & $venv -m agent_digest.setup_wizard
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
