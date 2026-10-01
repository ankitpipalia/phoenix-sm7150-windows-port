#!/bin/sh
# Runs ON THE PHONE as root (Linux; needs sfdisk, losetup, truncate). Writes
# NOTHING to UFS: it builds the new LUN0 partition table on a sparse replica of
# LUN0 and leaves the exact sectors to write in OUTDIR.
#
# The new table replaces LUN0's last partition (userdata) with two entries,
# esp and win, using the partition GUIDs and sizes of the VHDX the Windows image
# was built in (windows/New-PhoenixVhdx.ps1 and Export-PhoenixPartitions.ps1 print
# them). Every other entry stays byte-identical, and so does the protective MBR
# (LBA 0). Stock phoenix LUN0 has exactly 32 entries in a 32-entry table, so the
# entry count is raised to 64; LUN4 already uses 64-entry tables, which the
# bootloaders read at every boot.
#
#   make-lun0-windows-gpt.sh ESP_GUID ESP_SECTORS WIN_GUID WIN_SECTORS [OUTDIR]
#
# DEV (default /dev/sda) selects the disk, for testing against a loop device.
# OUTDIR gets lun0-orig-{head,tail}.bin (the current table, for the write guard
# and for restoring) and lun0-new-{head,tail}.bin, plus SHA256SUMS. Check them
# with tools/check-gpt.py and windows/Test-GptOnWindows.ps1 before writing them
# with device/apply-lun0-gpt.sh.
set -eu
esp_guid=${1:?usage: $0 ESP_GUID ESP_SECTORS WIN_GUID WIN_SECTORS [OUTDIR]}
esp_n=${2:?}; win_guid=${3:?}; win_n=${4:?}
out=${5:-/tmp/lun0-windows}
dev=${DEV:-/dev/sda}
name=${dev##*/}
mkdir -p "$out"

bs=$(cat "/sys/class/block/$name/queue/logical_block_size")
[ "$bs" = 4096 ] || { echo "LUN0 sector size is $bs, expected 4096" >&2; exit 1; }
lbas=$(( $(cat "/sys/class/block/$name/size") * 512 / bs ))
sfdisk -d "$dev" > "$out/lun0-orig.sfdisk"
last=$(grep '^/dev/' "$out/lun0-orig.sfdisk" | tail -1)
case "$last" in *'name="userdata"'*) ;; *) echo "the last LUN0 partition is not userdata: $last" >&2; exit 1 ;; esac
start=$(echo "$last" | sed 's/.*start= *\([0-9]*\).*/\1/')
lastlba=$(awk -F': ' '/^last-lba:/ {print $2}' "$out/lun0-orig.sfdisk")
win_start=$((start + esp_n))
[ $((win_start + win_n - 1)) -le "$lastlba" ] || { echo "esp+win do not fit before last-lba $lastlba" >&2; exit 1; }

# Original sectors: primary GPT (LBA 0-5) and backup GPT (last 5 LBAs).
dd if="$dev" of="$out/lun0-orig-head.bin" bs="$bs" count=6 status=none
dd if="$dev" of="$out/lun0-orig-tail.bin" bs="$bs" skip=$((lbas - 5)) count=5 status=none

# New table script: same header (64 entries), entries 1..N-1 unchanged, then esp and win.
{
	grep -v -e '^device:' -e '^/dev/' "$out/lun0-orig.sfdisk" | sed 's/^table-length: .*/table-length: 64/'
	grep '^/dev/' "$out/lun0-orig.sfdisk" | sed '$d' | sed 's|^/dev/[a-z0-9]* : ||'
	echo "start=$start, size=$esp_n, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, uuid=$esp_guid, name=\"esp\""
	echo "start=$win_start, size=$win_n, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, uuid=$win_guid, name=\"win\""
} > "$out/lun0-windows.script"

replica="$out/replica.img"
rm -f "$replica"; truncate -s $((lbas * bs)) "$replica"
dd if="$out/lun0-orig-head.bin" of="$replica" bs="$bs" conv=notrunc status=none
dd if="$out/lun0-orig-tail.bin" of="$replica" bs="$bs" seek=$((lbas - 5)) conv=notrunc status=none
loop=$(losetup -b "$bs" -f --show "$replica")
trap 'losetup -d "$loop"; rm -f "$replica"' EXIT
sfdisk --no-reread --no-tell-kernel --wipe never --wipe-partitions never "$loop" < "$out/lun0-windows.script" >/dev/null
# Keep the original protective MBR; take LBA 1-5 and the backup GPT from the replica.
{ dd if="$out/lun0-orig-head.bin" bs="$bs" count=1 status=none
  dd if="$loop" bs="$bs" skip=1 count=5 status=none; } > "$out/lun0-new-head.bin"
dd if="$loop" of="$out/lun0-new-tail.bin" bs="$bs" skip=$((lbas - 5)) count=5 status=none
# Verify exactly the bytes that will be written: put them back into the replica.
dd if="$out/lun0-new-head.bin" of="$loop" bs="$bs" conv=notrunc status=none
dd if="$out/lun0-new-tail.bin" of="$loop" bs="$bs" seek=$((lbas - 5)) conv=notrunc status=none
sync
sfdisk --verify "$loop"
sfdisk -d "$loop" | tail -3
(cd "$out" && sha256sum lun0-orig-head.bin lun0-orig-tail.bin lun0-new-head.bin lun0-new-tail.bin | tee SHA256SUMS)
echo "LUN0: $lbas sectors; esp at $start ($esp_n sectors), win at $win_start ($win_n sectors)"
