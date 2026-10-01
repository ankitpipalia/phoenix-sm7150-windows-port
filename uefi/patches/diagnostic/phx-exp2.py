# Experiment 2 for the phoenix UEFI hang: restore the SoC step that made UFS DMA
# coherent (MooreaPkg PrePi code from f154b949, deleted in a72d7eb4).
from pathlib import Path
p = Path("Silicon/Qualcomm/MooreaPkg/Library/PlatformSecLib/PlatformSec.c")
s = p.read_text()
old = """VOID
PlatformInitialize ()
{
  // Disable WatchDog Timer
  DisableWatchDogTimer ();
"""
new = """//
// Restored from f154b949 (deleted in a72d7eb4) for the phoenix UFS experiment.
//
#define PHX_SMMU_BASE 0x15000000

VOID
ConfigureIOMMUContextBankCacheSetting (UINT32 ContextBankId)
{
  UINT32 ContextBankAddr = PHX_SMMU_BASE + SMMU_CTX_BANK_0_OFFSET + ContextBankId * SMMU_CTX_BANK_SIZE;

  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_SCTLR_OFFSET, SMMU_CCA_SCTLR);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR0_0_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR0_1_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR1_0_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBR1_1_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_MAIR0_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_MAIR1_OFFSET, 0);
  MmioWrite32 (ContextBankAddr + SMMU_CTX_BANK_TTBCR_OFFSET, 0);
}

VOID
PlatformInitialize ()
{
  // Configure Cache Coherency for the UFS Context Bank (restored)
  ConfigureIOMMUContextBankCacheSetting (UFS_CTX_BANK);

  // Disable WatchDog Timer
  DisableWatchDogTimer ();
"""
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new))
print("exp2 applied: UFS context bank coherency restored")
