# The rescue shell: offline debugging without Windows networking

The most reliable way to see what Windows did on phoenix is **not** to get
Windows online — it is to boot a small Linux over USB, mount the Windows
partition read-only, and read the boot log, crash dumps and driver state
straight off the UFS. This loop needs only `fastboot` and the USB cable, and it
works whether or not Windows itself is healthy.

## Build it

`device/build-rescue-shell.sh` takes the postmarketOS kernel `.apk` (the same
version the device runs) and the davinci U-Boot image, and produces a
RAM-bootable image with:

- the postmarketOS initramfs debug shell (busybox: `dd`, `nc`, `sha256sum`,
  `losetup`, `parted`, `e2fsck`), on `<phone-usb-ip>` over USB;
- **`ntfs3.ko` bundled** — the in-tree NTFS driver, so the shell can read NTFS;
- the phoenix DTB with davinci's `qcom,msm-id`/`board-id` so ABL accepts it.

```sh
device/build-rescue-shell.sh linux-postmarketos-qcom-sm7150-*.apk \
    u-boot-sm7150-xiaomi-davinci-samsung.img out/phoenix-rescue-shell.img
```

Boot it (RAM only, writes nothing):

```sh
fastboot reboot-bootloader
fastboot boot out/phoenix-rescue-shell.img
```

The shell comes up on telnet (port 23). Drive it from the host with
`device/rescue-telnet.py run '<cmd>'`, and move files with its `push`/`pull`
(a one-shot `nc -l` per transfer — do not probe the port first, that consumes
the listener).

## One catch: NTFS3 vs `$Secure`

This kernel's in-tree `ntfs3` refuses to mount the Windows volume:

```
ntfs3(sdaNN): Failed to initialize $Secure (-22)
mount: ... Invalid argument
```

That is an `ntfs3` limitation, not a corrupt volume. Use the **userspace** NTFS
tools instead (`ntfscat`, `ntfsls`, `ntfscp` from `ntfs-3g`/`ntfsprogs`): they
parse the MFT directly, tolerate a dirty volume, and need no `$Secure`. The
phone runs Alpine/musl, so musl-linked aarch64 binaries from an Alpine arm64
container run as-is. Bundle them once:

```sh
docker run --rm --platform linux/arm64 -v "$PWD":/o alpine:edge sh -c '
  apk add --no-cache ntfs-3g-progs >/dev/null
  mkdir -p b/bin b/lib
  for t in ntfscat ntfsls ntfscp ntfsinfo; do cp "$(command -v $t)" b/bin/; done
  for f in b/bin/*; do ldd "$f"; done | awk "/=>/{print \$3}/ld-musl/{print \$1}" | sort -u |
    while read l; do [ -f "$l" ] && cp "$l" b/lib/; done
  cp /lib/ld-musl-aarch64.so.1 b/lib/; tar -cf /o/ntfstools.tar b/bin b/lib'
```

Push the tar into the rescue shell and run against the Windows partition
(`/dev/sdaNN`, the `win` partition; `blockdev --rereadpt /dev/sda` first so the
new GPT is visible):

```sh
device/rescue-telnet.py push ntfstools.tar /tmp/ntfstools.tar
device/rescue-telnet.py run 'cd /tmp && tar -xf ntfstools.tar && LD_LIBRARY_PATH=/tmp/b/lib \
   ./b/bin/ntfsls -l -p /Windows /dev/sdaNN'
```

## What to read, and where it is

| file (on the Windows volume) | tells you |
| --- | --- |
| `/Windows/ntbtlog.txt` (UTF-16LE) | which boot drivers loaded (`BOOTLOG_LOADED`) and which did not (`BOOTLOG_NOT_LOADED`). Enabled by `bootlog yes` in the BCD. |
| `/Windows/Minidump/*.dmp` | the bugcheck of a crash. Header `PAGEDU64`; the bugcheck code is a uint32 at offset `0x38`, its four parameters are uint64 from `0x40`. |
| `/Windows/INF/setupapi.dev.log` | driver install results from the offline DISM staging. |
| `/Windows/Panther/setupact.log` | specialize / OOBE. |
| `/Windows/System32/config/SYSTEM` | the offline registry: driver `Start` types, `Enum\…\Problem` codes, power settings. `ntfscat` it out, then read it on the host with `hivex` (`hivexsh`, `hivexregedit`). |

Dates on these files read as 2024 because phoenix has no working RTC under
Windows — the clock is wrong, not the files.

## Why this matters

- It confirmed Windows reached the desktop (all installed drivers `BOOTLOG_LOADED`, no relevant failures).
- It read the power-button crash as bugcheck `0xA0 INTERNAL_POWER_ERROR` — a
  PEP notification failure. The attempted v2 power-policy workaround did not
  fix it; the latest dump identifies notification 0x27. See
  [review-request.md](review-request.md). Policy changes may avoid a trigger,
  but the PEP/Windows compatibility issue still needs diagnosis.
- `ntfscp` can also **write** single files back to the volume, so small fixes
  (a config file, a registry hive edited on the host with `hivex`) can be
  applied without a full 15-minute partition reflash. Driver changes still need
  the PC + DISM + reflash path, because they touch the driver store and catalog.

## Current read-only precautions and observed limitations

Identify the WIN partition by its expected layout/PARTUUID, set its kernel
block-device read-only flag with `blockdev --setro`, and verify `--getro` before
reading. Do not assume a RAM rescue image makes explicit disk-write commands
safe. No raw UFS USB mass-storage exposure is needed.

The tested ntfsprogs build required paths **without** a leading slash, e.g.
`Windows/System32/config/SYSTEM`. Confirm the actual tar layout; the bundle
used during the latest review had `/tmp/bin` and `/tmp/lib`, not `/tmp/b/...`.
Set `LD_LIBRARY_PATH` in each new shell session.

On this Mac, `nc` telnet worked while the Python helper returned "No route to
host". Treat that as a host-client limitation, not proof the phone is offline.

An attempted `ntfscp` hive write was refused because NTFS metadata was unclean.
The original hive hash remained unchanged. **Do not clear the NTFS journal or
bypass hibernation/dirty-volume protection to force an edit.** The subsequent
control was prepared on a separate PC VHDX and explicitly authorized for a
WIN-only reflash. Missing logs alone do not prove Windows wrote nothing.
