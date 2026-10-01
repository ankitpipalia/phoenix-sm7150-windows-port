#!/bin/bash
# Host side, phone in ABL fastboot AFTER device/apply-lun0-gpt.sh wrote the new
# table and the phone was rebooted to the bootloader. Writes only esp and win.
#   device/flash-windows.sh ESP_SPARSE WIN_SPARSE
# The sparse images come from tools/vhdx-to-android-sparse.py. ABL writes each
# chunk in the background, so the per-chunk "Writing" step prints ~0.001s; that
# is normal. Verify afterwards from the rescue shell against the PC's raw hashes
# (windows/Export-PhoenixPartitions.ps1).
set -euo pipefail
esp=${1:?usage: $0 ESP_SPARSE WIN_SPARSE}; win=${2:?}
fastboot devices | grep -q fastboot || { echo "no fastboot device" >&2; exit 1; }
size() { fastboot getvar "partition-size:$1" 2>&1 | awk '/partition-size/ {print $NF}' | head -1; }
total() { python3 - "$1" <<'PY'
import struct,sys
m,_,_,_,_,blk,blocks,_,_=struct.unpack('<IHHHHIIII',open(sys.argv[1],'rb').read(28))
assert m==0xED26FF3A, 'not an Android sparse image'; print(blk*blocks)
PY
}
for p in esp win; do
  eval img=\$$p
  ps=$(( $(size $p) )); is=$(total "$img")
  echo "$p: ABL=$ps image=$is"
  [ "$ps" = "$is" ] || { echo "$p size mismatch (partition $ps vs image $is)" >&2; exit 1; }
done
fastboot flash esp "$esp"
fastboot flash win "$win"
echo "esp and win written"
