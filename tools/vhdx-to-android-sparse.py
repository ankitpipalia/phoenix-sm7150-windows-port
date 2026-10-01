#!/usr/bin/env python3
"""Extract one byte range of a dynamic VHDX (for example one partition) as an
Android sparse image that `fastboot flash` can write to a partition of the
same size.

Windows images for phoenix are built in a 4Kn VHDX on a Windows PC; macOS
has no VHDX reader that handles 4096-byte logical sectors (qemu-img does
not), so this reads the format directly (MS-VHDX v1: headers, region table,
metadata, BAT).

Blocks the VHDX has never allocated read as zeros. By default they become
DONT_CARE chunks, so fastboot leaves whatever the phone partition held there;
pass --zero-unallocated to write zeros instead (needed when the filesystem
does not describe every block, e.g. a FAT ESP should be written in full).

  vhdx-to-android-sparse.py DISK.vhdx --offset BYTES --size BYTES -o OUT.img
  vhdx-to-android-sparse.py DISK.vhdx --list
  vhdx-to-android-sparse.py --expand OUT.img        # sha256 of the expanded image,
                                                    # DONT_CARE counted as zeros
"""
import argparse
import hashlib
import struct
import sys
import uuid

KIB, MIB = 1024, 1024 * 1024
BAT_GUID = uuid.UUID('2DC27766-F623-4200-9D64-115E9BFD4A08')
METADATA_GUID = uuid.UUID('8B7CA206-4790-4B9A-B8FE-575F050F886E')
FILE_PARAMS = uuid.UUID('CAA16737-FA36-4D43-B3B6-33F0AA44E76B')
DISK_SIZE = uuid.UUID('2FA54224-CD1B-4876-B211-5DBED83BF4B8')
LOGICAL_SECTOR = uuid.UUID('8141BF1D-A96F-4709-BA47-F233A8FAAB5F')
PHYSICAL_SECTOR = uuid.UUID('CDA348C7-445D-4471-9CC9-E9885251C556')

# BAT payload block states (MS-VHDX 2.5.1.1)
NOT_PRESENT, UNDEFINED, ZERO, UNMAPPED, FULLY_PRESENT, PARTIALLY_PRESENT = 0, 1, 2, 3, 6, 7

SPARSE_MAGIC = 0xED26FF3A
RAW, FILL, DONT_CARE = 0xCAC1, 0xCAC2, 0xCAC3
BLK = 4096
MAX_RAW_BLOCKS = 4096  # 16 MiB per RAW chunk keeps memory bounded


def _crc32c_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        table.append(c)
    return table


_CRC_TABLE = _crc32c_table()


