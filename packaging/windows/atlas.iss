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

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.venv\*,.codex\*,.agents\*,.pytest_cache\*,.docker-tmp\*,work\*,outputs\*,.env,packaging\windows\Output\*"

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
