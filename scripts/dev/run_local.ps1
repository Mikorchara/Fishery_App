param([ValidateSet('full','water-only')][string]$SimulationMode='full', [switch]$InteractiveMode,
 [string]$DeviceReportDirectory, [string]$DeviceReportDeviceId, [switch]$AutoDeviceReports,
    [ValidateSet('normal','low_oxygen','oxygen_drop_recovery','suspected_disease','reduced_feeding','combined_anomaly','device_offline','device_visual_recovery')]
    [string]$Scenario = 'normal',
    [ValidateRange(1,65535)][int]$Port = 8766,
    [int]$Seed = 42,
    [switch]$NoAssistant,
    [switch]$NoStreaming,
    [switch]$NoMultiRound,
    [switch]$NoHistory,
    [string]$DataRoot,
    [switch]$UserData,
    [switch]$Demo,
    [switch]$ShowTerminals,
    [switch]$InteractiveScenario,
    [switch]$OpenBrowser,
    [switch]$Detach,
    [switch]$DialogErrors,
    [string]$DemoVideo,
    [switch]$ScoreTrial,
    [switch]$EventTrial,
    [switch]$EventBoardReports
)
$ErrorActionPreference = 'Stop'
try {
if ($InteractiveScenario -and -not $ShowTerminals) { throw 'LOCAL_SCENARIO_MENU_REQUIRES_TERMINALS' }
if ($InteractiveMode) {
 do { $choice=Read-Host '运行模式：1. 完整模拟（默认）  2. 设备联调（仅模拟水质）  0. 退出；选择 [1/2/0]' } while ($choice -notin @('','1','2','0'))
 if ($choice -eq '0') { exit 0 }
 $SimulationMode=if ($choice -eq '2') {'water-only'} else {'full'}
}
if ($Detach) {
    # Keep only the two service consoles visible. No elevated execution/policy bypass.
    $detachedArgs = @('-NoLogo','-NoProfile','-File',('"{0}"' -f $PSCommandPath),
        '-DialogErrors','-Scenario',$Scenario,'-Port',"$Port",'-Seed',"$Seed")
    foreach ($name in @('Demo','ShowTerminals','InteractiveScenario','OpenBrowser','NoAssistant','NoStreaming','NoMultiRound','NoHistory','UserData','ScoreTrial','EventTrial','EventBoardReports','AutoDeviceReports')) {
        if (Get-Variable -Name $name -ValueOnly) { $detachedArgs += ('-' + $name) }
    }
    if ($DataRoot) { $detachedArgs += @('-DataRoot',('"{0}"' -f $DataRoot)) }
    if ($DemoVideo) { $detachedArgs += @('-DemoVideo',('"{0}"' -f $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DemoVideo))) }
    $detachedArgs += @('-SimulationMode',$SimulationMode)
    if ($DeviceReportDirectory) { $detachedArgs += @('-DeviceReportDirectory',('"{0}"' -f $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DeviceReportDirectory))) }
    if ($DeviceReportDeviceId) { $detachedArgs += @('-DeviceReportDeviceId',$DeviceReportDeviceId) }
    Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $detachedArgs -WindowStyle Hidden -ErrorAction Stop | Out-Null
    exit 0
}
$workspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $workspaceRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'LOCAL_VENV_REQUIRED' }
$launchArgs = @('-X','utf8','-I','-B','-u',(Join-Path $PSScriptRoot 'local_session.py'),'--scenario',$Scenario,'--port',"$Port",'--seed',"$Seed")
if (($DataRoot -and $UserData) -or ($Demo -and ($DataRoot -or $UserData))) { throw 'DATA_ROOT_OPTIONS_CONFLICT' }
if ($DataRoot) { $launchArgs += @('--data-root',$DataRoot) }
if ($UserData) { $launchArgs += '--user-data' }
if ($NoAssistant) { $launchArgs += '--no-assistant' }
if ($NoStreaming) { $launchArgs += '--no-streaming' }
if ($NoMultiRound) { $launchArgs += '--no-multi-round' }
if ($NoHistory) { $launchArgs += '--no-history' }
if ($Demo) { $launchArgs += '--demo' }
if ($ShowTerminals) { $launchArgs += '--show-terminals' }
if ($InteractiveScenario) { $launchArgs += '--interactive-scenario' }
if ($OpenBrowser) { $launchArgs += '--open-browser' }
if ($DemoVideo) { $launchArgs += @('--demo-video',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DemoVideo)) }
if ($ScoreTrial) { $launchArgs += '--score-trial' }
if ($EventTrial) { $launchArgs += '--event-trial' }
if ($EventBoardReports) { $launchArgs += '--event-board-reports' }
# Approved Qwen unified trial follows History/transport switches in the supervisor.
# Foreground supervisor owns only its two children; no Provider call on startup.
$launchArgs+=@('--simulation-mode',$SimulationMode)
if ($AutoDeviceReports) { $launchArgs+='--auto-device-reports' }
if ($DeviceReportDirectory) { $launchArgs+=@('--device-report-directory',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DeviceReportDirectory)) }
if ($DeviceReportDeviceId) { $launchArgs+=@('--device-report-device-id',$DeviceReportDeviceId) }
& $pythonPath @launchArgs
$result = $LASTEXITCODE
if ($result -ne 0 -and $DialogErrors) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show('演示启动失败或服务异常退出。请在项目根的 PowerShell 执行 .\scripts\dev\run_local.ps1 -Demo -ShowTerminals 查看具体错误。不要清空或重新初始化已有数据。','AI 监测系统') | Out-Null
}
exit $result
} catch {
    if ($DialogErrors) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show('无法启动演示系统。请检查 .venv、启动脚本权限和数据路径，或在 PowerShell 中运行 run_local.ps1 查看错误。','AI 监测系统') | Out-Null
    } else { Write-Error $_ }
    exit 1
}
