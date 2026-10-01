#!/bin/bash
# Host side (macOS or Linux): full off-device backup of a phoenix running
# postmarketOS from userdata, before userdata is replaced by Windows.
#
#   device/backup-phone.sh OUT_DIR
#
# Writes to OUT_DIR:
#   gpt-sfdisk.txt, gpt-sdX-head.bin / gpt-sdX-tail.bin   every LUN's GPT, text and raw
#   lun-sdb..sdf.img.zst                                  LUN1-LUN5 whole (XBL, CDT/DDR,
#                                                         firmware incl. abl/boot/modem,
#                                                         persist/modemst/fsg calibration)
#   lun-sda-before-userdata.img.zst                       LUN0 up to userdata (incl. super)
#   userdata.img.zst                                      userdata, consistent (freeze-userdata.sh)
#   SHA256-phone.txt / VERIFY.txt                         phone-side hashes, host-side comparison
#
# The LUN dumps contain this phone's IMEI, calibration and keys: keep them
# private and never publish them.
#
# Environment:
#   PHONE=user@172.16.42.1   SSH target (USB networking)
#   PHONE_SUDO_PASSWORD      if set, passed to `sudo -S` (visible in the phone's
#                            process list while a command runs); otherwise
#                            `sudo -n` is used, which needs a NOPASSWD rule
#   REMOTE_ZSTD=zstd         zstd on the phone (apk add zstd)
#   STOP_SERVICES            passed to freeze-userdata.sh
set -u
out=${1:?usage: $0 OUT_DIR}
here=$(cd "$(dirname "$0")" && pwd)
PHONE=${PHONE:-user@172.16.42.1}
Z=${REMOTE_ZSTD:-zstd}
if [ -n "${PHONE_SUDO_PASSWORD:-}" ]; then
	S="printf '%s\n' '$PHONE_SUDO_PASSWORD' | sudo -S -p ''"
else
	S="sudo -n"
fi
mkdir -p "$out"
cd "$out" || exit 1
log() { echo "[$(date +%T)] $*"; }
run() { ssh -o BatchMode=yes -o ServerAliveInterval=15 "$PHONE" "$@"; }
remote_sum() { run "$S sh -c '$1 | sha256sum'" | cut -d' ' -f1; }
check() {  # check FILE.zst EXPECTED_SHA256
	local h
	h=$(zstd -dc "$1" | shasum -a 256 | cut -d' ' -f1)
	if [ "$h" = "$2" ]; then echo "OK        $1"; else echo "MISMATCH  $1 ($h, phone $2)"; fi
}

luns=$(run 'cd /sys/block && ls -d sd? | tr "\n" " "')
log "LUNs: $luns"
run "$S sh -c 'for d in $luns; do echo == \$d; sfdisk -d /dev/\$d; done; echo; losetup -l; lsblk -b -o NAME,SIZE,PARTLABEL,FSTYPE,MOUNTPOINT'" > gpt-sfdisk.txt
for d in $luns; do
	lbas=$(( $(run "cat /sys/block/$d/size") / 8 ))
	run "$S dd if=/dev/$d bs=4096 count=6 status=none" > "gpt-$d-head.bin"
	run "$S dd if=/dev/$d bs=4096 skip=$((lbas - 5)) count=5 status=none" > "gpt-$d-tail.bin"
done
ud=$(awk '/^== sda/{f=1;next} /^== /{f=0} f && /name="userdata"/' gpt-sfdisk.txt)
ud_start=$(echo "$ud" | sed 's/.*start= *\([0-9]*\).*/\1/')
[ -n "$ud_start" ] || { echo "no userdata partition on sda" >&2; exit 1; }
log "userdata starts at LBA $ud_start"

: > SHA256-phone.txt
for d in $luns; do
	[ "$d" = sda ] && continue
	log "LUN $d"
	run "$S sh -c 'dd if=/dev/$d bs=1M status=none | $Z -T0 -3 -q -c'" > "lun-$d.img.zst"
	echo "$(remote_sum "dd if=/dev/$d bs=1M status=none")  lun-$d.img.zst" >> SHA256-phone.txt
done
log "LUN0 before userdata ($ud_start sectors)"
run "$S sh -c 'dd if=/dev/sda bs=4096 count=$ud_start status=none | $Z -T0 -3 -q -c'" > lun-sda-before-userdata.img.zst
echo "$(remote_sum "dd if=/dev/sda bs=4096 count=$ud_start status=none")  lun-sda-before-userdata.img.zst" >> SHA256-phone.txt

log "userdata (root frozen while it is read)"
scp -q -o BatchMode=yes "$here/freeze-userdata.sh" "$PHONE:/tmp/freeze-userdata.sh"
run "$S env ZSTD=$Z STOP_SERVICES='${STOP_SERVICES:-}' sh /tmp/freeze-userdata.sh" > userdata.img.zst 2> userdata.log
log "userdata stream: $(tail -1 userdata.log)"

log "verifying"
while read -r h f; do check "$f" "$h"; done < SHA256-phone.txt | tee VERIFY.txt
ud_size=$(echo "$ud" | sed 's/.*size= *\([0-9]*\).*/\1/')
size=$(zstd -dc userdata.img.zst | wc -c | tr -d ' ')
if zstd -tq userdata.img.zst && [ "$size" = $((ud_size * 4096)) ]; then
	echo "OK        userdata.img.zst (zstd intact, $size bytes = partition size)" | tee -a VERIFY.txt
else
	echo "MISMATCH  userdata.img.zst ($size bytes, partition $((ud_size * 4096)))" | tee -a VERIFY.txt
fi
shasum -a 256 ./*.zst ./*.bin > SHA256SUMS
grep -q MISMATCH VERIFY.txt && exit 1
log "backup complete; also run the deep userdata check in docs/backup-restore.md"
