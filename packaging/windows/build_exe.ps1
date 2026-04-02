param(
    [string]$Version = "v0.0.0-dev",
    [switch]$BuildInstaller
)

$ErrorActionPreference = "Stop"

$PackagingRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $PackagingRoot "..\..")
$DistRoot = Join-Path $ProjectRoot "dist"
$BuildRoot = Join-Path $ProjectRoot "build\windows"
$SpecFile = Join-Path $PackagingRoot "tradeforagents.spec"
$PyInstallerOutput = Join-Path $DistRoot "TradeforAgentsLauncher"
$BundleName = "TradeforAgents-minimal-windows-noinstall"
$BundleRoot = Join-Path $DistRoot $BundleName
$PythonExe = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }
$NormalizedVersion = if ([string]::IsNullOrWhiteSpace($Version)) { "v0.0.0-dev" } else { $Version }
$ReleaseNotesTemplate = Join-Path $ProjectRoot "docs\releases\GITHUB_RELEASE_TEMPLATE.md"

function Invoke-Step {
    param([string]$Message, [scriptblock]$Action)
    Write-Host "==> $Message"
    & $Action
}

function Copy-LauncherSupportFiles {
    $supportFiles = @(
        "start.bat",
        "debug_console.bat",
        "launch_app.bat",
        "README_WINDOWS.txt"
    )
    foreach ($name in $supportFiles) {
        Copy-Item (Join-Path $PackagingRoot $name) (Join-Path $BundleRoot $name) -Force
    }
}

function Ensure-RuntimeLayout {
    $directories = @(
        "ai_stock_sim\data\logs",
        "ai_stock_sim\data\cache",
        "ai_stock_sim\data\cache\charts",
        "ai_stock_sim\data\reports",
        "ai_stock_sim\data\reports\daily",
        "ai_stock_sim\data\reports\weekly",
        "ai_stock_sim\data\reports\monthly",
        "ai_stock_sim\data\reports\backtest",
        "ai_stock_sim\data\accounts",
        "ai_trade_system\reports",
        "results"
    )
    foreach ($relative in $directories) {
        New-Item -ItemType Directory -Path (Join-Path $BundleRoot $relative) -Force | Out-Null
    }
}

function Write-BuildMetadata {
    $manifest = @{
        version = $NormalizedVersion
        built_at = (Get-Date).ToString("s")
        bundle = $BundleName
    } | ConvertTo-Json
    Set-Content -Path (Join-Path $BundleRoot "VERSION.txt") -Value $NormalizedVersion -Encoding UTF8
    Set-Content -Path (Join-Path $BundleRoot "build-manifest.json") -Value $manifest -Encoding UTF8
    if (Test-Path $ReleaseNotesTemplate) {
        $releaseNotesTarget = Join-Path $DistRoot ("tradeforagents-release-notes-{0}.md" -f $NormalizedVersion)
        $content = Get-Content $ReleaseNotesTemplate -Raw
        $content = $content.Replace("{{VERSION}}", $NormalizedVersion)
        Set-Content -Path $releaseNotesTarget -Value $content -Encoding UTF8
    }
}

function Find-Iscc {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

Invoke-Step "Installing Python build dependencies" {
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements.txt") -r (Join-Path $ProjectRoot "ai_stock_sim\requirements.txt") pyinstaller
}

Invoke-Step "Cleaning old Windows build output" {
    if (Test-Path $PyInstallerOutput) {
        Remove-Item -Recurse -Force $PyInstallerOutput
    }
    if (Test-Path $BundleRoot) {
        Remove-Item -Recurse -Force $BundleRoot
    }
    New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
}

Invoke-Step "Running PyInstaller onedir build" {
    & $PythonExe -m PyInstaller $SpecFile --noconfirm --clean --distpath $DistRoot --workpath $BuildRoot
}

Invoke-Step "Preparing no-install bundle" {
    Copy-Item $PyInstallerOutput $BundleRoot -Recurse -Force
    Copy-LauncherSupportFiles
    Ensure-RuntimeLayout
    Write-BuildMetadata
}

Invoke-Step "Creating no-install zip" {
    & (Join-Path $PackagingRoot "build_zip.ps1") -Version $NormalizedVersion -SourceDir $BundleRoot
}

if ($BuildInstaller.IsPresent) {
    Invoke-Step "Building Inno Setup installer" {
        $iscc = Find-Iscc
        if (-not $iscc) {
            throw "ISCC.exe not found. Install Inno Setup 6 or omit -BuildInstaller."
        }
        & $iscc "/DAppVersion=$NormalizedVersion" "/DSourceDir=$BundleRoot" "/DOutputDir=$DistRoot" (Join-Path $PackagingRoot "installer.iss")
        $genericInstaller = Join-Path $DistRoot "TradeforAgents-minimal-windows-installer.exe"
        if (Test-Path $genericInstaller) {
            Copy-Item $genericInstaller (Join-Path $DistRoot ("tradeforagents-windows-installer-{0}.exe" -f $NormalizedVersion)) -Force
        }
    }
}

Write-Host ""
Write-Host "Windows bundle ready:"
Write-Host "  $BundleRoot"
Write-Host "  $(Join-Path $DistRoot 'TradeforAgents-minimal-windows-noinstall.zip')"
