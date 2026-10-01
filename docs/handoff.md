# Handoff — phoenix Windows on Arm

Written 2026-10-01 for whoever (human or agent) continues this. It is the
single entry point: current state, what works, what is open, the exact
artifacts, and the next steps. Operational access details (device IP,
credentials, local file paths, the exact in-flight image) are **not** in this
public repo — they are in the operator's local notes alongside the artifacts.

## One-paragraph state

Windows 11 Arm64 **boots to the desktop on real phoenix hardware.** The UEFI
UFS freeze is fixed, phoenix runs on borrowed surya + Moorea ACPI tables,
`userdata` was replaced by an `esp`+`win` layout, Windows 11 Pro 25H2 was
flashed, and the tested UEFI replaced U-Boot in `boot`. Storage, the side
buttons and the framebuffer work. **Open:** touch, landscape orientation, the
USB-C dock (USB host), and a power-button crash — a second, updated image that
addresses the crash and adds the USB-host + SSH drivers is **built and waiting
to be flashed** (see "In flight").

## Device facts

- POCO X2 / Redmi K30 4G, codename **phoenix**, SM7150-AB (Snapdragon 730G),
  soc_id 365, PMICs PM6150 + PM6150L. Flash: Samsung KM2V8001CM-B707, **4Kn**
  (4096-byte logical sectors) on every LUN.
- Boot chain for Windows: ABL → (`boot` = the Mu-Silicium UEFI) → Windows Boot
  Manager on the ESP → winload. ABL selects a DTB by `qcom,msm-id`/`board-id`;
  only the davinci ids (0x16d / 0x28) make this ABL hand off.
- Normal (Linux) boot chain, for restore: ABL → (`boot` = davinci U-Boot) →
  systemd-boot → postmarketOS. Keep the davinci U-Boot image; it is the `boot`
  rollback and the source of the ABL-select DTB.
- **LUN0 GPT (`/dev/sda`):** disk GUID `461AA1DA-62E5-C93D-D55F-BDAAF5E431AD`,
  30922752 sectors, 32 entries originally. `userdata` was the last entry at LBA
  2851328. The Windows layout keeps entries 1–31 and replaces `userdata` with:
  - `esp`: LBA 2851328, 131072 sectors (512 MiB), FAT32, partition GUID
    `9B4A6475-3991-48BD-944C-5AF099121189`, type `C12A7328-…`.
  - `win`: LBA 2982400, 27940096 sectors (106.6 GiB), NTFS, partition GUID
    `9534131F-1CDC-418B-A661-2DCAA77D0B76`, type `EBD0A0A2-…`.

  The Windows image is built in a VHDX carrying **the same disk GUID and these
  same partition GUIDs**, because the BCD names its boot partitions by disk
  GUID + partition GUID.
- Everything else is untouched: the other 31 LUN0 partitions, and LUN1–LUN5
  (XBL, CDT/DDR, firmware incl. `abl`/`boot`/`modem`, calibration
  `persist`/`modemst`/`fsg`).

## What works, what is open

| area | state | notes |
| --- | --- | --- |
| UEFI boot / BDS | works | UFS freeze fixed; see [uefi.md](uefi.md). Runs 3 & 4 booted to BDS; Windows boots from the ESP. |
| UFS (storage) | works | inbox `storufs`; `BOOTLOG_LOADED`. |
| Side buttons | works | inbox `hidinterrupt` + `qcpmicgpio`. |
| Display | **portrait only** | BasicDisplay on the UEFI framebuffer; 1080×2400, no rotation. Landscape needs the GPU driver (excluded — panel-rail mismatch) or a BasicDisplay rotation set live. |
| Touch | **not working** | no driver installed. surya's DSDT describes a *different* touch bus (SPI 0x880000) than phoenix (SPI 0x890000); needs a phoenix touch device in the DSDT + `nt36xxx`. See [acpi-audit.md](acpi-audit.md) risk #1. |
| USB-C dock (host) | **not working on image v1** | v1 had no USB-host drivers. v2 (in flight) adds UCSI + XhciFilter + URS ext. Type-C role detection is non-functional per the BSP; forcing host role may be needed. |
| Power button | **crashes (v1)** | press → display off; press again → bugcheck `0xA0 INTERNAL_POWER_ERROR` (subcode 0x605), a power-transition failure. v2 disables modern standby and sets the button to do nothing. |
| Battery / thermal / CPU-freq | non-functional | SM7150 BSP limitation. No thermal or charge management under Windows — keep sessions short and supervised. |

## In flight — the v2 image (built, not yet flashed)

A second Windows image is finalized on the Windows PC's VHDX, **not yet on the
phone**. The phone still runs image **v1**. The partition layout is identical
(same GUIDs/sizes), so resuming only needs reflashing `esp` and `win` — the GPT
and `boot` are already correct.

v2 adds, over v1:
- **USB-host + Type-C drivers** (`windows/usb-drivers.txt`: UCSI `qcusbcucsi7150`,
  `QcXhciFilter7150`, URS ext `qcursext`), so the dock and its Ethernet can
  enumerate.
