#!/bin/bash
# Build the phoenix Windows UEFI.
#
# Mu-Silicium at a pinned commit plus the patches in uefi/patches/, built in
# Docker the way upstream CI builds (ubuntu 24.04, amd64, setup_env.sh -p apt);
# macOS is not a supported build host. The result is repacked for the stock
# Xiaomi ABL (tools/abl-bootimg.py uefi) and must pass the FFU gate
# (tools/ffucheck.py) before it is ever booted.
#
#   uefi/build.sh UBOOT_IMG [OUT_DIR]
#
# UBOOT_IMG is the sm7150-mainline U-Boot boot image for davinci
# (u-boot-sm7150-xiaomi-davinci-samsung.img, as postmarketOS flashes to `boot`).
# Only its device tree is used: ABL picks a DTB by qcom,msm-id/board-id, and
# the davinci one (0x16d / 0x28) is the only one known to make this ABL hand
# off to the UEFI. The image itself is not modified.
#
# Environment:
#   MU_SILICIUM_COMMIT  default d19ae66c49fa47e47fd56a28e0e4db58b3638968 (2026-09-25)
#   TARGET              DEBUG (default; prints its log on screen) or RELEASE
#   FORCE_MENU=1        also build a variant that always opens the boot menu
#   MU_SILICIUM_VOLUME  Docker volume holding the source tree (default mu-silicium-src)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
uboot=${1:?usage: $0 UBOOT_IMG [OUT_DIR]}
out=${2:-$repo/out}
pin=${MU_SILICIUM_COMMIT:-d19ae66c49fa47e47fd56a28e0e4db58b3638968}
target=${TARGET:-DEBUG}
menu=${FORCE_MENU:-0}
volume=${MU_SILICIUM_VOLUME:-mu-silicium-src}

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon is not running" >&2; exit 1; }
[ -r "$uboot" ] || { echo "cannot read $uboot" >&2; exit 1; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
docker volume create "$volume" >/dev/null

inner=$(mktemp)
trap 'rm -f "$inner"' EXIT
cat > "$inner" <<EOF
#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq sudo git ca-certificates python3 >/dev/null
git config --global advice.detachedHead false
git config --global --add safe.directory '*'
R=/work/Mu-Silicium
[ -d \$R/.git ] || git clone --quiet https://github.com/Project-Silicium/Mu-Silicium.git \$R
cd \$R
git fetch --quiet origin
git checkout --quiet --detach "$pin"
git submodule sync --recursive --quiet
git submodule update --init --recursive --jobs 8 >/dev/null
restore() {
  git -C \$R checkout -- Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/KeyCallback.c \
    Platforms/Xiaomi/phoenixPkg/phoenix.dsc Platforms/Xiaomi/phoenixPkg/phoenix.fdf
  rm -rf \$R/Silicium-ACPI/Platforms/Xiaomi/phoenix
  git -C \$R/Binaries checkout -- phoenix/QcomPkg/Drivers/DALSYSDxe/DALSYSDxe.inf \
    phoenix/QcomPkg/Drivers/UFSDxe/UFSDxe.inf phoenix/QcomPkg/Drivers/HALIOMMUDxe/HALIOMMUDxe.inf
  rm -f \$R/Binaries/phoenix/QcomPkg/Drivers/DALSYSDxe/DALSYSDxe.phxcca.efi \
    \$R/Binaries/phoenix/QcomPkg/Drivers/UFSDxe/UFSDxe.surya-stock.efi \
    \$R/Binaries/phoenix/QcomPkg/Drivers/UFSDxe/*.noffu.efi
}
restore
trap 'restore; echo "source tree restored"' EXIT
for p in /patches/01-*.py /patches/02-*.py /patches/03-*.py /patches/04-*.py; do python3 "\$p"; done
bash ./setup_env.sh -p apt > /out/setup.log 2>&1
{ echo "superproject \$(git rev-parse HEAD)"; git submodule status --recursive; } > /out/provenance.txt
build() {
  python3 build_uefi.py -d phoenix -m 1 -r "$target" 2>&1 | tail -8 | tee "/out/build-\$1.log"
  img=\$(ls -1 Mu-phoenix*.img | head -1)
  mv "\$img" "/out/Mu-phoenix-1-$target-\$1.raw.img"
}
build windows
if [ "$menu" = 1 ]; then python3 /patches/optional-force-boot-menu.py; build windows-menu; fi
EOF

docker run --rm --platform linux/amd64 -v "$volume":/work -v "$out":/out \
	-v "$here/patches":/patches:ro -v "$inner":/build.sh:ro ubuntu:24.04 bash /build.sh

python3 "$repo/tools/abl-bootimg.py" extract-dtb "$uboot" -o "$out/abl-select.dtb"
ids=$(python3 "$repo/tools/abl-bootimg.py" dt-ids "$out/abl-select.dtb" | tr '\n' ' ')
case "$ids" in
*"qcom,msm-id 0x16d 0x0"*"qcom,board-id 0x28 0x0"*) ;;
*) echo "unexpected DTB ids in $uboot: $ids" >&2; exit 1 ;;
esac
status=0
for raw in "$out"/Mu-phoenix-1-"$target"-*.raw.img; do
	abl=${raw%.raw.img}.img
	python3 "$repo/tools/abl-bootimg.py" uefi "$raw" "$out/abl-select.dtb" -o "$abl"
	python3 "$repo/tools/ffucheck.py" "$abl" || status=1
done
cd "$out" && shasum -a 256 Mu-phoenix-1-"$target"-*.img | grep -v raw.img | tee SHA256SUMS
exit $status
