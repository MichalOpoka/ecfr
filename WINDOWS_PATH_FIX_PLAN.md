# Plan: Fix All Windows-Incompatible Paths

## Problem

The repo has many Windows-incompatible paths:
- **~5,120** paths contain invalid characters (newlines in directory names)
- **~167,814** paths exceed the 240-character length limit

Root cause: directory names include long descriptive suffixes (e.g., `chapter-II-Office-Assistant-Secretary-Housing-Federal-Housing-Commissioner-Department-Housing-Urban-Development`) and some contain newlines from data conversion issues.

## Solution

`scripts/fix_windows_paths.py` strips descriptive suffixes from directory names, keeping only the type prefix and identifier. This fixes both issues simultaneously — invalid characters are always in the description portion, and shortened names dramatically reduce path lengths.

Examples:
- `title-24-Housing-Urban-Development` → `title-24`
- `chapter-II-Office-Assistant-Secretary-Housing-Federal-Housing-Commissioner-Department-Housing-Urban-Development` → `chapter-II`
- `subpart-C-Eligibility-Requirements-Supplemental-Loans-To-Finance-...` → `subpart-C`
- `subjectgroup-ECFR9a8a9bd30592f04-Eligible-Security-Instruments` → `subjectgroup-ECFR9a8a9bd30592f04`
- `part-241-Supplementary-Financing-Insured-Project-Mortgages` → `part-241`

HTML entities in names (`&apos;`, `&mdash;`, `&#160;`) are also decoded and normalized.

## Scope

- **51,705 directories** to rename under `cfr/`
- **0 files** need renaming (section files already have short names)
- **0 file content changes** needed (all cross-references are text-based legal citations, not file path links)

## Known Collision

There is **1 collision**: `cfr/title-02-Federal-Financial-Assistance` and `cfr/title-02-Grants-Agreements` both shorten to `title-02`.

**Resolution**: Keep the full names for these two directories only — they will be skipped during rename and retain their current names. Their child directories will still be shortened as normal.

## Steps

### 1. Verify dry-run output

```bash
python scripts/fix_windows_paths.py --all
```

Review the output to confirm renames look correct. Check for any collision warnings.

### 2. Apply renames

```bash
python scripts/fix_windows_paths.py --all --apply --max-workers 4
```

This uses `os.rename` for each rename (parallelized up to `--max-workers`), then stages all changes with `git add -A`. Runs top-down (parents first), which means renaming a parent directory automatically moves all its children.

### 3. Verify no remaining issues

```bash
python scripts/count_windows_path_issues.py
```

Expected output: `invalid-char` and `path-too-long` counts should be 0 (or significantly reduced).

### 4. Spot-check paths

```bash
# Verify a previously problematic path is now short
ls cfr/title-24/subtitle-B/chapter-II/

# Verify the longest paths are now within limits
git ls-files | awk '{ print length, $0 }' | sort -rn | head -5
```

### 5. Commit

```bash
git add -A
git commit -m "Shorten directory names for Windows compatibility

Rename ~52,000 directories by stripping descriptive suffixes from names,
keeping only the type prefix and identifier (e.g., chapter-II-Office-Assistant-...
becomes chapter-II). This resolves invalid-character issues (newlines) and
path-too-long issues."
```

## Risks and Rollback

- **Rollback**: `git reset --hard HEAD~1` reverts everything since all renames are tracked by git
- **No content changes**: file contents are untouched, only directory names change
- **Collision detection**: dry-run checks for collisions before applying — aborts if any are found
- **Concurrency control**: `--max-workers` limits parallel subprocess execution (default: 4)
