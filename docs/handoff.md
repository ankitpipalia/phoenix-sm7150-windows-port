# Handoff — phoenix Windows on Arm

Updated 2026-10-01 for whoever (human or agent) continues this. It is the
single entry point: current state, what works, what is open, the exact
artifacts, and the next steps. Operational access details (device IP,
credentials, local file paths, the exact in-flight image) are **not** in this
public repo — they are in the operator's local notes alongside the artifacts.

## One-paragraph state

Windows 11 Arm64 **boots to the desktop on real phoenix hardware.** The UEFI
UFS freeze is fixed, phoenix runs on borrowed surya + Moorea ACPI tables,
`userdata` was replaced by an `esp`+`win` layout, Windows 11 Pro 25H2 was
flashed, and the tested UEFI replaced U-Boot in `boot`. Storage, the side
buttons and the framebuffer work. **Open:** touch, landscape orientation,
USB-C dock/ Ethernet, and a power-button crash. Original v2 was flashed and
failed with `0x14E`; a control with only UCSI disabled then reached the desktop
but still crashes on display-off/wake. SSH is configured, not remotely
verified. The phone was last inspected in a RAM rescue shell with Windows
storage read-only. See [review-request.md](review-request.md) before making
changes: it supersedes the earlier optimistic v2 claims.

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
| Display | **portrait only** | BasicDisplay, 1080×2400. Supported rotation has not been tested; do not assume registry edits or BasicDisplay can rotate it. Surya GPU/panel setup remains excluded. |
| Touch | **not working** | no driver installed. Phoenix needs SPI 0x890000, appropriate PEP pinmux/resources and phoenix firmware. Surya's touch INF references j20s firmware, not phoenix's g7b firmware. |
| USB-C dock (host) | **not working** | original v2 UCSI-enabled boot fails; UCSI-disabled control boots, but ACPI URS0 depends on UCS0 and no URS controller appears in the saved Enum tree. |
| SSH | **configured, unreachable** | automatic sshd service and PID file observed; no working network path or successful phone SSH authentication yet. |
| Power button | **still crashes** | UCSI-disabled v2 dump: 0xA0, parameters 0x605 / 0x27 / plugin pointer / 0. Previous offline button edits target wrong brace-wrapped GUID keys. |
| Battery / thermal / CPU-freq | non-functional | SM7150 BSP limitation. No thermal or charge management under Windows — keep sessions short and supervised. |

## Deployment history — v2 and the UCSI-disabled control

Original v2 was flashed to ESP and WIN; all fastboot writes returned OKAY.
It failed with `SOC_CRITICAL_DEVICE_REMOVED (0x14E)`, photo parameters
`0x71706530`, `0x15`, `0`, `0`. The signature matches PEP bugcheck call sites,
but does not identify a unique device or prove physical removal. Booting
without a USB cable also failed (owner report; fresh parameters not supplied).

Next, a copy of the PC master was changed only semantically at
`ControlSet001\Services\qcusbcucsi\Start`: DWORD 3 → 4. Full registry-tree
comparison verified that single value change. Windows mounting also changed
filesystem metadata, so this was **not** a byte-only whole-image comparison.
Only WIN was reflashed; ESP, GPT, boot and firmware partitions were preserved.
The owner reports desktop boot; fresh offline files confirm Windows ran,
UCSI remains disabled, and a subsequent power-button crash produced a dump.

v2 adds, over v1:
- **USB-host + Type-C drivers** (private v2 manifest: UCSI `qcusbcucsi7150`,
  `QcXhciFilter7150`, URS ext `qcursext`), intended to enable the dock.
  Host enumeration and Ethernet did not work in the tests so far.
- **OpenSSH Server (ARM64 10.0), public-key auth**, installed fully offline:
  host keys + `administrators_authorized_keys` in `ProgramData\ssh` (ACLs
  locked to SYSTEM+Administrators), the `sshd` service created in the SYSTEM
  hive with `Start=2`. No account password needed (autologon stays). RDP also
  enabled (`fDenyTSConnections=0`, blank-password remote allowed). Firewall
  disabled on all profiles (dev device).
- **Attempted power workaround (ineffective):** `Power\CsEnabled=0` and button
  defaults were edited. Modern-standby disablement was not verified. The
  button edits used `{GUID}` key names while Windows' existing keys use
  unbraced GUIDs; real defaults retained nonzero values. The crash persists.

v2 partition hashes (raw, read from the VHDX re-attached read-only):
- `esp`: `489ba62727577bee0827009e51a6c759ba3b791da0ea16b36b0b090fd887b212`
- `win`: `5566c979f6d05812a1c4fac5bfa556f17167508551be1cac618fc4c2d8a87fd0`
- VHDX file: `416431b83cf10d36e5d11c471b23b560b38bf95c5d800b6d32c055259dc93b70`

`tools/vhdx-to-android-sparse.py` prints the same `esp`/`win` hashes as
"expanded sha256" when it converts them — they must match before flashing.

UCSI-disabled control artifact hashes:

- Sparse WIN file: `f0b6b520c722664fb25bd92847f68d01871324ae0be87163558b39f08d9a849c`.
- Expanded WIN/raw PC partition: `91de0202833a9026ce048cb79c84a4812a9e227b41b435c410e2099e618f5c38`.
- Expanded size: 114442633216 bytes. All 20 fastboot writes returned OKAY.
- DONT_CARE areas may retain old phone bytes; image hashes are not full-device
  readback verification. The control artifact is private and its operational
  one-service patch script is not yet integrated into this repo's builder.

### Resume checklist — review before another flash

1. Read [review-request.md](review-request.md) and obtain the private evidence
   from the owner if needed. No static-host, touch or rotation fix has been
   built/deployed since the UCSI-disabled test.
2. Preserve the current Windows logs/hive/dump before replacing WIN again.
   A full reflash loses new Windows files and runtime state.
3. Review a minimal static-host design (including URS0's dependency on UCS0)
   without re-enabling the known-failing UCSI path blindly.
4. Correct effective power policy as a **workaround**, then investigate why
   PEP rejects notification 0x27. Do not suppress the bugcheck or claim sleep
   is supported merely because the button no longer triggers it.
5. Establish dock Ethernet and verify sshd/authentication before live display
   tests. Audit phoenix touch resources and firmware before installing it.
6. Keep owner present, backup/rollback available and image/FFU gates enforced.

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
