#!/usr/bin/env python3
"""Scan entire repo and print per-issue-type counts.

Usage:
    python scripts/count_windows_path_issues.py
"""
import collections
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_windows_paths import validate_path, find_case_collisions


def main():
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, check=True,
    )
    paths = [line for line in result.stdout.splitlines() if line]

    counts = collections.Counter()

    for path in paths:
        for check_name, _ in validate_path(path):
            counts[check_name] += 1

    for _, check_name, _ in find_case_collisions(paths):
        counts[check_name] += 1

    for issue, count in sorted(counts.items()):
        print(f"{issue} : {count}")


if __name__ == "__main__":
    main()
