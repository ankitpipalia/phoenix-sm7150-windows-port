@echo off
rem Offline registry settings for a supervised first boot of the phoenix image.
rem   Set-PhoenixOfflineSettings.cmd W      (letter of the mounted Windows volume)
rem
rem  - a bugcheck stays on screen (AutoReboot 0) so its stop code can be read;
rem    an automatic restart would only lead back into the same failure
rem  - no hibernation or Fast Startup, so the NTFS volume stays cleanly readable
rem    from the rescue shell or another machine
rem  - no automatic device encryption (and there is no working TPM)
rem  - OOBE's network requirement bypassed, in case a network page appears
rem reg.exe add only creates or sets values; it never deletes keys.
setlocal
set W=%~1
if "%W%"=="" set W=W
reg load HKLM\PHXSYS %W%:\Windows\System32\config\SYSTEM >nul || exit /b 1
reg load HKLM\PHXSW %W%:\Windows\System32\config\SOFTWARE >nul || (reg unload HKLM\PHXSYS >nul & exit /b 1)
set C=HKLM\PHXSYS\ControlSet001\Control
reg add "%C%\CrashControl" /v AutoReboot /t REG_DWORD /d 0 /f >nul
reg add "%C%\CrashControl" /v DisplayParameters /t REG_DWORD /d 1 /f >nul
reg add "%C%\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f >nul
reg add "%C%\Power" /v HibernateEnabled /t REG_DWORD /d 0 /f >nul
reg add "%C%\Power" /v HibernateEnabledDefault /t REG_DWORD /d 0 /f >nul
reg add "%C%\BitLocker" /v PreventDeviceEncryption /t REG_DWORD /d 1 /f >nul
reg add "HKLM\PHXSW\Microsoft\Windows\CurrentVersion\OOBE" /v BypassNRO /t REG_DWORD /d 1 /f >nul
reg query "%C%\CrashControl" /v AutoReboot | findstr AutoReboot
reg query "%C%\Power" /v HibernateEnabled | findstr HibernateEnabled
reg query "%C%\BitLocker" /v PreventDeviceEncryption | findstr PreventDeviceEncryption
reg unload HKLM\PHXSW >nul
reg unload HKLM\PHXSYS >nul
echo offline settings applied
