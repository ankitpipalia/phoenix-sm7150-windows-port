#!/usr/bin/env python3
"""Boot gate for any phoenix UEFI image in which UFS works.

Surya's UFSDxe (the driver that makes UFS work on phoenix) contains a Xiaomi
UFS *firmware update* routine, called at RVA 0x2fe4. Its table matches this
phone's Samsung KM2V8001CM-B707 (rev 1000) and it would send data read from a
fixed, unmapped address (0xC9400000) to the chip as new firmware. In a test
image that disabled nothing it faulted before writing, by luck.
uefi/patches/phx-noffu.py replaces the call with `mov w0, #0` ("no update").

This extracts the UFSDxe module from an image and requires its SHA-256 to be
exactly one of the known FFU-disabled builds, i.e. the call is gone and no
other byte differs from the pinned Binaries driver. Exit 1 on any failure.
"Never boot an image whose UFS works unless this passes."

    python3 tools/ffucheck.py IMAGE.img [...]
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fvwalk import Walk, volume  # noqa: E402

FFU_CALL, NO_UPDATE, RVA = 0x97FFFD7E, 0x52800000, 0x2FE4
# Mu-Silicium Binaries 203fb36b, surya/QcomPkg/Drivers/UFSDxe:
#   UFSDxe.efi          sha256 276256e4..., git blob c983d972...
#   UFSDxe.patched.efi  sha256 84d07d59..., git blob 0ab0b883...  (IOMMU setup stubbed)
SAFE = {
    '9990ab53b5c71033d2b2dd1fb0d41600491cd38eddd4c0721bf60499d9ef82c3': 'surya stock UFSDxe, FFU call disabled',
    '403a228aec596460d6debc3a14ae397dcc4061476e27caaffc8e1592aa109dd5': 'surya stubbed UFSDxe, FFU call disabled',
}
UNSAFE = {
    '276256e47eaf697932b9c05aeb6390230cbbd4aca68cb09c3b259171dd50614b': 'surya stock UFSDxe WITH the FFU call',
    '84d07d59353713fe04eef57aba4139e4bbdee0e250dc3c08d8642d6b0ac6b2d3': 'surya stubbed UFSDxe WITH the FFU call',
}


def ufsdxe_bodies(path):
    """PE32 bodies of every module named UFSDxe in the image, and walk errors."""
    raw = volume(path)
    w = Walk()
    orig = w.sections

    def sections(buf, f, where):
        p = 0
        while p + 4 <= len(buf):
            size, t = int.from_bytes(buf[p:p + 3], 'little'), buf[p + 3]
            if size < 4 or p + size > len(buf):
                break
            if t == 0x10:
                f.setdefault('_body', buf[p + 4:p + size])
            p = (p + size + 3) & ~3
        return orig(buf, f, where)

    w.sections = sections
    w.fv(raw, raw.find(b'_FVH') - 40, 'fd')
    return [f['_body'] for f in w.files if f['ui'] == 'UFSDxe' and '_body' in f], w.errors


def main(paths):
    ok = True
    for img in paths:
        bodies, errors = ufsdxe_bodies(img)
        name = os.path.basename(img)
        if errors or len(bodies) != 1:
            print(f'{name}: FAIL ({len(bodies)} UFSDxe modules, {len(errors)} structure errors)')
            ok = False
            continue
        body = bodies[0]
        digest = hashlib.sha256(body).hexdigest()
        insn = struct.unpack_from('<I', body, RVA)[0] if len(body) > RVA + 4 else None
        calls = body.count(struct.pack('<I', FFU_CALL))
        good = digest in SAFE and insn == NO_UPDATE and calls == 0
        what = SAFE.get(digest) or UNSAFE.get(digest) or 'unknown UFSDxe build'
        print(f'{name}: UFSDxe {digest[:16]} ({what}); 0x{RVA:x} = {insn:#010x}; '
              f'FFU calls {calls}: {"PASS" if good else "FAIL"}')
        ok &= good
    return 0 if ok else 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
