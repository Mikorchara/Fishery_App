function Invoke-ManagementPython {
    param([Parameter(Mandatory=$true)][string[]]$NativeArguments)
    $taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
    $taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'MANAGEMENT_PYTHON_MISSING' }
    & $taskPython -X utf8 -I -B @NativeArguments
    if ($LASTEXITCODE -ne 0) { throw "MANAGEMENT_COMMAND_FAILED ($LASTEXITCODE)" }
}
