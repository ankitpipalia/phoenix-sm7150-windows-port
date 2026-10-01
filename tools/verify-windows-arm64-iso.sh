#!/bin/sh
# Verify a Windows 11 Arm64 ISO against the SHA-256 values Microsoft publishes
# on its official download page, as captured in windows-arm64-iso-sha256.tsv.
#
#   tools/verify-windows-arm64-iso.sh ~/Downloads/Win11_25H2_English_Arm64.iso [Language]
#
# Language defaults to "English 64-bit" (Microsoft's label for English (US) on
# this page; "English International 64-bit" is the other English build).
#
# The table is a snapshot. Microsoft republishes ISOs; if yours is newer than
# the snapshot, compare the printed hash by eye with the table shown under
# "Verify your download" on
# https://www.microsoft.com/en-us/software-download/windows11arm64
# (the script does not scrape that page).
set -eu

iso=${1:?usage: $0 ISO [language-label]}
lang=${2:-"English 64-bit"}
table="$(dirname "$0")/windows-arm64-iso-sha256.tsv"
[ -r "$iso" ] || { echo "cannot read $iso" >&2; exit 2; }
[ -r "$table" ] || { echo "cannot read $table" >&2; exit 2; }

captured=$(grep -o 'captured [0-9-]*' "$table" | head -1)
expected=$(grep -v '^#' "$table" | awk -F '\t' -v l="$lang" '$1 == l {print $2}')
[ -n "$expected" ] || {
	echo "no hash for \"$lang\" in $table; available labels:" >&2
	grep -v '^#' "$table" | cut -f1 | sed 's/^/  /' >&2
	exit 3
}

echo "hashing $(basename "$iso") ($(du -h "$iso" | cut -f1)) ..."
actual=$(shasum -a 256 "$iso" | awk '{print $1}')
echo "published ($lang, $captured): $expected"
echo "actual:                                $actual"
if [ "$actual" = "$expected" ]; then
	echo "OK - matches Microsoft's published SHA-256"
else
	echo "MISMATCH against the $captured snapshot." >&2
	echo "If Microsoft has republished the ISO since, compare with the live table on its download page." >&2
	exit 1
fi
