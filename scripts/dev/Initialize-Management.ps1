[CmdletBinding()]
param([switch]$Check)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'management_stack_common.ps1')
$taskArguments=@('-m','apps.management_setup')
if ($Check) { $taskArguments+='--check' }
Invoke-ManagementPython -NativeArguments $taskArguments
