"""Run the Studio unit suite without a site-packages ``tests`` package shadowing us."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START = ROOT / "tests"
SKIP_DEFAULT = {"test_capacity.py", "test_bench.py"}


def _load(path: Path) -> unittest.TestSuite:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return unittest.defaultTestLoader.loadTestsFromModule(mod)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Karmin Satellite unit tests")
    p.add_argument(
        "--full",
        action="store_true",
        help="also run test_capacity.py and test_bench.py",
    )
    args = p.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "substrate"))

    suite = unittest.TestSuite()
    files = sorted(START.glob("test_*.py"))
    if not args.full:
        files = [f for f in files if f.name not in SKIP_DEFAULT]
    for path in files:
        suite.addTests(_load(path))

    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
