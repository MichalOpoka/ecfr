# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is a read-only data repository containing the **Electronic Code of Federal Regulations (eCFR)** in Markdown format. It is not a software project — there is no build system, test suite, or application code. The primary artifact is the `cfr/` directory tree of ~297,000 Markdown files.

## Directory Structure

All regulatory content lives under `cfr/` with a hierarchical path structure:

```
cfr/
  title-{NN}-{Name}/
    [subtitle-{X}-{Name}/]
      chapter-{X}-{Name}/
        [subchapter-{X}-{Name}/]
          part-{NNN}-{Name}/
            [subpart-{X}-{Name}/]
              [subjectgroup-ECFR{hash}-{Name}/]
                section-{N}.{N}.md
```

Not all levels are present in every title — the hierarchy varies by title. Each `section-*.md` file contains the text of a single CFR section, formatted in Markdown with a `##### § N.N Name #####` header.

## Maintenance Script

**`fix_colon_names.py`** — Run this after any new data release to sanitize directory names:

```bash
python3 fix_colon_names.py          # runs on current directory
python3 fix_colon_names.py /path    # runs on specified repo path
```

It performs two passes using `git mv`:
1. Replaces `:` with `-` in directory names
2. Collapses resulting `--` (from `:-` patterns) to `-`

Run this script whenever new CFR data is committed, before pushing a release.

## Data Conventions

- Directory names use kebab-case with the structural level prefix (`title-`, `chapter-`, `subchapter-`, `subpart-`, `part-`, `section-`, `subjectgroup-`)
- `subjectgroup-` directories use an opaque eCFR hash identifier followed by a human-readable name
- Section files are named `section-{number}.md` where the number matches the CFR §-number (e.g., `section-1.1.md` for § 1.1)
- There are 50 titles (title-01 through title-50) plus some titles with split entries (e.g., title-02 appears twice for different chapters)

## Git Workflow

New data is committed as releases named `release(cfr): YYYY-MM-DD issue`. When updating data:
1. Add/update files under `cfr/`
2. Run `fix_colon_names.py` to sanitize any new directory names
3. Commit with the release naming convention
