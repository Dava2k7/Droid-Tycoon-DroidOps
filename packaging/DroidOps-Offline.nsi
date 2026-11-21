Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef VERSION
  !define VERSION "1.0.54"
!endif
Name "Danksy DroidOps"
OutFile "${OUTPUT}"
InstallDir "$PROGRAMFILES64\Danksy\DroidOps"
InstallDirRegKey HKLM "Software\Danksy\DroidOps" "InstallDir"
RequestExecutionLevel admin
SetCompressor zlib
SetCompressionLevel 6
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Danksy DroidOps"
VIAddVersionKey "CompanyName" "Danksy"
VIAddVersionKey "FileDescription" "Danksy DroidOps Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright 2026 Danksy"

!define MUI_ICON "${PAYLOAD}/app.ico"
!define MUI_UNICON "${PAYLOAD}/app.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\DroidOps.exe"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PAYLOAD}/LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "DroidOps requires 64-bit Windows 10 or Windows 11."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "DroidOps requires Windows 10 or later."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "Danksy DroidOps"
  SetShellVarContext all
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}/*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Danksy\DroidOps" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "DisplayName" "Danksy DroidOps"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "Publisher" "Danksy"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\Danksy DroidOps"
  CreateShortcut "$SMPROGRAMS\Danksy DroidOps\Danksy DroidOps.lnk" "$INSTDIR\DroidOps.exe" "" "$INSTDIR\app.ico"
  CreateShortcut "$SMPROGRAMS\Danksy DroidOps\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Danksy DroidOps.lnk" "$INSTDIR\DroidOps.exe" "" "$INSTDIR\app.ico"

  ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Services\ViGEmBus" "ImagePath"
  ${If} $0 == ""
    DetailPrint "Installing the bundled virtual Xbox controller driver..."
    ExecWait '$\"$INSTDIR\Driver\ViGEmBus_1.22.0_x64_x86_arm64.exe$\" /quiet /norestart' $1
    ${If} $1 == 3010
      SetRebootFlag true
    ${ElseIf} $1 != 0
      MessageBox MB_ICONEXCLAMATION "The controller driver returned code $1. DroidOps files are installed. Restart Windows, then run the included Driver installer if controller connection fails."
    ${EndIf}
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetRegView 64
  SetShellVarContext all
  !include "${UNINSTALL_LIST}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\Danksy DroidOps.lnk"
  Delete "$SMPROGRAMS\Danksy DroidOps\Danksy DroidOps.lnk"
  Delete "$SMPROGRAMS\Danksy DroidOps\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Danksy DroidOps"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DanksyDroidOps"
  DeleteRegKey HKLM "Software\Danksy\DroidOps"
SectionEnd
