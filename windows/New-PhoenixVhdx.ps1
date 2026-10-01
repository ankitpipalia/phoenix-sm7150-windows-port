# Creates the phoenix LUN0 VHDX that the Windows image is built in, laid out
# exactly as the phone's LUN0 will be after userdata is replaced:
#
#   - 4096-byte logical and physical sectors (the UFS LUNs are 4Kn, and NTFS/FAT
#     made on 512-byte sectors would not mount on the phone),
#   - the same size as LUN0 and the same GPT disk GUID as LUN0, because the BCD
#     that bcdboot writes names its boot partitions by disk GUID + partition GUID,
#   - the ESP starting at userdata's first LBA, Windows right after it to the end.
#
# Read LUN0's numbers on the phone first (Linux or the rescue shell):
#   sfdisk -d /dev/sda        -> label-id (DiskGuid), userdata start
#   cat /sys/block/sda/size   -> 512-byte units; divide by 8 for LUN0 sectors
#
#   .\New-PhoenixVhdx.ps1 -Path C:\phx\phoenix-lun0.vhdx -DiskGuid '{xxxxxxxx-...}' `
#       [-Lun0Sectors 30922752] [-UserdataStartLba 2851328] [-EspSizeMiB 512]
#
# Prints the two partition GUIDs at the end: the phone's new esp/win GPT
# entries must carry exactly these (device/make-lun0-windows-gpt.sh).
param(
  [Parameter(Mandatory)] [string] $Path,
  [Parameter(Mandatory)] [string] $DiskGuid,
  [uint64] $Lun0Sectors = 30922752,
  [uint64] $UserdataStartLba = 2851328,
  [int] $EspSizeMiB = 512,
  [char] $EspLetter = 'S',
  [char] $WinLetter = 'W'
)
$ErrorActionPreference = 'Stop'
$size = $Lun0Sectors * 4096
if ($UserdataStartLba % 256) { throw 'userdata start is expected to be 1 MiB aligned' }
& (Join-Path $PSScriptRoot 'New-4knVhdx.ps1') -Path $Path -Size $size | Out-Null
$disk = Mount-DiskImage -ImagePath $Path -NoDriveLetter -PassThru | Get-Disk
if ($disk.LogicalSectorSize -ne 4096 -or $disk.PhysicalSectorSize -ne 4096) { throw 'VHDX did not attach with 4096-byte sectors' }
Initialize-Disk -Number $disk.Number -PartitionStyle GPT
Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | Remove-Partition -Confirm:$false
Set-Disk -Number $disk.Number -Guid $DiskGuid
$espKB = $UserdataStartLba * 4
$winKB = $espKB + $EspSizeMiB * 1024
$script = @"
select disk $($disk.Number)
create partition efi size=$EspSizeMiB offset=$espKB
format quick fs=fat32 label=ESP
assign letter=$EspLetter
create partition primary offset=$winKB
format quick fs=ntfs label=Windows
assign letter=$WinLetter
"@
$f = [IO.Path]::GetTempFileName()
Set-Content -Path $f -Value $script -Encoding ASCII
diskpart /s $f | Out-Null
Remove-Item $f
$d = Get-Disk -Number $disk.Number
"disk {0}: {1} bytes, {2}-byte sectors, GUID {3}" -f $d.Number, $d.Size, $d.LogicalSectorSize, $d.Guid
Get-Partition -DiskNumber $disk.Number | ForEach-Object {
  "  partition {0}: LBA {1}, {2} sectors, type {3}, GUID {4}" -f $_.PartitionNumber, ($_.Offset / 4096), ($_.Size / 4096), $_.GptType, $_.Guid
}
