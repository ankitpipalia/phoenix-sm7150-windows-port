# Independent review request — current Windows blockers

Updated 2026-10-01 after a successful desktop boot of the UCSI-disabled v2
control. This document is the review entry point; [handoff.md](handoff.md) has
the platform, GPT and artifact context. Please separate demonstrated facts,
source-derived conclusions and hypotheses. We need evidence-backed fixes and
safe, discriminating tests, not a wholesale surya driver transplant.

## What is working

- ABL → Mu-Silicium → Windows Boot Manager → Windows 11 Arm64 Pro 25H2
  reaches the desktop on the actual POCO X2 / Redmi K30 4G (`phoenix`, SM7150-AB).
- UEFI storage initialization works with surya stock UFS (chip updater
  disabled), phoenix stock HALIOMMU and phoenix DALSys UFS CCA=1, retaining
  the June SEC SMMU detach. UEFI previously loaded an installed Linux kernel
  and initramfs from UFS end to end.
- Windows uses inbox `storufs`, BasicDisplay and the audited minimal driver
  set. Side buttons report input, but power-button behavior is unsafe.
- The owner chose Windows-only storage; Linux userdata is no longer installed.
  A private off-device backup and RAM Linux rescue image remain available.
- Latest rescue checks still report Samsung UFS firmware revision 1000 on all
  six sd* LUN device revision files. This is not proof of zero disk writes.

## Experiment chronology and limits

| Configuration | Result | Interpretation |
| --- | --- | --- |
| v1, minimal audited drivers | Desktop; power-button display-off then wake crashes | Storage/framebuffer can work; power transitions do not |
| Original v2: adds UCSI, XHCI filter, URS extension, offline SSH/RDP and attempted power policy | `SOC_CRITICAL_DEVICE_REMOVED (0x14E)` before desktop; photo parameters `0x71706530 / 0x15 / 0 / 0` | Matches PEP's bugcheck reporting signature; underlying failing device not uniquely identified |
| Original v2, cable disconnected | Still failed, owner report | Weakens cable-trigger-only explanation; fresh parameters unavailable |
| v2 with only `qcusbcucsi` service Start DWORD 3 → 4 | Desktop, owner report; new registry/logs/dump recovered | UCSI or its interactions implicated in early failure; not a complete USB solution |
| Same control: power button turns display off, second press | Dump `0xA0`, parameters `0x605 / 0x27 / plugin pointer / 0` | Mandatory PEP notification rejected; root fix unresolved |

Before/after PC SYSTEM hive comparison included every key, value type and raw
value: the UCSI control changed exactly that one registry value. Attaching the
VHDX on Windows also changed filesystem metadata. WIN alone was reflashed;
ESP, GPT, boot and firmware partitions were not reflashed for the control.
All 20 fastboot writes returned OKAY, not full-device readback verification.

## Blocker 1 — USB host, dock Ethernet and remote debugging

Observed:

- Dock keyboard/mouse do not work (owner test); no successful phone network
  connection yet. Ethernet adapter identity/ARM64 driver compatibility are
  not established.
- Latest SYSTEM has `qcusbcucsi Start=4`, staged `QcXhciFilter Start=3` and
  `UrsSynopsys Start=3`. No `Enum/URS` or ACPI QCOM1497 controller was found.
- Borrowed DSDT `URS0` has HID `QCOM1497`, compatible IDs `PNP0CA1` and
  `QCOMFFE1`, and `_DEP = {PEP0, UCS0}`. UCS0 has HID `QCOM14A9` and depends
  on PEP0. This is a concrete dependency blocker with UCSI disabled.
- The BSP's URS extension sets `RoleSwitchMode=3`; the Windows ISO's inbox
  `qcursext.inf` sets 1. These facts alone do not prove which extension wins
  on this phone. The controller is absent, so no effective per-device role
  setting was captured.
