param(
    [string]$Repository = "ghcr.io/example/asgardian",
    [string]$Version = "0.4.0",
    [string]$Platform = "linux/arm64",
    [switch]$Push,
    [switch]$Load
)

$ErrorActionPreference = "Stop"

$dockerPath = "C:\Program Files\Docker\Docker\resources\bin"
if (Test-Path -LiteralPath $dockerPath) {
    $env:Path = "$dockerPath;$env:Path"
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$backendTag = "${Repository}:backend-${Version}-arm64"
$webTag = "${Repository}:web-${Version}-arm64"

$output = @()
if ($Push) {
    $output += "--push"
} elseif ($Load) {
    $output += "--load"
} else {
    throw "Choose either -Push or -Load."
}

docker buildx version | Out-Host

docker buildx build `
    --platform $Platform `
    --file Dockerfile.backend `
    --tag $backendTag `
    @output `
    .
if ($LASTEXITCODE -ne 0) { throw "Backend image build failed." }

docker buildx build `
    --platform $Platform `
    --file Dockerfile.web `
    --tag $webTag `
    @output `
    .
if ($LASTEXITCODE -ne 0) { throw "Web image build failed." }

Write-Host "Built images:"
Write-Host "  $backendTag"
Write-Host "  $webTag"
