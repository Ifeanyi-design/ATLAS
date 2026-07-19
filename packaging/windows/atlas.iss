#define MyAppName "Atlas"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Atlas"
#define SourceDir "..\.."

[Setup]
AppId={{6C0F3C62-8F7F-4CF5-BC14-49D36E9F6C9C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; The user may choose any folder. {app} is passed to every setup action below,
; so neither PATH nor generated Codex config points to a hard-coded location.
DefaultDirName={localappdata}\Atlas
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=AtlasSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
SetupIconFile=assets\atlas.ico
DisableDirPage=no
AlwaysShowDirOnReadyPage=yes

[InstallDelete]
; Refresh program files on reinstall without touching user/runtime state.
; Keep {app}\work, {app}\.env, and {app}\.venv intact.
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\dashboard"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\infra"
Type: filesandordirs; Name: "{app}\mcp_server"
Type: filesandordirs; Name: "{app}\packaging"
Type: files; Name: "{app}\atlas.cmd"
Type: files; Name: "{app}\docker-compose.yml"
Type: files; Name: "{app}\install-atlas.ps1"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\pytest.ini"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\requirements.txt"

[Files]
Source: "{#SourceDir}\atlas.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\docker-compose.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\install-atlas.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\pytest.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\.env.example"; DestDir: "{app}"; Flags: ignoreversion

Source: "{#SourceDir}\backend\alembic.ini"; DestDir: "{app}\backend"; Flags: ignoreversion
Source: "{#SourceDir}\backend\app\*"; DestDir: "{app}\backend\app"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#SourceDir}\backend\migrations\*"; DestDir: "{app}\backend\migrations"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#SourceDir}\backend\scripts\*"; DestDir: "{app}\backend\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#SourceDir}\backend\tests\*"; DestDir: "{app}\backend\tests"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"

Source: "{#SourceDir}\dashboard\*.html"; DestDir: "{app}\dashboard"; Flags: ignoreversion
Source: "{#SourceDir}\dashboard\*.css"; DestDir: "{app}\dashboard"; Flags: ignoreversion
Source: "{#SourceDir}\dashboard\*.js"; DestDir: "{app}\dashboard"; Flags: ignoreversion

Source: "{#SourceDir}\docs\*.md"; DestDir: "{app}\docs"; Flags: ignoreversion

Source: "{#SourceDir}\infra\postgres\init\*"; DestDir: "{app}\infra\postgres\init"; Flags: ignoreversion

Source: "{#SourceDir}\mcp_server\*.py"; DestDir: "{app}\mcp_server"; Flags: ignoreversion

Source: "{#SourceDir}\packaging\windows\README.md"; DestDir: "{app}\packaging\windows"; Flags: ignoreversion
Source: "{#SourceDir}\packaging\windows\atlas.iss"; DestDir: "{app}\packaging\windows"; Flags: ignoreversion
Source: "{#SourceDir}\packaging\windows\assets\*"; DestDir: "{app}\packaging\windows\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Atlas Setup"; Filename: "{app}\atlas.cmd"; Parameters: "setup"; WorkingDir: "{app}"
Name: "{group}\Atlas Doctor"; Filename: "{app}\atlas.cmd"; Parameters: "doctor"; WorkingDir: "{app}"

[Tasks]
Name: "addtopath"; Description: "Add Atlas to my user PATH"; GroupDescription: "Command line access:"; Flags: checkedonce

[Run]
; This builds the local virtual environment and optionally updates PATH. It runs
; hidden, so -NoPathPrompt prevents an invisible Read-Host prompt.
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install-atlas.ps1"" -InstallDir ""{app}"" -AddToPath -NoPathPrompt"; WorkingDir: "{app}"; Flags: postinstall runhidden; Tasks: addtopath
Filename: "{app}\atlas.cmd"; Parameters: "setup"; WorkingDir: "{app}"; Description: "Run Atlas setup now"; Flags: postinstall skipifsilent unchecked
