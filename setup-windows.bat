@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" || exit /b 1
where uv.exe >nul 2>&1
if errorlevel 1 (
    echo Install uv first: winget install --id astral-sh.uv -e
    echo Then reopen this installer.
    popd
    pause
    exit /b 1
)
uv sync --locked && uv run --locked python -m agent_digest.setup_wizard
set "RESULT=%ERRORLEVEL%"
popd
echo.
if not "%RESULT%"=="0" echo Setup stopped. See the message above.
pause
exit /b %RESULT%
