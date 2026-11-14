[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

while ($true) {
    $source = (Read-Host '输入开发板当前 IPv4 或完整 RTSP 地址，输入 0 退出').Trim()
    if ($source -eq '0') { exit 0 }

    if ($source -match '\A(?:[0-9]{1,3}\.){3}[0-9]{1,3}\z') {
        $source = 'rtsp://{0}:554/normal.264' -f $source
    }
    if ($source -cmatch '\Artsp://(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?:/[A-Za-z0-9_-][A-Za-z0-9._-]*)+\z') {
        break
    }
    Write-Host '请输入当前板端地址。例如 192.168.68.178，或 rtsp://192.168.68.178:554/normal.264。'
}

if (-not (Get-Command ffmpeg -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error '电脑端找不到 FFmpeg。请确认在当前 PowerShell 中能运行 ffmpeg -version。'
}

$launch = @{
    Request = Join-Path $projectRoot 'outputs/qq-m3-real-config/request.json'
    WithBot = $true
    SimulationMode = 'water-only'
    AutoDeviceReports = $true
    BoardVideo = $source
    InteractiveScenario = $true
    OpenBrowser = $true
    ScoreTrial = $true
    EventTrial = $true
}

Write-Host '设备联调模式。请在模拟器窗口选择水质场景，在 Bot 窗口核对并确认本次运行。'
Write-Host '网页： http://127.0.0.1:8766/#video'
Write-Host '板端报告仍由独立的 8780 接收器接收。退出请在本窗口按 Ctrl+C。'
& (Join-Path $PSScriptRoot 'Start-ManagementStack.ps1') @launch
