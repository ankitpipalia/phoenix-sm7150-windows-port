# Optional: always open Silicium's Boot Manager menu instead of auto-booting.
# The Volume Up hotkey only sets mEnterBootManager = TRUE; on phoenix the key
# notification did not fire (run 5), so start with the flag already set.
from pathlib import Path
p = Path("Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/KeyCallback.c")
s = p.read_text()
old = "STATIC BOOLEAN                            mEnterBootManager    = FALSE;"
assert s.count(old) == 1
p.write_text(s.replace(old, "STATIC BOOLEAN                            mEnterBootManager    = TRUE;  // phoenix: force boot menu"))
print("forcemenu applied: mEnterBootManager = TRUE")
