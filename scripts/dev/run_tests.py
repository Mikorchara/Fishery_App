"""Independent management unittest/Node tiers; no Prototype discovery or real requests."""
import argparse
from pathlib import Path
import sys
import shutil
import subprocess
import time
import unittest
import os
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FAST_MODULES = (
    "apps.ai_backend.tests.test_protocol_specs",
    "apps.ai_service.runtime.tests.test_foundation",
    "apps.monitoring.tests.test_water_capture",
)


def build_suite(selection):
    loader = unittest.TestLoader()
    if selection == "fast":
        return loader.loadTestsFromNames(FAST_MODULES)
    groups = ("apps/device_reports/tests", "apps/ai_backend/tests", "apps/ai_service/runtime/tests", "apps/ai_service/tests",
              "apps/monitoring/tests", "apps/simulator/tests", "apps/knowledge/tests", "apps/management_web/tests",
              "apps/qq_bot/tests")
    names = tuple(".".join(path.relative_to(ROOT).with_suffix("").parts)
        for group in groups for path in sorted((ROOT/group).glob("test_*.py")))
    return loader.loadTestsFromNames(names)


def main(argv=None):
    temporary = ROOT / 'outputs/test-tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    tempfile.tempdir = str(temporary)
    parser = argparse.ArgumentParser(description="Offline unittest tiers; no Provider requests")
    parser.add_argument("selection", nargs="?", default="management",
        choices=("fast", "management", "management-independent"))
    parser.add_argument("--list", action="store_true", help="Count discovery without executing tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    suite = build_suite(args.selection)
    count = suite.countTestCases()
    if count == 0:
        parser.error("empty test suite")
    print(f"{args.selection}: {count} unittest cases", flush=True)
    node_files = sorted((ROOT / "apps/management_web/tests").glob("*.test.mjs")) if args.selection in ('management','management-independent') else []
    if node_files:
        print(f"management: {len(node_files)} Node test files (offline)", flush=True)
    if args.list:
        return 0
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    print(f"{args.selection}: {result.testsRun} cases / {time.perf_counter()-started:.3f}s", flush=True)
    node_result = 0
    if node_files:
        node = shutil.which("node")
        if node is None:
            print("management: NODE_REQUIRED", flush=True)
            return 1
        node_result = subprocess.run([node, "--test", *map(str, node_files)], cwd=ROOT).returncode
    return 0 if result.wasSuccessful() and node_result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
