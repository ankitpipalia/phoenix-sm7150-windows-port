# Experiment 4 for the phoenix UEFI hang: SEC as it was before d3f5d84c
# ("MooreaPkg: Enable MMU Detach", 2026-06-29). That commit replaced the UFS
# context-bank coherency write with ArmSmmuDetach(), which detaches every SMMU
# stream except the display's. Phoenix's stubbed UFSDxe never re-attaches UFS.
# This restores EnableUfsCacheCoherency() exactly as in a72d7eb4 and drops the detach.
from pathlib import Path
p = Path("Silicon/Qualcomm/MooreaPkg/Library/PlatformSecLib/PlatformSec.c")
s = p.read_text()
old = """VOID
PlatformInitialize ()
{
  // Disable WatchDog Timer
  DisableWatchDogTimer ();

  // Set MDP SIDs
  CONST UINT16 MdpStreams[] = { 0x800, 0x801, 0x840, 0x841, 0xC00, 0xC01, 0xC40, 0xC41 };

  // Detach IOMMU Domains
  ArmSmmuDetach (MdpStreams, ARRAY_SIZE (MdpStreams));
}"""
new = """VOID
EnableUfsCacheCoherency ()
{
  EFI_STATUS                   Status;
  EFI_MEMORY_REGION_DESCRIPTOR SmmuRegion;
  UINT32                       ContextBankAddr;

  // Locate "SMMU" Memory Region
  Status = LocateMemoryRegionByName ("SMMU", &SmmuRegion);
  if (EFI_ERROR (Status)) {
    return;
  }

  // Set UFS Context Bank Address
  ContextBankAddr = SmmuRegion.Address + SMMU_CTX_BANK_0_OFFSET + UFS_CTX_BANK * SMMU_CTX_BANK_SIZE;

  // Configure UFS Context Bank
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_SCTLR_OFFSET,   SMMU_CCA_SCTLR);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR0_0_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR0_1_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR1_0_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR1_1_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_MAIR0_OFFSET,   0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_MAIR1_OFFSET,   0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBCR_OFFSET,   0);
}

VOID
PlatformInitialize ()
{
  // Disable WatchDog Timer
  DisableWatchDogTimer ();

  // phoenix experiment 4: SEC as before d3f5d84c, no SMMU detach
  EnableUfsCacheCoherency ();
}"""
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new))
print("exp4 applied: SMMU detach removed, EnableUfsCacheCoherency restored")
