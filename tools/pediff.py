# Byte-level diff of two PE/COFF binaries (e.g. a patched .efi against its stock
# version), reported as runs with section name and RVA.
#   python3 pediff.py OLD.efi NEW.efi [OLD2.efi NEW2.efi ...]
import os, struct, sys
def sections(b):
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    n = struct.unpack_from('<H', b, pe+6)[0]; opt = struct.unpack_from('<H', b, pe+20)[0]
    base = pe + 24 + opt; out = []
    for i in range(n):
        name, vsz, va, rsz, raw = struct.unpack_from('<8sIIII', b, base + 40*i)
        out.append((name.rstrip(b'\0').decode(), va, vsz, raw, rsz))
    return out
def where(secs, off):
    for name, va, vsz, raw, rsz in secs:
        if raw <= off < raw + rsz: return f"{name}+{off-raw:#x} (rva {va+off-raw:#x})"
    return "header"
def runs(a, b):
    d = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    r = []
    for i in d:
        if r and i - r[-1][1] <= 4: r[-1][1] = i
        else: r.append([i, i])
    return d, r
if __name__ == '__main__':
  for x, y in [(sys.argv[i], sys.argv[i+1]) for i in range(1, len(sys.argv), 2)]:
      a, b = open(x,'rb').read(), open(y,'rb').read()
      d, r = runs(a, b)
      print(f"== {os.path.basename(x)} vs {os.path.basename(y)}: sizes {len(a)}/{len(b)}, {len(d)} bytes differ in {len(r)} runs")
      secs = sections(b)
      for s, e in r[:12]:
          print(f"   {s:#08x}-{e:#08x} ({e-s+1:3d} B) {where(secs, s):28s} old {a[s:e+1].hex()[:48]}  new {b[s:e+1].hex()[:48]}")
      if len(r) > 12: print(f"   ... {len(r)-12} more runs")
