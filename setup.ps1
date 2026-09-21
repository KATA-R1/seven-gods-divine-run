param(
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONUTF8 = "1"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Downloads = Join-Path $Runtime "downloads"
$PythonHome = Join-Path $Runtime "python312"
$PythonExe = Join-Path $PythonHome "python.exe"
$DenoHome = Join-Path $Runtime "deno"
$DenoExe = Join-Path $DenoHome "deno.exe"
$FfmpegBin = Join-Path $Runtime "ffmpeg\bin"
$FfmpegExe = Join-Path $FfmpegBin "ffmpeg.exe"
$FfprobeExe = Join-Path $FfmpegBin "ffprobe.exe"

$PythonVersion = "3.12.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$DenoUrl = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

function Download-File {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Write-Host "Downloading $Label ..."
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

function Get-ShortPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
    $command = 'for %I in ("' + $resolved + '") do @echo %~sI'
    $shortPath = & $env:ComSpec /d /c $command
    if ($LASTEXITCODE -eq 0 -and $shortPath) {
        return ($shortPath | Select-Object -First 1).Trim()
    }
    return $resolved
}

function Extract-ZipEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$EntrySuffix,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $normalizedSuffix = $EntrySuffix.Replace("\", "/")
        $entry = $zip.Entries |
            Where-Object { $_.FullName.Replace("\", "/").EndsWith($normalizedSuffix) } |
            Select-Object -First 1
        if (-not $entry) {
            throw "The required file '$EntrySuffix' was not found in $Archive."
        }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile(
            $entry,
            $Destination,
            $true
        )
    }
    finally {
        $zip.Dispose()
    }
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This automatic setup supports 64-bit Windows 10/11 only."
}

New-Item -ItemType Directory -Force -Path $Runtime, $Downloads | Out-Null

if (-not (Test-Path -LiteralPath $PythonExe)) {
    $pythonArchive = Join-Path $Downloads "python-embed.zip"
    Download-File -Url $PythonUrl -Destination $pythonArchive -Label "portable Python $PythonVersion"
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $PythonHome -Force

    $pthFile = Join-Path $PythonHome "python312._pth"
    $pthContent = Get-Content -Raw -LiteralPath $pthFile
    $pthContent = $pthContent.Replace("#import site", "import site")
    Set-Content -LiteralPath $pthFile -Value $pthContent -Encoding ASCII
    Remove-Item -LiteralPath $pythonArchive -Force
}

Write-Host "Python: $(& $PythonExe --version)"

$savedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m pip --version *> $null
$pipAvailable = $LASTEXITCODE -eq 0
$ErrorActionPreference = $savedErrorActionPreference
if (-not $pipAvailable) {
    $getPip = Join-Path $Downloads "get-pip.py"
    Download-File -Url $GetPipUrl -Destination $getPip -Label "pip"
    $ErrorActionPreference = "Continue"
    & $PythonExe $getPip
    $pipExitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedErrorActionPreference
    if ($pipExitCode -ne 0) {
        throw "pip setup failed with exit code $pipExitCode."
    }
    Remove-Item -LiteralPath $getPip -Force
}

Write-Host "Installing Python packages ..."
$ErrorActionPreference = "Continue"
# No blanket --upgrade here: only yt-dlp needs to chase upstream (below).
# Upgrading streamlit/pandas/openai wholesale would risk breaking the UI on
# every setup run; requirements.txt floors pull them up only when needed.
& $PythonExe -m pip install `
    --disable-pip-version-check `
    --no-warn-script-location `
    --quiet `
    -r (Join-Path $Root "requirements.txt")
$pipInstallExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference
if ($pipInstallExitCode -ne 0) {
    throw "Python package installation failed with exit code $pipInstallExitCode."
}

# YouTube changes its player frequently, so an already-satisfied requirement
# pin is not enough: always pull the newest yt-dlp during setup.
Write-Host "Updating yt-dlp ..."
$ErrorActionPreference = "Continue"
& $PythonExe -m pip install `
    --disable-pip-version-check `
    --no-warn-script-location `
    --quiet `
    --upgrade `
    yt-dlp
$ytdlpExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference
if ($ytdlpExitCode -ne 0) {
    Write-Warning "Could not update yt-dlp. Downloads may fail until it is updated."
}

if (-not (Test-Path -LiteralPath $DenoExe)) {
    $denoArchive = Join-Path $Downloads "deno.zip"
    Download-File -Url $DenoUrl -Destination $denoArchive -Label "portable Deno"
    New-Item -ItemType Directory -Force -Path $DenoHome | Out-Null
    Extract-ZipEntry -Archive $denoArchive -EntrySuffix "deno.exe" -Destination $DenoExe
    Remove-Item -LiteralPath $denoArchive -Force
}

if (-not (Test-Path -LiteralPath $FfmpegExe) -or
    -not (Test-Path -LiteralPath $FfprobeExe)) {
    $ffmpegArchive = Join-Path $Downloads "ffmpeg.zip"
    Download-File -Url $FfmpegUrl -Destination $ffmpegArchive -Label "portable ffmpeg"
    New-Item -ItemType Directory -Force -Path $FfmpegBin | Out-Null
    Extract-ZipEntry -Archive $ffmpegArchive -EntrySuffix "/bin/ffmpeg.exe" -Destination $FfmpegExe
    Extract-ZipEntry -Archive $ffmpegArchive -EntrySuffix "/bin/ffprobe.exe" -Destination $FfprobeExe
    Remove-Item -LiteralPath $ffmpegArchive -Force
}

Write-Host "Deno: $((& $DenoExe --version | Select-Object -First 1))"
Write-Host "ffmpeg: $((& $FfmpegExe -version | Select-Object -First 1))"

$env:Path = "$FfmpegBin;$DenoHome;$env:Path"
$ErrorActionPreference = "Continue"
& $PythonExe -c "import streamlit, pandas, yt_dlp, googleapiclient, google_auth_oauthlib, openai; assert tuple(map(int, openai.__version__.split('.')[:2])) >= (2, 44)"
$verificationExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference
if ($verificationExitCode -ne 0) {
    throw "Application dependency verification failed."
}

if (-not $NoShortcut) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktop "YouTube Search Downloader.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcutRoot = Get-ShortPath $Root
        $shortcutBatchPath = Join-Path $shortcutRoot "start_app.bat"
        # WScript.Shell or cmd.exe can corrupt non-ASCII paths in shortcut
        # arguments on some Windows locales, so store the ASCII 8.3 path.
        $shortcut.TargetPath = $env:ComSpec
        $shortcut.Arguments = '/c ""' + $shortcutBatchPath + '""'
        $shortcut.WorkingDirectory = $shortcutRoot
        $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
        $shortcut.Description = "YouTube Search and Downloader"
        $shortcut.Save()
        Write-Host "Desktop shortcut created: $shortcutPath"
    }
    catch {
        Write-Warning "Could not create the desktop shortcut: $($_.Exception.Message)"
    }
}

Write-Host ""
Write-Host "Setup completed successfully."
