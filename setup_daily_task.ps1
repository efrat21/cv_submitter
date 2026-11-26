<#
Registers a Windows scheduled task that prepares the daily job queue, syncs
application email, and prints a local digest. It does not open the review UI or
approve applications/calendar events.

Run once from your project folder (e.g. D:\cv_submitter):
    powershell -ExecutionPolicy Bypass -File .\setup_daily_task.ps1 -Name "Your Name" -Email "you@mail.com"

Options:
    -Time "09:00"        when to run
    -ProjectDir "D:\cv_submitter"   folder that contains data\ and src\ (default: current folder)
    -TaskName "JobAgentDaily"
    -NoRemoteLetters     skip cloud cover-letter generation (enabled by default)

Test it right now:     Start-ScheduledTask -TaskName JobAgentDaily
Remove it:             Unregister-ScheduledTask -TaskName JobAgentDaily -Confirm:$false
#>
param(
    [string]$ProjectDir = (Get-Location).Path,
    [string]$Time = "09:00",
    [string]$Name = "",
    [string]$Email = "",
    [string]$TaskName = "JobAgentDaily",
    [switch]$NoRemoteLetters
)

$ErrorActionPreference = "Stop"

if ($ProjectDir -match '["&|<>^%!()]' -or $Name -match '["&|<>^%!()]' -or $Email -match '["&|<>^%!()]') {
    throw "ProjectDir, Name, and Email cannot contain cmd.exe metacharacters."
}

# --- write the non-interactive launcher the task will run -------------------
$bat = Join-Path $ProjectDir "run_daily.bat"
$lines = @(
    '@echo off',
    'title Job Agent - Daily Preparation',
    'cd /d "{0}"' -f $ProjectDir,
    'set "PYTHONPATH={0}\src;%PYTHONPATH%"' -f $ProjectDir,
    ':: start Ollama if it is not running yet',
    'tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || (start "" /min ollama serve & timeout /t 8 /nobreak >nul)'
)
$lines += 'call ".venv\Scripts\activate.bat"'
$dailyCommand = 'python -m job_agent.cli.host daily --name "{0}" --email "{1}"' -f $Name, $Email
if ($NoRemoteLetters) {
    $dailyCommand += ' --no-remote-letters'
}
$lines += $dailyCommand
$lines | Set-Content -Path $bat -Encoding ASCII
Write-Host "Wrote launcher: $bat"


# --- register the task -------------------------------------------------------
# Run in the currently logged-in user's session so local OAuth credentials work.
$action = New-ScheduledTaskAction `
    -Execute "$env:WINDIR\System32\cmd.exe" `
    -Argument "/c `"$bat`"" `
    -WorkingDirectory $ProjectDir

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

# Use the full Windows account name rather than just USERNAME.
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Task '$TaskName' registered: daily at $Time."
Write-Host "Test now with: Start-ScheduledTask -TaskName '$TaskName'"
