# Deploying Windows on phoenix

The end-to-end workflow, in order. It replaces the single `userdata` partition
(which holds the nested postmarketOS install) with an ESP and a Windows
partition, leaving every firmware, calibration and bootloader partition intact.
Windows 11 Arm64 boots and reaches the desktop; **touch, landscape display and
the USB-C dock do not work yet** (see [`handoff.md`](handoff.md)).

Three machines are involved:

- **host** — a Mac or Linux box with `fastboot`, Docker and Python 3; drives the
  phone over USB.
- **phone** — phoenix, reachable over USB networking as `user@<phone>` while
  Linux runs, or as a telnet shell when the rescue image runs.
- **windows-pc** — a Windows box with the Windows 11 ADK; builds the image.

## Safety rules (apply throughout)

- **Test UEFI images with `fastboot boot` (RAM) only.** Never
  `fastboot flash boot` until step 7, which is a deliberate, reversible choice.
- **Never select USB mass-storage / FFU mode in the UEFI while the phone is
  plugged into a Mac** — macOS auto-mounts and writes to the Android FAT
  partitions.
- **The owner must be at the phone and filming** for every boot; the phone is a
  production device and each boot takes it offline.
- **Every destructive step comes after a verified backup** (step 2), and needs
  explicit confirmation.
- Identify every image by SHA-256; `fastboot reboot-bootloader` before each boot.

## 1. Build and smoke-test the UEFI

Build per [`uefi.md`](uefi.md) and confirm `tools/ffucheck.py` passes. Then,
with the owner filming, RAM-boot it and confirm it reaches BDS and still boots
the existing OS:

```sh
fastboot reboot-bootloader
fastboot boot out/Mu-phoenix-1-DEBUG-acpi-ubootdtb-v1.img
```

Optionally build and boot the rescue image now too
([`rescue-shell.md`](rescue-shell.md)) and confirm it reaches a telnet shell and
sees all UFS LUNs — you will need it in steps 5 and 8.

## 2. Full device backup (non-destructive, required)

```sh
device/backup-phone.sh <artifacts>/phoenix-backup
```

This dumps every LUN's GPT, images LUN1–LUN5 whole (XBL, CDT/DDR, firmware incl.
`abl`/`boot`/`modem`, and the `persist`/`modemst`/`fsg` calibration), images
LUN0 up to `userdata`, and takes a consistent image of `userdata` itself
(`device/freeze-userdata.sh` freezes the root while it reads it). It then
re-hashes every region on the phone and compares. Also capture the live hardware
state for later ACPI work:

```sh
ssh user@<phone> 'sudo sh capture-hw-state.sh' > <artifacts>/hw-state.tar
```

See [`backup-restore.md`](backup-restore.md) for verification and the exact
Linux-restore procedure. **Do not proceed past here until the backup verifies.**
These images contain the phone's IMEI, keys and calibration — keep them private.

## 3. Build the Windows image (on windows-pc)

