#!/usr/bin/env python3
"""
Fix directory names in a Git repository for cross-platform compatibility:
  1. Replace ':' with '-'
  2. Collapse '--' (from ':-' patterns) to single '-'
  3. Truncate names exceeding --max-length chars at a word (hyphen) boundary

Uses `git mv` so all renames are tracked by Git.

Usage:
    python3 fix_colon_names.py [repo_path] [--max-length N]

    repo_path     Path to the git repo (default: current working directory)
    --max-length  Maximum directory name length in chars (default: 100)
                  Use 0 to skip truncation.
"""
import argparse
import os
import subprocess
import sys


def find_dirs_with(pattern, repo):
    matches = []
    for dirpath, dirnames, _ in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for d in dirnames:
            if pattern in d:
                matches.append(os.path.join(dirpath, d))
    # Deepest first so nested renames don't break parent paths
    matches.sort(key=lambda p: p.count(os.sep), reverse=True)
    return matches


def find_dirs_over_length(max_len, repo):
    matches = []
    for dirpath, dirnames, _ in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for d in dirnames:
            if len(d) > max_len:
                matches.append(os.path.join(dirpath, d))
    matches.sort(key=lambda p: p.count(os.sep), reverse=True)
    return matches


def truncate_name(name, max_len):
    """Truncate name to max_len, cutting at the last hyphen boundary."""
    if len(name) <= max_len:
        return name
    cut = name.rfind("-", 0, max_len + 1)
    if cut == -1:
        cut = max_len  # no hyphen found, hard cut
    return name[:cut]


def unique_name(parent, name):
    """Return name, appending -2/-3/... if it already exists in parent."""
    candidate = name
    suffix = 2
    while os.path.exists(os.path.join(parent, candidate)):
        candidate = f"{name}-{suffix}"
        suffix += 1
    return candidate


def git_mv(old, new, repo):
    result = subprocess.run(
        ["git", "mv", old, new],
        capture_output=True, text=True, cwd=repo
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def rename_all(dirs, replace_from, replace_to, repo):
    renamed = errors = 0
    for old_path in dirs:
        parent = os.path.dirname(old_path)
        old_name = os.path.basename(old_path)
        new_name = old_name.replace(replace_from, replace_to)
        if new_name == old_name:
            continue
        new_path = os.path.join(parent, new_name)
        if git_mv(old_path, new_path, repo):
            print(f"  {old_name}\n  -> {new_name}\n")
            renamed += 1
        else:
            errors += 1
    return renamed, errors


def truncate_long_dirs(dirs, max_len, repo):
    renamed = errors = 0
    for old_path in dirs:
        parent = os.path.dirname(old_path)
        old_name = os.path.basename(old_path)
        new_name = truncate_name(old_name, max_len)
        if new_name == old_name:
            continue
        new_name = unique_name(parent, new_name)
        new_path = os.path.join(parent, new_name)
        if git_mv(old_path, new_path, repo):
            print(f"  {old_name}\n  -> {new_name}\n")
            renamed += 1
        else:
            errors += 1
    return renamed, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo", nargs="?", default=os.getcwd(),
                        help="Path to the git repository (default: cwd)")
    parser.add_argument("--max-length", type=int, default=100, metavar="N",
                        help="Max directory name length; 0 to skip (default: 100)")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    print(f"Repo: {repo}\n")

    # Pass 1: replace ':' with '-'
    colon_dirs = find_dirs_with(":", repo)
    print(f"Found {len(colon_dirs)} directories with ':'.\n")
    renamed1, errors1 = rename_all(colon_dirs, ":", "-", repo)

    # Pass 2: collapse '--' to '-' (produced by ':-' patterns)
    double_dirs = find_dirs_with("--", repo)
    print(f"Found {len(double_dirs)} directories with '--'.\n")
    renamed2, errors2 = rename_all(double_dirs, "--", "-", repo)

    # Pass 3: truncate names exceeding max-length
    renamed3 = errors3 = 0
    if args.max_length > 0:
        long_dirs = find_dirs_over_length(args.max_length, repo)
        print(f"Found {len(long_dirs)} directories exceeding {args.max_length} chars.\n")
        renamed3, errors3 = truncate_long_dirs(long_dirs, args.max_length, repo)

    total_errors = errors1 + errors2 + errors3
    print(f"Done: {renamed1} colon renames, {renamed2} double-hyphen fixes, "
          f"{renamed3} length truncations, {total_errors} errors.")
    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
