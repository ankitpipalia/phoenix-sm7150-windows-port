# SHA-256 of bytes [Offset, Offset+Length) of a physical disk, read raw (needs an
# elevated shell). Attach a VHDX read-only first, or NTFS may still hold
# unflushed data and the hash will not match what was written.
#   .\Get-RawDiskHash.ps1 -Disk 3 -Offset 11679039488 -Length 536870912
param([Parameter(Mandatory)] [int] $Disk, [Parameter(Mandatory)] [int64] $Offset, [Parameter(Mandatory)] [int64] $Length)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class RawDisk {
  [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr sa, uint disp, uint flags, IntPtr tmpl);
  public static string Sha256(int disk, long offset, long length) {
    var h = CreateFile(@"\\.\PhysicalDrive" + disk, 0x80000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
    if (h.IsInvalid) throw new IOException("open failed: " + Marshal.GetLastWin32Error());
    using (var fs = new FileStream(h, FileAccess.Read, 1 << 20, false))
    using (var sha = System.Security.Cryptography.SHA256.Create()) {
      fs.Seek(offset, SeekOrigin.Begin);
      var buf = new byte[4 << 20];
      long left = length;
      while (left > 0) {
        int want = (int)Math.Min(buf.Length, left);
        int got = fs.Read(buf, 0, want);
        if (got <= 0) throw new IOException("short read");
        sha.TransformBlock(buf, 0, got, null, 0);
        left -= got;
      }
      sha.TransformFinalBlock(buf, 0, 0);
      return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
    }
  }
}
"@
"{0}  disk {1} offset {2} length {3}" -f [RawDisk]::Sha256($Disk, $Offset, $Length), $Disk, $Offset, $Length
