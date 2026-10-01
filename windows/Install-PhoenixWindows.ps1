# Fills the attached phoenix VHDX (see New-PhoenixVhdx.ps1): applies Windows,
# stages the first-boot drivers, writes the boot files and BCD, drops in
# unattend.xml and applies the offline first-boot settings.
#
# Needs an elevated PowerShell and the Windows ADK "Deployment Tools" feature
# matching the image (ADK 10.1.26100.x for Windows 11 24H2/25H2): Microsoft does
# not support servicing a Windows 11 image with an older host's DISM.
#
#   .\Install-PhoenixWindows.ps1 -Iso D:\Win11_25H2_English_Arm64_v2.iso `
#       -DriverRoot D:\drivers [-Index 3] [-DriverList .\first-boot-drivers.txt]
#
#   -DriverRoot  folder holding checkouts of Project-Aloha/windows_silicon_qcom_moorea
#                (and windows_oem_xiaomi_surya); paths in -DriverList are relative to it
#   -Index       image index in install.wim (3 = Windows 11 Pro on the 25H2 multi-edition ISO;
#                check with: dism /Get-ImageInfo /ImageFile:<iso>\sources\install.wim)
param(
  [Parameter(Mandatory)] [string] $Iso,
  [Parameter(Mandatory)] [string] $DriverRoot,
  [int] $Index = 3,
  [string] $DriverList = (Join-Path $PSScriptRoot 'first-boot-drivers.txt'),
  [string] $Unattend = (Join-Path $PSScriptRoot 'unattend.xml'),
  [char] $EspLetter = 'S',
  [char] $WinLetter = 'W'
)
$ErrorActionPreference = 'Stop'
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
$kit = "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\$arch"
$dism = "$kit\DISM\dism.exe"; $bcdboot = "$kit\BCDBoot\bcdboot.exe"
foreach ($t in $dism, $bcdboot) { if (-not (Test-Path $t)) { throw "ADK Deployment Tools not found: $t" } }
$S = "${EspLetter}:"; $W = "${WinLetter}:"
foreach ($v in $S, $W) { if (-not (Test-Path "$v\")) { throw "$v is not mounted (attach the VHDX first)" } }

"== 1/5 apply Windows (index $Index)"
$img = Get-DiskImage -ImagePath $Iso
if (-not $img.Attached) { $img = Mount-DiskImage -ImagePath $Iso -PassThru }
$wim = "$(($img | Get-Volume).DriveLetter):\sources\install.wim"
& $dism /English /Get-ImageInfo /ImageFile:$wim /Index:$Index | Select-String 'Name|Version|Architecture'
& $dism /English /Apply-Image /ImageFile:$wim /Index:$Index /ApplyDir:$W\
if ($LASTEXITCODE) { throw "apply failed: $LASTEXITCODE" }

"== 2/5 stage drivers from $DriverList"
$infs = Get-Content $DriverList | ForEach-Object { ($_ -replace '#.*$', '').Trim() } | Where-Object { $_ }
foreach ($rel in $infs) {
  $inf = Join-Path $DriverRoot $rel
  if (-not (Test-Path $inf)) { throw "missing $inf" }
  # The packs are test-signed: /ForceUnsigned to stage, testsigning (below) to load.
  & $dism /English /Image:$W\ /Add-Driver /Driver:$inf /ForceUnsigned | Out-Null
  if ($LASTEXITCODE) { throw "add-driver failed for $rel" }
  "  staged $rel"
}

"== 3/5 boot files and BCD"
& $bcdboot "$W\Windows" /s $S /f UEFI /l en-us
if ($LASTEXITCODE) { throw "bcdboot failed: $LASTEXITCODE" }
$bcd = "$S\EFI\Microsoft\Boot\BCD"
function B { & bcdedit.exe /store $bcd @args | Out-Null; if ($LASTEXITCODE) { throw "bcdedit $args failed" } }
B /set '{default}' testsigning on          # the driver packs are test-signed
B /set '{default}' bootlog yes             # C:\Windows\ntbtlog.txt
B /set '{default}' hypervisorlaunchtype off  # Hyper-V does not work on SM7150 phones
B /set '{bootmgr}' displaybootmenu yes
B /set '{bootmgr}' timeout 5
# A second entry for kernel debugging over USB, as in the Moorea BSP's docs/NTDBG.md.
$copy = & bcdedit.exe /store $bcd /copy '{default}' /d 'Windows 11 (KDNET debug)'
$dbg = [regex]::Match(($copy -join ' '), '\{[0-9a-fA-F-]{36}\}').Value
if (-not $dbg) { throw "bcdedit /copy failed: $copy" }
B /set $dbg debug on
B /dbgsettings NET BUSPARAMS:1 KEY:1.2.3.4 HOSTIP:169.254.255.255 PORT:50000 NODHCP
if (-not (Test-Path "$S\EFI\Boot\bootaa64.efi")) {
  New-Item -ItemType Directory -Force "$S\EFI\Boot" | Out-Null
  Copy-Item "$S\EFI\Microsoft\Boot\bootmgfw.efi" "$S\EFI\Boot\bootaa64.efi"
}

"== 4/5 unattend.xml"
New-Item -ItemType Directory -Force "$W\Windows\Panther" | Out-Null
Copy-Item $Unattend "$W\Windows\Panther\unattend.xml" -Force

"== 5/5 offline settings"
& cmd.exe /c (Join-Path $PSScriptRoot 'Set-PhoenixOfflineSettings.cmd') $WinLetter
if ($LASTEXITCODE) { throw "offline settings failed" }
"done; next: .\Test-PhoenixImage.ps1, then .\Export-PhoenixPartitions.ps1"
