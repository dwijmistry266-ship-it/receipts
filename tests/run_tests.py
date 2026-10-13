#!/usr/bin/env python3
"""Stdlib test runner for receipts (used when pytest isn't installed).

Discovers tests/test_*.py, runs every test_* function, and reports.
Handles SystemExit raised by argparse (e.g. --version) correctly.
Exit code: 0 if all pass, 1 otherwise.
"""

import glob
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


def main() -> int:
    import time

    start = time.time()
    total = passed = 0
    failed = []
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        mod_name = os.path.basename(path)[:-3]
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(mod, name)()
            except SystemExit as e:
                # argparse-driven exits: only code 0 counts as pass and
                # only when the test itself expected it.
                failed.append((mod_name, name, "SystemExit(%r)" % (e.code,)))
            except BaseException:
                failed.append((mod_name, name, traceback.format_exc()))
            else:
                passed += 1
    elapsed = time.time() - start
    print("%d/%d tests passed" % (passed, total))
    # pytest-style summary line so receipts can verify the count.
    if failed:
        print("%d passed, %d failed in %.2fs" % (passed, len(failed), elapsed))
    else:
        print("%d passed in %.2fs" % (passed, elapsed))
    for mod_name, name, tb in failed:
        print("\nFAIL %s.%s\n%s" % (mod_name, name, tb[-1500:]))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
