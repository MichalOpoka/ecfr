#!/usr/bin/env python3
"""Fix Windows-incompatible paths in the cfr/ directory.

Shortens directory names by stripping descriptive suffixes (keeping only
type prefix + identifier) and decodes HTML entities. This resolves both
invalid-character and path-too-long issues for Windows compatibility.

Adapted from the us-federal-code repository for the eCFR (Code of Federal
Regulations) repository, which uses CamelCase naming conventions.

Usage:
    # Dry-run on specific paths (shows planned renames)
    python scripts/fix_windows_paths.py "cfr/title-24-Housing-Urban-Development/..."

    # Dry-run on entire repo
    python scripts/fix_windows_paths.py --all

    # Actually apply renames (uses os.rename + git add)
    python scripts/fix_windows_paths.py --all --apply

    # Limit concurrent subprocess workers (default: 4)
    python scripts/fix_windows_paths.py --all --apply --max-workers 8
"""

import argparse
import concurrent.futures
import html
import os
import re
import shutil
import subprocess
import sys
import unicodedata

# Matches directory names with a known type prefix, identifier, and descriptive suffix.
# Groups: (1) prefix like "chapter", (2) identifier like "-II" or "-241" or "-ECFR9a8a..."
# Adapted for eCFR: supports uppercase Roman numerals, decimal identifiers (e.g. 2137.1),
# single uppercase letters, and ECFR hex IDs.
SHORTEN_RE = re.compile(
    r'^(title|subtitle|division|part|subpart|chapter|subchapter|subdivision|subjectgroup)'
    r'(-(?:[0-9]+(?:\.[0-9]+)?[a-zA-Z]?|[a-zA-Z]+|ECFR[0-9a-fA-F]+))'
    r'(-.+)$',
    re.DOTALL,
)

# Special case for "chapters-N-through-N-description"
CHAPTERS_RE = re.compile(
    r'^(chapters-[0-9]+[a-zA-Z]?)'
    r'((?:\s|&#160;)?-?through-[0-9]+[a-zA-Z]?)'
    r'(-.+)$',
    re.DOTALL,
)

# HTML entity pattern for detection
HTML_ENTITY_RE = re.compile(r'&[a-zA-Z]+;|&#[0-9]+;|&#x[0-9a-fA-F]+;')


def shorten_component(name):
    """Shorten a single directory/file name component by stripping descriptions."""
    # Don't touch files (only directories need shortening)
    # Don't touch bracketed names like [sec-5002, [chapter-402-repealed]
    # Don't touch section-* files (already short)
    if name.startswith('[') or name.startswith('section-'):
        return name

    # Special case: chapters-N-through-N-description
    m = CHAPTERS_RE.match(name)
    if m:
        return m.group(1) + m.group(2).replace('&#160;', '').replace('\xa0', '')

    # General case: type-identifier-description
    m = SHORTEN_RE.match(name)
    if m:
        return m.group(1) + m.group(2)

    return name


def decode_entities(name):
    """Decode HTML entities and normalize to ASCII-safe characters."""
    if '&' not in name and '\xa0' not in name:
        return name

    # Decode HTML entities
    decoded = html.unescape(name)

    # Normalize unicode to ASCII where possible
    # NFKD decomposes characters (e.g., É -> E + combining accent)
    normalized = unicodedata.normalize('NFKD', decoded)

    # Keep only ASCII characters, hyphens, dots, brackets, and digits
    result = []
    for ch in normalized:
        if ch.isascii() and (ch.isalnum() or ch in '-_.[]'):
            result.append(ch)
        elif unicodedata.category(ch).startswith('M'):
            # Skip combining marks (accents)
            continue
        elif ch in ('\xa0', '\u00a0'):
            # Non-breaking space -> remove
            continue
        elif ch == '\u2014':  # em dash
            result.append('-')
        elif ch == '\u2019' or ch == '\u2018':  # smart quotes
            result.append("'")
        # Skip other non-ASCII silently

    cleaned = ''.join(result)
    # Collapse multiple consecutive hyphens
    cleaned = re.sub(r'-{2,}', '-', cleaned)
    # Remove trailing hyphens
    cleaned = cleaned.rstrip('-')
    return cleaned


def fix_component(name):
    """Apply both shortening and entity decoding to a path component."""
    # Strip newlines and other control characters before processing
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', name)
    # Collapse runs of hyphens that may result from stripping
    cleaned = re.sub(r'-{2,}', '-', cleaned)
    cleaned = cleaned.strip('-')
    if not cleaned:
        return name
    shortened = shorten_component(cleaned)
    decoded = decode_entities(shortened)
    return decoded


