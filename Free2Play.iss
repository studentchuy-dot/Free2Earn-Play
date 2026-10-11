#define AppName "Free2Play"
#define AppVersion "1.0.0"
#define SourceDir "dist\Free2Play"

[Setup]
AppId={{F7BA280A-1C3D-4B34-9C32-8A47B2CB102E}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=Free2Play-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Free2Play"; Filename: "{app}\Free2Play.exe"
Name: "{autodesktop}\Free2Play"; Filename: "{app}\Free2Play.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Free2Play.exe"; Description: "Iniciar Free2Play"; Flags: postinstall nowait skipifsilent
