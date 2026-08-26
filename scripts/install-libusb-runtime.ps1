[CmdletBinding()]
param(
    [string]$PythonDirectory = (Join-Path $PSScriptRoot "..\.venv\Scripts")
)

$ErrorActionPreference = "Stop"
$version = "1.0.30"
$expectedSha256 = "7FB1DFEC805B97983763D7D0AE244320DA12ADD1003D4249C96CC4D586398C79"
$downloadUrl = "https://github.com/libusb/libusb/releases/download/v$version/libusb-$version.7z"
$archive = Join-Path ([IO.Path]::GetTempPath()) "nxt-mcp-libusb-$version-$PID.7z"
$extractDirectory = Join-Path ([IO.Path]::GetTempPath()) "nxt-mcp-libusb-$version-$PID"
$targetDirectory = [IO.Path]::GetFullPath($PythonDirectory)
$target = Join-Path $targetDirectory "libusb-1.0.dll"

if (-not (Test-Path -LiteralPath (Join-Path $targetDirectory "python.exe"))) {
    throw "Python executable not found in $targetDirectory. Create .venv first or pass -PythonDirectory."
}

$sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
if (-not $sevenZip) {
    throw "7z.exe is required. Install 7-Zip, then make sure 7z is available on PATH."
}

New-Item -ItemType Directory -Path $extractDirectory | Out-Null
try {
    Write-Host "Downloading official libusb $version Windows binaries..."
    Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $archive
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    if ($actualSha256 -ne $expectedSha256) {
        throw "libusb archive SHA-256 mismatch. Expected $expectedSha256, got $actualSha256."
    }

    & $sevenZip.Source e $archive "VS2022\MS64\dll\libusb-1.0.dll" "-o$extractDirectory" -y | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip could not extract the x64 libusb runtime."
    }
    Copy-Item -LiteralPath (Join-Path $extractDirectory "libusb-1.0.dll") -Destination $target -Force
    Write-Host "Installed $target"
}
finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $extractDirectory "libusb-1.0.dll") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $extractDirectory -Force -ErrorAction SilentlyContinue
}

$env:PATH = "$targetDirectory;$env:PATH"
& (Join-Path $targetDirectory "python.exe") -c `
    "import usb.backend.libusb1 as b; assert b.get_backend() is not None; print('PyUSB libusb backend: OK')"
