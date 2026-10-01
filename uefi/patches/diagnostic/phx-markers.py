# Diagnostic markers for the phoenix UEFI hang (not a fix). Applied to the pinned Mu-Silicium tree.
from pathlib import Path
def sub(path, old, new):
    p = Path(path); s = p.read_text()
    assert s.count(old) == 1, (path, s.count(old), old[:60])
    p.write_text(s.replace(old, new))
img = "Mu_Basecore/MdeModulePkg/Core/Dxe/Image/Image.c"
sub(img, """  Status = ProtectUefiImage (&Image->Info, Image->LoadedImageDevicePath);
  if (EFI_ERROR (Status)) {
    goto Done;
  }

  //""", """  DEBUG ((DEBUG_ERROR, "[PHX] protect+ %p\\n", Image->Info.ImageBase));
  Status = ProtectUefiImage (&Image->Info, Image->LoadedImageDevicePath);
  DEBUG ((DEBUG_ERROR, "[PHX] protect- %p %r\\n", Image->Info.ImageBase, Status));
  if (EFI_ERROR (Status)) {
    goto Done;
  }

  //""")
sub(img, """    Image->Started = TRUE;
    Image->Status  = Image->EntryPoint (ImageHandle, Image->Info.SystemTable);
""", """    Image->Started = TRUE;
    DEBUG ((DEBUG_ERROR, "[PHX] start+ %p\\n", Image->Info.ImageBase));
    Image->Status  = Image->EntryPoint (ImageHandle, Image->Info.SystemTable);
    DEBUG ((DEBUG_ERROR, "[PHX] start- %p %r\\n", Image->Info.ImageBase, Image->Status));
""")
mmu = "Mu_Basecore/UefiCpuPkg/Library/ArmMmuLib/AArch64/ArmMmuLibCore.c"
sub(mmu, """      DisableMmu = TRUE;
      DEBUG ((DEBUG_WARN, "%a: splitting block entry with MMU disabled\\n", __func__));
    }

    mReplaceLiveEntryFunc (Entry, Value, RegionStart, DisableMmu);
""", """      DisableMmu = TRUE;
      DEBUG ((DEBUG_WARN, "%a: splitting block entry with MMU disabled\\n", __func__));
    }

    DEBUG ((DEBUG_ERROR, "[PHX] split region=%lx mask=%lx entry=%p fn=%lx mmuoff=%d\\n",
            RegionStart, BlockMask, Entry, (UINT64)(UINTN)mReplaceLiveEntryFunc, DisableMmu));
    mReplaceLiveEntryFunc (Entry, Value, RegionStart, DisableMmu);
    DEBUG ((DEBUG_ERROR, "[PHX] split done %lx\\n", RegionStart));
""")
print("markers applied")
