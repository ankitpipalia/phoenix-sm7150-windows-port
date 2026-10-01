# Diagnostic instrumentation for the phoenix UEFI hang (not a fix). Apply after phx-markers.py.
from pathlib import Path
def sub(path, old, new):
    p = Path(path); s = p.read_text()
    assert s.count(old) == 1, (path, s.count(old), old[:60])
    p.write_text(s.replace(old, new))

# 1. Timer interrupt: every 250 ms print the interrupted PC and LR (a sampling profiler).
sub("Mu_Basecore/ArmPkg/Drivers/TimerDxe/TimerDxe.c",
"""  if ((ArmGenericTimerGetTimerCtrlReg ()) & ARM_ARCH_TIMER_ISTATUS) {
    if (mTimerNotifyFunction != 0) {""",
"""  if ((ArmGenericTimerGetTimerCtrlReg ()) & ARM_ARCH_TIMER_ISTATUS) {
    {
      STATIC UINT64  PhxElapsed;
      STATIC UINT32  PhxSeq;

      PhxElapsed += mTimerPeriod * mElapsedPeriod;
      if (PhxElapsed >= 2500000) {
        PhxElapsed = 0;
        DEBUG ((DEBUG_ERROR, "[PHX] tick %u pc=%lx lr=%lx\\n", ++PhxSeq,
                SystemContext.SystemContextAArch64->ELR, SystemContext.SystemContextAArch64->LR));
      }
    }

    if (mTimerNotifyFunction != 0) {""")

# 2. DXE core: turn tracing on when UFSDxe's entry point is called.
img = "Mu_Basecore/MdeModulePkg/Core/Dxe/Image/Image.c"
sub(img, '#include "MemoryProtectionSupport.h" // MU_CHANGE\n',
         '#include "MemoryProtectionSupport.h" // MU_CHANGE\n\nBOOLEAN  gPhxTrace = FALSE;\n')
sub(img, """    DEBUG ((DEBUG_ERROR, "[PHX] start+ %p\\n", Image->Info.ImageBase));""",
"""    if ((Image->ImageContext.PdbPointer != NULL) && (AsciiStrStr (Image->ImageContext.PdbPointer, "UFSDxe") != NULL)) {
      gPhxTrace = TRUE;
    }

    DEBUG ((DEBUG_ERROR, "[PHX] start+ %p\\n", Image->Info.ImageBase));""")

# 3. GCD: while tracing, print every SetMemorySpaceAttributes request and its result.
sub("Mu_Basecore/MdeModulePkg/Core/Dxe/Gcd/Gcd.c",
"""  DEBUG ((DEBUG_GCD, "  Attributes  = %016lx\\n", Attributes));

  return CoreConvertSpace (GCD_SET_ATTRIBUTES_MEMORY_OPERATION, (EFI_GCD_MEMORY_TYPE)0, (EFI_GCD_IO_TYPE)0, BaseAddress, Length, 0, Attributes);
}""",
"""  DEBUG ((DEBUG_GCD, "  Attributes  = %016lx\\n", Attributes));

  {
    extern BOOLEAN  gPhxTrace;
    EFI_STATUS      PhxStatus;

    if (gPhxTrace) {
      DEBUG ((DEBUG_ERROR, "[PHX] gcdattr+ base=%lx len=%lx attr=%lx\\n", BaseAddress, Length, Attributes));
    }

    PhxStatus = CoreConvertSpace (GCD_SET_ATTRIBUTES_MEMORY_OPERATION, (EFI_GCD_MEMORY_TYPE)0, (EFI_GCD_IO_TYPE)0, BaseAddress, Length, 0, Attributes);
    if (gPhxTrace) {
      DEBUG ((DEBUG_ERROR, "[PHX] gcdattr- %r\\n", PhxStatus));
    }

    return PhxStatus;
  }
}""")
print("instrumentation applied")
