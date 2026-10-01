# Windows on Arm for the Xiaomi POCO X2 / Redmi K30 4G (`phoenix`, SM7150)

Experimental, community port of **Windows 11 Arm64** to the Xiaomi POCO X2 /
Redmi K30 4G (codename **phoenix**, Snapdragon 730G / SM7150-AB, soc_id 365).

This repo is the tooling, the UEFI patches and the findings. It holds **no
binaries** — no UEFI images, no Windows images, no Qualcomm blobs, no device
backups (all gitignored). Everything is built from pinned upstream sources and
a Microsoft ISO you supply.

> Status: **Windows boots to the desktop on real hardware.** UFS (storage),
> the side buttons and the UEFI framebuffer work. Touch, landscape orientation
> and the USB-C dock (USB host) do **not** work yet, and several SoC features
> are non-functional (see below). This is a proof of concept, not a daily
> driver. Read [docs/handoff.md](docs/handoff.md) before continuing the work.

## How it got here

phoenix is an *inactive* target in [Project Silicium's
Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium); Windows boot was
blocked by two things this project solved:

1. **The UEFI froze in `UFSDxe`.** SM7150's SEC detaches every non-display SMMU
   stream, and phoenix shipped a stubbed UFS driver that never re-attached UFS.
   Fix: surya's (POCO X3 NFC) June-2026 UFS/SMMU driver design. See
   [docs/uefi.md](docs/uefi.md).
2. **phoenix had no ACPI tables.** Windows needs them. We borrow surya's DSDT
   plus the shared SM7150 (Moorea) tables, after a per-device/per-rail risk
   audit. See [docs/acpi-audit.md](docs/acpi-audit.md).

Credit: Project Silicium (Mu-Silicium UEFI), [Project
Aloha](https://github.com/Project-Aloha) (SM7150 / surya Windows BSP), and the
postmarketOS phoenix port (the Linux the device normally runs).

## Safety rules (read before touching a device)

- **Test UEFI images with `fastboot boot` (RAM) only.** Never `fastboot flash
  boot` unless you intend to replace the bootloader (and have the rollback image).
- **Never choose Mass Storage / FFU Mode in the UEFI, or expose the raw UFS,
  while the phone is plugged into a Mac** — macOS writes to the Android FAT
  partitions and can corrupt firmware.
- **Any image in which UFS works must pass `tools/ffucheck.py`** first. Surya's
  UFSDxe contains a Xiaomi UFS firmware-update routine that matches this phone's
  flash chip; it is disabled by a patch, and the gate proves it.
- **Every destructive step (repartition, flash) comes after a verified,
  off-device backup** ([docs/backup-restore.md](docs/backup-restore.md)) and
  with the owner present.
- Identify every image by SHA-256; always `fastboot reboot-bootloader` before a
  `fastboot boot`.

## Layout

| path | what |
| --- | --- |
| `uefi/build.sh`, `uefi/patches/` | build the phoenix Windows UEFI from pinned Mu-Silicium + the patches |
| `tools/abl-bootimg.py` | build/inspect the Android boot images ABL boots (UEFI repack, rescue image, DTB id swap) |
| `tools/ffucheck.py` | the UFS firmware-update safety gate |
| `tools/fvwalk.py`, `fvcheck.py`, `pediff.py` | inspect UEFI firmware volumes and driver binaries |
| `tools/vhdx-to-android-sparse.py` | turn a 4Kn VHDX partition into a `fastboot flash` sparse image (reads VHDX directly; no qemu-img) |
| `tools/check-gpt.py` | independently verify a new GPT against the current one |
| `tools/verify-windows-arm64-iso.sh` | check a Microsoft ISO against the published hashes |
| `windows/*.ps1`, `*.cmd` | build the Windows image on a Windows PC (ADK): 4Kn VHDX, apply, drivers, BCD, verify, export |
| `windows/first-boot-drivers.txt` | the minimal, audited first-boot driver set |
| `device/backup-phone.sh`, `freeze-userdata.sh`, `capture-hw-state.sh` | full off-device backup and live hardware capture |
| `device/make-lun0-windows-gpt.sh`, `apply-lun0-gpt.sh`, `flash-windows.sh` | repartition LUN0 and flash Windows |
| `device/build-rescue-shell.sh`, `rescue-telnet.py` | a RAM-boot rescue shell with NTFS3, for offline debugging |
| `docs/` | the findings and the workflows |

## Docs

- [docs/handoff.md](docs/handoff.md) — **start here**: current state, what works,
  what's open, exact artifact hashes, next steps, the offline-debug loop.
- [docs/uefi.md](docs/uefi.md) — building the UEFI, the UFS freeze and its fix, the FFU hazard.
- [docs/acpi-audit.md](docs/acpi-audit.md) — the borrowed-ACPI risk analysis and the driver set it justifies.
- [docs/deployment.md](docs/deployment.md) — end-to-end install workflow.
- [docs/backup-restore.md](docs/backup-restore.md) — back the device up, and restore Linux.
- [docs/rescue-shell.md](docs/rescue-shell.md) — the offline NTFS debug channel.

## Requirements

- A host (macOS or Linux) with `fastboot`, `docker`, `python3`, `zstd`.
- A **Windows PC** with the matching Windows 11 ADK "Deployment Tools"
  (DISM/bcdboot) to build the image — Microsoft does not support servicing a
  Windows 11 image with an older host's DISM.
- A Microsoft Windows 11 Arm64 ISO (you download it; verify with the tool).
- The device, unlocked bootloader, and the davinci U-Boot image used by the
  postmarketOS port (for the ABL-select DTB and as the `boot` rollback).

## Non-functional on SM7150 (Project Aloha's BSP)

Battery/charging management, thermal and bandwidth management, CPU-frequency
management (730/730G), Type-C role detection, NFC, PCIe, TPM, Hyper-V,
LED/haptics PWM, some TLMM interrupts. **There is no thermal or battery
management under Windows** — treat every session as supervised, keep it short,
and watch the device's temperature.
