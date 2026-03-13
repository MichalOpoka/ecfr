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


def unquote_git_path(line):
    """Decode git's C-style quoted path (e.g. \"path with \\n\" -> actual path)."""
    if line.startswith('"') and line.endswith('"'):
        line = line[1:-1]
        # Decode C-style escapes
        line = line.encode('utf-8').decode('unicode_escape').encode('latin-1').decode('utf-8')
    return line


def main():
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True, check=True,
    )
    paths = [p.decode('utf-8', errors='replace')
             for p in result.stdout.split(b'\x00') if p]

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
