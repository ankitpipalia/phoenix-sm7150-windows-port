# Walk a Silicium boot image the way the PI spec lays it out: gzip kernel slot ->
# firmware volume -> FFS files -> sections, expanding LZMA GUID-defined sections and
# nested FV images. Checks the FV header checksum and every FFS header and file
# checksum, and lists each file with its UI name and the SHA-256 of its PE32/TE body.
# A binary module's PE32 section is its .efi file unchanged, so the hash identifies
# exactly which prebuilt driver an image carries.
#
#   python3 fvwalk.py <img>              list files, report checksum errors
#   python3 fvwalk.py <img> <name>...    only files whose UI name contains <name>
import hashlib, lzma, struct, sys, uuid, zlib

LZMA_GUID = uuid.UUID("EE4E5898-3914-4259-9D6E-DC7BD79403CF")
SEC_NAMES = {0x01: "COMPRESSION", 0x02: "GUID_DEFINED", 0x10: "PE32", 0x11: "PIC", 0x12: "TE",
             0x13: "DXE_DEPEX", 0x14: "VERSION", 0x15: "UI", 0x17: "FV_IMAGE", 0x18: "FREEFORM",
             0x19: "RAW", 0x1B: "PEI_DEPEX", 0x1C: "MM_DEPEX"}

def volume(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'ANDROID!', path
    ks, ps = struct.unpack_from('<I', d, 8)[0], struct.unpack_from('<I', d, 36)[0]
    return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(d[ps:ps + ks])

def align(x, a): return (x + a - 1) & ~(a - 1)

class Walk:
    def __init__(self):
        self.files, self.errors, self.modules = [], [], []

    def fv(self, buf, off, where):
        if buf[off + 40:off + 44] != b'_FVH':
            self.errors.append(f"{where}: no _FVH at {off:#x}"); return
        fvlen = struct.unpack_from('<Q', buf, off + 32)[0]
        hlen, ext = struct.unpack_from('<H', buf, off + 48)[0], struct.unpack_from('<H', buf, off + 52)[0]
        if sum(struct.unpack_from('<%dH' % (hlen // 2), buf, off)) & 0xffff:
            self.errors.append(f"{where}: FV header checksum")
        p = off + hlen
        if ext:
            p = off + ext + struct.unpack_from('<I', buf, off + ext + 16)[0]
        end, p = off + fvlen, align(p, 8)
        while p + 24 <= end:
            hdr = buf[p:p + 24]
            if hdr == b'\xff' * 24: break
            name = str(uuid.UUID(bytes_le=hdr[:16])).upper()
            ftype, attr, state = hdr[18], hdr[19], hdr[23]
            size, hsz = int.from_bytes(hdr[20:23], 'little'), 24
            if attr & 0x01:  # FFS_ATTRIB_LARGE_FILE
                size, hsz = struct.unpack_from('<Q', buf, p + 24)[0], 32
            h = bytearray(buf[p:p + hsz]); h[17] = 0; h[23] = 0
            if sum(h) & 0xff:
                self.errors.append(f"{where}: FFS header checksum of {name}")
            data = buf[p + hsz:p + size]
            if attr & 0x40:
                if (sum(data) + hdr[17]) & 0xff: self.errors.append(f"{where}: FFS file checksum of {name}")
            elif hdr[17] != 0xAA:
                self.errors.append(f"{where}: FFS fixed checksum of {name} is {hdr[17]:#x}")
            if ftype != 0xF0:  # not a pad file
                f = {"guid": name, "type": ftype, "ui": None, "pe32": None, "te": None, "where": where}
                self.files.append(f)
                self.sections(data, f, f"{where}/{name[:8]}")
            p = align(p + size, 8)

    def sections(self, buf, f, where):
        p = 0
        while p + 4 <= len(buf):
            size, stype, hsz = int.from_bytes(buf[p:p + 3], 'little'), buf[p + 3], 4
            if size == 0xFFFFFF:
                size, hsz = struct.unpack_from('<I', buf, p + 4)[0], 8
            if size < hsz or p + size > len(buf):
                self.errors.append(f"{where}: bad section size {size:#x} at {p:#x}"); return
            body = buf[p + hsz:p + size]
            if stype == 0x02:
                guid = uuid.UUID(bytes_le=body[:16]); doff = struct.unpack_from('<H', body, 16)[0]
                inner = buf[p + doff:p + size]
                if guid == LZMA_GUID:
                    try:
                        out = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(inner)
                    except lzma.LZMAError as e:
                        self.errors.append(f"{where}: LZMA section: {e}"); out = b""
                    self.sections(out, f, where + "/lzma")
                else:
                    self.sections(inner, f, where + "/guid")
            elif stype == 0x17:
                self.fv(body, 0, where + "/fv")
            elif stype == 0x15:
                f["ui"] = body.decode('utf-16-le').rstrip('\0')
            elif stype in (0x10, 0x12):
                f["pe32" if stype == 0x10 else "te"] = hashlib.sha256(body).hexdigest()
                self.modules.append(body)
            p = align(p + size, 4)

def walk(path):
    raw = volume(path)
    w = Walk()
    off = raw.find(b'_FVH') - 40
    w.fv(raw, off, "fd")
    return w

if __name__ == "__main__":
    w = walk(sys.argv[1])
    names = sys.argv[2:]
    for f in w.files:
        if names and not any(n.lower() in (f["ui"] or "").lower() for n in names): continue
        h = f["pe32"] or f["te"]
        print(f"{f['ui'] or '-':34s} {f['guid']}  {'TE  ' if f['te'] else 'PE32' if f['pe32'] else '    '} {h or ''}")
    print(f"{len(w.files)} files, {len(w.errors)} checksum/structure errors")
    for e in w.errors: print("  ERROR", e)
