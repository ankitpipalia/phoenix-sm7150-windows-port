# SAFETY patch: disable the Xiaomi UFS firmware-update (FFU) routine in whichever
# UFSDxe phoenix's INF currently loads. Surya's UFSDxe (stock and stubbed) calls
# FFU at RVA 0x2fe4 (bl 0x25dc). On this phone's Samsung KM2V8001CM-B707 rev 1000 it
# matches its table and tries to "update" to rev 1500 with data read from a fixed
# address (0xC9400000). Replace the call with mov w0, #0 (the "no update" result).
import re, struct
from pathlib import Path
d = Path("Binaries/phoenix/QcomPkg/Drivers/UFSDxe")
inf = d / "UFSDxe.inf"; s = inf.read_text()
name = re.search(r"PE32\|([^|]+)\|\*", s).group(1)
src = (d / name).read_bytes()
off, bl, mov = 0x2fe4, 0x97FFFD7E, 0x52800000
assert struct.unpack_from("<I", src, off)[0] == bl, hex(struct.unpack_from("<I", src, off)[0])
assert src.count(struct.pack("<I", bl)) == 1
new = name.replace(".efi", ".noffu.efi")
(d / new).write_bytes(src[:off] + struct.pack("<I", mov) + src[off + 4:])
inf.write_text(s.replace(f"PE32|{name}|*", f"PE32|{new}|*"))
print(f"03 applied: {name} -> {new} (0x2fe4: bl FFU -> mov w0,#0)")
