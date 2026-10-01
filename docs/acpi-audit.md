# Borrowed surya ACPI on phoenix: risk audit

2026-10-01. Phoenix has no ACPI tables of its own, so the Windows UEFI image
(see docs/uefi.md) ships surya's DSDT unchanged plus the shared SM7150
(Moorea) tables, enabled by `uefi/patches/04-acpi-from-surya.py`.

This audit checks, read-only, what those tables would make Windows do to
phoenix hardware. The DSDT in the built image is byte-identical to
`Silicium-ACPI/Platforms/Xiaomi/surya/DSDT.aml` (SHA-256 `e81b2134…8930`).

Phoenix ground truth came from:
- the live and pristine phoenix DTBs;
- pinctrl, GPIO and regulator state captured from the running Linux
  (`<artifacts>/linux-hw-state/` (device/capture-hw-state.sh));
- the stock MIUI phoenix device-tree overlay.

Line numbers refer to the audit's own decompile. That decompile and the full
tables (device inventory, all 125 PMIC votes, all TLMM actions) are in
the audit scratch tree (gitignored).

**[V]** = verified, **[I]** = inferred.

## Result

**No over-voltage vote was found in the audited data.** None of the 125 PMIC votes
in the DSDT or in the PEP data the Moorea pack installs exceeds phoenix's
limit for that rail **[V]**.

This is a static audit, not a guarantee of runtime electrical safety. Driver
initialization, shared resources, inferred GPIO numbering and unobserved
firmware actions remain review points. In particular, do not assume a missing
function driver makes every PEP action unreachable.

The tables never touch memory-mapped hardware from AML:
- no SystemMemory or SystemIO operation regions;
- no `_INI`, `_OSC`, `_PTS` or `_WAK` **[V]**.

Every board-specific hardware action is one of:
- PEP data;
- a `_CRS` GPIO, I2C or SPI resource;
- the panel configuration blob.

The original audit treated these as actions triggered when the corresponding
device driver starts. That reachability assumption needs independent review,
particularly for shared PEP resources and initialization. Driver selection
limits risk but is not a complete safety boundary.

## Board mismatches that matter (each only with the named driver)

| Driver | What it would do on phoenix | Evidence |
| --- | --- | --- |
| `qcspi7150` / `x3n_spi` (+ `nt36xxx`) | The SPI1 PEP block re-muxes GPIO 49–52 to SPI and drives 50–52 as outputs. On phoenix these pins are the I2S bus to the NXP TFA98xx amp, and GPIO 52 is the amp's data output into the SoC. Phoenix touch is on another SPI bus (0x890000) that the DSDT does not describe. | DSDT L28733–28904; stock `pri_i2s_*`; `pinctrl-sm7150.c` **[V]** |
| `qcdx7150` / `x3n_dx` | Sets LDO18_A to 2.8 V (phoenix's panel 3.3 V rail is fixed at 3.0 V: an under-voltage). Toggles PM6150L GPIO "index 2"; read 0-based, that is GPIO3, the 2.8 V supply of phoenix's depth/ultra-wide cameras. Sends surya's non-DSC panel init to a DSC panel; GPU table up to 825 MHz, phoenix's speed bin unknown. | L4195, L3922/4179, L36746, L36411 **[V]**; GPIO target **[I]** |
| `tas256X_win` | Interrupts on GPIO 91 (phoenix: DS28E16 battery-authentication line) and GPIO 8 (phoenix: touch reset) | L41408 **[V]** |
| audio stack | GPIO 63–66 muxed to TSIF functions (phoenix: 63 = fingerprint 1.8 V enable, 66 = amp reset); GPIO 24/51/52 driven at 16 mA | L3142–3245 **[V]** |
| `qcipa` / `x3n_ipa` | Drives GPIO 12 low at 16 mA (phoenix: camera pin, held high) | L19505 **[V]** |
| USB / UCSI | Switches PM6150 GPIO7 (unused in the audited phoenix DTs) and may drive TLMM GPIO 104. The borrowed URS0 depends on UCS0. Original v2 fails with UCSI enabled; the disabled control boots without a visible URS controller. Removing that dependency for a static-host test is not yet validated. | L2095, L42673 **[I]**; latest state in review-request.md |
| subsystems / PIL / TrEE | Load surya-built DSP, modem and Wi-Fi firmware, board data and surya's `goodixfp.mbn` | packs **[V]**; effect **[I]** |

These all match phoenix **[V]**:
- the UFS, SD, USB PHY and WCN3998 rails;
- the panel I/O rail;
- touch reset/IRQ (GPIO 8/9);
- the BT UART and I2C pins;
- SD card-detect (GPIO 69);
- the PMIC SIDs;
- every SoC-level address and IRQ.

## What runs without any extra driver

The only hardware action of the first-boot set beyond the in-range UFS and SD
rail votes is `qcgpio` setting up an interrupt on GPIO 117. GPIO 117 is unused on
phoenix and already an input with pull-down.

Windows' inbox drivers bind by themselves:
- `storufs`: UFS0;
- `sdbus`: the SD controllers;
- `hidinterrupt`: buttons;
- `acpitime`: RTC, inert without `qcabd`;
- `urssynopsys` / `usbxhci`: USB, blocked until UCSI is installed.

UFS0 depends on PEP0, which depends on PMIC, which depends on SPMI.

## First-boot driver set (staged into the image)

Staged, with DISM confirmed to pre-install the boot-start services and map the
DSDT IDs:

- `HalExtQCTimer7150` (QCOM1403) and `HalExtQCWdogTimer7150` (QCOM1404).
  - The watchdog extension is Microsoft HAL-signed.
  - The timer extension is signed with a community certificate. It is first
    loaded on the *second* boot, after PnP registers it; if winload rejects it,
    the error names the file.
- `qcspmi7150` (QCOM140C), `qcpmic7150` (QCOM142E) and `qcpep.wd7150`
  (QCOM1419; only the desktop variant). These are needed for the UFS boot disk.
- `qcgpio7150` (QCOM140D) and `qcpmicgpio7150` (QCOM1430, keys, inputs only).

Excluded for now: everything in the mismatch table above, plus:
- I2C/UART/GPI/BAM;
- SMMU/IOMMU;
- SCM and system cache;
- the PEP extension and PPM settings;
- ADC;
- battery current limit;
- `QcSOCPartition`;
- the subsystem stack.

All need `testsigning on`.

`DSDT_Minimal.asl` (CPUs only) cannot boot Windows: it has no UFS0. A
zero-actuation variant is the minimal DSDT plus surya's UFS0 without its PEP
dependency. It compiles and is kept at
the audit's `minimal/DSDT_PhoenixBoot_candidate.asl` as a fallback smoke test.
It is not built into any image.

## Before adding more drivers

- Phoenix needs its own DSDT entries for:
  - touch on SPI 0x890000 (GPIO 53–56);
  - the TFA98xx amp at 0x34 on 0xA84000;
  - the DSC panel (rails, PM6150L GPIO9 reset).
- Remove surya's SPI1, TAS256x, NFC GPIO 12, IPA GPIO 12 and IR entries.
- Confirm on hardware what PM6150 GPIO6/GPIO7 and TLMM GPIO 33/104 connect to
  before enabling USB.
- Phoenix's GPU speed bin is unknown.
- The surya `nt36xxx.inf` references `j20s_novatek_ts_fw01/02.bin`; phoenix's
  stock overlay names `novatek_nt36672c_g7b_fw01/02.bin`. Audit firmware upload
  behavior and matching before testing touch, even after correcting SPI wiring.
