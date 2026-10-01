# Completes surya's 2026-06-29 design on top of 01-ufs-surya-stock-dalsys-cca.py: load phoenix's own
# unpatched HALIOMMUDxe.efi instead of HALIOMMUDxe.patched.efi (whose patch skips
# the SDC1/SDC2/SDC4/USB3-0 domain attaches that the SEC SMMU detach now requires).
import hashlib
from pathlib import Path
def blob(d): return hashlib.sha1(b"blob %d\0" % len(d) + d).hexdigest()
d = Path("Binaries/phoenix/QcomPkg/Drivers/HALIOMMUDxe")
assert blob((d / "HALIOMMUDxe.efi").read_bytes()) == "9f01e170e40a5f3523379d0b5ab321c77e115c45"
inf = d / "HALIOMMUDxe.inf"; s = inf.read_text()
assert s.count("PE32|HALIOMMUDxe.patched.efi|*") == 1
inf.write_text(s.replace("PE32|HALIOMMUDxe.patched.efi|*", "PE32|HALIOMMUDxe.efi|*"))
print("02 applied: phoenix stock HALIOMMUDxe.efi")
