#!/usr/bin/env python3
"""
Extract global context from git diff for MR review.
Analyzes entire diff and creates context file with:
- All modified files
- Types of changes
- Affected components
- Potential breaking changes
"""

import argparse
import logging
import re
from pathlib import Path
from datetime import datetime
import requests
import yaml


# === Load config ===
config_path = Path(__file__).parent / "config.yml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# === Paths ===
MR_CONTEXT_FILE = Path(config['paths']['OUT_DIR']) / "mr_context.md"
LOG_FILE = Path(config['paths']['LOG_FILE'])

# === LLM Settings ===
API_URL = config['llm']['api_url']
MODEL = config['llm']['model']
MAX_TOKENS = config['llm']['max_tokens']
TEMPERATURE = config['llm']['temperature']

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


# === Prompt ===
EXTRACT_CONTEXT_PROMPT = """You are analyzing a git diff for a Merge Request (MR) in an OpenSearch plugin project.

This plugin provides a Splunk-like query language for OpenSearch.
Language: Java

GIT DIFF:
```diff
{diff}
```

TASK: Create a comprehensive MR context file that will help code reviewers understand the global scope of changes.

OUTPUT FORMAT (in English):

---
# MR Context - Global Changes Overview

**Generated:** {timestamp}

---

## Summary

[2-3 sentences: what is the main goal of this MR]

---

## Files Changed ({file_count})

### New Files
- `path/to/File.java` - [brief purpose]

### Modified Files
- `path/to/File.java` - [what changed: added method X, refactored Y]

### Deleted Files
- `path/to/File.java` - [why deleted]

---

## Affected Components

List affected packages/modules:
- `com.company.query.parser` - [what changed]
- `com.company.query.executor` - [what changed]
- `com.company.aggregation` - [what changed]

---

## API Changes

### Public API Modifications
**IF any public methods/classes were added/removed/modified:**
- Class: `UserService`
  - Added: `getUserById(String id)` → returns Optional<User>
  - Modified: `getUsers()` → now returns List instead of Array
  - Removed: `deleteUser(int id)` → BREAKING CHANGE

**IF no public API changes:**
No public API changes detected.

---

## Query Language Changes ⚠️

**CRITICAL SECTION - analyze carefully:**

### Syntax Changes
**IF query syntax was modified:**
- [Describe what changed in query parsing/execution]
- Example: "Added support for `| stats avg(field) by group`"

### Semantic Changes
**IF query behavior changed:**
- [Describe how existing queries might behave differently]
- Example: "Aggregation now sorts by value desc instead of key asc"

### Breaking Changes
**IF queries that worked before might break:**
- [List specific breaking changes]
- Example: "Removed support for deprecated `timechart` command"

**IF no query language changes:**
No query language changes detected.

---

## Dependencies Between Files

List files that depend on each other in this MR:

**Example:**
- `UserController.java` calls `UserService.getUserById()`
  - ✓ Method is added in `UserService.java` (same MR)

- `QueryExecutor.java` uses `QueryParser.parseExpression()`
  - ⚠️ Signature changed in `QueryParser.java` - verify compatibility

**IF files are independent:**
No significant cross-file dependencies detected.

---

## Potential Risks

### High Risk
- [List high-risk changes: breaking changes, business logic modifications]

### Medium Risk
- [List medium-risk changes: refactorings, new features]

### Low Risk
- [List low-risk changes: code style, minor improvements]

---

## Test Coverage

**Test files in this MR:**
- `UserServiceTest.java` - [what's tested]

**Missing tests for:**
- [List production files without corresponding test changes]

---

RULES:
1. Be specific - mention actual class/method names from the diff
2. Focus on CHANGES, not entire file content
3. Identify cross-file dependencies
4. Flag query language changes prominently
5. Use "No X detected" if section is empty (don't skip sections)
6. Write in English
"""


# === Functions ===

def extract_changed_files(diff_text):
    """Extract list of changed files from diff."""
    files = []
    for match in re.finditer(r'^diff --git a/(.*?) b/', diff_text, re.MULTILINE):
        files.append(match.group(1))
    return files


def call_llm(prompt):
    """Call LLM API and return response."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a technical architect analyzing code changes."},
            {"role": "user", "content": prompt}
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS
    }

    log.info("MR_CONTEXT LLM REQUEST START")
    start = datetime.now()

    try:
        r = requests.post(API_URL, json=payload, timeout=600)
        r.raise_for_status()
    except Exception as e:
        log.error(f"LLM REQUEST FAILED: {e}")
        raise

    dt = (datetime.now() - start).total_seconds()
    log.info(f"MR_CONTEXT LLM REQUEST FINISH time={dt}s status={r.status_code}")

    return r.json()["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser(description="Extract MR context from git diff")
    parser.add_argument("--diff", required=True, help="Path to diff file")
    args = parser.parse_args()

    log.info(f"MR_CONTEXT EXTRACTION START diff={args.diff}")

    # Read diff
    diff_path = Path(args.diff)
    if not diff_path.exists():
        log.error(f"DIFF FILE NOT FOUND: {diff_path}")
        return

    diff_text = diff_path.read_text(errors="ignore")
    log.info(f"DIFF LOADED size={len(diff_text)} bytes")

    # Quick analysis
    changed_files = extract_changed_files(diff_text)
    file_count = len(changed_files)
    log.info(f"FILES CHANGED: {file_count}")
    log.info(f"FILES: {', '.join(changed_files[:5])}{'...' if file_count > 5 else ''}")

    # Truncate if too large
    MAX_DIFF_CHARS = 60_000  # ~80k tokens upper bound
    if len(diff_text) > MAX_DIFF_CHARS:
        log.warning(f"DIFF TOO LARGE ({len(diff_text)} chars), TRUNCATING to {MAX_DIFF_CHARS}")
        diff_text = diff_text[:MAX_DIFF_CHARS]

    # Build prompt
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = EXTRACT_CONTEXT_PROMPT.format(
        diff=diff_text,
        timestamp=timestamp,
        file_count=file_count
    )

    log.info(f"PROMPT SIZE chars={len(prompt)}")

    # Call LLM
    context = call_llm(prompt)

    # Save result
    MR_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    MR_CONTEXT_FILE.write_text(context)

    log.info(f"MR_CONTEXT WRITTEN to {MR_CONTEXT_FILE} bytes={len(context)}")
    log.info("MR_CONTEXT EXTRACTION END")

    # Print summary
    print(f"\n{'='*60}")
    print(f"MR Context extracted successfully!")
    print(f"Output: {MR_CONTEXT_FILE}")
    print(f"Files analyzed: {file_count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()