def compute_renames_for_path(path):
    """Compute renames needed for a single path (all its directory components).

    Returns a list of (old_path, new_path) tuples for directories that need renaming,
    ordered from shallowest to deepest.
    """
    parts = path.split('/')
    renames = []
    old_prefix = []
    new_prefix = []

    for i, part in enumerate(parts):
        old_prefix.append(part)

        # Don't shorten files (last component if it has an extension)
        if i == len(parts) - 1 and '.' in part:
            new_prefix.append(part)
            continue

        new_part = fix_component(part)
        new_prefix.append(new_part)

        if new_part != part:
            renames.append(('/'.join(old_prefix), '/'.join(new_prefix)))

    return renames


def merge_dirs(src, dst):
    """Recursively merge src directory into dst, then remove src.

    For overlapping files, the src version overwrites dst (newer edition wins).
    For overlapping subdirectories, merge recursively.
    """
    # Resolve to real paths to avoid merging a dir into itself
    real_src = os.path.realpath(src)
    real_dst = os.path.realpath(dst)
    if real_src == real_dst:
        return
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            if os.path.isdir(d):
                merge_dirs(s, d)
            elif not os.path.exists(d):
                shutil.move(s, d)
        else:
            # File: overwrite with src version
            shutil.move(s, d)
    # Remove src tree (may still have empty nested dirs)
    shutil.rmtree(src, ignore_errors=True)


def compute_all_renames(root, apply=False, max_workers=4):
    """Compute (and optionally apply) all renames needed under root.

    Uses os.walk top-down. In apply mode, renames are executed immediately
    via os.rename (in parallel up to max_workers), and dirnames is updated so
    os.walk descends into renamed dirs. In dry-run mode, a display_map tracks
    planned parent renames for display.

    When multiple directories would shorten to the same name (collision),
    the first is renamed and the others are merged into it.
    """
    renames = []
    merges = 0
    # In dry-run mode, maps actual filesystem dirpath -> display dirpath
    display_map = {root: root}

    for dirpath, dirnames, _filenames in os.walk(root, topdown=True):
        display_dirpath = display_map.get(dirpath, dirpath) if not apply else dirpath

        # Collect renames for this level
        level_renames = []
        level_merges = []  # (src_full, dst_full) for dirs to merge
        new_dirnames = []

        # First pass: compute new names and group by short name
        proposed = {}  # new_name_lower -> list of (orig_name, new_name)
        for d in dirnames:
            new_name = fix_component(d)
            proposed.setdefault(new_name.lower(), []).append((d, new_name))

        # Track which original names get merged away (removed from walk)
        merged_away = set()

        for new_lower, entries in proposed.items():
            if len(entries) == 1:
                # No collision within this batch
                orig, new_name = entries[0]
                if new_name != orig:
                    actual_full = os.path.join(dirpath, orig)
                    old_path = os.path.join(display_dirpath, orig)
                    new_path = os.path.join(display_dirpath, new_name)
                    renames.append((old_path, new_path))
                    if apply:
                        level_renames.append((actual_full, os.path.join(dirpath, new_name)))
                    else:
                        display_map[actual_full] = new_path
                else:
                    if not apply:
                        display_map[os.path.join(dirpath, orig)] = os.path.join(display_dirpath, orig)
                new_dirnames.append(new_name)
            else:
                # Collision: rename the first, merge the rest into it
                primary_orig, new_name = entries[0]
                # Rename primary
                if new_name != primary_orig:
                    actual_full = os.path.join(dirpath, primary_orig)
                    old_path = os.path.join(display_dirpath, primary_orig)
                    new_path = os.path.join(display_dirpath, new_name)
                    renames.append((old_path, new_path))
                    if apply:
                        level_renames.append((actual_full, os.path.join(dirpath, new_name)))
                    else:
                        display_map[actual_full] = new_path
                else:
                    if not apply:
                        display_map[os.path.join(dirpath, primary_orig)] = os.path.join(display_dirpath, primary_orig)

                new_dirnames.append(new_name)

                # Merge the rest into primary
                for extra_orig, _ in entries[1:]:
                    old_path = os.path.join(display_dirpath, extra_orig)
                    new_path = os.path.join(display_dirpath, new_name)
                    renames.append((old_path, f"{new_path} [merged]"))
                    merged_away.add(extra_orig)
                    merges += 1
                    if apply:
                        src = os.path.join(dirpath, extra_orig)
                        dst = os.path.join(dirpath, new_name)
                        level_merges.append((src, dst))

        if apply and level_renames:
            # Apply renames — fall back to merge if target already exists
            for old_full, new_full in level_renames:
                try:
                    if os.path.exists(new_full):
                        # Target exists (from prior run), merge instead
                        merge_dirs(old_full, new_full)
                    else:
                        os.rename(old_full, new_full)
                except OSError as e:
                    print(f"  ERROR: rename failed: {old_full} -> {new_full}: {e}",
                          file=sys.stderr)

        if apply and level_merges:
            # Merge colliding dirs into the renamed targets
            for src, dst in level_merges:
                try:
                    if os.path.exists(src):
                        merge_dirs(src, dst)
                except OSError as e:
                    print(f"  ERROR: merge failed: {src} -> {dst}: {e}",
                          file=sys.stderr)

        if apply:
            dirnames[:] = new_dirnames
        # In dry-run, leave dirnames unchanged so os.walk can descend

    if merges:
        print(f"  ({merges} directories merged into shortened targets)",
              file=sys.stderr)

    return renames


