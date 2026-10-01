#!/bin/sh
# Runs ON THE PHONE as root, under the postmarketOS install that lives inside
# userdata (pmOS flashes a whole GPT disk image into userdata and Linux maps it
# with a loop device). Streams a consistent image of the entire userdata
# partition to stdout as zstd:
#
#   [nested GPT + Linux ESP] [ext4 root, used blocks only] [nested backup GPT]
#
# The root filesystem is frozen only while it is read; an EXIT trap and a
# 30-minute sleeper both thaw it. Unused root blocks come out as zeros, so the
# stream is small (a 107 GiB partition with 9 GB used compressed to 5 GB).
#
# Two traps this script avoids:
#  - e2image's mount check creates /.ismount-test-file on the root filesystem,
#    which blocks forever once / is frozen. The root is therefore read through
#    a second, unmounted, read-only loop device.
#  - The kernel's page cache: the head and tail are read with O_DIRECT.
#
# Environment:
#   LOOP=/dev/loop0             loop device over userdata (losetup -l)
#   ROOT=${LOOP}p2              the ext4 root inside it
#   ZSTD=zstd                   zstd binary on the phone
#   STOP_SERVICES="a.service"   services to stop before freezing (restarted after)
#
# Usage from the host (sudo must not prompt on a tty):
#   ssh phone 'sudo sh freeze-userdata.sh' > userdata.img.zst 2> userdata.log
set -u
set -o pipefail
LOOP=${LOOP:-/dev/loop0}
ROOT=${ROOT:-${LOOP}p2}
ZSTD=${ZSTD:-zstd}
STOP_SERVICES=${STOP_SERVICES:-}
log() { echo "[$(date +%T)] $*" >&2; }

[ "$(findmnt -n -o SOURCE /)" = "$ROOT" ] || { log "/ is not mounted from $ROOT"; exit 1; }
bs=$(cat "/sys/class/block/${LOOP##*/}/queue/logical_block_size")
total=$(( $(cat "/sys/class/block/${LOOP##*/}/size") * 512 / bs ))
rstart=$(( $(cat "/sys/class/block/${ROOT##*/}/start") * 512 / bs ))
rsize=$(( $(cat "/sys/class/block/${ROOT##*/}/size") * 512 / bs ))
tail_start=$((rstart + rsize))
log "$LOOP: $total sectors of $bs bytes; root $ROOT at $rstart, $rsize sectors; tail $((total - tail_start)) sectors"
fsblocks=$(dumpe2fs -h "$ROOT" 2>/dev/null | awk -F': *' '/^Block count/ {print $2}')
fsbs=$(dumpe2fs -h "$ROOT" 2>/dev/null | awk -F': *' '/^Block size/ {print $2}')
[ "$((fsblocks * fsbs))" = "$((rsize * bs))" ] || { log "ext4 size differs from its partition; refusing"; exit 1; }

thaw() {
	trap "" PIPE HUP
	fsfreeze -u / 2>/dev/null && log "thawed /"
	mount -o remount,rw /boot 2>/dev/null && log "/boot rw again"
	[ -n "${SNAP:-}" ] && losetup -d "$SNAP" && log "detached $SNAP"
	[ -n "${SAFETY:-}" ] && kill "$SAFETY" 2>/dev/null
	journalctl --flush >/dev/null 2>&1
	[ -n "$STOP_SERVICES" ] && systemctl start $STOP_SERVICES >&2 2>&1
	log "done"
}
trap 'thaw' EXIT
trap 'exit 1' HUP INT TERM PIPE

SNAP=$(losetup -r -b "$bs" --direct-io=on -f --show "$ROOT") || exit 1
[ -n "$STOP_SERVICES" ] && systemctl stop $STOP_SERVICES >&2 2>&1
journalctl --relinquish-var
sync
mount -o remount,ro /boot && log "/boot ro"
setsid sh -c 'sleep 1800; fsfreeze -u /' </dev/null >/dev/null 2>&1 &
SAFETY=$!
sync
fsfreeze -f / || exit 1
log "frozen /"
echo 1 > /proc/sys/vm/drop_caches
{
	dd if="$LOOP" bs="$bs" count="$rstart" iflag=direct status=none &&
	e2image -ra "$SNAP" - &&
	dd if="$LOOP" bs="$bs" skip="$tail_start" count="$((total - tail_start))" iflag=direct status=none
} | "$ZSTD" -T0 -3 -q -c
rc=$?
log "stream rc=$rc"
exit $rc
