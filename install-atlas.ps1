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

function Grant-AtlasWorkPermission {
  param([string]$Target)
  $workPath = Join-Path $Target "work"
  New-Item -ItemType Directory -Path $workPath -Force | Out-Null
  $group = "CodexSandboxUsers"
  & icacls $workPath /grant "${group}:(OI)(CI)M" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Could not grant CodexSandboxUsers Modify permission on $workPath. If Atlas tools fail to write, run: icacls `"$workPath`" /grant `"CodexSandboxUsers:(OI)(CI)M`""
    return
  }
  Write-Host "Granted Codex sandbox write access to $workPath"
}

function Copy-AtlasPath {
  param(
    [string]$SourceRoot,
    [string]$TargetRoot,
    [string]$RelativePath
  )
  $sourcePath = Join-Path $SourceRoot $RelativePath
  if (-not (Test-Path $sourcePath)) {
    return
  }
  $destinationPath = Join-Path $TargetRoot $RelativePath
  $destinationParent = Split-Path -Parent $destinationPath
  New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
  Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
}

function Copy-AtlasFiles {
  param(
    [string]$SourceRoot,
    [string]$TargetRoot,
    [string]$Pattern,
    [string]$DestinationRelativePath
  )
  $destination = Join-Path $TargetRoot $DestinationRelativePath
  New-Item -ItemType Directory -Path $destination -Force | Out-Null
  Get-ChildItem -Path (Join-Path $SourceRoot $Pattern) -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destination $_.Name) -Force
  }
}

function Copy-AtlasProgramFiles {
  param(
    [string]$SourceRoot,
    [string]$TargetRoot
  )
  $programRoots = @("backend", "dashboard", "docs", "infra", "mcp_server", "packaging")
  foreach ($root in $programRoots) {
    $destination = Join-Path $TargetRoot $root
    if (Test-Path $destination) {
      Remove-Item -LiteralPath $destination -Recurse -Force
    }
  }

  $rootFiles = @("atlas.cmd", "docker-compose.yml", "install-atlas.ps1", "LICENSE", "pytest.ini", "README.md", "requirements.txt", ".env.example")
  foreach ($file in $rootFiles) {
    Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath $file
  }

  $directories = @(
    "backend\app",
    "backend\migrations",
    "backend\scripts",
    "backend\tests",
    "infra\postgres\init"
  )
  foreach ($directory in $directories) {
    Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath $directory
  }

  Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath "backend\alembic.ini"
  Copy-AtlasFiles -SourceRoot $SourceRoot -TargetRoot $TargetRoot -Pattern "dashboard\*.html" -DestinationRelativePath "dashboard"
  Copy-AtlasFiles -SourceRoot $SourceRoot -TargetRoot $TargetRoot -Pattern "dashboard\*.css" -DestinationRelativePath "dashboard"
  Copy-AtlasFiles -SourceRoot $SourceRoot -TargetRoot $TargetRoot -Pattern "dashboard\*.js" -DestinationRelativePath "dashboard"
  Copy-AtlasFiles -SourceRoot $SourceRoot -TargetRoot $TargetRoot -Pattern "docs\*.md" -DestinationRelativePath "docs"
  Copy-AtlasFiles -SourceRoot $SourceRoot -TargetRoot $TargetRoot -Pattern "mcp_server\*.py" -DestinationRelativePath "mcp_server"
  Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath "packaging\windows\README.md"
  Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath "packaging\windows\atlas.iss"
  Copy-AtlasPath -SourceRoot $SourceRoot -TargetRoot $TargetRoot -RelativePath "packaging\windows\assets"
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
  Copy-AtlasProgramFiles -SourceRoot $source -TargetRoot $target
  Write-Host "Copied Atlas program files to $target"
}

$venvPython = Join-Path $target ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Host "Creating Atlas virtual environment..."
  New-AtlasVenv -Target $target
} else {
  Write-Host "Atlas virtual environment already exists."
}

Grant-AtlasWorkPermission -Target $target

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
