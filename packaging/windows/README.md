# Atlas Windows Installer Packaging

Atlas currently ships with a PowerShell installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-atlas.ps1 -InstallDir "$env:USERPROFILE\Atlas"
```

That script is the source of truth for the install workflow:

1. Copy only known Atlas program files into the install folder.
2. Skip local state such as `.env`, `.venv`, `.codex`, `.git`, and `work`.
3. Create `.venv`.
4. Create `work` and grant the Codex sandbox user group Modify permission there when available.
5. Optionally add the install folder to the user PATH.
6. Leave storage selection to `atlas setup`.

## EXE Installer Path

Use Inno Setup first. It is the simplest way to wrap the PowerShell workflow into a normal Windows installer.

1. Install Inno Setup.
2. Build Atlas from a clean checkout.
3. Open `packaging/windows/atlas.iss` in Inno Setup Compiler.
4. Set `SourceDir` to the Atlas repository folder if needed.
5. Compile.

The Inno script intentionally lists the packaged folders and files instead of copying the entire repository tree. On reinstall it refreshes program folders such as `backend`, `dashboard`, `docs`, `infra`, `mcp_server`, and `packaging`, while preserving `.env`, `.venv`, and `work`. This prevents stale nested folders from a previous bad install, such as `backend\backend`, from surviving into the next build.

The compiled release artifact is:

```text
packaging\windows\Output\AtlasSetup.exe
```

Publish that file as a GitHub Release asset so judges can download it without cloning or rebuilding Atlas.

The installer defaults to:

```text
{localappdata}\Atlas
```

but the person can choose any folder. The destination page is forced on so a reinstall does not silently reuse a previous Atlas location without showing it. For the current local workflow, `C:\Users\Admin\Atlas` is also fine.

The installer uses the selected folder for the optional user PATH entry. When `atlas attach` runs, it writes that same folder into your global `~/.codex/config.toml` and the project's `.codex/config.toml`. If Atlas is later moved or reinstalled elsewhere, rerun `atlas attach . --project-name <name>` once in each attached project.

## MSI Later

MSI/WiX is better for enterprise deployment, but it is more work. Start with Inno Setup, validate the install/attach flow, then consider WiX only if Atlas needs managed corporate install/uninstall behavior.

## PATH Note

Run the installer from a normal user PowerShell, not a different elevated/sandboxed identity, when testing PATH. If `atlas` is still not recognized after install, open a new terminal. If it still fails, verify:

```powershell
reg query HKCU\Environment /v Path
```

The value should include the Atlas install folder.
