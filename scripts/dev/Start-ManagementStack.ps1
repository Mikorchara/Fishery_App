[CmdletBinding()]
param([string]$Request, [string]$DataRoot, [int]$Port=8766,
      [string]$Scenario='normal', [switch]$WithBot, [switch]$NoBot,
      [switch]$OfflineDemo, [switch]$Check, [int]$RunSeconds=0, [switch]$NoAssistant)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'management_stack_common.ps1')
if ($WithBot -and $NoBot) { throw 'SELECT_ONE_BOT_MODE' }
$taskArguments=@((Join-Path $PSScriptRoot 'management_stack.py'),'--port',"$Port",'--scenario',$Scenario)
if ($Request) { $taskArguments+=@('--request',$Request) }
if ($DataRoot) { $taskArguments+=@('--data-root',$DataRoot) }
if ($WithBot) { $taskArguments+='--with-bot' }
if ($OfflineDemo) { $taskArguments+='--offline-demo' }
if ($Check) { $taskArguments+='--check' }
if ($RunSeconds) { $taskArguments+=@('--seconds',"$RunSeconds") }
if ($NoAssistant) { $taskArguments+='--no-assistant' }
Invoke-ManagementPython -NativeArguments $taskArguments
