[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RunDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'management_stack_common.ps1')
Invoke-ManagementPython -NativeArguments @((Join-Path $PSScriptRoot 'management_stack.py'),'--stop-directory',$RunDirectory,'--stop-role','all')
