# Checks a finished phoenix image before it is exported:
#  - boot files, BCD entries and unattend.xml are present;
#  - both volumes pass a read-only chkdsk;
#  - the BCD's boot devices name this disk's GUID and the ESP/Windows partition
#    GUIDs (bootmgr finds its partitions by these on the phone);
#  - the boot-critical drivers were pre-installed as boot-start services and the
#    offline device database maps each DSDT ID to them. UFS0 depends on
#    PEP0 -> PMIC -> SPMI, so without these the first boot cannot reach its disk.
#   .\Test-PhoenixImage.ps1 [-EspLetter S] [-WinLetter W]
param([char] $EspLetter = 'S', [char] $WinLetter = 'W')
$ErrorActionPreference = 'Stop'
$S = "${EspLetter}:"; $W = "${WinLetter}:"
$fail = 0
function Check($ok, $what) { if ($ok) { "  ok    $what" } else { "  FAIL  $what"; $script:fail++ } }

"== files"
foreach ($f in "$S\EFI\Boot\bootaa64.efi", "$S\EFI\Microsoft\Boot\BCD", "$W\Windows\System32\winload.efi",
               "$W\Windows\System32\ntoskrnl.exe", "$W\Windows\Panther\unattend.xml") {
  Check (Test-Path $f) $f
}

"== read-only chkdsk"
foreach ($v in $S, $W) {
  $r = & chkdsk.exe $v 2>&1 | Out-String
  Check ($r -match 'found no problems') "chkdsk $v"
}

"== BCD boot devices"
$esp = Get-Partition -DriveLetter $EspLetter
$win = Get-Partition -DriveLetter $WinLetter
$disk = Get-Disk -Number $esp.DiskNumber
# Load copies: loading a hive in place can rewrite it, and the image may already be final.
$tmp = Join-Path $env:TEMP "phx-$PID"; New-Item -ItemType Directory -Force $tmp | Out-Null
Copy-Item "$S\EFI\Microsoft\Boot\BCD" "$tmp\BCD"; Copy-Item "$W\Windows\System32\config\SYSTEM" "$tmp\SYSTEM"
reg.exe load HKLM\PHXBCD "$tmp\BCD" | Out-Null
try {
  foreach ($obj in Get-ChildItem HKLM:\PHXBCD\Objects) {
    $p = "$($obj.PSPath)\Elements\11000001"
    if (-not (Test-Path $p)) { continue }
    $b = (Get-ItemProperty $p).Element
    $part = [Guid]::new([byte[]]$b[0x20..0x2f]); $dg = [Guid]::new([byte[]]$b[0x38..0x47])
    $desc = (Get-ItemProperty "$($obj.PSPath)\Elements\12000004" -ErrorAction SilentlyContinue).Element
    Check (($part -eq [Guid]$esp.Guid -or $part -eq [Guid]$win.Guid) -and $dg -eq [Guid]$disk.Guid) "$desc -> partition $part on disk $dg"
  }
} finally { [GC]::Collect(); Start-Sleep 1; reg.exe unload HKLM\PHXBCD | Out-Null }

"== boot-critical drivers"
reg.exe load HKLM\PHXSYS "$tmp\SYSTEM" | Out-Null
try {
  foreach ($svc in 'qcspmi', 'qcpmic', 'qcpep', 'qcgpio', 'storufs') {
    $k = "HKLM:\PHXSYS\ControlSet001\Services\$svc"
    $start = (Get-ItemProperty $k -ErrorAction SilentlyContinue).Start
    Check ($start -eq 0) "service $svc boot-start (Start=$start)"
  }
  $ids = @{ QCOM140C = 'qcspmi'; QCOM142E = 'qcpmic'; QCOM1419 = 'qcpep'; QCOM140D = 'qcgpio';
            QCOM1430 = 'qcpmicgpio'; QCOM1403 = 'HAL timer'; QCOM1404 = 'HAL watchdog'; QCOM24A5 = 'storufs' }
  foreach ($id in $ids.Keys) {
    $k = "HKLM:\PHXSYS\DriverDatabase\DeviceIds\ACPI\$id"
    $infs = if (Test-Path $k) { (Get-Item $k).Property -join ',' } else { '' }
    Check ($infs -ne '') "ACPI\$id ($($ids[$id])) -> $infs"
  }
} finally { [GC]::Collect(); Start-Sleep 1; reg.exe unload HKLM\PHXSYS | Out-Null; Remove-Item -Recurse -Force $tmp }

if ($fail) { "$fail check(s) failed"; exit 1 } else { "all checks passed" }
