# Finalises the phoenix VHDX for transfer: detaches it cleanly (which flushes
# NTFS and empties the VHDX log), re-attaches it read-only and hashes the ESP
# and Windows partitions as raw bytes, plus the VHDX file itself.
#
# tools/vhdx-to-android-sparse.py prints the same SHA-256 for each partition
# it converts ("expanded sha256", unallocated blocks counted as zeros); the
# values must be identical before anything is flashed.
#   .\Export-PhoenixPartitions.ps1 -Path C:\phx\phoenix-lun0.vhdx
param([Parameter(Mandatory)] [string] $Path)
$ErrorActionPreference = 'Stop'
if ((Get-DiskImage -ImagePath $Path).Attached) { Dismount-DiskImage -ImagePath $Path | Out-Null }
$disk = Mount-DiskImage -ImagePath $Path -Access ReadOnly -NoDriveLetter -PassThru | Get-Disk
try {
  "disk GUID {0}" -f $disk.Guid
  foreach ($p in Get-Partition -DiskNumber $disk.Number) {
    $h = & (Join-Path $PSScriptRoot 'Get-RawDiskHash.ps1') -Disk $disk.Number -Offset $p.Offset -Length $p.Size
    "partition {0}: --offset {1} --size {2}  GUID {3}  type {4}" -f $p.PartitionNumber, $p.Offset, $p.Size, $p.Guid, $p.GptType
    "  raw sha256 {0}" -f ($h -split ' ')[0]
  }
} finally { Dismount-DiskImage -ImagePath $Path | Out-Null }
"vhdx sha256 {0}  {1} bytes" -f (Get-FileHash -Algorithm SHA256 $Path).Hash.ToLower(), (Get-Item $Path).Length
