[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $ProjectRoot "VERSION"
if (-not $Version) {
    $Version = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
}
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?$') {
    throw "版本号格式无效：$Version"
}

$BuildBase = Join-Path $ProjectRoot ".build"
$PackageName = "FGO-MuMu-Auto-v$Version-Windows"
$PackageRoot = Join-Path $BuildBase $PackageName
$DistRoot = Join-Path $ProjectRoot "dist"
$ZipPath = Join-Path $DistRoot "$PackageName.zip"
$ChecksumPath = Join-Path $DistRoot "SHA256SUMS.txt"

function Assert-SafeGeneratedPath {
    param([string]$Path, [string]$AllowedParent)
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullParent = [IO.Path]::GetFullPath($AllowedParent).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作项目生成目录以外的路径：$fullPath"
    }
}

Assert-SafeGeneratedPath -Path $PackageRoot -AllowedParent $BuildBase
Assert-SafeGeneratedPath -Path $ZipPath -AllowedParent $DistRoot

$Python = $null
$pythonCandidates = @()
$venvCandidate = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvCandidate -PathType Leaf) {
    $pythonCandidates += $venvCandidate
}
$systemPython = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($systemPython) {
    $pythonCandidates += $systemPython.Source
}
foreach ($candidate in $pythonCandidates | Select-Object -Unique) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $candidate -c "import cv2, numpy, yaml" 2>$null
    $runtimeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($runtimeExitCode -eq 0) {
        $Python = $candidate
        break
    }
}
if (-not $Python) {
    throw "找不到依赖完整的 Python；先运行启动控制面板.bat完成环境准备。"
}

$wheelSource = Join-Path $ProjectRoot "vendor\wheels"
Write-Host "检查Windows离线依赖..."
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot "prepare_wheelhouse.ps1") -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "离线依赖准备失败，停止构建发布包。"
}

if (-not $SkipTests) {
    Write-Host "运行单元测试..."
    & $Python -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) {
        throw "测试失败，停止构建发布包。"
    }
}

if (Test-Path -LiteralPath $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null

$rootFiles = @(
    "启动控制面板.bat",
    "main.py",
    "fgo_gui_launcher.pyw",
    "requirements.txt",
    "requirements-lock.txt",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "VERSION"
)
foreach ($relativePath in $rootFiles) {
    $source = Join-Path $ProjectRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "缺少发布文件：$relativePath"
    }
    Copy-Item -LiteralPath $source -Destination $PackageRoot -Force
}

$moduleTarget = Join-Path $PackageRoot "fgo_bot"
New-Item -ItemType Directory -Path $moduleTarget -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "fgo_bot") -File -Filter "*.py" |
    Copy-Item -Destination $moduleTarget -Force

$profileTarget = Join-Path $PackageRoot "profiles"
New-Item -ItemType Directory -Path $profileTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "profiles\fgo_cn_1600x900.yaml") `
    -Destination $profileTarget -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "profiles\templates") `
    -Destination $profileTarget -Recurse -Force

$scriptTarget = Join-Path $PackageRoot "scripts"
New-Item -ItemType Directory -Path $scriptTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "scripts\bootstrap.ps1") `
    -Destination $scriptTarget -Force

$wheelTarget = Join-Path $PackageRoot "wheels"
New-Item -ItemType Directory -Path $wheelTarget -Force | Out-Null
Get-ChildItem -LiteralPath $wheelSource -File |
    Where-Object { $_.Extension -eq ".whl" -or $_.Name -eq "SHA256SUMS.txt" } |
    Copy-Item -Destination $wheelTarget -Force

$blockedNames = @(".venv", "runs", "logs", "user.yaml", "__pycache__", ".git")
foreach ($blockedName in $blockedNames) {
    $leak = Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force |
        Where-Object { $_.Name -eq $blockedName } |
        Select-Object -First 1
    if ($leak) {
        throw "发布包混入本地文件：$($leak.FullName)"
    }
}

$textFiles = Get-ChildItem -LiteralPath $PackageRoot -Recurse -File |
    Where-Object { $_.Extension -in @(".py", ".pyw", ".yaml", ".md", ".txt", ".ps1", ".bat") }
$absolutePathLeak = $textFiles | Select-String -Pattern '[A-Za-z]:\\Users\\|F:\\MuMu\\' |
    Select-Object -First 1
if ($absolutePathLeak) {
    throw "检测到本机绝对路径：$($absolutePathLeak.Path):$($absolutePathLeak.LineNumber)"
}

New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $ChecksumPath -Value "$hash  $([IO.Path]::GetFileName($ZipPath))" -Encoding ASCII

Write-Host "发布包：$ZipPath"
Write-Host "校验值：$ChecksumPath"