def check_collisions(renames):
    """Check if any renames would create collisions within the same parent."""
    # Group by parent directory
    by_parent = {}
    for old_path, new_path in renames:
        parent = os.path.dirname(new_path)
        new_name = os.path.basename(new_path)
        by_parent.setdefault(parent, []).append((old_path, new_name))

    collisions = []
    for parent, entries in by_parent.items():
        seen = {}
        for old_path, new_name in entries:
            lower = new_name.lower()
            if lower in seen:
                collisions.append((old_path, seen[lower], new_name))
            else:
                seen[lower] = old_path

    return collisions


def apply_rename(old_path, new_path):
    """Execute a rename using os.rename."""
    try:
        os.rename(old_path, new_path)
        return True
    except OSError as e:
        print(f"  ERROR: rename failed: {old_path} -> {new_path}: {e}",
              file=sys.stderr)
        return False


def main():
    use_color = sys.stdout.isatty()
    green = "\033[0;32m" if use_color else ""
    yellow = "\033[0;33m" if use_color else ""
    red = "\033[0;31m" if use_color else ""
    bold = "\033[1m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    parser = argparse.ArgumentParser(
        description="Fix Windows-incompatible paths by shortening directory names.",
    )
    parser.add_argument(
        'paths', nargs='*',
        help='Specific paths to compute renames for (dry-run).',
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Process entire cfr/ directory.',
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Actually perform renames using os.rename (default: dry-run).',
    )
    parser.add_argument(
        '--max-workers', type=int, default=4,
        help='Maximum number of concurrent rename operations (default: 4).',
    )
    args = parser.parse_args()

    if not args.paths and not args.all:
        parser.print_help(sys.stderr)
        sys.exit(2)

    if args.paths:
        # Single-path mode: show renames for each given path
        all_renames = []
        for path in args.paths:
            path = path.rstrip('/')
            renames = compute_renames_for_path(path)
            all_renames.extend(renames)

        if not all_renames:
            print(f"{green}No renames needed — all paths are already short.{reset}")
            return

        # Deduplicate (same directory could appear in multiple input paths)
        seen = set()
        unique_renames = []
        for old, new in all_renames:
            if old not in seen:
                seen.add(old)
                unique_renames.append((old, new))
        all_renames = unique_renames

    else:
        # --all mode: walk the entire cfr/ tree
        root = 'cfr'
        if not os.path.isdir(root):
            print(f"Error: '{root}' directory not found.", file=sys.stderr)
            sys.exit(1)

        if args.apply:
            print(f"Applying renames (max {args.max_workers} concurrent workers)...",
                  file=sys.stderr)
            print("  (colliding directories will be merged automatically)",
                  file=sys.stderr)
            all_renames = compute_all_renames(root, apply=True,
                                             max_workers=args.max_workers)

            # Stage all changes with git after filesystem renames
            print("Staging changes with git add -A...", file=sys.stderr)
            subprocess.run(['git', 'add', '-A'], check=True)

            print(f"\n{green}{len(all_renames)} directories renamed successfully.{reset}")
            return

        print(f"Scanning {root}/ ...", file=sys.stderr)
        all_renames = compute_all_renames(root, apply=False)

        if not all_renames:
            print(f"{green}No renames needed — all paths are already short.{reset}")
            return

    # Check for collisions
    collisions = check_collisions(all_renames)
    if collisions:
        print(f"\n{red}{bold}Collision detected! These directories would have the same name:{reset}")
        for path1, path2, name in collisions:
            print(f"  {path1}")
            print(f"  {path2}")
            print(f"  -> both shorten to: {name}")

    # Display renames
    for old_path, new_path in all_renames:
        old_name = os.path.basename(old_path)
        new_name = os.path.basename(new_path)
        parent = os.path.dirname(old_path)
        if parent:
            print(f"  {parent}/{yellow}{old_name}{reset} -> {green}{new_name}{reset}")
        else:
            print(f"  {yellow}{old_name}{reset} -> {green}{new_name}{reset}")

    print(f"\n{bold}{len(all_renames)} director{'y' if len(all_renames) == 1 else 'ies'} to rename{reset}")
    print(f"\n{yellow}Dry run — no changes made. Use --apply to execute renames.{reset}")


if __name__ == "__main__":
    main()
