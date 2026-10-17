; No Man's Sky Companion - standalone installer (Inno Setup 6.3+).
;
; Per-user by design: the in-app updater replaces the install folder, which needs no elevation here.
; The two optional parts (the AI assistant and spoken replies) are a wizard page; postinstall.ps1
; fetches whatever was ticked. Nothing of the game's is packaged - mapping.json (LGPL-3.0) is downloaded
; at runtime and item names and icons are read from the user's own installation.
;
; What IS packaged, and therefore credited: the embeddable Python and the five wheels the host imports,
; one of which (pystray) is LGPL-3.0. It is shipped unmodified and dynamically imported, and its own
; licence text travels with it in vendor\python\Lib\site-packages\pystray-*.dist-info. The full list is
; THIRD-PARTY-NOTICES.md, which is installed beside the program and shown on the wizard's info page.

#define MyAppName "NMS Companion"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{8D4D5B4E-6F2A-4C5D-9E1B-NMSCOMPANION}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Reto Kummer alias Reat Kay, Shorthand Dev / TronTronic Entertainment
AppPublisherURL=https://github.com/trontronicent/40k-assistant-nomanssky
DefaultDirName={localappdata}\Programs\NMS Companion
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=nms-companion-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\LICENSE
; Shown after the licence page, so the third-party notices are read before anything is copied.
InfoBeforeFile=..\THIRD-PARTY-NOTICES.md
AppSupportURL=https://github.com/trontronicent/40k-assistant-nomanssky/issues
AppUpdatesURL=https://github.com/trontronicent/40k-assistant-nomanssky/releases
AppCopyright=Copyright (c) 2026 Reto Kummer alias Reat Kay, Shorthand Dev / TronTronic Entertainment

[Files]
Source: "..\nms_connector\*"; DestDir: "{app}\nms_connector"; Flags: recursesubdirs ignoreversion
Source: "..\standalone\*";    DestDir: "{app}\standalone";    Flags: recursesubdirs ignoreversion
Source: "..\codex\*";         DestDir: "{app}\codex";         Flags: recursesubdirs ignoreversion
Source: "..\vendor\*";        DestDir: "{app}\vendor";        Flags: recursesubdirs ignoreversion
Source: "..\strategicum-plugin.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\HELP.md";         DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE";         DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "postinstall.ps1";    DestDir: "{app}"; Flags: ignoreversion
Source: "40k-12b-companion.Modelfile"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\vendor\python\pythonw.exe"; \
  Parameters: "-m standalone"; WorkingDir: "{app}"; \
  IconFilename: "{app}\standalone\web\favicon.ico"
Name: "{group}\{#MyAppName} help"; Filename: "{app}\HELP.md"
Name: "{group}\{#MyAppName} credits"; Filename: "{app}\THIRD-PARTY-NOTICES.md"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\vendor\python\pythonw.exe"; \
  Parameters: "-m standalone"; WorkingDir: "{app}"; \
  IconFilename: "{app}\standalone\web\favicon.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "autostart";   Description: "Start with Windows (tray icon only, no window)"; Flags: unchecked

[Registry]
; The tray icon is the face of a windowless start, so autostart opens no browser.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "NMS Companion"; \
  ValueData: """{app}\vendor\python\pythonw.exe"" -m standalone --no-browser"; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\postinstall.ps1"" {code:GetExtraFlags}"; \
  StatusMsg: "Setting up the optional parts (this can take a while)..."; Flags: runhidden
Filename: "{app}\vendor\python\pythonw.exe"; Parameters: "-m standalone"; WorkingDir: "{app}"; \
  Description: "Start {#MyAppName}"; Flags: postinstall nowait skipifsilent

[Code]
var
  OptionsPage: TInputOptionWizardPage;

procedure InitializeWizard;
begin
  OptionsPage := CreateInputOptionPage(wpSelectTasks,
    'Optional parts', 'What should be set up as well?',
    'Both are optional. Without the AI assistant the program still shows your inventories, maps, ' +
    'timers, discoveries and companions, and searches the Codex; only the chat needs it.',
    False, False);
  OptionsPage.Add('AI assistant: install Ollama if missing, then gemma4:12b and the 40k-12b-companion ' +
                  'model (several GB)');
  OptionsPage.Add('Spoken replies: download Piper and one voice (about 70 MB)');
  OptionsPage.Values[0] := False;
  OptionsPage.Values[1] := False;
end;

function GetExtraFlags(Param: String): String;
begin
  Result := '';
  if OptionsPage.Values[0] then Result := Result + ' -WithAi';
  if OptionsPage.Values[1] then Result := Result + ' -WithVoice';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // The data dir holds months of planet history, the settings and the generated Codex. It is kept
  // unless the user says otherwise - deleting it silently would be unrecoverable.
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\NMS Companion');
    if DirExists(DataDir) then
      if MsgBox('Also delete your companion data (settings, planet history, Codex documents)?' + #13#10 +
                DataDir, mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
