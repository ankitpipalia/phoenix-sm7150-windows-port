# The phoenix Windows UEFI

Windows on Arm needs a UEFI with ACPI. Phoenix (Xiaomi POCO X2, SM7150-AB,
`soc_id` 365) has no first-class UEFI: the only firmware with a phoenix target
is [Project Silicium's Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium),
where phoenix is an **inactive** target that upstream CI never builds and whose
Windows boot was marked "does not work". This repo builds that firmware from a
pinned commit, with four local patches, into an image that boots through BDS
and hands off to an OS on this phone.

- Base commit: `d19ae66c49fa47e47fd56a28e0e4db58b3638968` (2026-09-25).
- Prebuilt Qualcomm DXE binaries: `Binaries` submodule
  `203fb36bf7bf560989ca6b6848bfa07c79a5a04a`.
- Built in Docker (`ubuntu:24.04`, `linux/amd64`, `setup_env.sh -p apt`), the
  way upstream CI builds; macOS is not a supported build host.
- Target `Platforms/Xiaomi/phoenixPkg`, model 1 (POCO X2), DEBUG by default
  (prints its log to the framebuffer; RELEASE is silent). UEFI variables are
  RAM-emulated, so a `fastboot boot` of the image writes nothing.

`uefi/build.sh` does the whole thing; the sections below explain each piece.

## 1. Making ABL hand off: the davinci DTB

Qualcomm's ABL picks a device tree by `qcom,msm-id` / `qcom,board-id` and only
hands off to an image whose DTB matches the SoC. Stock Silicium appends
`Resources/DTBs/phoenix.dtb`, which is a generic 16-DTB bundle for unrelated
boards (APQ8016, DB820c, SDMMAGPIE with board-id 0, …). With it, `fastboot boot`
answers `Booting OKAY` but ABL never hands off — the screen stays blank and
fastboot keeps responding.

Replacing that bundle with the **davinci** DTB from the sm7150-mainline U-Boot
image (`qcom,msm-id = 0x16d`, `qcom,board-id = 0x28`) makes ABL hand off every
time, within a second. Phoenix's own Linux DTB uses board-id `0x2b`, which this
ABL does not accept; davinci's `0x28` is the only id known to work.

The boot-image layout ABL accepts (same as the U-Boot image it already boots):

| field | value |
| --- | --- |
| header version | v1 |
| page size | 2048 |
| base | 0x10000000 |
| kernel offset | 0x8000 |
| ramdisk offset | 0x01000000 |
| tags offset | 0x100 |

The kernel slot is Silicium's gzip stream (a small `ARMd` shim plus the firmware
volume) with the DTB appended; the ramdisk is Silicium's 5-byte `dummy`.
`tools/abl-bootimg.py uefi MU.img DAVINCI.dtb -o OUT.img` performs exactly this
repack, and `tools/abl-bootimg.py extract-dtb UBOOT.img -o davinci.dtb` pulls
the davinci DTB out of the U-Boot image. `build.sh` runs both automatically.

> **Method trap.** After one failed boot, this ABL answers `Load Error` to
> *every* later `fastboot boot` until restarted. Always run
> `fastboot reboot-bootloader` before each attempt.

## 2. The UFSDxe freeze and the fix (core finding)

The unmodified build reaches DXE, loads ~27 drivers, and then **freezes inside
`UFSDxe`'s entry point**: the driver is loaded and its entry point is called but
never returns, and ~16–17 s later the phone resets. A marker build (printing
`[PHX]` tags around `ProtectUefiImage`, the entry-point call, and live page-table
splits) placed the hang precisely: everything up to and including `SdccDxe`
starts and returns `Success`; `UFSDxe` starts and does not.

Leading causal explanation, supported by driver diffs, disassembly, Mu history
and the successful hardware configurations below:

- Since Mu commit `d3f5d84c` (2026-06-29, *"MooreaPkg: Enable MMU Detach"*), the
  SM7150 SEC calls `ArmSmmuDetach` and keeps only the display's eight stream IDs.
  Every other SMMU stream mapping that ABL left — UFS's included — is invalidated
  and its context bank disabled.
- Phoenix still ships the **pre-June** UFS set: a *stubbed* `UFSDxe.patched.efi`
  (surya's stock driver with its IOMMU-setup function replaced by `mov w0,#0; ret`
  at RVA `0x2488`), phoenix's *patched* `HALIOMMUDxe` (its four SDC/USB attach
  calls stubbed), and stock `DALSYSDxe`. Nothing in that set re-attaches UFS to
  the SMMU after the detach, so UFS DMA never completes and `UFSDxe` waits
  forever.

The fix is surya's own June-2026 design, applied to phoenix by two patches:

- `uefi/patches/01-ufs-surya-stock-dalsys-cca.py` — load surya's **stock**
  `UFSDxe.efi` (which sets up its own SMMU domain and attaches `\_SB_.UFS0`), and
  set the `\_SB_.UFS0` IORT Cache-Coherency-Attribute byte to `1` in phoenix's
  `DALSYSDxe.efi` (one byte at file offset `0x27adf`, `00` → `01`).
- `uefi/patches/02-haliommu-stock.py` — load phoenix's **stock** (unpatched)
  `HALIOMMUDxe.efi`, so SDC and USB get their SMMU mappings rebuilt too.

