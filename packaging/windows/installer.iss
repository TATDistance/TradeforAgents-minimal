#define MyAppName "TradeforAgents-minimal"
#define MyAppPublisher "TradeforAgents"

#ifndef AppVersion
  #define AppVersion "v0.0.0-dev"
#endif

#ifndef SourceDir
  #define SourceDir "..\..\dist\TradeforAgents-minimal-windows-noinstall"
#endif

#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{5DA3A896-ADEB-4E50-B819-BEC86E9E8A3A}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\TradeforAgents-minimal
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
WizardStyle=modern
OutputDir={#OutputDir}
OutputBaseFilename=TradeforAgents-minimal-windows-installer
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TradeforAgentsLauncher.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\TradeforAgents-minimal"; Filename: "{app}\TradeforAgentsLauncher.exe"; Parameters: "launch"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\TradeforAgents-minimal"; Filename: "{app}\TradeforAgentsLauncher.exe"; Parameters: "launch"; WorkingDir: "{app}"
Name: "{group}\TradeforAgents-minimal Debug Console"; Filename: "{app}\debug_console.bat"; WorkingDir: "{app}"
Name: "{group}\卸载 TradeforAgents-minimal"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\TradeforAgentsLauncher.exe"; Parameters: "launch"; Description: "安装后立即启动桌面版首页"; Flags: nowait postinstall skipifsilent
