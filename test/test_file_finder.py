import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.file_finder import open_file, find_file

MP4_NAME = "2018020116551100_c.mp4"

passed = 0
failed = 0


def ok(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}")


print("=== FASE 6: mp4-bestand zoeken ===")

results = find_file(MP4_NAME)

ok(f"'{MP4_NAME}' wordt gezocht zonder crash", isinstance(results, list))
ok(f"nieuwe opname mp4 gevonden", len(results) >= 1)

with patch("os.startfile") as m:
    result = open_file(MP4_NAME)
    if len(results) == 1:
        ok("open_file opent het gevonden mp4-bestand (gemockt)", m.called)
    else:
        ok("meerdere matches -> nette melding (geen open)", not m.called and "meerdere" in result)

print()
print(f"RESULTAAT: {passed} geslaagd, {failed} gefaald")
sys.exit(1 if failed else 0)