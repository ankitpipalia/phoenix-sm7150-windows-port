# Creates a dynamic VHDX with 4096-byte logical and physical sectors through
# the VirtDisk API (CREATE_VIRTUAL_DISK_VERSION_2), which Windows 10 Home has
# even without the Hyper-V module's New-VHD.
param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [uint64] $Size)
$ErrorActionPreference = 'Stop'
$src = @"
using System;
using System.Runtime.InteropServices;
public static class VDisk {
  [StructLayout(LayoutKind.Explicit, Size = 256)]
  public struct CreateParamsV2 {
    [FieldOffset(0)]   public int Version;
    [FieldOffset(8)]   public Guid UniqueId;
    [FieldOffset(24)]  public ulong MaximumSize;
    [FieldOffset(32)]  public uint BlockSizeInBytes;
    [FieldOffset(36)]  public uint SectorSizeInBytes;
    [FieldOffset(40)]  public uint PhysicalSectorSizeInBytes;
    [FieldOffset(48)]  public IntPtr ParentPath;
    [FieldOffset(56)]  public IntPtr SourcePath;
    [FieldOffset(64)]  public int OpenFlags;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct StorageType { public uint DeviceId; public Guid VendorId; }
  [DllImport("virtdisk.dll", CharSet = CharSet.Unicode)]
  public static extern uint CreateVirtualDisk(ref StorageType type, string path, uint mask, IntPtr sd,
      uint flags, uint providerFlags, ref CreateParamsV2 p, IntPtr overlapped, out IntPtr handle);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  public static uint Create(string path, ulong size) {
    var t = new StorageType { DeviceId = 3, VendorId = new Guid("EC984AEC-A0F9-47e9-901F-71415A66345B") };
    var p = new CreateParamsV2 { Version = 2, UniqueId = Guid.Empty, MaximumSize = size,
      BlockSizeInBytes = 0, SectorSizeInBytes = 4096, PhysicalSectorSizeInBytes = 4096 };
    IntPtr h;
    uint rc = CreateVirtualDisk(ref t, path, 0, IntPtr.Zero, 0, 0, ref p, IntPtr.Zero, out h);
    if (rc == 0) CloseHandle(h);
    return rc;
  }
}
"@
Add-Type -TypeDefinition $src
if (Test-Path $Path) { throw "$Path already exists" }
$rc = [VDisk]::Create($Path, $Size)
if ($rc -ne 0) { throw "CreateVirtualDisk failed: $rc ($([ComponentModel.Win32Exception]::new([int]$rc).Message))" }
Get-Item $Path | Select-Object FullName, Length | Format-List | Out-String