def crc32c(data):
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC_TABLE[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def checked(buf, what):
    """Verify a structure whose CRC-32C sits at offset 4 (computed with it zeroed)."""
    stored = struct.unpack_from('<I', buf, 4)[0]
    if crc32c(buf[:4] + b'\0\0\0\0' + buf[8:]) != stored:
        raise ValueError(f'{what}: bad checksum')
    return buf


class Vhdx:
    def __init__(self, path):
        self.f = open(path, 'rb')
        if self._read(0, 8) != b'vhdxfile':
            raise ValueError('not a VHDX file')
        headers = []
        for off in (64 * KIB, 128 * KIB):
            h = self._read(off, 4 * KIB)
            if h[:4] != b'head':
                continue
            try:
                checked(h, f'header at {off}')
            except ValueError:
                continue
            seq = struct.unpack_from('<Q', h, 8)[0]
            log_guid = uuid.UUID(bytes_le=h[48:64])
            headers.append((seq, log_guid))
        if not headers:
            raise ValueError('no valid VHDX header')
        _, log_guid = max(headers)
        if log_guid.int:
            raise ValueError('VHDX log is not empty: detach the disk cleanly in Windows first')
        rt = checked(self._read(192 * KIB, 64 * KIB), 'region table')
        if rt[:4] != b'regi':
            raise ValueError('bad region table')
        regions = {}
        for i in range(struct.unpack_from('<I', rt, 8)[0]):
            e = rt[16 + 32 * i:48 + 32 * i]
            regions[uuid.UUID(bytes_le=e[:16])] = struct.unpack_from('<QI', e, 16)
        md_off, md_len = regions[METADATA_GUID]
        md = self._read(md_off, md_len)
        if md[:8] != b'metadata':
            raise ValueError('bad metadata table')
        items = {}
        for i in range(struct.unpack_from('<H', md, 10)[0]):
            e = md[32 + 32 * i:64 + 32 * i]
            item_off, item_len = struct.unpack_from('<II', e, 16)
            items[uuid.UUID(bytes_le=e[:16])] = md[item_off:item_off + item_len]
        self.block_size, flags = struct.unpack('<II', items[FILE_PARAMS][:8])
        if flags & 2:
            raise ValueError('differencing VHDX (has a parent) is not supported')
        self.size = struct.unpack('<Q', items[DISK_SIZE][:8])[0]
        self.logical_sector = struct.unpack('<I', items[LOGICAL_SECTOR][:4])[0]
        self.physical_sector = struct.unpack('<I', items[PHYSICAL_SECTOR][:4])[0]
        self.chunk_ratio = (2 ** 23 * self.logical_sector) // self.block_size
        bat_off, bat_len = regions[BAT_GUID]
        self.bat = self._read(bat_off, bat_len)

    def _read(self, off, n):
        self.f.seek(off)
        b = self.f.read(n)
        if len(b) != n:
            raise ValueError(f'short read at {off}')
        return b

    def block(self, i):
        """(state, file offset) of payload block i."""
        e = struct.unpack_from('<Q', self.bat, 8 * (i + i // self.chunk_ratio))[0]
        return e & 7, (e >> 20) * MIB

    def read(self, off, n):
        """Bytes [off, off + n) of the virtual disk, or None where unallocated.
        The range must lie within one payload block."""
        i, within = divmod(off, self.block_size)
        assert within + n <= self.block_size
        state, foff = self.block(i)
        if state == FULLY_PRESENT:
            return self._read(foff + within, n)
        if state in (NOT_PRESENT, UNDEFINED, ZERO, UNMAPPED):
            return None
        raise ValueError(f'payload block {i}: unsupported state {state}')


def update_zeros(h, n):
    """Feed n zero bytes to hash h."""
    z = b'\0' * MIB
    while n >= MIB:
        h.update(z)
        n -= MIB
    h.update(b'\0' * n)


def runs(vhdx, offset, size, zero_unallocated):
    """Yield (chunk type, n blocks, data) runs covering [offset, offset + size)."""
    cur_type, cur_n, cur_data = None, 0, []
    pos, end = offset, offset + size
    while pos < end:
        n = min(end - pos, vhdx.block_size - pos % vhdx.block_size)
        data = vhdx.read(pos, n)
        if data is None:
            pieces = [(FILL if zero_unallocated else DONT_CARE, n // BLK, None)]
        else:
            pieces = []
            for j in range(0, n, BLK):
                b = data[j:j + BLK]
                pieces.append((FILL, 1, None) if b.count(0) == BLK else (RAW, 1, b))
        for t, k, b in pieces:
            if t != cur_type or (t == RAW and cur_n >= MAX_RAW_BLOCKS):
                if cur_type is not None:
                    yield cur_type, cur_n, cur_data
                cur_type, cur_n, cur_data = t, 0, []
            cur_n += k
            if b is not None:
                cur_data.append(b)
        pos += n
    if cur_type is not None:
        yield cur_type, cur_n, cur_data


def write_sparse(vhdx, offset, size, out, zero_unallocated):
    if offset % BLK or size % BLK:
        raise ValueError('offset and size must be multiples of 4096')
    if offset + size > vhdx.size:
        raise ValueError('range is beyond the end of the virtual disk')
    expanded = hashlib.sha256()
    chunks, counts = 0, {RAW: 0, FILL: 0, DONT_CARE: 0}
    with open(out, 'wb') as o:
        o.write(b'\0' * 28)
        for t, n, data in runs(vhdx, offset, size, zero_unallocated):
            if t == RAW:
                payload = b''.join(data)
                for b in data:
                    expanded.update(b)
            else:
                payload = b'\0\0\0\0' if t == FILL else b''
                update_zeros(expanded, n * BLK)
            o.write(struct.pack('<HHII', t, 0, n, 12 + len(payload)) + payload)
            chunks += 1
            counts[t] += n
        o.seek(0)
        o.write(struct.pack('<IHHHHIIII', SPARSE_MAGIC, 1, 0, 28, 12, BLK, size // BLK, chunks, 0))
    return expanded.hexdigest(), counts


def expand_hash(path):
    """sha256 of a sparse image's content, DONT_CARE taken as zeros."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        magic, major, _, fhs, chs, blk, total, nchunks, _ = struct.unpack('<IHHHHIIII', f.read(28))
        if magic != SPARSE_MAGIC or major != 1:
            raise ValueError('not an Android sparse image')
        f.seek(fhs)
        blocks = 0
        for _ in range(nchunks):
            t, _, n, tot = struct.unpack('<HHII', f.read(chs))
            body = f.read(tot - chs)
            if t == RAW:
                h.update(body)
            elif t == FILL and body[:4] != b'\0\0\0\0':
                for _ in range(n):
                    h.update(body[:4] * (blk // 4))
            elif t in (FILL, DONT_CARE):
                update_zeros(h, n * blk)
            blocks += n
        if blocks != total:
            raise ValueError(f'chunks cover {blocks} blocks, header says {total}')
    return h.hexdigest(), total * blk


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('vhdx', nargs='?')
    ap.add_argument('--offset', type=int)
    ap.add_argument('--size', type=int)
    ap.add_argument('-o', '--output')
    ap.add_argument('--zero-unallocated', action='store_true')
    ap.add_argument('--list', action='store_true', help='print geometry and allocation summary')
    ap.add_argument('--expand', metavar='SPARSE', help='print sha256 and size of a sparse image')
    a = ap.parse_args()
    if a.expand:
        digest, size = expand_hash(a.expand)
        print(f'{digest}  {size} bytes  {a.expand}')
        return
    if not a.vhdx:
        ap.error('VHDX path required')
    v = Vhdx(a.vhdx)
    if a.list:
        blocks = -(-v.size // v.block_size)
        present = sum(1 for i in range(blocks) if v.block(i)[0] == FULLY_PRESENT)
        print(f'virtual size {v.size}, logical sector {v.logical_sector}, physical sector '
              f'{v.physical_sector}, block {v.block_size}, chunk ratio {v.chunk_ratio}, '
              f'{present}/{blocks} blocks present')
        return
    if None in (a.offset, a.size, a.output):
        ap.error('--offset, --size and -o are required')
    digest, counts = write_sparse(v, a.offset, a.size, a.output, a.zero_unallocated)
    print(f'{a.output}: {a.size} bytes, raw {counts[RAW]} / fill {counts[FILL]} / '
          f"don't-care {counts[DONT_CARE]} blocks; expanded sha256 {digest}")


if __name__ == '__main__':
    sys.exit(main())
