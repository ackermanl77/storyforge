; Instalador por usuario (sin permisos de administrador) para el build onedir
; de StoryForge (`dist\StoryForge\`). Compilar con Inno Setup 6:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=0.4.0 /DBuildVariant=cpu installer\StoryForge.iss
; El script deja el instalador en dist\installer\ y NO incluye modelos .gguf:
; solo crea {app}\models\README.txt para que el usuario copie su modelo aparte.

#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
#ifndef BuildVariant
  #define BuildVariant "local"
#endif
#define AppName "StoryForge Local"
#define AppExe "StoryForge.exe"
#define AppKey "StoryForge"
#define AppSourceDir "..\dist\StoryForge"
; Sin el build no hay instalador: antes se generaba uno vacio en silencio.
#if !FileExists(AddBackslash(SourcePath) + AppSourceDir + "\" + AppExe)
  #error dist\StoryForge\StoryForge.exe no existe: corre build.bat (o PyInstaller) antes de compilar el instalador.
#endif

[Setup]
AppId={{1F1D66AF-74BC-4AA6-A3B9-BD2D1B7278D7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MELEJ
DefaultDirName={localappdata}\Programs\{#AppKey}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=StoryForge-{#AppVersion}-{#BuildVariant}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Al actualizar, cerrar StoryForge si esta abierto.
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Dirs]
; Los modelos .gguf que copie el usuario aqui no los instalo el setup, asi que
; el desinstalador no los borra.
Name: "{app}\models"

[InstallDelete]
; Una actualizacion no debe dejar archivos de una version anterior mezclados.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\models\README.txt"; DestDir: "{app}\models"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent
