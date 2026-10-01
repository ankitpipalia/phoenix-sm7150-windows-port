#!/usr/bin/env python3
"""Build and take apart the Android boot images that phoenix's stock Xiaomi ABL
boots, without mkbootimg or a device-tree compiler.

Subcommands:

  extract-dtb BOOT.img -o OUT.dtb
      The first device tree appended after the gzip kernel of a boot image,
      e.g. the davinci DTB inside the sm7150-mainline U-Boot image.

  dt-ids DTB
      Print qcom,msm-id and qcom,board-id (what ABL selects a DTB by).

  copy-ids TARGET.dtb DONOR.dtb -o OUT.dtb
      Copy qcom,msm-id and qcom,board-id from DONOR into TARGET (values must be
      the same length; they are replaced in place, nothing else changes).

  uefi MU.img DTB -o OUT.img
      Repack a Mu-Silicium phoenix image for ABL: keep only the gzip stream of
      its kernel slot, append DTB, header v1, page 2048, base 0x10000000
      (kernel +0x8000, ramdisk +0x01000000, tags +0x100), the image's own
      ramdisk. The stock Silicium image appends a 16-DTB bundle with which ABL
      answers "Booting OKAY" but never hands off; with the davinci DTB
      (msm-id 0x16d, board-id 0x28) it hands off every time.

  linux KERNEL RAMDISK DTB -o OUT.img [--cmdline STR]
      A Linux image in the layout of the U-Boot image ABL already boots:
      header v0, page 4096, kernel 0x8000, ramdisk 0x1000000, second
      0xf00000, tags 0x100. KERNEL is a raw arm64 Image, gzip'd Image, or an
      EFI zboot vmlinuz (unwrapped automatically); it is gzip'd and DTB is
      appended.

  info BOOT.img
      Header fields and what the kernel slot contains.
"""
import argparse
import gzip
import hashlib
import struct
import subprocess
import sys
import zlib

FDT_MAGIC = b'\xd0\x0d\xfe\xed'
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def header(d):
    if d[:8] != b'ANDROID!':
        raise SystemExit('not an Android boot image')
    ks, ka, rs, ra, ss, sa, ta, ps, hv, osv = struct.unpack_from('<10I', d, 8)
    return dict(ks=ks, ka=ka, rs=rs, ra=ra, ss=ss, sa=sa, ta=ta, ps=ps, hv=hv, osv=osv,
                cmdline=d[64:576].rstrip(b'\0'))


def pages(n, ps):
    return (n + ps - 1) // ps * ps


def kernel_slot(d):
    h = header(d)
    return d[h['ps']:h['ps'] + h['ks']]


def ramdisk_slot(d):
    h = header(d)
    off = h['ps'] + pages(h['ks'], h['ps'])
    return d[off:off + h['rs']]


def split_gzip(slot):
    """(gzip stream, data appended after it)."""
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    z.decompress(slot)
    if not z.eof:
        raise SystemExit('kernel slot is not a complete gzip stream')
    return slot[:len(slot) - len(z.unused_data)], z.unused_data


def first_dtb(blob):
    i = blob.find(FDT_MAGIC)
    if i < 0:
        raise SystemExit('no device tree found')
    size = struct.unpack_from('>I', blob, i + 4)[0]
    return blob[i:i + size]


def root_props(dtb):
    """{name: (value offset, value length)} for properties of the root node."""
    if dtb[:4] != FDT_MAGIC:
        raise SystemExit('not a flattened device tree')
    off_struct, off_strings = struct.unpack_from('>II', dtb, 8)
    p, depth, props = off_struct, 0, {}
    while True:
        tok = struct.unpack_from('>I', dtb, p)[0]
        p += 4
        if tok == FDT_BEGIN_NODE:
            end = dtb.index(b'\0', p)
            p = (end + 4) & ~3
            depth += 1
        elif tok == FDT_END_NODE:
            depth -= 1
            if depth == 0:
                return props
        elif tok == FDT_PROP:
            length, nameoff = struct.unpack_from('>II', dtb, p)
            p += 8
            s = off_strings + nameoff
            name = dtb[s:dtb.index(b'\0', s)].decode()
            if depth == 1:
                props[name] = (p, length)
            p = (p + length + 3) & ~3
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            return props
        else:
            raise SystemExit(f'bad FDT token {tok}')


def dt_ids(dtb):
    props = root_props(dtb)
    out = {}
    for name in ('qcom,msm-id', 'qcom,board-id'):
        if name in props:
            off, n = props[name]
            out[name] = struct.unpack_from('>%dI' % (n // 4), dtb, off)
    return out


def copy_ids(target, donor):
    t, d = bytearray(target), donor
    tp, dp = root_props(target), root_props(donor)
    for name in ('qcom,msm-id', 'qcom,board-id'):
        if name not in tp or name not in dp:
            raise SystemExit(f'{name} missing')
        (to, tn), (do, dn) = tp[name], dp[name]
        if tn != dn:
            raise SystemExit(f'{name}: lengths differ ({tn} vs {dn}); edit with dtc instead')
        t[to:to + tn] = d[do:do + dn]
    return bytes(t)


def unwrap_kernel(k):
    """A raw arm64 Image from an Image, Image.gz or EFI zboot vmlinuz."""
    if k[:2] == b'\x1f\x8b':
        k = gzip.decompress(k)
    if k[:2] == b'MZ' and k[4:8] == b'zimg':
        off, size = struct.unpack_from('<II', k, 8)
        comp = k[24:32].rstrip(b'\0')
        payload = k[off:off + size]
        if comp == b'gzip':
            k = gzip.decompress(payload)
        elif comp == b'zstd':
            k = subprocess.run(['zstd', '-dc'], input=payload, capture_output=True, check=True).stdout
        else:
            raise SystemExit(f'unsupported zboot compression {comp!r}')
    if k[0x38:0x3c] != b'ARMd':
        raise SystemExit('kernel is not an arm64 Image')
    return k


def boot_id(*blobs):
    sha = hashlib.sha1()
    for b in blobs:
        sha.update(b)
        sha.update(struct.pack('<I', len(b)))
    return sha.digest()


def pack(version, page, kernel, ramdisk, addrs, cmdline=b''):
    ka, ra, sa, ta = addrs
    if len(cmdline) >= 512:
        raise SystemExit('cmdline too long')
    blobs = (kernel, ramdisk, b'') + ((b'',) if version >= 1 else ())
    hdr = struct.pack('<8s10I16s512s32s1024s', b'ANDROID!', len(kernel), ka, len(ramdisk), ra,
                      0, sa, ta, page, version, 0, b'', cmdline, boot_id(*blobs), b'')
    if version == 1:
        hdr += struct.pack('<IQI', 0, 0, 1648)
    elif version != 0:
        raise SystemExit('only header v0 and v1 are supported')
    pad = lambda b: b + b'\0' * (-len(b) % page)
    return pad(hdr) + pad(kernel) + pad(ramdisk)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('extract-dtb'); s.add_argument('boot'); s.add_argument('-o', required=True)
    s = sub.add_parser('dt-ids'); s.add_argument('dtb')
    s = sub.add_parser('copy-ids'); s.add_argument('target'); s.add_argument('donor'); s.add_argument('-o', required=True)
    s = sub.add_parser('uefi'); s.add_argument('mu'); s.add_argument('dtb'); s.add_argument('-o', required=True)
    s = sub.add_parser('linux'); s.add_argument('kernel'); s.add_argument('ramdisk'); s.add_argument('dtb')
    s.add_argument('-o', required=True); s.add_argument('--cmdline', default='')
    s = sub.add_parser('info'); s.add_argument('boot')
    a = ap.parse_args()

    if a.cmd == 'extract-dtb':
        _, rest = split_gzip(kernel_slot(read(a.boot)))
        dtb = first_dtb(rest)
        open(a.o, 'wb').write(dtb)
        print(f'{a.o}: {len(dtb)} bytes, {dt_ids(dtb)}')
    elif a.cmd == 'dt-ids':
        for k, v in dt_ids(read(a.dtb)).items():
            print(k, ' '.join(f'{x:#x}' for x in v))
    elif a.cmd == 'copy-ids':
        out = copy_ids(read(a.target), read(a.donor))
        open(a.o, 'wb').write(out)
        print(f'{a.o}: {dt_ids(out)}')
    elif a.cmd == 'uefi':
        mu = read(a.mu)
        gz, _ = split_gzip(kernel_slot(mu))
        dtb = read(a.dtb)
        if dtb[:4] != FDT_MAGIC:
            raise SystemExit('DTB is not a flattened device tree')
        img = pack(1, 2048, gz + dtb, ramdisk_slot(mu), (0x10008000, 0x11000000, 0, 0x10000100))
        open(a.o, 'wb').write(img)
        print(f'{a.o}: {len(img)} bytes, sha256 {hashlib.sha256(img).hexdigest()}')
    elif a.cmd == 'linux':
        image = unwrap_kernel(read(a.kernel))
        dtb = read(a.dtb)
        gz = bytearray(gzip.compress(image, compresslevel=9, mtime=0))
        gz[9] = 3  # OS = Unix, as gzip(1) writes it, so builds match `gzip -9 -n` byte for byte
        kernel = bytes(gz) + dtb
        img = pack(0, 4096, kernel, read(a.ramdisk), (0x8000, 0x1000000, 0xf00000, 0x100), a.cmdline.encode())
        open(a.o, 'wb').write(img)
        print(f'{a.o}: {len(img)} bytes, sha256 {hashlib.sha256(img).hexdigest()}')
    elif a.cmd == 'info':
        d = read(a.boot)
        h = header(d)
        print({k: (hex(v) if isinstance(v, int) else v) for k, v in h.items()})
        gz, rest = split_gzip(kernel_slot(d))
        print(f'kernel slot: gzip {len(gz)} bytes, then {len(rest)} bytes '
              f"({'device tree ' + str(dt_ids(first_dtb(rest))) if FDT_MAGIC in rest[:16] else 'no DTB'})")


if __name__ == '__main__':
    sys.exit(main())
