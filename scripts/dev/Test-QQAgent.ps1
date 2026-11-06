[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Run,
    [ValidateSet('smoke','full')][string]$Suite = 'full',
    [ValidateRange(1,100)][int]$Repeats = 3,
    [ValidateRange(0,44)][int]$Cases = 0,
    [string]$CaseIds = '',
    [ValidateRange(1,4096)][int]$OutputTokens = 2048
)
$ErrorActionPreference = 'Stop'
if ($Check -and $Run) { throw 'CHECK_AND_RUN_ARE_MUTUALLY_EXCLUSIVE' }
if ($CaseIds) {
    if ($CaseIds -cnotmatch '\A[A-Z][0-9]{2}(?:,[A-Z][0-9]{2})*\z') { throw 'RESEARCH_CASE_IDS_INVALID' }
    if ($Cases -gt 0) { throw 'RESEARCH_CASE_SELECTION_CONFLICT' }
}
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'MANAGEMENT_VENV_PYTHON_REQUIRED' }
$driverPath = Join-Path $PSScriptRoot 'check_qq_agent.py'
$arguments = @('-X', 'utf8', '-I', '-B', $driverPath, '--suite', $Suite,
    '--repeats', [string]$Repeats, '--output-tokens', [string]$OutputTokens)
if ($Cases -gt 0) { $arguments += @('--cases', [string]$Cases) }
if ($CaseIds) { $arguments += @('--case-ids', $CaseIds) }
if ($Run) {
    Write-Host '真实 Qwen 批测：只用新建合成数据，不连接 QQ。核对计划后批准一次，随后自动逐题执行。'
    $arguments += '--run'
} else {
    Write-Host '离线检查：不联网、不读取密钥、不打开业务数据库。'
    $arguments += '--check'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath @arguments
    $driverExit = $LASTEXITCODE
} finally { Pop-Location }
if ($driverExit -ne 0) { throw ('QQ_AGENT_RESEARCH_FAILED (' + $driverExit + ')；请保留上方错误代码和报告路径。') }
