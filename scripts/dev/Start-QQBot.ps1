[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Request, [switch]$Run, [switch]$Check,
      [switch]$OfflineDemo, [int]$RunSeconds=0)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'management_stack_common.ps1')
if ($Check -and $Run) { throw 'SELECT_CHECK_OR_RUN' }
$Request = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Request)
$taskArguments=@((Join-Path $PSScriptRoot 'management_stack.py'),'--bot-only','--request',$Request)
if (-not $Run) { $taskArguments+='--check' }
if ($OfflineDemo) { $taskArguments+='--offline-demo' }
if ($RunSeconds) { $taskArguments+=@('--seconds',"$RunSeconds") }
Invoke-ManagementPython -NativeArguments $taskArguments
