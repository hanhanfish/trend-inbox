#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidatePattern('^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$DailyAt = '08:10',
    [ValidatePattern('^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$WeeklyAt = '08:30',
    [DayOfWeek]$WeeklyDay = 'Monday',
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [switch]$WakeToRun
)

$ErrorActionPreference = 'Stop'
$pythonPath = (Resolve-Path -LiteralPath $Python).ProviderPath
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Provide the path to python.exe.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env') -PathType Leaf)) {
    throw 'Copy .env.example to .env and configure the model and mailbox first.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $pythonPath -c 'import bs4, dotenv, markdown_it, requests, yaml; import agent_digest'
    if ($LASTEXITCODE -ne 0) { throw 'Install requirements.txt into this Python environment first.' }
} finally {
    Pop-Location
}

$pythonw = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
$executable = if (Test-Path -LiteralPath $pythonw -PathType Leaf) { $pythonw } else { $pythonPath }
$dailyTime = [datetime]::Today.Add([timespan]::ParseExact($DailyAt, 'hh\:mm', [cultureinfo]::InvariantCulture))
$weeklyTime = [datetime]::Today.Add([timespan]::ParseExact($WeeklyAt, 'hh\:mm', [cultureinfo]::InvariantCulture))
$tasks = @(
    @{ Name = 'Agent Digest Daily'; Kind = 'daily'; Time = $dailyTime; Schedule = "daily at $DailyAt" },
    @{ Name = 'Agent Digest Weekly'; Kind = 'weekly'; Time = $weeklyTime; Schedule = "$WeeklyDay at $WeeklyAt" }
)

foreach ($task in $tasks) {
    if (-not $PSCmdlet.ShouldProcess("$($task.Name) ($($task.Schedule))", 'Register or update local scheduled task')) {
        continue
    }
    $account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -WakeToRun:$WakeToRun.IsPresent
    $trigger = if ($task.Kind -eq 'daily') {
        New-ScheduledTaskTrigger -Daily -At $task.Time
    } else {
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $task.Time
    }
    $arguments = "-m agent_digest $($task.Kind) --send --log .digest/$($task.Kind).log"
    $action = New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $PSScriptRoot
    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output "Configured $($task.Name) ($($task.Schedule))"
}
