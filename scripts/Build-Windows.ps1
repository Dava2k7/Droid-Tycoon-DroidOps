param(
    [ValidateSet('Desktop', 'Build')][string]$VerificationProfile = 'Desktop'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
New-Item -ItemType Directory -Force -Path 'artifacts', 'release' | Out-Null
Start-Transcript -LiteralPath (Join-Path $root 'artifacts\build.log') -Force | Out-Null
$previousDriverSetting = $env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL
try {
    $env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = 'true'
    $driver = Get-Content -LiteralPath 'packaging\driver.json' -Raw | ConvertFrom-Json
    $driverPath = Join-Path $root ('packaging\' + $driver.name)
    if ((Get-FileHash -LiteralPath $driverPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $driver.sha256) {
        throw 'The bundled driver does not match its recorded checksum.'
    }
    $python = Join-Path $root '.venv-build\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
            throw 'Install 64-bit Python 3.12 from python.org, including the Python launcher.'
        }
        & py.exe -3.12 -m venv '.venv-build'
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.12 build environment.' }
    }
    & $python -c 'import struct,sys; assert sys.version_info[:2] == (3,12) and struct.calcsize(chr(80)) == 8'
    if ($LASTEXITCODE -ne 0) { throw 'The build environment must use 64-bit Python 3.12.' }
    & $python -m pip install --disable-pip-version-check -r requirements-windows-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    & $python scripts\Collect-Licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'Dependency notice collection failed.' }
    & $python scripts\Write-VersionInfo.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable version metadata could not be written.' }
    $buildArgs = @(
        '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir', '--noupx',
        '--name', 'DroidTycoonDroidOps', '--icon', 'droidops\assets\app.ico',
        '--version-file', 'artifacts\version-info.txt',
        '--add-data', 'droidops\assets:assets',
        '--add-data', 'artifacts\third-party:third-party',
        '--add-data', 'LICENSE:.', '--add-data', 'THIRD_PARTY_NOTICES.md:.',
        '--additional-hooks-dir', 'packaging',
        '--collect-data', 'rapidocr', '--collect-binaries', 'rapidocr',
        '--collect-binaries', 'onnxruntime', '--collect-binaries', 'cv2',
        '--collect-binaries', 'vgamepad', 'launch.py'
    )
    & $python @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $exe = Join-Path $root 'dist\DroidTycoonDroidOps\DroidTycoonDroidOps.exe'
    $checkArgs = @('--self-check', (Join-Path $root 'artifacts\runtime-check.json'))
    if ($VerificationProfile -eq 'Build') { $checkArgs += '--no-desktop-check' }
    $quotedArgs = ($checkArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $process = Start-Process -FilePath $exe -ArgumentList $quotedArgs -PassThru
    try {
        if (-not $process.WaitForExit(180000)) {
            $process.Kill()
            throw 'Frozen application verification timed out.'
        }
        $exitCode = $process.ExitCode
    } finally { $process.Dispose() }
    if ($exitCode -ne 0) { throw 'Frozen application verification failed; see artifacts\runtime-check.json.' }
    $report = Get-Content -LiteralPath 'artifacts\runtime-check.json' -Raw | ConvertFrom-Json
    if (-not $report.ok) { throw 'Frozen application checks did not pass.' }
    $version = (& $python -c 'from droidops import __version__; print(__version__)').Trim()
    $inno = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $inno) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) { $inno = $command.Source }
    }
    if (-not $inno) { throw 'Install Inno Setup from jrsoftware.org, then run the build again.' }
    & $inno "/DMyAppVersion=$version" 'packaging\DroidOps.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
    & $python scripts\Prepare-Release.py
    if ($LASTEXITCODE -ne 0) { throw 'Release archive creation failed.' }
    Write-Host "Danksy DroidOps $version build complete. Files are in release\." -ForegroundColor Green
} catch {
    Write-Error $_
    exit 1
} finally {
    $env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = $previousDriverSetting
    Stop-Transcript | Out-Null
}