Read LUN0's identity from the phone first (`sfdisk -d /dev/sda` for the disk
label-id and `userdata`'s start LBA; `cat /sys/block/sda/size` for the sector
count). Then, in an elevated PowerShell with the ADK "Deployment Tools"
installed (ADK **10.1.26100.x** for a Windows 11 24H2/25H2 image — an older
host's DISM is not supported for servicing Windows 11):

```powershell
# 1. a 4Kn VHDX the exact size of LUN0, carrying LUN0's disk GUID, with the ESP
#    at userdata's start LBA and Windows filling the rest:
windows\New-PhoenixVhdx.ps1 -Path C:\phx\phoenix-lun0.vhdx `
    -DiskGuid '{<lun0-disk-guid>}' -Lun0Sectors <n> -UserdataStartLba <lba>
#    -> prints the ESP and Windows partition GUIDs; keep them for step 4.

# 2. apply Windows, stage the first-boot drivers, write the BCD + unattend:
windows\Install-PhoenixWindows.ps1 -Iso D:\Win11_25H2_English_Arm64_v2.iso `
    -DriverRoot D:\drivers

# 3. check the image is internally consistent:
windows\Test-PhoenixImage.ps1

# 4. detach cleanly and hash the partitions (flushes NTFS, empties the VHDX log):
windows\Export-PhoenixPartitions.ps1 -Path C:\phx\phoenix-lun0.vhdx
```

Why this shape:

- **4Kn VHDX** — the UFS LUNs use 4096-byte logical sectors; NTFS/FAT made on
  512-byte sectors will not mount on the phone. `New-4knVhdx.ps1` creates it via
  the VirtDisk API (works on Windows editions without Hyper-V's `New-VHD`).
- **LUN0 disk GUID + the ESP/Windows partition GUIDs** — `bcdboot` writes a BCD
  that names its boot partitions by *disk GUID + partition GUID*. The VHDX
  therefore uses LUN0's disk GUID, and the phone's new `esp`/`win` entries
  (step 4) must carry the GUIDs this step printed.
- **First-boot drivers** (`windows/first-boot-drivers.txt`) — only the drivers
  the ACPI audit cleared: the HAL timer/watchdog extensions and SPMI, PMIC, PEP,
  GPIO, PMIC-GPIO (the UFS boot disk depends on PEP → PMIC → SPMI). The display,
  touch, audio, IPA and subsystem drivers are **excluded** on purpose — see
  [`acpi-audit.md`](acpi-audit.md). USB-host drivers are an open iteration.
- **testsigning** — the driver packs are test-signed, so the BCD sets
  `testsigning on` (and `bootlog yes`, `hypervisorlaunchtype off`); no
  `nointegritychecks`, recovery left intact.
- **unattend.xml** — a local admin account and skip-OOBE, because the phone has
  no working input device under Windows yet.

## 4. Build and verify the new LUN0 GPT (on the phone, non-destructive)

Pass the ESP and Windows partition GUIDs and sizes from step 3:

```sh
ssh user@<phone> 'sudo sh make-lun0-windows-gpt.sh \
    <esp-guid> <esp-sectors> <win-guid> <win-sectors> /tmp/lun0-windows'
```

`device/make-lun0-windows-gpt.sh` writes **nothing** to UFS: it applies the new
table to a sparse replica of LUN0 and leaves the exact sectors to write
(`lun0-orig-*.bin`, `lun0-new-*.bin`) plus `SHA256SUMS`. It keeps entries 1..N-1
byte-identical, replaces `userdata` with `esp`+`win`, raises the entry count to
64 (LUN4 already uses 64), and preserves the protective MBR.

Verify the result two independent ways before trusting it:

```sh
# on the host: CRCs, primary==backup, entries 1..31 unchanged, no overlaps
tools/check-gpt.py lun0-orig-head.bin lun0-orig-tail.bin \
    lun0-new-head.bin lun0-new-tail.bin --lbas <n> --keep 31
```

```powershell
# on windows-pc: write the exact bytes into an empty 4Kn VHDX and see what
# Windows' partition manager makes of them
windows\Test-GptOnWindows.ps1 -Head lun0-new-head.bin -Tail lun0-new-tail.bin -Lun0Sectors <n>
```

## 5. Write the new GPT (DESTRUCTIVE — explicit go, after backup)

Best done from the rescue shell, so nothing is running from `userdata`:

```sh
device/apply-lun0-gpt.sh /dev/sda \
    lun0-orig-head.bin lun0-orig-tail.bin lun0-new-head.bin lun0-new-tail.bin
```

It refuses to write unless LUN0 still carries exactly the backed-up original
table, writes LBA 0–5 and the last 5 LBAs only, and reads them back. A normal
reboot now stops in U-Boot (no `userdata` to map, no bootable ESP yet); hold
Volume-Down + Power to reach fastboot.

## 6. Flash Windows (DESTRUCTIVE)

Copy the VHDX to the host, convert each partition to an Android sparse image,
and flash:

```sh
tools/vhdx-to-android-sparse.py phoenix-lun0.vhdx --offset <esp-off> --size <esp-size> --zero-unallocated -o esp.sparse.img
tools/vhdx-to-android-sparse.py phoenix-lun0.vhdx --offset <win-off> --size <win-size> -o win.sparse.img
device/flash-windows.sh esp.sparse.img win.sparse.img
```

The converter reads the 4Kn VHDX directly (qemu-img cannot) and prints each
partition's expanded SHA-256; it must equal the raw hash
`Export-PhoenixPartitions.ps1` printed. `flash-windows.sh` checks each image
against ABL's `partition-size` before writing. ABL writes each chunk in the
background, so the per-chunk `Writing` step prints ~0.001 s — that is normal.
Afterwards, verify from the rescue shell against the PC's raw hashes
([`rescue-shell.md`](rescue-shell.md) shows reading partitions with the
userspace NTFS tools).

## 7. Replace U-Boot in `boot` with the UEFI (reversible)

With Linux gone, U-Boot has no job, and on every Windows restart it would try to
start the Windows boot manager with no ACPI. Put the tested UEFI in `boot`:

```sh
tools/ffucheck.py Mu-phoenix-1-DEBUG-acpi-ubootdtb-v1.img   # MUST pass first
fastboot flash boot Mu-phoenix-1-DEBUG-acpi-ubootdtb-v1.img
```

Confirm beforehand that `boot` currently holds the saved U-Boot image (so you
know the rollback is exact). **Rollback:**

```sh
fastboot flash boot u-boot-sm7150-xiaomi-davinci-samsung.img
```

## 8. First boot

`fastboot reboot-bootloader`, then boot (or, after step 7, just reboot). Windows
Setup runs its specialize/OOBE pass once and restarts. Confirm what happened
from the offline debug loop rather than trusting the screen: boot the rescue
shell, mount the Windows partition read-only, and read `ntbtlog.txt`, the
`Panther` logs, `Minidump`, and driver problem codes straight from the image —
see [`rescue-shell.md`](rescue-shell.md). To restore Linux at any point, follow
[`backup-restore.md`](backup-restore.md).
