# Enable ACPI for phoenix, starting from surya's DSDT unchanged plus the shared
# SM7150 (Moorea) tables. Creates Silicium-ACPI/Platforms/Xiaomi/phoenix and
# uncomments phoenix's ACPI lines in phoenix.dsc / phoenix.fdf.
import shutil
from pathlib import Path
src = Path("Silicium-ACPI/Platforms/Xiaomi/surya")
dst = Path("Silicium-ACPI/Platforms/Xiaomi/phoenix")
assert not dst.exists()
dst.mkdir()
shutil.copy(src / "DSDT.aml", dst / "DSDT.aml")
shutil.copy(src / "AcpiTables.inf", dst / "AcpiTables.inf")
dsc = Path("Platforms/Xiaomi/phoenixPkg/phoenix.dsc"); s = dsc.read_text()
assert s.count("  #phoenix/AcpiTables.inf\n") == 1
dsc.write_text(s.replace("  #phoenix/AcpiTables.inf\n", "  phoenix/AcpiTables.inf\n"))
fdf = Path("Platforms/Xiaomi/phoenixPkg/phoenix.fdf"); t = fdf.read_text()
for line in ["INF MdeModulePkg/Universal/Acpi/AcpiTableDxe/AcpiTableDxe.inf",
             "INF MdeModulePkg/Universal/Acpi/AcpiPlatformDxe/AcpiPlatformDxe.inf",
             "INF RuleOverride = ACPITABLE phoenix/AcpiTables.inf"]:
    assert t.count("  #" + line + "\n") == 1, line
    t = t.replace("  #" + line + "\n", "  " + line + "\n")
fdf.write_text(t)
print("04 applied: phoenix uses surya DSDT + Moorea tables")
