param(
  [string]$InstallDir = "$env:USERPROFILE\Atlas",
  [switch]$AddToPath,
  [switch]$RunSetup,
  [switch]$NoPathPrompt,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Resolve-AtlasPython {
  $commands = @(
    @{ File = "py"; Args = @("-3.11") },
    @{ File = "py"; Args = @() },
    @{ File = "python"; Args = @() }
  )
  foreach ($candidate in $commands) {
    try {
      $output = & $candidate.File @($candidate.Args + @("-c", "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')")) 2>$null
      if ($LASTEXITCODE -eq 0 -and $output) {
        return @{ File = $candidate.File; Args = $candidate.Args }
      }
    } catch {
      continue
    }
  }
  throw "Atlas requires Python 3.11 or newer. Install Python, then rerun this installer."
}

function New-AtlasVenv {
  param([string]$Target)
  $python = Resolve-AtlasPython
  & $python.File @($python.Args + @("-m", "venv", (Join-Path $Target ".venv")))
  if ($LASTEXITCODE -ne 0) {
    throw "Could not create Atlas .venv."
  }
}

function Add-AtlasToUserPath {
  param([string]$Target)
  $current = [Environment]::GetEnvironmentVariable("Path", "User")
  $parts = @($current -split ";" | Where-Object { $_ })
  $alreadyPresent = $parts | Where-Object { $_.TrimEnd("\") -ieq $Target.TrimEnd("\") }
  if ($alreadyPresent) {
    Write-Host "Atlas is already on the user PATH."
    return
  }
  $next = (($parts + $Target) -join ";")
  [Environment]::SetEnvironmentVariable("Path", $next, "User")
  $saved = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($saved -notlike "*$Target*") {
    & reg add "HKCU\Environment" /v Path /t REG_EXPAND_SZ /d $next /f | Out-Null
    $saved = [Environment]::GetEnvironmentVariable("Path", "User")
  }
  if ($saved -notlike "*$Target*") {
    throw "Atlas could not update the user PATH automatically. Add this folder manually: $Target"
  }
  $env:Path = (($env:Path -split ";" | Where-Object { $_ }) + $Target) -join ";"
  Write-Host "Added Atlas to the user PATH. New terminals can run 'atlas' from any folder."
}

$source = Split-Path -Parent $PSCommandPath
$target = [System.IO.Path]::GetFullPath($InstallDir)
$sourceFull = [System.IO.Path]::GetFullPath($source)

if ($sourceFull.TrimEnd("\") -ieq $target.TrimEnd("\")) {
  Write-Host "Atlas is already in the requested install folder: $target"
} else {
  if ((Test-Path $target) -and -not $Force) {
    $answer = Read-Host "Install folder exists: $target. Replace Atlas program files there? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
      throw "Install cancelled."
    }
  }

  New-Item -ItemType Directory -Path $target -Force | Out-Null
  $exclude = @(".git", ".venv", ".codex", ".agents", ".pytest_cache", ".docker-tmp", "work", "outputs", ".env")
  Get-ChildItem -LiteralPath $source -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
    $destination = Join-Path $target $_.Name
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
  }
  Write-Host "Copied Atlas program files to $target"
}

$venvPython = Join-Path $target ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Host "Creating Atlas virtual environment..."
  New-AtlasVenv -Target $target
} else {
  Write-Host "Atlas virtual environment already exists."
}

if ($AddToPath) {
  Add-AtlasToUserPath -Target $target
} elseif (-not $NoPathPrompt) {
  $answer = Read-Host "Add $target to your user PATH so 'atlas' works from any project? [y/N]"
  if ($answer -in @("y", "Y", "yes", "YES")) {
    Add-AtlasToUserPath -Target $target
  }
}

if ($RunSetup) {
  & (Join-Path $target "atlas.cmd") setup
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Atlas install is ready."
Write-Host "Next:"
Write-Host "  cd $target"
Write-Host "  .\atlas setup"
Write-Host ""
Write-Host "Then attach a project:"
Write-Host "  atlas attach C:\path\to\project --project-name my-project"
