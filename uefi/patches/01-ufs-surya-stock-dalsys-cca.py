# Surya's June 2026 UFS/SMMU design for phoenix (the fix for the UFSDxe freeze). Phoenix's own
# DALSys with the \_SB_.UFS0 IORT CCA byte set, plus surya's stock (unstubbed) UFSDxe.
import hashlib
from pathlib import Path
B = Path("Binaries")
def blob(d): return hashlib.sha1(b"blob %d\0" % len(d) + d).hexdigest()
dal = B / "phoenix/QcomPkg/Drivers/DALSYSDxe"
src = (dal / "DALSYSDxe.efi").read_bytes()
off = 0x27adf
assert blob(src) == "0af15319628f4b9a9f1773503a4cc30215305cb3", blob(src)
assert src[off] == 0 and src[off + 9:off + 19] == b"\\_SB_.UFS0", (src[off], src[off + 9:off + 19])
(dal / "DALSYSDxe.phxcca.efi").write_bytes(src[:off] + b"\x01" + src[off + 1:])
inf = dal / "DALSYSDxe.inf"; s = inf.read_text()
assert s.count("PE32|DALSYSDxe.efi|*") == 1
inf.write_text(s.replace("PE32|DALSYSDxe.efi|*", "PE32|DALSYSDxe.phxcca.efi|*"))
ufs = B / "phoenix/QcomPkg/Drivers/UFSDxe"
stock = (B / "surya/QcomPkg/Drivers/UFSDxe/UFSDxe.efi").read_bytes()
assert blob(stock) == "c983d9729b780fc10fee5ebbe9ff3a874cc30a18", blob(stock)
(ufs / "UFSDxe.surya-stock.efi").write_bytes(stock)
inf = ufs / "UFSDxe.inf"; s = inf.read_text()
assert s.count("PE32|UFSDxe.patched.efi|*") == 1
inf.write_text(s.replace("PE32|UFSDxe.patched.efi|*", "PE32|UFSDxe.surya-stock.efi|*"))
print("01 applied: DALSys UFS0 CCA=1 (0x27adf), surya stock UFSDxe")
