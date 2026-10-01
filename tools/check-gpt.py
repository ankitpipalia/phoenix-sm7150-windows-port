#!/usr/bin/env python3
"""Independent check of a new GPT against the current one, from the raw sectors
(primary = LBA 0-5, backup = last 5 LBAs, as device/make-lun0-windows-gpt.sh
writes them). Does not trust the tool that made them.

  check-gpt.py CUR_HEAD CUR_TAIL NEW_HEAD NEW_TAIL --lbas N [--keep K] [--sector 4096]

Checks, for both tables: header signature and CRC, entry-array CRC, primary
and backup headers pointing at each other, primary and backup entry arrays
identical. Then compares new against current: disk GUID, usable range and
entry size unchanged; entries 1..K byte-identical (--keep); protective MBR
identical; prints every entry that changed. Exit 1 on any failed check.
"""
import argparse
import struct
import sys
import uuid
import zlib


def load(path, n, sector):
    b = open(path, 'rb').read()
    if len(b) != n * sector:
        sys.exit(f'{path}: {len(b)} bytes, expected {n} sectors of {sector}')
    return b


def header(blk, what):
    (sig, rev, hsize, crc, _, my, alt, first, last, guid, entlba, nent, entsize, entcrc) = \
        struct.unpack_from('<8sIIIIQQQQ16sQIII', blk, 0)
    if sig != b'EFI PART':
        sys.exit(f'{what}: no GPT signature')
    hb = bytearray(blk[:hsize])
    hb[16:20] = b'\0' * 4
    ok = zlib.crc32(bytes(hb)) == crc
    return dict(ok=ok, rev=rev, my=my, alt=alt, first=first, last=last, guid=uuid.UUID(bytes_le=guid),
                entlba=entlba, nent=nent, entsize=entsize, entcrc=entcrc)


def entries(head, tail, h, lbas, sector, from_tail):
    n = h['nent'] * h['entsize']
    if from_tail:
        off = (h['entlba'] - (lbas - 5)) * sector
        raw = tail[off:off + n]
    else:
        off = h['entlba'] * sector
        raw = head[off:off + n]
    return raw, zlib.crc32(raw) == h['entcrc']


def describe(e):
    t, u, first, last, attrs = struct.unpack_from('<16s16sQQQ', e)
    name = e[56:128].decode('utf-16-le').rstrip('\0')
    if t == b'\0' * 16:
        return 'empty'
    return f'{name!r} LBA {first}-{last} type {uuid.UUID(bytes_le=t)} guid {uuid.UUID(bytes_le=u)} attrs {attrs:#x}'


def table(head, tail, lbas, sector, what, problems):
    p = header(head[sector:2 * sector], f'{what} primary')
    b = header(tail[4 * sector:], f'{what} backup')
    pe, pe_ok = entries(head, tail, p, lbas, sector, False)
    be, be_ok = entries(head, tail, b, lbas, sector, True)
    for ok, msg in ((p['ok'], 'primary header CRC'), (b['ok'], 'backup header CRC'),
                    (pe_ok, 'primary entries CRC'), (be_ok, 'backup entries CRC'),
                    ((p['my'], p['alt'], b['my'], b['alt']) == (1, lbas - 1, lbas - 1, 1), 'header locations'),
                    (pe == be, 'primary and backup entries identical')):
        print(f'  {"ok  " if ok else "FAIL"} {what}: {msg}')
        if not ok:
            problems.append(f'{what}: {msg}')
    size = p['entsize']
    return p, [pe[i:i + size] for i in range(0, len(pe), size)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cur_head'); ap.add_argument('cur_tail'); ap.add_argument('new_head'); ap.add_argument('new_tail')
    ap.add_argument('--lbas', type=int, required=True, help='disk size in sectors')
    ap.add_argument('--keep', type=int, default=0, help='entries 1..K must be byte-identical')
    ap.add_argument('--sector', type=int, default=4096)
    a = ap.parse_args()
    s = a.sector
    ch, ct = load(a.cur_head, 6, s), load(a.cur_tail, 5, s)
    nh, nt = load(a.new_head, 6, s), load(a.new_tail, 5, s)
    problems = []
    cp, ce = table(ch, ct, a.lbas, s, 'current', problems)
    np_, ne = table(nh, nt, a.lbas, s, 'new', problems)
    for k in ('guid', 'first', 'last', 'entsize', 'rev'):
        if cp[k] != np_[k]:
            problems.append(f'{k} changed: {cp[k]} -> {np_[k]}')
    print(f'  disk {np_["guid"]}, usable LBA {np_["first"]}-{np_["last"]}, entries {cp["nent"]} -> {np_["nent"]}')
    print(f'  protective MBR {"identical" if ch[:s] == nh[:s] else "CHANGED"}')
    if ch[:s] != nh[:s]:
        problems.append('protective MBR changed')
    if ne[:a.keep] != ce[:a.keep]:
        problems.append(f'entries 1..{a.keep} are not byte-identical')
    for i in range(max(len(ce), len(ne))):
        old = ce[i] if i < len(ce) else b'\0' * 128
        new = ne[i] if i < len(ne) else b'\0' * 128
        if old != new:
            print(f'  entry {i + 1}:\n    was {describe(old)}\n    now {describe(new)}')
    used = [(e, describe(e)) for e in ne if e[:16] != b'\0' * 16]
    spans = sorted(struct.unpack_from('<QQ', e, 32) for e, _ in used)
    for (f1, l1), (f2, l2) in zip(spans, spans[1:]):
        if f2 <= l1:
            problems.append(f'overlap: {f1}-{l1} and {f2}-{l2}')
    if any(f < np_['first'] or l > np_['last'] for f, l in spans):
        problems.append('an entry lies outside the usable range')
    if problems:
        print('FAIL:\n  ' + '\n  '.join(problems))
        return 1
    print(f'OK: both tables valid, {len(used)} entries, no overlaps' + (f', entries 1..{a.keep} unchanged' if a.keep else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
