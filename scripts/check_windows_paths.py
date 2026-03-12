#!/usr/bin/env python3
"""Check if file paths are compatible with Windows.

Usage:
    git ls-files | head -20 | python scripts/check_windows_paths.py
    python scripts/check_windows_paths.py path1 path2 ...
"""

import argparse
import re
import sys

INVALID_CHARS_RE = re.compile(r'[<>:\"\\|?*]')
CONTROL_CHARS_RE = re.compile(r'[\x01-\x1f]')
RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})
MAX_PATH_LENGTH = 240  # 260 minus 20-char buffer


def validate_path(path):
    """Return a list of (check_name, detail) issues for a single path."""
    issues = []
    components = path.split("/")

    for component in components:
        if not component:
            continue

        # Check for invalid characters
        match = INVALID_CHARS_RE.search(component)
        if match:
            issues.append((
                "invalid-char",
                f"Component '{component}' contains invalid character '{match.group()}'",
            ))

        # Check for control characters
        if CONTROL_CHARS_RE.search(component):
            issues.append((
                "control-char",
                f"Component '{component}' contains ASCII control character",
            ))

        # Check for NUL byte
        if "\x00" in component:
            issues.append((
                "nul-byte",
                f"Component '{component}' contains NUL byte",
            ))

        # Check for reserved device names (stem before first dot)
        stem = component.split(".")[0]
        if stem.upper() in RESERVED_NAMES:
            issues.append((
                "reserved-name",
                f"Component '{component}' uses reserved Windows device name '{stem.upper()}'",
            ))

        # Check for trailing space or period
        if component[-1] in (" ", "."):
            issues.append((
                "trailing-space-or-period",
                f"Component '{component}' ends with '{component[-1]}'",
            ))

        # Check for bare . or ..
        if component in (".", ".."):
            issues.append((
                "dot-component",
                f"Component '{component}' is a special directory name",
            ))

    # Check path length
    if len(path) > MAX_PATH_LENGTH:
        issues.append((
            "path-too-long",
            f"Path length {len(path)} exceeds {MAX_PATH_LENGTH} character limit",
        ))

    return issues


def find_case_collisions(paths):
    """Return a list of (path, check_name, detail) for case-insensitive collisions."""
    seen = {}
    collisions = []
    for path in paths:
        lower = path.lower()
        if lower in seen:
            if seen[lower] != path:
                collisions.append((
                    path,
                    "case-collision",
                    f"Collides (case-insensitive) with: {seen[lower]}",
                ))
        else:
            seen[lower] = path
    return collisions


def main():
    use_color = sys.stdout.isatty()
    red = "\033[0;31m" if use_color else ""
    green = "\033[0;32m" if use_color else ""
    bold = "\033[1m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    parser = argparse.ArgumentParser(
        description="Check file paths for Windows compatibility issues.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to check. If omitted, reads from stdin.",
    )
    args = parser.parse_args()

    if args.paths:
        paths = args.paths
    elif not sys.stdin.isatty():
        paths = [line.rstrip("\n") for line in sys.stdin if line.strip()]
    else:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if not paths:
        print("No paths provided.", file=sys.stderr)
        sys.exit(2)

    issue_count = 0
    files_with_issues = set()

    # Per-path checks
    for path in paths:
        issues = validate_path(path)
        if issues:
            files_with_issues.add(path)
            for check_name, detail in issues:
                issue_count += 1
                print(f"{red}FAIL{reset} [{check_name}] {path}")
                print(f"      {detail}")

    # Batch check: case collisions
    for path, check_name, detail in find_case_collisions(paths):
        issue_count += 1
        files_with_issues.add(path)
        print(f"{red}FAIL{reset} [{check_name}] {path}")
        print(f"      {detail}")

    # Summary
    print()
    if issue_count == 0:
        print(f"{green}No Windows path compatibility issues found.{reset}")
        print(f"Checked {len(paths)} paths.")
    else:
        print(
            f"{red}{bold}Found {issue_count} issue(s) "
            f"across {len(files_with_issues)} file(s).{reset}"
        )
        print(f"Checked {len(paths)} paths total.")
        sys.exit(1)


if __name__ == "__main__":
    main()
