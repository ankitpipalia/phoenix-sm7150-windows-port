# Unpack a Silicium boot image (via fvwalk.py) and count the [PHX] marker strings
# in its PE32/TE modules. Also reports any FV/FFS checksum or structure error.
import sys
from fvwalk import walk
if __name__ == "__main__":
    for p in sys.argv[1:]:
        w = walk(p)
        blob = b"".join(w.modules)  # PE32/TE bodies, each counted once
        print(p.split('/')[-1], "files", len(w.files), "errors", len(w.errors), "[PHX]", blob.count(b"[PHX]"),
              "tick", blob.count(b"[PHX] tick"), "gcdattr", blob.count(b"[PHX] gcdattr"))
        for e in w.errors: print("  ERROR", e)
