[CmdletBinding()]
param(
    [string]$BoardVideo,
    [switch]$NoAssistant
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$defaultVideo = 'rtsp://192.168.68.178:554/normal.264'

if ([string]::IsNullOrWhiteSpace($BoardVideo)) {
    $BoardVideo = Read-Host "板端 RTSP 地址（回车使用 $defaultVideo，输入 0 退出）"
    if ($BoardVideo -eq '0') { exit 0 }
    if ([string]::IsNullOrWhiteSpace($BoardVideo)) { $BoardVideo = $defaultVideo }
}

if (-not (Get-Command ffmpeg -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error '电脑端找不到 FFmpeg。请确认在当前 PowerShell 中能运行 ffmpeg -version。'
}

$launch = @{
    DataRoot = Join-Path $projectRoot 'outputs/qq-m3-real-test'
    SimulationMode = 'water-only'
    AutoDeviceReports = $true
    BoardVideo = $BoardVideo.Trim()
    Scenario = 'normal'
    NoAssistant = $NoAssistant.IsPresent
    ScoreTrial = -not $NoAssistant.IsPresent
    EventTrial = -not $NoAssistant.IsPresent
}

Write-Host '打开 http://127.0.0.1:8766/#video 查看板端视频。'
Write-Host '接收新报告需单独启动 8780 接收器。按 Ctrl+C 停止本脚本的网页和模拟水质。'
& (Join-Path $PSScriptRoot 'run_local.ps1') @launch
exit $LASTEXITCODE
