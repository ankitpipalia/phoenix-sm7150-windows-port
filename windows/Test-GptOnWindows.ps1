# Acceptance test for a new phone GPT before it is written to the phone:
# writes the exact primary (LBA 0-5) and backup (last 5 LBAs) GPT sectors into
# an empty LUN0-sized 4Kn VHDX and lists what Windows' partition manager makes
# of them. The VHDX is deleted afterwards.
#   .\Test-GptOnWindows.ps1 -Head lun0-new-head-lba0-5.bin -Tail lun0-new-tail.bin [-Lun0Sectors 30922752]
param(
  [Parameter(Mandatory)] [string] $Head,
  [Parameter(Mandatory)] [string] $Tail,
  [uint64] $Lun0Sectors = 30922752,
  [string] $Scratch = (Join-Path $env:TEMP 'phoenix-gpt-test.vhdx')
)
$ErrorActionPreference = 'Stop'
if (Test-Path $Scratch) { Dismount-DiskImage -ImagePath $Scratch -ErrorAction SilentlyContinue | Out-Null; Remove-Item $Scratch }
& (Join-Path $PSScriptRoot 'New-4knVhdx.ps1') -Path $Scratch -Size ($Lun0Sectors * 4096) | Out-Null
$d = Mount-DiskImage -ImagePath $Scratch -NoDriveLetter -PassThru | Get-Disk
try {
  Add-Type -TypeDefinition @"
using System; using System.IO; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
public static class RawWrite {
  [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  static extern SafeFileHandle CreateFile(string n, uint a, uint s, IntPtr sa, uint d, uint f, IntPtr t);
  public static void Write(int disk, long offset, byte[] data) {
    var h = CreateFile(@"\\.\PhysicalDrive" + disk, 0xC0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
    if (h.IsInvalid) throw new IOException("open failed: " + Marshal.GetLastWin32Error());
    using (var fs = new FileStream(h, FileAccess.ReadWrite)) { fs.Seek(offset, SeekOrigin.Begin); fs.Write(data, 0, data.Length); fs.Flush(); }
  }
}
"@
  $tailBytes = [IO.File]::ReadAllBytes((Resolve-Path $Tail))
  [RawWrite]::Write($d.Number, 0, [IO.File]::ReadAllBytes((Resolve-Path $Head)))
  [RawWrite]::Write($d.Number, ($Lun0Sectors * 4096) - $tailBytes.Length, $tailBytes)
  Update-Disk -Number $d.Number
  Start-Sleep 2
  $d = Get-Disk -Number $d.Number
  "partition style {0}, disk GUID {1}" -f $d.PartitionStyle, $d.Guid
  $parts = Get-Partition -DiskNumber $d.Number
  "partitions seen by Windows: $($parts.Count)"
  $parts | Select-Object -Last 4 PartitionNumber, @{n='StartLBA';e={$_.Offset / 4096}}, @{n='Sectors';e={$_.Size / 4096}}, GptType, Guid |
    Format-Table -AutoSize | Out-String -Width 200
} finally {
  Dismount-DiskImage -ImagePath $Scratch | Out-Null
  Remove-Item $Scratch
}
