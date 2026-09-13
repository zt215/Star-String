; 星弦 安装包脚本（Inno Setup 6）
;
; 作用：
;   1) 安装星弦客户端（PyInstaller 打包产物）
;   2) 随包注册虚拟摄像头驱动，设备名固定为「星弦虚拟摄像头」
;   3) 卸载时自动注销该虚拟摄像头
;
; 编译前请先打包客户端（见 installer/README.md）：
;   cd client-python
;   pyinstaller --noconfirm --windowed --name 星弦 ^
;       --add-data "app/resources;app/resources" start.py
; 然后用 Inno Setup 编译本脚本：
;   iscc installer\star_string.iss

#define AppName "星弦"
#define AppVersion "0.1.0"
#define AppPublisher "StarString"
#define AppExeName "星弦.exe"
#define CameraName "星弦虚拟摄像头"
#define DistDir "..\client-python\dist\星弦"
#define DriverDir "..\client-python\app\resources\virtualcam"

[Setup]
AppId={{8C1E4A3B-2F5D-4E9A-9B7C-3D6F1A2E5C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\StarString
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=星弦安装包
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 注册/注销驱动需要管理员权限
PrivilegesRequired=admin

[Tasks]
Name: "installvcam"; Description: "安装「{#CameraName}」虚拟摄像头（直播伴侣可直接选用）"; GroupDescription: "组件:"; Flags: checkedonce
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
; 客户端本体（PyInstaller 产物）
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 虚拟摄像头驱动（UnityCapture，MIT 许可）
; 注意：必须放在纯 ASCII 路径，否则 UnityCapture 注册时会截断路径导致设备不可用
Source: "{#DriverDir}\UnityCaptureFilter32.dll"; DestDir: "{commonappdata}\StarString\virtualcam"; Flags: ignoreversion
Source: "{#DriverDir}\UnityCaptureFilter64.dll"; DestDir: "{commonappdata}\StarString\virtualcam"; Flags: ignoreversion
Source: "{#DriverDir}\UnityCapture-README.md"; DestDir: "{commonappdata}\StarString\virtualcam"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; 注册 64 位虚拟摄像头（自定义设备名）
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{commonappdata}\StarString\virtualcam\UnityCaptureFilter64.dll"" ""/i:UnityCaptureName={#CameraName}"""; StatusMsg: "正在安装虚拟摄像头驱动..."; Flags: runhidden waituntilterminated; Tasks: installvcam
; 注册 32 位虚拟摄像头（供 32 位软件使用）
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s ""{commonappdata}\StarString\virtualcam\UnityCaptureFilter32.dll"" ""/i:UnityCaptureName={#CameraName}"""; StatusMsg: "正在安装虚拟摄像头驱动..."; Flags: runhidden waituntilterminated; Tasks: installvcam
Filename: "{app}\{#AppExeName}"; Description: "立即启动{#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\regsvr32.exe"; Parameters: "/u /s ""{commonappdata}\StarString\virtualcam\UnityCaptureFilter64.dll"""; Flags: runhidden waituntilterminated
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/u /s ""{commonappdata}\StarString\virtualcam\UnityCaptureFilter32.dll"""; Flags: runhidden waituntilterminated
