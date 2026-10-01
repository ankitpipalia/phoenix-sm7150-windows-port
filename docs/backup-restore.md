# Back up the device, and restore Linux

Replacing the device's storage layout with Windows is destructive. The
postmarketOS install lives entirely inside the `userdata` partition (a whole
GPT disk image flashed into it; Linux maps it with a loop device). Windows
replaces `userdata` with an `esp` and a `win` partition. Everything else — the
other LUN0 partitions, and every other LUN (firmware, calibration,
bootloaders) — is left untouched.

**Do a verified backup before any destructive step, and keep it private**: the
LUN images contain the IMEI, calibration and keys.

## Full backup

`device/backup-phone.sh OUT_DIR` runs from the host against the device's
postmarketOS over USB SSH and writes:

| file | content |
| --- | --- |
| `gpt-sfdisk.txt`, `gpt-sdX-{head,tail}.bin` | every LUN's partition table (text + raw primary/backup GPT sectors) |
| `lun-sdb..sdf.img.zst` | LUN1–LUN5 whole: XBL, CDT/DDR, LUN4 firmware (incl. `abl`, `boot`, `modem`), LUN5 calibration (`persist`, `modemst`, `fsg`) |
| `lun-sda-before-userdata.img.zst` | LUN0 from LBA 0 up to `userdata` (incl. `super`) |
| `userdata.img.zst` | the whole `userdata` partition, taken consistently |
| `SHA256-phone.txt` / `VERIFY.txt` | phone-side hashes, and the host-side comparison |

It re-reads each region on the device and compares SHA-256 against the local
copy, and checks `userdata.img.zst` decompresses to exactly the partition size.

### Consistent `userdata`

`device/freeze-userdata.sh` (invoked by the backup) images `userdata` while the
root filesystem is frozen, so the ext4 inside is consistent. Two traps it
avoids: `e2image`'s mount-check file would block on the frozen root (so the
root is read through a second, read-only loop device), and the page cache (head
and tail are read with `O_DIRECT`). Unused ext4 blocks come out as zeros, so a
107 GiB `userdata` with ~9 GB used compresses to a few GB. A 30-minute sleeper
and an `EXIT` trap both thaw the filesystem no matter how the stream ends.

### Deep verification (recommended)

After the backup, mount the image's partitions by offset in an aarch64
container and compare a handful of files (kernel, initramfs, `/etc/fstab`)
against the live device, and run `e2fsck -fn` on the root:

```sh
zstd -d --sparse userdata.img.zst -o userdata.img
docker run --rm --privileged --platform linux/arm64 -v "$PWD":/v alpine:edge sh -c '
  apk add --no-cache util-linux e2fsprogs >/dev/null
  # offsets from the nested GPT (sfdisk -d /dev/loop0 on the device): ESP at 2048,
  # root at 124928, 4096-byte sectors
  R=$(losetup -r -o $((124928*4096)) --sizelimit <root-bytes> -f --show /v/userdata.img)
  e2fsck -fn "$R"; losetup -d "$R"'
```

### Capacity note

A raw `userdata` backup is ~107 GiB; the compressed consistent image is a few
GB. Make sure the host has room for the compressed image plus the LUN dumps
(tens of GB total), not for a raw copy.

## Capture live hardware state

`device/capture-hw-state.sh` (run on the device under Linux) tars the live
device tree, pinctrl/GPIO/regulator/clock state, interrupts, bound drivers,
and the boot log. This is the ground truth the ACPI audit
([acpi-audit.md](acpi-audit.md)) compares surya's borrowed tables against, and
it is irreplaceable once Linux is gone — capture it **before** repartitioning.

## Restore Linux

From fastboot, or the rescue shell ([rescue-shell.md](rescue-shell.md)):

1. **Partition table.** Write the saved original LUN0 GPT back. If you kept the
   `device/make-lun0-windows-gpt.sh` output, the originals are
   `lun0-orig-head.bin` / `lun0-orig-tail.bin`; apply them with
   `device/apply-lun0-gpt.sh /dev/sda <new-head> <new-tail> <orig-head> <orig-tail>`
   (the write guard refuses unless the disk currently holds the "new" table, so
   pass the current/new pair first and the originals second). This brings back
   the 32-entry table with `userdata`.
2. **userdata.** Decompress `userdata.img.zst` back onto `userdata`. From the
   rescue shell, stream it with `zstd -dc … | nc` into `dd`; or convert it to a
   sparse image and `fastboot flash userdata`.
3. **boot.** If you replaced U-Boot in `boot` with the UEFI, flash the saved
   davinci U-Boot image back: `fastboot flash boot u-boot-…-davinci-samsung.img`.
   That image is the exact rollback — confirm its SHA-256 matches the first
   630,784 bytes of your `boot` backup.

Then boot normally: ABL → U-Boot → systemd-boot → postmarketOS.
