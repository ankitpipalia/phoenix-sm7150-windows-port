#!/bin/sh
# Runs ON THE PHONE as root, under Linux: captures hardware state that only the running
# Linux can report (live DT, pin/GPIO/regulator/clock state, boot log), for
# comparing against the borrowed surya ACPI tables once Linux is gone.
#   ssh phone 'sudo sh capture-hw-state.sh' > hw-state.tar
# The output contains serial numbers: keep it private.
set -u
cd "$(mktemp -d /run/hwstate.XXXXXX)" || exit 1
cp /sys/firmware/fdt phoenix-live.dtb
dmesg > dmesg.txt
cat /proc/cmdline > cmdline.txt
cat /proc/interrupts > interrupts.txt
cat /proc/iomem > iomem.txt
cat /proc/cpuinfo > cpuinfo.txt
lsmod > lsmod.txt 2>&1
mount -t debugfs none /sys/kernel/debug 2>/dev/null
D=/sys/kernel/debug
cat $D/gpio > gpio.txt 2>&1
for f in $D/pinctrl/*/pinmux-pins $D/pinctrl/*/pinconf-pins $D/pinctrl/*/pins; do
	[ -r "$f" ] && { echo "== $f"; cat "$f"; }
done > pinctrl.txt 2>&1
cat $D/regulator/regulator_summary > regulators.txt 2>&1
cat $D/clk/clk_summary > clocks.txt 2>&1
cat $D/interconnect/interconnect_summary > interconnect.txt 2>&1
cat $D/iommu/arm-smmu*/* > /dev/null 2>&1
for d in /sys/bus/platform/devices/*; do
	printf '%s\t%s\t%s\n' "${d##*/}" "$(cat $d/of_node/compatible 2>/dev/null | tr '\0' ' ')" "$(basename "$(readlink $d/driver)" 2>/dev/null)"
done > platform-devices.tsv
for d in /sys/bus/i2c/devices/* /sys/bus/spi/devices/*; do
	printf '%s\t%s\t%s\n' "${d##*/}" "$(cat $d/name 2>/dev/null || cat $d/modalias 2>/dev/null)" "$(basename "$(readlink $d/driver)" 2>/dev/null)"
done > i2c-spi-devices.tsv
for p in /sys/class/power_supply/*; do echo "== $p"; cat $p/uevent; done > power-supply.txt 2>&1
for t in /sys/class/thermal/thermal_zone*; do printf '%s %s %s\n' "${t##*/}" "$(cat $t/type)" "$(cat $t/temp 2>/dev/null)"; done > thermal.txt
cat /sys/firmware/devicetree/base/model > model.txt 2>/dev/null
tar -cf - .