Two hardware runs confirmed it:

- **Run 3** (`instr-nodetach-noffu`): SEC restored to pre-June (no detach), stubbed
  driver. `UFSDxe` returned `Success`, all later DXE drivers loaded, BDS mounted
  the internal storage and booted systemd-boot from the Linux ESP; Linux came up
  logging `efi: EFI v2.7 by Project Silicium`.
- **Run 4** (`instr-surya-full-noffu`): the detach **kept**, with surya's stock
  `UFSDxe` + phoenix's stock `HALIOMMU` + the DALSYS CCA byte. Same full boot to
  BDS and on to Linux, with UFS intact (all LUNs still firmware rev 1000, no UFS
  or ext4 errors).

What both share is that **UFS gets a working SMMU mapping**. Run 4's design is
the one carried forward, because it matches what upstream runs on the active
surya target. (Patches 01+02 are that design.)

These runs changed multiple components: run 3 also restored the old coherency
setup, while run 4 changed UFS, HALIOMMU and DALSys together. They establish
working configurations and strongly support the mapping explanation, but do
not isolate SMMU detach as the sole cause. "UFS intact" above means no damage
was detected in the checks performed, not that no storage writes occurred;
Linux writes during normal boot.

## 3. The FFU hazard — a hard safety gate

Surya's `UFSDxe` (both the stock and the stubbed binary) contains a Xiaomi UFS
**firmware-update (FFU)** routine, called once from the init path at RVA
`0x2fe4` (the routine itself is at `0x25dc`). In run 2 — the first image in which
UFS actually worked — this routine matched the phone's Samsung
**`KM2V8001CM-B707`** at firmware revision 1000 and set out to "update" it to
1500, reading the new firmware from a fixed address `0xC9400000` ("from splash")
and writing it with SCSI WRITE BUFFER. It faulted reading `0xC9400000`
(unmapped) *before* the write, so nothing was flashed — by luck.

`uefi/patches/03-ufsdxe-disable-ffu.py` neutralises it: it replaces the `bl` at
RVA `0x2fe4` with `mov w0, #0` (the "no update" result) in whichever `UFSDxe`
the INF loads.

**Hard rule: never boot any image in which UFS works unless `tools/ffucheck.py`
passes on it.** The gate extracts the `UFSDxe` PE32 and requires:

- its SHA-256 is one of the known FFU-disabled builds
  (`9990ab53b5c71033…` = surya stock with the call disabled;
  `403a228aec596460…` = surya stubbed with the call disabled);
- the instruction at `0x2fe4` is `0x52800000` (`mov w0,#0`);
- zero remaining FFU call sites.

It exits non-zero otherwise, and `build.sh` runs it on every image it produces.
`ffucheck.py` uses `tools/fvwalk.py`, which walks the image by PI-spec structure
(firmware volume → FFS files → sections, expanding LZMA and nested volumes),
verifies every checksum, and reports each module's PE32 SHA-256 — so it also
tells you exactly which `UFSDxe` an image carries.

## 4. ACPI

Windows needs ACPI tables; phoenix has none.
`uefi/patches/04-acpi-from-surya.py` creates
`Silicium-ACPI/Platforms/Xiaomi/phoenix` from **surya's DSDT unchanged** plus the
shared SM7150 ("Moorea") tables (APIC, CSRT, DBG2, FACP, FACS, GTDT, IORT, MCFG,
PPTT and a common SSDT), and uncomments the ACPI lines in `phoenix.dsc` /
`phoenix.fdf`. The borrowed DSDT is a deliberate risk: its devices describe
surya's wiring, which differs from phoenix on several buses. See
[`acpi-audit.md`](acpi-audit.md) for the full per-device/per-rail risk analysis
and the resulting first-boot driver policy.

`uefi/patches/optional-force-boot-menu.py` is a diagnostic that makes Silicium's
Boot Manager menu open instead of auto-booting (it initialises
`mEnterBootManager = TRUE`); use it only when you want the menu without relying
on the Volume-Up hotkey. `uefi/patches/diagnostic/` holds the marker and
instrumentation patches used to find the freeze.

## 5. Build it

```sh
# UBOOT_IMG = the sm7150-mainline davinci U-Boot image (only its DTB is used)
uefi/build.sh  path/to/u-boot-sm7150-xiaomi-davinci-samsung.img  out/

# options:
#   TARGET=RELEASE     silent build (default DEBUG prints its log)
#   FORCE_MENU=1       also emit a boot-menu variant
```

`build.sh` checks out the pinned commit, applies patches 01→04, builds in
Docker, repacks the result for ABL with the davinci DTB, runs `tools/ffucheck.py`
on each output, and writes `SHA256SUMS`. The current known-good image —
surya DSDT + Moorea tables, run-4 driver set, FFU disabled — is:

```
5c389a094304261587b48988d9952a1b9a8203bac875e0269873e251c00ac112  Mu-phoenix-1-DEBUG-acpi-ubootdtb-v1.img
```

Always identify an image by SHA-256, run `fastboot reboot-bootloader` before
each boot, and test with `fastboot boot` (RAM) — never `fastboot flash boot` —
until you have deliberately decided to replace U-Boot (see
[`deployment.md`](deployment.md)).
