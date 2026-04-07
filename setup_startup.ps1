$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$python  = (Get-Command pythonw -ErrorAction SilentlyContinue)?.Source
if (-not $python) { $python = "pythonw" }

$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$dir\server.py`"" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -AllowStartIfOnBatteries $true -DontStopIfGoingOnBatteries $true

Register-ScheduledTask -TaskName "GridTracker_Server" `
    -Action $action -Trigger $trigger -Settings $settings `
    -RunLevel Highest -Force | Out-Null

# Sunucuyu hemen de başlat
Start-ScheduledTask -TaskName "GridTracker_Server"
Write-Host "Tamam. GridTracker sunucusu baslatildi ve her acilista otomatik calisacak."
