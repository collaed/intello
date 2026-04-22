#!/usr/bin/env python3
"""Run all test suites: whitebox, greybox, blackbox, additional."""
import subprocess, sys, os

os.chdir(os.path.dirname(os.path.dirname(__file__)))

suites = [
    ("⬜ WHITE-BOX (unit tests)", "tests/test_all.py"),
    ("⬜ WHITE-BOX ADDITIONAL", "tests/test_additional.py"),
    ("🔲 GREY-BOX (integration tests)", "tests/test_greybox.py"),
    ("⬛ BLACK-BOX (HTTP API tests)", "tests/test_blackbox.py"),
]

total_pass = total_fail = 0
for name, path in suites:
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}\n")
    r = subprocess.run([sys.executable, path], capture_output=False)
    if r.returncode == 0:
        total_pass += 1
    else:
        total_fail += 1

print(f"\n{'='*50}")
print(f"  FINAL: {total_pass} suites passed, {total_fail} failed")
print(f"{'='*50}")
sys.exit(1 if total_fail else 0)
