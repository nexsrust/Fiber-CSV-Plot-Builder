$ErrorActionPreference = 'Stop'

$appName = 'Fiber CSV Plot Builder'
$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$opxFile = Join-Path $packageDir "$appName.opx"
$opxList = Join-Path $env:LOCALAPPDATA 'OriginLab\Apps\OPXList.xml'

if (Get-Process -Name Origin64 -ErrorAction SilentlyContinue) {
    throw '请先关闭 Origin，然后重新运行安装程序。'
}

if (-not (Test-Path -LiteralPath $opxFile)) {
    throw "找不到正式安装包: $opxFile"
}

if ((Test-Path -LiteralPath $opxList) -and (Select-String -LiteralPath $opxList -SimpleMatch $appName -Quiet)) {
    Write-Host "$appName 已经注册到 Origin。" -ForegroundColor Green
    Write-Host '请重新启动 Origin，并在 View > Apps 打开 Apps 面板。'
    Read-Host '按 Enter 键关闭'
    exit 0
}

$origin = New-Object -ComObject Origin.Application
try {
    $origin.Visible = 0
    $escaped = $opxFile.Replace('"', '\"')
    $origin.Execute("instOPX fname:=`"$escaped`" verbose:=0;")
    $origin.Run()
    Start-Sleep -Seconds 2
}
finally {
    try { $origin.Exit($false) } catch { }
}

if (-not ((Test-Path -LiteralPath $opxList) -and (Select-String -LiteralPath $opxList -SimpleMatch $appName -Quiet))) {
    throw 'Origin 已运行安装命令，但没有写入应用注册记录。'
}

Write-Host "$appName 已正式安装并注册。" -ForegroundColor Green
Write-Host '现在启动 Origin，在 View > Apps 面板中打开应用。'
Read-Host '按 Enter 键关闭'
