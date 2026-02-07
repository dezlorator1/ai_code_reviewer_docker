#!/usr/bin/env python3
"""
Merge multiple diff files from different projects into one.
Adds project prefix to file paths to avoid conflicts.
"""

import argparse
import re
import logging
from pathlib import Path
from datetime import datetime
import yaml

# === Load config ===
config_path = Path(__file__).parent / "config.yml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# === Paths ===
DIFF_DIR = Path(config['paths']['DIFF_DIR'])
LOG_FILE = Path(config['paths']['LOG_FILE'])

# Константное имя для объединенного diff
MERGED_DIFF_NAME = "merged.diff"

# === Logging ===
SCRIPT_NAME = Path(__file__).name
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(SCRIPT_NAME)


def add_project_prefix(diff_text, project_name):
    """Add project name prefix to all file paths in diff."""

    log.info(f"Adding prefix '{project_name}' to diff paths")

    # Pattern: diff --git a/path/file b/path/file
    def replace_path(match):
        original_path = match.group(1)
        return f"diff --git a/{project_name}/{original_path} b/{project_name}/{original_path}"

    # Replace paths in diff headers
    result = re.sub(
        r'diff --git a/(.*?) b/\1',
        replace_path,
        diff_text
    )

    # Also update +++ and --- lines
    result = re.sub(r'^--- a/(.+)$', rf'--- a/{project_name}/\1', result, flags=re.MULTILINE)
    result = re.sub(r'^\+\+\+ b/(.+)$', rf'+++ b/{project_name}/\1', result, flags=re.MULTILINE)

    return result


def merge_diffs(diff_files, project_names):
    """Merge multiple diffs with project prefixes."""

    log.info(f"Merging {len(diff_files)} diff files")

    merged = []
    total_size = 0

    for diff_file, project_name in zip(diff_files, project_names):
        diff_path = Path(diff_file)

        if not diff_path.exists():
            log.error(f"Diff file not found: {diff_file}")
            raise FileNotFoundError(f"Diff file not found: {diff_file}")

        diff_text = diff_path.read_text(errors='ignore')
        size = len(diff_text)
        total_size += size

        log.info(f"Loaded {project_name}: {diff_file} ({size} bytes)")

        # Add separator comment
        merged.append(f"\n### PROJECT: {project_name} ###\n")

        # Add prefixed diff
        prefixed = add_project_prefix(diff_text, project_name)
        merged.append(prefixed)

    result = "\n".join(merged)
    log.info(f"Merged total size: {total_size} bytes → {len(result)} bytes (with prefixes)")

    return result


def main():
    parser = argparse.ArgumentParser(description="Merge multiple diff files into one")
    parser.add_argument("--diffs", nargs='+', required=True, help="Diff files to merge")
    parser.add_argument("--names", nargs='+', required=True, help="Project names (same order as diffs)")

    args = parser.parse_args()

    log.info("MERGE_DIFFS START")
    log.info(f"Input diffs: {args.diffs}")
    log.info(f"Project names: {args.names}")

    # Validate
    if len(args.diffs) != len(args.names):
        log.error(f"Mismatch: {len(args.diffs)} diffs vs {len(args.names)} names")
        print("ERROR: Number of diffs must match number of project names")
        return 1

    # Merge
    try:
        merged = merge_diffs(args.diffs, args.names)

        # Save to configured location with constant name
        DIFF_DIR.mkdir(parents=True, exist_ok=True)
        output_path = DIFF_DIR / MERGED_DIFF_NAME
        output_path.write_text(merged)

        log.info(f"MERGE_DIFFS SUCCESS: written to {output_path}")

        # Print summary
        print(f"\n{'='*60}")
        print(f"✅ Merged {len(args.diffs)} diff files")
        print(f"Projects: {', '.join(args.names)}")
        print(f"Output: {output_path}")
        print(f"Size: {len(merged)} bytes")
        print(f"{'='*60}\n")

    except Exception as e:
        log.error(f"MERGE_DIFFS FAILED: {e}")
        raise

    log.info("MERGE_DIFFS END")
    return 0


if __name__ == "__main__":
    exit(main())