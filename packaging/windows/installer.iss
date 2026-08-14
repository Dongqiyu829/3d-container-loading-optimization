#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif
#ifndef MyAppSource
  #define MyAppSource "..\..\dist\3DContainerLoading"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\..\artifacts"
#endif

#define MyAppName "3D Container Loading Optimizer"
#define MyAppExeName "3DContainerLoading.exe"

[Setup]
AppId={{6C5A304E-91D0-4B46-99C6-29A9596F8DA3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=3D Container Loading Optimization contributors
AppPublisherURL=https://github.com/Dongqiyu829/3d-container-loading-optimization
AppSupportURL=https://github.com/Dongqiyu829/3d-container-loading-optimization/issues
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename=3DContainerLoading-Windows-x64-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Windows installer
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#MyAppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

