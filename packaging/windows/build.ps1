[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Cxx = "g++",
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$env:PYTHONNOUSERSITE = "1"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildRoot = Join-Path $RepositoryRoot "build\windows"
$DistRoot = Join-Path $RepositoryRoot "dist"
$ArtifactRoot = Join-Path $RepositoryRoot "artifacts"
$GreedyExecutable = Join-Path $BuildRoot "Bin_packing_3D.exe"
$FrozenDirectory = Join-Path $DistRoot "3DContainerLoading"
$FrozenExecutable = Join-Path $FrozenDirectory "3DContainerLoading.exe"
$SmokeOutput = Join-Path $BuildRoot "packaged-smoke"
$PortableZip = Join-Path $ArtifactRoot "3DContainerLoading-Windows-x64-Portable.zip"
$InstallerOutput = Join-Path $ArtifactRoot "3DContainerLoading-Windows-x64-Setup.exe"
$ChecksumOutput = Join-Path $ArtifactRoot "SHA256SUMS.txt"

New-Item -ItemType Directory -Force -Path $BuildRoot, $ArtifactRoot | Out-Null

if (-not $SkipTests) {
    & $Python -m unittest discover -s (Join-Path $RepositoryRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }
}

& $Cxx -std=c++17 -O2 -static -static-libgcc -static-libstdc++ `
    (Join-Path $RepositoryRoot "Bin_packing_3D.cpp") -o $GreedyExecutable
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $GreedyExecutable)) {
    throw "Windows Greedy backend compilation failed."
}

& $Python -m PyInstaller --clean --noconfirm `
    (Join-Path $PSScriptRoot "3DContainerLoading.spec")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $FrozenExecutable)) {
    throw "PyInstaller build failed."
}

if (Test-Path $SmokeOutput) {
    Remove-Item -LiteralPath $SmokeOutput -Recurse -Force
}
$OriginalPath = $env:Path
$OriginalQtPlatform = $env:QT_QPA_PLATFORM
$OriginalMatplotlibBackend = $env:MPLBACKEND
try {
    $env:Path = "$env:SystemRoot\System32"
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:MPLBACKEND = "Agg"
    $process = Start-Process -FilePath $FrozenExecutable `
        -ArgumentList "--packaging-self-test", ('"' + $SmokeOutput + '"') `
        -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(180000)) {
        Stop-Process -Id $process.Id -Force
        throw "Packaged application self-test exceeded 180 seconds."
    }
    if ($process.ExitCode -ne 0) {
        throw "Packaged application self-test failed with exit code $($process.ExitCode)."
    }
} finally {
    $env:Path = $OriginalPath
    $env:QT_QPA_PLATFORM = $OriginalQtPlatform
    $env:MPLBACKEND = $OriginalMatplotlibBackend
}
if (-not (Test-Path (Join-Path $SmokeOutput "summary.json"))) {
    throw "Packaged application self-test did not write its summary."
}

if (Test-Path $PortableZip) { Remove-Item -LiteralPath $PortableZip -Force }
Compress-Archive -Path (Join-Path $FrozenDirectory "*") -DestinationPath $PortableZip

if (-not $SkipInstaller) {
    $IsccCandidates = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
    $Iscc = $IsccCandidates | Select-Object -First 1
    if (-not $Iscc) {
        throw "Inno Setup 6 compiler (ISCC.exe) was not found."
    }
    & $Iscc "/DMyAppVersion=1.1.0" "/DMyAppSource=$FrozenDirectory" `
        "/DMyOutputDir=$ArtifactRoot" (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $InstallerOutput)) {
        throw "Inno Setup build failed."
    }
}

$ChecksumTargets = @($PortableZip)
if (Test-Path $InstallerOutput) { $ChecksumTargets += $InstallerOutput }
$ChecksumLines = foreach ($Path in $ChecksumTargets) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    "$Hash  $([IO.Path]::GetFileName($Path))"
}
$ChecksumLines | Set-Content -LiteralPath $ChecksumOutput -Encoding ascii

Write-Host "Frozen application: $FrozenDirectory"
Write-Host "Portable archive: $PortableZip"
if (Test-Path $InstallerOutput) { Write-Host "Installer: $InstallerOutput" }
Write-Host "Checksums: $ChecksumOutput"
