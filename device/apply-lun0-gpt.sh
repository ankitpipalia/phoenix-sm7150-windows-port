#!/bin/sh
# DESTRUCTIVE. Runs ON THE PHONE as root, in Linux or in the busybox rescue
# shell (docs/rescue-shell.md); the rescue shell is better because nothing is
# running from userdata then.
#
# Writes new primary (LBA 0-5) and backup (last 5 LBAs) GPT sectors to a 4Kn
# disk, but only if the disk still carries exactly the expected current ones,
# then reads them back. Touches nothing else on the disk.
#
#   apply-lun0-gpt.sh DEVICE CUR_HEAD CUR_TAIL NEW_HEAD NEW_TAIL
#   e.g. apply-lun0-gpt.sh /dev/sda lun0-orig-head.bin lun0-orig-tail.bin \
#            lun0-new-head.bin lun0-new-tail.bin
#
# Restoring the original table is the same command with the pairs swapped.
set -eu
dev=${1:?usage: $0 DEVICE CUR_HEAD CUR_TAIL NEW_HEAD NEW_TAIL}
cur_head=${2:?}; cur_tail=${3:?}; new_head=${4:?}; new_tail=${5:?}
name=${dev##*/}
sum() { sha256sum | cut -d' ' -f1; }

bs=$(cat "/sys/class/block/$name/queue/logical_block_size")
[ "$bs" = 4096 ] || { echo "$dev: sector size $bs, expected 4096" >&2; exit 1; }
lbas=$(( $(cat "/sys/class/block/$name/size") / 8 ))
for f in "$cur_head" "$new_head"; do [ "$(wc -c < "$f")" -eq $((6 * bs)) ] || { echo "$f is not 6 sectors" >&2; exit 1; }; done
for f in "$cur_tail" "$new_tail"; do [ "$(wc -c < "$f")" -eq $((5 * bs)) ] || { echo "$f is not 5 sectors" >&2; exit 1; }; done

head_now=$(dd if="$dev" bs="$bs" count=6 2>/dev/null | sum)
tail_now=$(dd if="$dev" bs="$bs" skip=$((lbas - 5)) count=5 2>/dev/null | sum)
[ "$head_now" = "$(sum < "$cur_head")" ] || { echo "$dev: primary GPT is not $cur_head; nothing written" >&2; exit 1; }
[ "$tail_now" = "$(sum < "$cur_tail")" ] || { echo "$dev: backup GPT is not $cur_tail; nothing written" >&2; exit 1; }
echo "current table confirmed; writing"

dd if="$new_head" of="$dev" bs="$bs" count=6 conv=notrunc,fsync 2>/dev/null
dd if="$new_tail" of="$dev" bs="$bs" seek=$((lbas - 5)) count=5 conv=notrunc,fsync 2>/dev/null
sync
blockdev --flushbufs "$dev" 2>/dev/null || true
echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
[ "$(dd if="$dev" bs="$bs" count=6 2>/dev/null | sum)" = "$(sum < "$new_head")" ] || { echo "READ-BACK MISMATCH (primary)" >&2; exit 2; }
[ "$(dd if="$dev" bs="$bs" skip=$((lbas - 5)) count=5 2>/dev/null | sum)" = "$(sum < "$new_tail")" ] || { echo "READ-BACK MISMATCH (backup)" >&2; exit 2; }
echo "written and read back"
# Make the kernel parse the new table, if nothing on the disk is in use.
if blockdev --rereadpt "$dev" 2>/dev/null; then
	for p in /sys/class/block/"$name"/"$name"*; do
		[ -e "$p/partition" ] && printf '%s start=%s size=%s %s\n' "${p##*/}" "$(cat "$p/start")" "$(cat "$p/size")" "$(grep PARTNAME "$p/uevent" | cut -d= -f2)"
	done | tail -4
else
	echo "partitions in use: the kernel keeps its old view until reboot"
fi
