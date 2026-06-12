; Inno Setup script for Stream Studio
; Produces a classic "Next -> Next -> Finish" Windows installer.

#define AppName "Stream Studio"
#define AppVersion "1.0.0"
#define AppPublisher "Stream Studio"
#define AppExe "StreamStudio.exe"

[Setup]
AppId={{3C9E5F18-7A2D-4B6E-9F41-2E8A5D0C7B34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Setup
OutputBaseFilename=StreamStudio-Setup
SetupIconFile=build_assets\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startup"; Description: "Start Stream Studio automatically when I sign in (recommended, so the Chrome button always works)"; GroupDescription: "Background service:"

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "chrome-extension\*"; DestDir: "{app}\chrome-extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist-readme.txt"; DestDir: "{app}"; DestName: "READ ME FIRST.txt"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Chrome extension folder"; Filename: "{app}\chrome-extension"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{commonstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--autostart"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent
