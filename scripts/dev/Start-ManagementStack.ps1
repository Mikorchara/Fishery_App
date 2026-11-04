[CmdletBinding()]
param([ValidateSet('full','water-only')][string]$SimulationMode='full', [switch]$InteractiveMode,
 [string]$DeviceReportDirectory, [string]$DeviceReportDeviceId, [string]$Request, [string]$DataRoot, [int]$Port=8766,
      [string]$Scenario='normal', [switch]$WithBot, [switch]$NoBot,
      [switch]$OfflineDemo, [switch]$Check, [int]$RunSeconds=0, [switch]$NoAssistant,
      [switch]$InteractiveScenario, [switch]$OpenBrowser, [string]$DemoVideo, [switch]$ScoreTrial)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'management_stack_common.ps1')
if ($WithBot -and $NoBot) { throw 'SELECT_ONE_BOT_MODE' }
$taskArguments=@((Join-Path $PSScriptRoot 'management_stack.py'),'--port',"$Port",'--scenario',$Scenario)
if ($Request) {
    $Request = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Request)
    $taskArguments+=@('--request',$Request)
}
if ($DataRoot) { $taskArguments+=@('--data-root',$DataRoot) }
if ($WithBot) { $taskArguments+='--with-bot' }
if ($OfflineDemo) { $taskArguments+='--offline-demo' }
if ($Check) { $taskArguments+='--check' }
if ($RunSeconds) { $taskArguments+=@('--seconds',"$RunSeconds") }
if ($NoAssistant) { $taskArguments+='--no-assistant' }
if ($InteractiveScenario) { $taskArguments+='--interactive-scenario' }
if ($OpenBrowser) { $taskArguments+='--open-browser' }
if ($DemoVideo) { $taskArguments+=@('--demo-video',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DemoVideo)) }
if ($ScoreTrial) { $taskArguments+='--score-trial' }
$taskArguments+=@('--simulation-mode',$SimulationMode)
if ($DeviceReportDirectory) { $taskArguments+=@('--device-report-directory',$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DeviceReportDirectory)) }
if ($DeviceReportDeviceId) { $taskArguments+=@('--device-report-device-id',$DeviceReportDeviceId) }
if ($InteractiveMode) { $taskArguments+='--interactive-mode' }
Invoke-ManagementPython -NativeArguments $taskArguments
