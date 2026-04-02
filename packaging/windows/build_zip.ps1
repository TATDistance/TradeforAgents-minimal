param(
    [string]$Version = "v0.0.0-dev",
    [Parameter(Mandatory = $true)]
    [string]$SourceDir
)

$ErrorActionPreference = "Stop"

$ResolvedSourceDir = Resolve-Path $SourceDir
$ProjectRoot = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\..")
$DistRoot = Join-Path $ProjectRoot "dist"
$GenericZip = Join-Path $DistRoot "TradeforAgents-minimal-windows-noinstall.zip"
$VersionedZip = Join-Path $DistRoot ("tradeforagents-windows-noinstall-{0}.zip" -f $Version)

if (Test-Path $GenericZip) {
    Remove-Item -Force $GenericZip
}
if (Test-Path $VersionedZip) {
    Remove-Item -Force $VersionedZip
}

Compress-Archive -Path (Join-Path $ResolvedSourceDir "*") -DestinationPath $GenericZip -Force
Copy-Item $GenericZip $VersionedZip -Force

Write-Host "Created zip bundle:"
Write-Host "  $GenericZip"
Write-Host "  $VersionedZip"
