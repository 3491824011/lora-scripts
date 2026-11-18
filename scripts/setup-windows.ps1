[CmdletBinding()]
param(
    [ValidateSet("cu130", "cu128")]
    [string]$Cuda = "cu130",
    [switch]$OfficialIndex,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Python311 {
    param([string]$Exe)
    if (-not (Test-Path -LiteralPath $Exe)) {
        return $false
    }
    & $Exe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

$pythonDir = Join-Path $repoRoot "python"
$pythonExe = Join-Path $pythonDir "python.exe"
$pythonVersion = "3.11.9"
$pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
$pythonSha256 = "5ee42c4eee1e6b4464bb23722f90b45303f79442df63083f05322f1785f5fdde"
$installer = Join-Path $env:TEMP "python-$pythonVersion-amd64.exe"

if (Test-Python311 $pythonExe) {
    Write-Step "Using the Python 3.11 runtime already present at $pythonExe"
} else {
    Write-Step "Python 3.11 x64 was not found in this project."
    Write-Host "It will be downloaded from: $pythonUrl"
    Write-Host "and installed into: $pythonDir"

    if ($DryRun) {
        Write-Host "Dry run: would download the installer, install Python $pythonVersion, then install the dependencies."
        return
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    if (-not (Test-Path -LiteralPath $installer)) {
        Write-Step "Downloading Python $pythonVersion"
        Invoke-WebRequest -Uri $pythonUrl -OutFile $installer -UseBasicParsing
    }

    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $pythonSha256) {
        throw "Python installer checksum mismatch. Expected $pythonSha256 but got $hash. Delete $installer and try again."
    }

    $signature = Get-AuthenticodeSignature -FilePath $installer
    if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw "The downloaded Python installer is not signed by the Python Software Foundation. Delete $installer and try again."
    }

    if (Test-Path -LiteralPath $pythonDir) {
        $backupDir = "$pythonDir.old-" + (Get-Date -Format "yyyyMMddHHmmss")
        Write-Step "Moving the existing python folder to $backupDir"
        Move-Item -LiteralPath $pythonDir -Destination $backupDir
    }

    Write-Step "Installing Python $pythonVersion into $pythonDir"
    $installerArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$pythonDir`"",
        "Include_pip=1",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_tcltk=0",
        "Shortcuts=0",
        "AssociateFiles=0",
        "PrependPath=0",
        "CompileAll=0"
    )
    $process = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }

    if (-not (Test-Python311 $pythonExe)) {
        throw "Python 3.11 x64 installation did not produce $pythonExe."
    }
    Write-Step "Python 3.11 is ready at $pythonExe"
}

& $pythonExe -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Bootstrapping pip"
    & $pythonExe -m ensurepip --upgrade
}

$installScript = if ($OfficialIndex) {
    Join-Path $PSScriptRoot "install.ps1"
} else {
    Join-Path $PSScriptRoot "install-cn.ps1"
}

Write-Step "Installing CUDA PyTorch ($Cuda) and the remaining dependencies"
Write-Host "Installer: $installScript"
if ($DryRun) {
    Write-Host "Dry run: would run $installScript -Cuda $Cuda"
    return
}

& $installScript -Cuda $Cuda

Write-Step "Setup completed. Double-click run_gui.bat to start the application."
