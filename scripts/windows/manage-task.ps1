param(
    [ValidateSet('Install', 'Remove', 'Status', 'Run', 'Preview')]
    [string]$Action = 'Status',
    [string]$PythonPath,
    [string]$ConfigPath
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $ConfigPath) { $ConfigPath = Join-Path $projectRoot 'config.toml' }
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$entryPath = Join-Path $projectRoot 'run.py'
$taskName = 'Autolycus-Inspection'
if ($Action -eq 'Remove') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output 'Autolycus task removed. Credentials and history retained.'
    exit 0
}
if ($Action -eq 'Status') {
    # Render a single object before exiting; avoid deferred mixed-table output
    # being lost in a short-lived Windows PowerShell process.
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
    [PSCustomObject]@{
        TaskName = $task.TaskName
        State = [string]$task.State
        LastRunTime = $taskInfo.LastRunTime
        LastTaskResult = $taskInfo.LastTaskResult
        NextRunTime = $taskInfo.NextRunTime
    } | Format-List | Out-String | Write-Output
    exit 0
}
if ($Action -eq 'Run') {
    Start-ScheduledTask -TaskName $taskName
    Write-Output 'Task started. Outside a reporting window it safely skips.'
    exit 0
}
if (-not $PythonPath) { $PythonPath = (& python -c 'import sys; print(sys.executable)').Trim() }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if ($Action -eq 'Install') {
    & $PythonPath -X utf8 $entryPath --config $ConfigPath --check-credentials
    if ($LASTEXITCODE -ne 0) { throw 'Initialize persistent credentials before installing the task.' }
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) { throw 'Task already exists. Inspect it or remove it explicitly before reinstalling.' }
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$escape = [System.Security.SecurityElement]
$backgroundPython = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $backgroundPython)) { throw 'pythonw.exe is required for windowless scheduled execution.' }
$xmlPython = $escape::Escape($backgroundPython)
$xmlRoot = $escape::Escape($projectRoot)
$xmlArgs = $escape::Escape(('-X utf8 "{0}" --config "{1}" --scheduled' -f $entryPath, $ConfigPath))
# A fixed +08:00 anchor keeps repetition aligned to :00/:30 in Beijing.
# Python selects only agreed reporting slots. Other invocations do no HTTP work.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Autolycus scheduled reports; Beijing schedule enforced by Python.</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger><Repetition><Interval>PT30M</Interval></Repetition><StartBoundary>2026-01-01T00:00:00+08:00</StartBoundary><Enabled>true</Enabled></TimeTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>$sid</UserId><Delay>PT30S</Delay></LogonTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$sid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable><Enabled>true</Enabled><Hidden>true</Hidden>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>2</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>$xmlPython</Command><Arguments>$xmlArgs</Arguments><WorkingDirectory>$xmlRoot</WorkingDirectory></Exec></Actions>
</Task>
"@
if ($Action -eq 'Preview') {
    $outputDirectory = Join-Path $projectRoot 'data'
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $outputPath = Join-Path $outputDirectory 'task-preview.xml'
    [System.IO.File]::WriteAllText($outputPath, $xml, [System.Text.Encoding]::Unicode)
    Write-Output $outputPath
    exit 0
}
Register-ScheduledTask -TaskName $taskName -Xml $xml -User $identity | Select-Object TaskName, State
& $PythonPath -X utf8 $entryPath --config $ConfigPath --begin-tracking
if ($LASTEXITCODE -ne 0) { throw 'Task installed but tracking initialization failed. Inspect configuration.' }
Write-Output 'Installed. Runs while this Windows user is logged in; locking the screen is allowed.'
Write-Output 'Shutdown, sleep, and logout prevent execution. No historical backfill is attempted.'
