; Instalador de Fontiador para Windows (Inno Setup 6).
;
; Compilar:
;   iscc packaging\windows\fontiador.iss
;
; Requiere haber empaquetado antes con PyInstaller:
;   pyinstaller packaging\fontiador.spec --noconfirm
;
; Se instala por usuario (en %LOCALAPPDATA%\Programs\Fontiador) para no pedir
; permisos de administrador y para que la app pueda escribir sus carpetas
; inbox/ y output/ dentro de su propia instalación.

#define MiAppName    "Fontiador"
#define MiVersion    "0.2.8"
#define MiPublisher  "mastopiramato"
#define MiUrl        "https://github.com/mastopiramato/fontiador"
#define MiExeName    "Fontiador.exe"

[Setup]
AppId={{8E4C1A72-5B3D-4F19-9C2E-7A6D0B45E831}
AppName={#MiAppName}
AppVersion={#MiVersion}
AppVerName={#MiAppName} {#MiVersion}
AppPublisher={#MiPublisher}
AppPublisherURL={#MiUrl}
AppSupportURL={#MiUrl}/issues
AppUpdatesURL={#MiUrl}/releases
DefaultDirName={localappdata}\Programs\{#MiAppName}
DefaultGroupName={#MiAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=Fontiador-{#MiVersion}-win-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MiAppName}
UninstallDisplayIcon={app}\{#MiExeName}
; Firmar aqui cuando haya certificado:
; SignTool=signtool
; SignedUninstaller=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
; La aplicacion completa (salida de PyInstaller, modo carpeta).
Source: "..\..\dist\Fontiador\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Documentacion que se copia a la carpeta docs del paquete si existe.
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
; Carpetas de trabajo, escribibles por el usuario en su propia instalacion.
Name: "{app}\inbox"; Permissions: users-modify
Name: "{app}\output"; Permissions: users-modify

[Icons]
Name: "{group}\{#MiAppName}"; Filename: "{app}\{#MiExeName}"; WorkingDir: "{app}"
Name: "{group}\Desinstalar {#MiAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MiAppName}"; Filename: "{app}\{#MiExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MiExeName}"; Description: "Abrir {#MiAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Los datos del usuario (fuentes generadas y proyecto) NO se borran solos:
; se avisa y se dejan, para no destruir trabajo por accidente.
Type: filesandordirs; Name: "{app}\__pycache__"
