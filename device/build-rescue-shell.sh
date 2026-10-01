#!/bin/bash
# Build a RAM-bootable postmarketOS rescue image for phoenix, with the NTFS3
# kernel module bundled so it can read the Windows partition offline. Boots via
# `fastboot boot` only; writes nothing.
#
# The debug shell comes up on 172.16.42.1 over USB (telnet, port 23), with
# busybox dd/nc/sha256sum, losetup, parted and e2fsck. With the bundled
# ntfs3.ko plus the userspace ntfs tools (tools/, fetched separately), it reads
# the Windows logs, crash dumps and driver state directly from the UFS — an
# autonomous debug loop that does not need Windows networking.
#
#   device/build-rescue-shell.sh KERNEL_APK UBOOT_IMG [OUT.img]
#
# KERNEL_APK  linux-postmarketos-qcom-sm7150 .apk (same version running on the
#             phone; provides /boot/vmlinuz, the initramfs modules and ntfs3.ko)
# UBOOT_IMG   davinci U-Boot image, for the ABL-select DTB (see uefi/build.sh)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
apk=${1:?usage: $0 KERNEL_APK UBOOT_IMG [OUT.img]}
uboot=${2:?}
out=${3:-$repo/out/phoenix-rescue-shell.img}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$(dirname "$out")"

tar -xzf "$apk" -C "$work" 2>/dev/null
kver=$(cd "$work"/usr/lib/modules 2>/dev/null && ls | head -1 || cd "$work"/lib/modules && ls | head -1)
vmlinuz=$(find "$work" -path '*/boot/vmlinuz' | head -1)
initramfs=$(find "$work" -path '*/boot/initramfs' | head -1)
ntfs3=$(find "$work" -name 'ntfs3.ko*' | head -1)
[ -n "$vmlinuz" ] && [ -n "$initramfs" ] && [ -n "$ntfs3" ] || { echo "apk missing vmlinuz/initramfs/ntfs3" >&2; exit 1; }
echo "kernel $kver; vmlinuz $vmlinuz; ntfs3 $ntfs3"

# Unpack the initramfs, add ntfs3.ko (decompress .zst so busybox insmod loads it), repack.
mkdir -p "$work/initfs"
( cd "$work/initfs" && gzip -dc "$initramfs" | cpio -idm --quiet )
if [ "${ntfs3##*.}" = zst ]; then zstd -dq "$ntfs3" -o "$work/initfs/lib/modules/ntfs3.ko"; else cp "$ntfs3" "$work/initfs/lib/modules/ntfs3.ko"; fi
( cd "$work/initfs" && find . | cpio --quiet -o -H newc -R 0:0 | gzip -9 -n > "$work/initramfs-ntfs3.gz" )

# ABL-select DTB: phoenix DTB with davinci's msm-id/board-id (the only ids this
# ABL accepts). Take the phoenix DTB from the kernel apk's /boot.
phxdtb=$(find "$work" -name 'sm7150-xiaomi-phoenix.dtb' | head -1)
[ -n "$phxdtb" ] || { echo "no phoenix dtb in apk" >&2; exit 1; }
python3 "$repo/tools/abl-bootimg.py" extract-dtb "$uboot" -o "$work/davinci.dtb"
python3 "$repo/tools/abl-bootimg.py" copy-ids "$phxdtb" "$work/davinci.dtb" -o "$work/phoenix-abl.dtb"
python3 "$repo/tools/abl-bootimg.py" linux "$vmlinuz" "$work/initramfs-ntfs3.gz" "$work/phoenix-abl.dtb" --cmdline 'pmos.debug-shell' -o "$out"
echo "rescue image: $out"