- The [Moorea BSP](https://github.com/Project-Aloha/windows_silicon_qcom_moorea)
  explicitly lists Type-C role detection as non-functional.

Questions for the reviewer:

1. Can URS0 safely operate in static host mode with its UCS0 dependency removed,
   while retaining PEP, correct PHY resources and the XHCI filter? Which exact
   ACPI/registry changes and rollback should be used?
2. Are the existing USB PEP actions safe for phoenix's actual PMIC/GPIO wiring
   (see [acpi-audit.md](acpi-audit.md))? DT-unused is not proof of unconnected.
3. Does the PEP require a registered UCS0 even when URS is static host? Would
   removing the dependency expose another PEP failure?
4. What is the smallest diagnostic capture that distinguishes dependency
   gating, wrong role, failed PHY/power initialization and missing dock-NIC
   driver? Do not equate a loaded USBXHCI binary with a functioning controller.

Microsoft's [dual-role architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-dual-role-driver-stack-architecture)
explains the host/function child stacks. A different device's
[static-host recipe](https://github.com/WaLoVayu/POCOX3Pro-Windows-Guides/blob/main/en/status.md)
is a reference, not hardware validation for phoenix.

## Blocker 2 — power-button wake crash

The latest 897404-byte small dump has `PAGEDU64` header, bugcheck `0xA0` and
parameters `0x605 / 0x27 / plugin pointer / 0`. Microsoft's
[0xA0 reference](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0xa0--internal-power-error)
defines 0x605 as PEP rejecting a mandatory device power-management notification.
Its [DPM notification table](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/dpm-notifications)
maps 0x27 to `PEP_DPM_QUERY_SOC_SUBSYSTEM_BLOCKING_TIME`.

Concrete earlier configuration error:

```text
Attempted: PowerSettings/<button GUID>/DefaultPowerSchemeValues/{scheme GUID}
Existing:  PowerSettings/<button GUID>/DefaultPowerSchemeValues/scheme GUID
```

The operational v2 script created brace-wrapped keys with AC/DC=0. Existing
unbraced power-button keys retained AC/DC=3, sleep-button keys retained 1.
Active Balanced `User/PowerSchemes` had no explicit button-action override.
The private operational script is not the public
`windows/Set-PhoenixOfflineSettings.cmd`; do not conflate the two.

`CsEnabled=0` exists, but actual supported power states were never captured
with `powercfg /a`. It is **not** evidence that modern standby is disabled.
Correcting policy might avoid the trigger; it does not repair the PEP contract
or demonstrate safe sleep/resume.

Review requests:

- Analyze the actual dump/stack and PEP notification handling. Is this a BSP
  compatibility gap with the current Windows build, missing prerequisite
  configuration, or a different PEP instance?
- Recommend an effective no-suspend/display-stays-on diagnostic policy and
  verification commands, distinct from a real wake fix.
- Do not bypass KeBugCheckEx, disable the storage-dependent PEP blindly, or
  force S3 on hardware without demonstrated support.

## Blocker 3 — touchscreen

Touch has no driver installed. Surya's ACPI touch uses SPI `0x880000` and PEP
pinmux GPIO 49–52; phoenix uses SPI `0x890000`, GPIO 53–56, reset/IRQ GPIO 8/9.
Surya pinmux would interfere with phoenix's speaker-amp I2S pins.

The supplied surya `nt36xxx.inf` names and installs
`j20s_novatek_ts_fw01.bin` and `j20s_novatek_ts_fw02.bin`. Phoenix stock overlay
instead specifies `novatek_nt36672c_g7b_fw01.bin` / `fw02.bin`, 5 MHz SPI,
software-reset address `0x3f0fe` and fast-read address `0x3f310`. It also has
panel-dependent variants and a PMIC TDDI reset resource.

Review the driver source/binary firmware-upload behavior, chip/panel matching,
SPI engine/IRQ/DMA/SMMU dependencies, reset sequencing and PEP actions. Merely
changing the bus address and installing the existing surya INF is not an
audited phoenix touch fix. Identify a safe phoenix-firmware package and
necessary signing/catalog changes before hardware testing.

## Blocker 4 — portrait framebuffer

BasicDisplay exposes a 1080×2400 UEFI framebuffer. No supported rotation test
has run. Earlier handoff wording assumed live BasicDisplay rotation would
work; it remains a hypothesis. Do not just swap registry width/height values
or falsify GOP geometry/stride: that can corrupt rendering or black-screen.
Use supported display-mode enumeration/test APIs and reversible changes once
remote access works. Surya's GPU/panel configuration is unsafe to transplant
unchanged (DSC, rail, GPIO and unknown GPU-bin differences).

## SSH and security

ARM64 OpenSSH is staged; SYSTEM has automatic `sshd Start=2` and the Windows
volume has an sshd PID file. No live service status, listener, key-auth login
or networking has been verified. Keys, credentials and IPs remain private.
Original v2 also disables the firewall and enables weak development RDP
settings: use an isolated network only. A usable image should instead expose
only required services, require authentication and restore firewall policy.

## Evidence and reproducibility limits

- Latest SYSTEM SHA-256:
  `4511cb36a8403a0af000cb78d5ebd979dfe61ef12cdbd4e2439d00f74f0abfcf`.
- Owner can provide the private latest dump, SYSTEM hive, `ntbtlog.txt`,
  `setupapi.dev.log`, flash logs and media. Raw hives/dumps may contain private
  data and are deliberately not published.
- Latest read-only collection found a pagefile and a small dump, unlike the
  early v2 failure. Missing files in that earlier boot did not prove no writes.
- Source pins and the initial builder are public; v2's SSH/power/USB additions
  and one-service control were operational scripts outside this repo. The
  current public build does **not** fully reproduce that deployed control.
  Reviewer must request sanitized recipes or inspect private artifacts with
  owner permission before asserting reproducibility.
- `ntfscp` refused an unclean-volume edit; no journal clearing or safety bypass
  was used. Offline changes currently may need a PC-built WIN replacement,
  losing new Windows data. NTFS3 cannot mount this image's `$Secure` with the
  current rescue kernel; userspace NTFS tools support read-only inspection.
- The two successful UFS configurations changed several components together.
  They strongly support the SMMU-mapping explanation but do not isolate detach
  as the only cause. Missing `CPU Vectors` did not prevent a full exception dump;
  that earlier hypothesis is not an active blocker.

## Proposed next test — NOT implemented or deployed

Keep UCSI disabled, correct effective power policy, and investigate a minimal
static USB-host ACPI/role configuration. Preserve touch/display as controls.
Audit electrical prerequisites first; validate the final UEFI FFU gate, image
hashes and exact changed modules. Use the existing working image as rollback.
Owner requested independent review before more work; no claim these proposals
are proven fixes.

Please return: (1) corrected causal analysis with exact source references,
(2) minimal patch/recipe per blocker, (3) safety and rollback requirements,
(4) validation commands and expected outputs, and (5) remaining uncertainty.
