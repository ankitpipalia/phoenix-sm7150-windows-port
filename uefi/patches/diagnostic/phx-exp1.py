# Experiment 1 for the phoenix UEFI hang: UFSDxe does its own DMA cache maintenance.
from pathlib import Path
p = Path("Platforms/Xiaomi/phoenixPkg/Library/ConfigurationMapLib/ConfigurationMapLib.c")
s = p.read_text(); old = '{"EnableUfsIOC", 1},'
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, '{"EnableUfsIOC", 0},'))
print("exp1 applied: EnableUfsIOC = 0")
