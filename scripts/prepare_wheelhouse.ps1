[CmdletBinding()]
param(
    [string]$Python
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RequirementsPath = Join-Path $ProjectRoot "requirements-lock.txt"
$WheelDirectory = Join-Path $ProjectRoot "vendor\wheels"
$ManifestPath = Join-Path $WheelDirectory "SHA256SUMS.txt"

$Expected = [ordered]@{
    "numpy-1.26.4-cp310-cp310-win_amd64.whl" = "b97fe8060236edf3662adfc2c633f56a08ae30560c56310562cb4f95500022d5"
    "numpy-1.26.4-cp311-cp311-win_amd64.whl" = "cd25bcecc4974d09257ffcd1f098ee778f7834c3ad767fe5db785be9a4aa9cb2"
    "numpy-1.26.4-cp312-cp312-win_amd64.whl" = "08beddf13648eb95f8d867350f6a018a4be2e5ad54c8d8caed89ebca558b2818"
    "opencv_python-4.9.0.80-cp37-abi3-win_amd64.whl" = "3f16f08e02b2a2da44259c7cc712e779eff1dd8b55fdb0323e8cab09548086c0"
    "PyYAML-6.0.2-cp310-cp310-win_amd64.whl" = "a4d3091415f010369ae4ed1fc6b79def9416358877534caf6a0fdd2146c87a3e"
    "PyYAML-6.0.2-cp311-cp311-win_amd64.whl" = "e10ce637b18caea04431ce14fabcf5c64a1c61ec9c56b071a4b7ca131ca52d44"
    "PyYAML-6.0.2-cp312-cp312-win_amd64.whl" = "7e7401d0de89a9a855c839bc697c079a4af81cf878373abd7dc625847d25cbd8"
}

if (-not $Python) {
    $command = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "找不到Python，无法准备离线依赖。"
    }
    $Python = $command.Source
}

New-Item -ItemType Directory -Path $WheelDirectory -Force | Out-Null

function Test-Wheels {
    foreach ($entry in $Expected.GetEnumerator()) {
        $path = Join-Path $WheelDirectory $entry.Key
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            return $false
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $entry.Value) {
            Remove-Item -LiteralPath $path -Force
            return $false
        }
    }
    return $true
}

if (-not (Test-Wheels)) {
    $indexes = @(
        "https://pypi.org/simple",
        "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
        "https://mirrors.aliyun.com/pypi/simple/"
    )
    foreach ($minor in @("310", "311", "312")) {
        $downloaded = $false
        foreach ($index in $indexes) {
            Write-Host "下载CPython $minor 离线轮子：$index"
            $previousErrorAction = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $Python -m pip download --disable-pip-version-check --no-deps `
                --only-binary=:all: --dest $WheelDirectory --platform win_amd64 `
                --python-version $minor --implementation cp --abi "cp$minor" --abi abi3 `
                --retries 2 --timeout 20 --index-url $index `
                --requirement $RequirementsPath
            $exitCode = $LASTEXITCODE
            $ErrorActionPreference = $previousErrorAction
            if ($exitCode -eq 0) {
                $downloaded = $true
                break
            }
        }
        if (-not $downloaded) {
            throw "Python $minor 的离线轮子下载失败。"
        }
    }
}

if (-not (Test-Wheels)) {
    throw "离线依赖文件缺失或SHA-256校验失败。"
}

$unexpected = Get-ChildItem -LiteralPath $WheelDirectory -File -Filter "*.whl" |
    Where-Object { -not $Expected.Contains($_.Name) }
if ($unexpected) {
    throw "离线目录包含未登记轮子：$($unexpected.Name -join ', ')"
}

$manifest = foreach ($entry in $Expected.GetEnumerator()) {
    "$($entry.Value)  $($entry.Key)"
}
Set-Content -LiteralPath $ManifestPath -Value $manifest -Encoding ASCII
Write-Host "离线依赖已就绪：$WheelDirectory"