- **OpenSSH Server (ARM64 10.0), public-key auth**, installed fully offline:
  host keys + `administrators_authorized_keys` in `ProgramData\ssh` (ACLs
  locked to SYSTEM+Administrators), the `sshd` service created in the SYSTEM
  hive with `Start=2`. No account password needed (autologon stays). RDP also
  enabled (`fDenyTSConnections=0`, blank-password remote allowed). Firewall
  disabled on all profiles (dev device).
- **Power fix:** `Power\CsEnabled=0` (modern standby off), power+sleep buttons
  set to "do nothing" in the default schemes. Stops the `0xA0` crash.

v2 partition hashes (raw, read from the VHDX re-attached read-only):
- `esp`: `489ba62727577bee0827009e51a6c759ba3b791da0ea16b36b0b090fd887b212`
- `win`: `5566c979f6d05812a1c4fac5bfa556f17167508551be1cac618fc4c2d8a87fd0`
- VHDX file: `416431b83cf10d36e5d11c471b23b560b38bf95c5d800b6d32c055259dc93b70`

`tools/vhdx-to-android-sparse.py` prints the same `esp`/`win` hashes as
"expanded sha256" when it converts them — they must match before flashing.

### Resume checklist

1. Phone to fastboot (`fastboot reboot-bootloader`, or Vol-Down+Power).
2. Copy the v2 VHDX from the PC to the host; convert `esp` and `win` with
   `tools/vhdx-to-android-sparse.py` (use `--zero-unallocated` for the ESP);
   check the expanded hashes equal the v2 hashes above.
3. `device/flash-windows.sh esp.sparse.img win.sparse.img` (checks sizes against ABL).
4. Boot the UEFI (already in `boot`) — the phone boots Windows on its own.
5. Verify with the rescue shell ([rescue-shell.md](rescue-shell.md)): did
   `qcusbcucsi7150`/`qcxhcifilter`/`qcursext` load, is `sshd` running? If the
   dock enumerates, its Ethernet gives SSH/RDP → iterate live.

### Then, live over SSH (fast, no reflash)

- **Landscape (#1):** flip the BasicDisplay rotation and revert instantly while
  watching. The monitor config is in the SYSTEM hive at
  `…\GraphicsDrivers\Configuration\MSNILNOEDID_1414_008D_…\00` (currently
  `PrimSurfSize.cx=0x438` (1080), `cy=0x960` (2400), no rotation). Do this live,
  not baked into a reflash — a wrong rotation can black-screen.
- **Touch (#2):** needs ACPI work — add a phoenix touch device (SPI 0x890000,
  reset/IRQ GPIO 8/9 per the audit) to the DSDT, rebuild the UEFI
  (`uefi/build.sh`), add `nt36xxx`. This is a UEFI rebuild + `boot` reflash.
- If USB host does **not** come up: the Type-C role-switch extension sets
  `RoleSwitchMode=3` (auto, which needs the non-functional detection). Try
  forcing host: set the URS extension's role to host, or statically bind the
  host child. Debug via the offline loop (no live SSH needed).

## The offline-debug loop (how to see results without Windows online)

This is the key capability. `fastboot boot` the rescue shell
([rescue-shell.md](rescue-shell.md)), mount the `win` partition read-only with
the userspace NTFS tools, and read `ntbtlog.txt`, `Minidump\*.dmp`, the
`setupapi.dev.log`, and the SYSTEM hive (driver `Start`/`Problem`, power
settings). It needs only the USB cable and does not depend on the dock or any
Windows networking. It is how the v1 state above was established (bugcheck
code, loaded-driver list). Dates read as 2024 — the RTC is wrong under Windows,
not the files.

## Artifacts (gitignored — kept with the operator, not in this repo)

- The davinci U-Boot image (ABL-select DTB source; `boot` rollback).
- The verified Windows 11 Arm64 25H2 ISO (`tools/verify-windows-arm64-iso.sh`).
- The Mu-Silicium UEFI, repacked for ABL, FFU-gate-passed. The booted image's
  UFSDxe SHA-256 is `9990ab53b5c71033…` (surya stock, FFU disabled); `uefi/build.sh`
  reproduces it and it must pass `tools/ffucheck.py`.
- The full device backup (`device/backup-phone.sh` output) — **private**
  (IMEI, keys, calibration).
- The rescue shell with NTFS3 (`device/build-rescue-shell.sh`).
- The v2 Windows VHDX on the Windows PC (hashes above).

## Upstreaming

The UFS fix (phoenix left on a stubbed UFS driver when Mu commit `d3f5d84c`
enabled the SMMU detach) should go to Project Silicium; it mirrors what surya
already did (Binaries `8a1ad8de`). sweet_k6a and j706f are likely in the same
state. The phoenix ACPI (a real DSDT, not borrowed from surya) and a phoenix
Windows driver pack are the larger follow-ups.
